"""
pcg100 c8: the Copernicus "geometry <-> layer" nodes, newly written to Houdini's semantics.

  point_generate     Point Generate: adds points to a point cloud (count from parameters / a point attribute / a detail attribute)
  layer_from_attrib  Layer from Attribute: fills pixels element by element from an attribute array
  geo_to_layer       Geometry to Layer: volume prim -> layer (a 3D volume takes one slice per Slice)
  sequence_clips     Sequence: cuts a clip from each of one or more sequences and joins them end to end
  time_pack          Time Pack: packs a sequence's frames at several times into one multi-layer image
  integrate_volume   Integrate Volume: line integral / transmittance / extremum of volume prims along each pixel's view ray
  configure_stamps   Configure Stamps: writes the sprite attributes Stamp Points recognizes onto points

A sequence (COPSEQ) is a list of CopImage; frame number = list index (from 0, consistent with Sequence Pick).

The old nodes (Layer to Points, Texture Render, Render Pass ...) compute something else; per audit [C]'s rule
they're left alone and these are separate implementations. SideFX's docs only give parameter names and one sentence, so wherever "the docs don't say",
the function notes state how we decided.
"""
from __future__ import annotations

import numpy as np

from .pattern import rnd
from ..core import Geometry, POINT, VERTEX, PRIM, DETAIL

PG_METHODS = ("parameters", "point_attribute", "detail_attribute")


def _point_cloud(g):
    """Keep only points (Houdini: "any incoming primitives will be lost"); point attributes / point groups / detail are copied as-is."""
    out = Geometry(g.npoints)
    for k, v in g.attribs[POINT].items():
        out.attribs[POINT][k] = v
    for k, v in g.groups[POINT].items():
        out.groups[POINT][k] = v
    for k, v in g.attribs[DETAIL].items():
        out.attribs[DETAIL][k] = v
    return out


def _detail_scalar(g, name):
    a = None if g is None else g.get(DETAIL, name)
    return None if a is None else float(np.asarray(a, np.float64).ravel()[0])


def point_generate(points=None, ref=None, method="parameters", number_of_points=10,
                   points_per_second=0.0, time_step=1.0 / 24, seed=0,
                   count_attrib="count", copy_attribs="*", append=True):
    """
    Point Generate.
      parameters        count = Number of Points + Points per Second x Time Step. The fractional part
                        is kept or dropped by a Seed random number (the docs' own words). **Adding** the two is our own choice:
                        the docs don't say whether they're alternatives or cumulative; with Points per Second at its default 0 the count is exact.
                        Houdini uses the simulation's current timestep; we have no simulation, so Time Step is a parameter (extension).
      point_attribute   each source point is copied as many times as its own Count Attribute (floored, negatives as 0);
                        point attributes matched by Copy Attributes are copied from the source point, the rest are defaults (0)
      detail_attribute  the source geometry's detail Count Attribute gives the count (floored; the fractional part is **not** randomly kept,
                        the docs say "integer detail attribute")
    Source = ref (if connected) otherwise points. New points without copied P sit at the origin (the docs don't say where; it can only be the default).
    Append on: output = points' points (all prims dropped) + new points; off: only the new points, but carrying points' point attribute definitions.
    id: if points has an id point attribute, new points continue the numbering -- start = detail nextid (if present) otherwise max(id)+1,
    step = detail idstep (if present) otherwise 1; when nextid exists it is updated to the next available value (the docs don't say whether to
    update it; our own choice).
    """
    if method not in PG_METHODS:
        raise ValueError(f"Method must be one of {PG_METHODS}")
    base = _point_cloud(points) if points is not None else Geometry()
    src = ref if ref is not None else points
    cnt = str(count_attrib).strip()
    rep = None                                  # point_attribute: which source point each new point comes from
    if method == "parameters":
        x = max(float(number_of_points) + float(points_per_second) * float(time_step), 0.0)
        n = int(np.floor(x))
        if x - n > 0 and rnd(np.array([0]), seed, 1)[0] < x - n:
            n += 1
    elif method == "detail_attribute":
        v = _detail_scalar(src, cnt)
        if v is None:
            raise ValueError(f"The source geometry has no detail attribute '{cnt}'")
        n = int(np.floor(max(np.nan_to_num(v), 0.0)))
    else:
        a = None if src is None else src.get(POINT, cnt)
        if a is None:
            raise ValueError(f"The source geometry has no point attribute '{cnt}'")
        k = np.floor(np.clip(np.nan_to_num(np.asarray(a, np.float64)[:, 0]), 0, None))
        rep = np.repeat(np.arange(len(k)), k.astype(np.int64))
        n = len(rep)

    new = Geometry(n)
    new.set(POINT, "P", np.zeros((n, 3), np.float32))
    for k, v in base.attribs[POINT].items():    # attribute definitions follow the input, values are defaults
        if k != "P":
            new.set(POINT, k, np.zeros((n, v.shape[1]), v.dtype), owned=True)
    if rep is not None:
        from ..ops import match_names
        for k in match_names(list(src.attribs[POINT]), copy_attribs):
            new.set(POINT, k, np.asarray(src.get(POINT, k))[rep])
    ids = base.get(POINT, "id")
    if ids is not None:
        nxt = _detail_scalar(base, "nextid")
        step = _detail_scalar(base, "idstep")
        start = int(nxt) if nxt is not None else (int(np.max(ids)) + 1 if len(ids) else 0)
        step = int(step) if step is not None else 1
        new.set(POINT, "id", (start + step * np.arange(n)).astype(ids.dtype).reshape(-1, 1))
        if nxt is not None:
            base.set(DETAIL, "nextid", np.array([[start + step * n]],
                                                 base.get(DETAIL, "nextid").dtype))
    if not append:
        for k, v in base.attribs[DETAIL].items():
            new.attribs[DETAIL][k] = v
        return new
    from ..ops import merge
    if base.npoints == 0:
        for k, v in base.attribs[DETAIL].items():
            new.attribs[DETAIL][k] = v
        return new
    return merge(base, new)             # with n = 0, merge itself drops the empty new


# ═══════════════════════════════════════════════════════════ Layer from Attribute
LFA_CLASSES = ("point", "prim", "vertex", "detail")
LFA_ORDERS = ("bottom_left", "top_left")
LFA_SHAPES = ("pow2_square", "square", "single_row", "single_column")
_CLS = {"point": POINT, "prim": PRIM, "vertex": VERTEX, "detail": DETAIL}


def _attrib_array(geo, cls, name):
    """-> (N, C) float64. A detail attribute counts as "one element"; Copernicus's detached attribute is a 1D array."""
    if cls not in LFA_CLASSES:
        raise ValueError(f"Class must be one of {LFA_CLASSES}")
    a = None if geo is None else geo.get(_CLS[cls], str(name).strip())
    if a is None:
        raise ValueError(f"The geometry has no {cls} attribute '{name}'")
    a = np.asarray(a)
    if a.dtype.kind in "OUS":
        raise ValueError(f"Attribute '{name}' is a string and can't be filled into a layer")
    return np.asarray(a, np.float64).reshape(len(a), -1)


def resize_shape(n, shape):
    """Resize Shape -> (W, H). With 0 elements gives 1x1 (a layer can't be empty)."""
    if shape not in LFA_SHAPES:
        raise ValueError(f"Resize Shape must be one of {LFA_SHAPES}")
    n = max(int(n), 1)
    if shape == "single_row":
        return n, 1
    if shape == "single_column":
        return 1, n
    import math
    s = math.isqrt(n - 1) + 1                   # the smallest s with s² >= n (integer square root, no floating-point error)
    if shape == "pow2_square":
        s = 1 << (s - 1).bit_length()
    return s, s


def layer_from_attrib(geo, attrib="Cd", attrib_class="point", order="bottom_left",
                      resize=False, shape="pow2_square", out_layer="attrib",
                      size_ref=None, index=None, index_layer="", xres=512, yres=512):
    """
    Layer from Attribute: element k fills pixel k.
      Data Ordering  bottom_left: first pixel at the bottom-left, left to right, bottom to top (Copernicus's canonical order;
                     our row 0 is the bottom); top_left: starting top-left, left to right, top to bottom
      Resize Layer   off: resolution = size_ref (resolution_x/y if not connected), adding a layer on size_ref;
                     on: resolution from the element count and Resize Shape, and the output has only this layer
      index          if connected: each pixel reads index_layer's value (rint) as the element number, ignoring Data Ordering
    Not stated in the docs: when there are more pixels than elements, the extra pixels are 0; when more elements than pixels, the extras are dropped; pixels with an out-of-range index (including negative)
    are 0. The output layer's channel count = the attribute's component count. A detail attribute is 1 element.
    """
    from .core import CopImage, check_res
    from .pixel import getn, put
    if order not in LFA_ORDERS:
        raise ValueError(f"Data Ordering must be one of {LFA_ORDERS}")
    a = _attrib_array(geo, attrib_class, attrib)
    n, C = a.shape
    if resize:
        W, H = resize_shape(n, shape)
        out = CopImage(W, H)
    elif size_ref is not None and len(size_ref):
        out, W, H = size_ref.copy(), size_ref.xres, size_ref.yres
    else:
        W, H = check_res(xres, yres)
        out = CopImage(W, H)
    if index is not None:
        if (index.xres, index.yres) != (W, H):
            raise ValueError(f"index resolution {index.xres}x{index.yres} differs from the output's {W}x{H}")
        k = np.rint(np.nan_to_num(getn(index, index_layer)[..., 0])).astype(np.int64)
    else:
        I, J = np.mgrid[0:H, 0:W]
        k = J + (I if order == "bottom_left" else (H - 1 - I)) * W
    ok = (k >= 0) & (k < n)
    img = np.zeros((H, W, C))
    img[ok] = a[k[ok]]
    return put(out, out_layer, img)


# ═══════════════════════════════════════════════════════════ Geometry to Layer
GTL_SLICES = ("xy", "yz", "zx")
GTL_TYPES = ("auto", "id", "mono", "uv", "rgb", "rgba")
_NCH = {"id": 1, "mono": 1, "uv": 2, "rgb": 3, "rgba": 4}
# plane -> indices of (horizontal axis u, vertical axis v, normal w) in (x, y, z); "ZX Plane" is literally Z horizontal, X vertical
_AX = {"xy": (0, 1, 2), "yz": (1, 2, 0), "zx": (2, 0, 1)}


def _slice(vox, origin, cell, plane, offset):
    """
    Takes a slice of voxels (rz, ry, rx) on the plane "normal coordinate = offset" -> (H, W). Linearly interpolates along the normal between adjacent
    voxel layers; when the plane falls outside the volume the whole slice is 0 (Houdini volumes' default constant-0 border).
    """
    a = np.transpose(np.asarray(vox, np.float64), (2, 1, 0))   # -> [x, y, z]
    iu, iv, iw = _AX[plane]
    a = np.transpose(a, (iw, iv, iu))                          # -> [w, v, u]
    n = a.shape[0]
    f = (float(offset) - origin[iw]) / cell[iw] if cell[iw] > 0 else 0.0
    if not -1e-9 <= f <= n - 1 + 1e-9:
        return np.zeros(a.shape[1:])
    f = min(max(f, 0.0), n - 1.0)
    k0 = min(int(np.floor(f)), n - 2) if n > 1 else 0
    t = f - k0
    return a[k0] * (1 - t) + (a[k0 + 1] * t if n > 1 else 0)


def _prim_names(geo, vp):
    nm = geo.get(PRIM, "name")
    return [str(nm[i, 0]) if nm is not None and str(nm[i, 0]) else "" for i in vp]


def geo_to_layer(geo, outputs="", out_type="auto", plane="xy", offset=0.0,
                 optional=False, default="0", size_ref=None):
    """
    Geometry to Layer: converts volume prims to layers, one layer per output, layer name = the prim's name (when unnamed,
    "output" + (prim number + 1)).
      outputs   space-separated; each item is a prim name, a volume index, or a wildcard name (e.g. vel.*: the matched
                volumes are sorted by name and combined into one multi-channel layer, with ".*" dropped from the layer name -- the docs' vel.* + RGB usage).
                Empty = one layer per volume (equivalent to Set Imports from Geometry)
      out_type  auto: channel count = number of matched volumes; id / mono / uv / rgb / rgba: truncated or zero-padded to 1 / 1 /
                2 / 3 / 4 channels, id also takes rint
      plane     XY / YZ / ZX: which direction a 3D volume is sliced in; plane position = normal coordinate offset (Volume Slice
                SOP's Plane Offset; the Geometry to Layer docs give no offset parameter, this is an extension, default 0)
      optional  when an item isn't found, fill with Default Value at size_ref's resolution instead of raising an error
    Pixel = voxel (one pixel per voxel, horizontal / vertical axes see _AX); all outputs must share a resolution (layers in one of our images
    share a resolution; in Houdini each output is an independent layer and can differ).
    """
    from .core import CopImage
    from .pixel import put, _vec
    from ..volume import volume_info
    from ..volops import volume_prims
    from ..ops import match_names
    if plane not in GTL_SLICES:
        raise ValueError(f"Slice must be one of {GTL_SLICES}")
    if out_type not in GTL_TYPES:
        raise ValueError(f"Type must be one of {GTL_TYPES}")
    vp = volume_prims(geo) if geo is not None else []
    names = _prim_names(geo, vp) if vp else []
    toks = str(outputs).split()
    if not toks:
        toks = [n or str(k) for k, n in enumerate(names)]
    jobs = []                                   # (layer name, [prim indices], original item)
    for t in toks:
        if t.lstrip("-").isdigit():
            k = int(t)
            hit = [vp[k]] if -len(vp) <= k < len(vp) else []
            lname = (names[k] or f"output{(k % len(vp)) + 1}") if hit else f"output{k + 1}"
        elif any(c in t for c in "*?["):
            m = sorted(match_names([n for n in names if n], t))
            hit = [vp[names.index(n)] for n in m]
            lname = t.replace(".*", "").replace("*", "").replace("?", "") or "output"
        else:
            hit = [vp[k] for k, n in enumerate(names) if n == t][:1]
            lname = t
        jobs.append((lname, hit, t))
    out, res = None, None
    for lname, hit, t in jobs:
        if hit:
            sl = []
            for i in hit:
                vox, origin, cell = volume_info(geo, i)
                sl.append(_slice(vox, origin, cell, plane, offset))
            shp = {x.shape for x in sl}
            if len(shp) > 1:
                raise ValueError(f"The volumes matched by '{t}' have different resolutions and can't be combined into one layer")
            arr = np.stack(sl, -1)
        elif optional:
            if size_ref is None or not len(size_ref):
                raise ValueError(f"Volume '{t}' not found; Optional needs size_ref connected to know the resolution")
            nc = _NCH.get(out_type, 1)
            arr = np.broadcast_to(_vec(default, nc), (size_ref.yres, size_ref.xres, nc)).copy()
        else:
            raise ValueError(f"The geometry has no volume '{t}' (turn on Optional to use the default value)")
        if out_type != "auto":
            nc = _NCH[out_type]
            c = arr.shape[-1]
            arr = arr[..., :nc] if c >= nc else np.concatenate(
                [arr, np.zeros(arr.shape[:2] + (nc - c,))], -1)
            if out_type == "id":
                arr = np.rint(arr)
        H, W = arr.shape[:2]
        if out is None:
            res = (W, H)
            out = CopImage(W, H)
        elif (W, H) != res:
            raise ValueError(f"The slice of '{t}' is {W}x{H}, which differs from the earlier {res[0]}x{res[1]}; "
                             "layers in one image must share a resolution, convert with two nodes")
        put(out, lname, arr)
    if out is None:
        raise ValueError("No volume prims in the input (create one with Volume, or Convert to volume_sdf / "
                         "volume_fog), and Outputs has nothing to convert")
    return out


# ═══════════════════════════════════════════════════════════ Sequence / Time Pack
def _hold(seq, f):
    """Take frame f; out of range holds the first / last frame (Time Shift's hold)."""
    return seq[min(max(int(f), 0), len(seq) - 1)]


def parse_clips(spec):
    """"0 10; 20 5" -> [(0, 10), (20, 5)]; separated by semicolons or newlines, each clip "start_frame frame_count"."""
    out = []
    for part in str(spec).replace("\n", ";").split(";"):
        t = part.replace(",", " ").split()
        if not t:
            continue
        if len(t) != 2:
            raise ValueError(f"Each Clips entry must be 'start_frame frame_count', got '{part.strip()}'")
        a, n = int(float(t[0])), int(float(t[1]))
        if n < 1:
            raise ValueError(f"Clip '{part.strip()}' needs a frame count >= 1")
        out.append((a, n))
    return out


def sequence_clips(inputs, clips="", output_start=0):
    """
    Sequence: clip k takes frames [Start Frame, Start Frame + Length) from input k, and the clips are joined end to end.
    When there are more clips than inputs, the extra clips all take from the **last** input (docs: with only one input every clip takes from it).
    Empty Clips = one clip, taking all frames of the first input.
    Not made clear in the docs, our own choices:
      · out-of-range frames in a clip hold the first / last frame, no error
      · Output Start Frame = S: output frame S is the first frame of the first clip. When S > 0, the first S frames repeat the first frame
        (our sequences start at frame 0 and can't be "left empty"); when S < 0, the first -S frames are dropped
    """
    seqs = [q for q in inputs if q is not None]
    if not seqs or not seqs[0]:
        raise ValueError("The first input sequence is empty")
    for k, q in enumerate(seqs):
        if not q:
            raise ValueError(f"Input sequence {k + 1} is empty")
    cl = parse_clips(clips) or [(0, len(seqs[0]))]
    res = []
    for k, (a, n) in enumerate(cl):
        q = seqs[min(k, len(seqs) - 1)]
        res.extend(_hold(q, f) for f in range(a, a + n))
    s = int(output_start)
    if s > 0:
        res = [res[0]] * s + res
    elif s < 0:
        res = res[-s:]
        if not res:
            raise ValueError(f"Output Start Frame {s} drops every frame")
    return res


TP_MODES = ("relative", "absolute")
TP_UNITS = ("frames", "seconds")
TP_ADD = ("prefix", "suffix")
TP_MAX = 4096


def time_pack(seq, frame=0, mode="relative", units="frames", range_start=-1.0,
              range_end=1.0, step=1.0, fps=24.0, add_time_as="suffix", layers=""):
    """
    Time Pack: takes a time every Step within Range and merges the sequence's frames at those times (the layers chosen in Layers, empty = all)
    into one image, adding the sample number to the layer names: Prefix -> "<k>_<layer>", Suffix -> "<layer>_<k>" (k counts from 0).
      relative  Range is relative to the current frame Frame (-1 1 = previous, current, next frame; the docs' example)
      absolute  Range is frame numbers
      seconds   Range / Step in seconds, multiplied by FPS to get frames (FPS is our added parameter; Houdini uses the scene frame rate)
    Not stated in the docs, our own choices: samples = start, start + step, ... (<= end, with a floating-point tolerance); times falling between two frames
    are linearly interpolated between them (Time Blend's approach); out-of-range frames hold the first / last frame; Method is only By Frame
    (the only one the docs list), so it isn't a parameter.
    """
    if not seq:
        raise ValueError("The sequence is empty")
    if mode not in TP_MODES:
        raise ValueError(f"Mode must be one of {TP_MODES}")
    if units not in TP_UNITS:
        raise ValueError(f"Units must be one of {TP_UNITS}")
    if add_time_as not in TP_ADD:
        raise ValueError(f"Add Time As must be one of {TP_ADD}")
    k = float(fps) if units == "seconds" else 1.0
    if not k > 0:
        raise ValueError("FPS must be > 0")
    a, b, st = float(range_start) * k, float(range_end) * k, float(step) * k
    if not st > 0:
        raise ValueError("Step must be > 0")
    if mode == "relative":
        a, b = a + float(frame), b + float(frame)
    n = int(np.floor((b - a) / st + 1e-9)) + 1
    if n < 1:
        raise ValueError(f"Range {range_start} - {range_end} is empty (the end is before the start)")
    if n > TP_MAX:
        raise ValueError(f"{n} samples requested, over the limit of {TP_MAX}; increase Step")
    from .hfvis import _lerp_img
    out = None
    for i in range(n):
        t = a + i * st
        f0 = int(np.floor(t + 1e-9))
        w = t - f0
        img = _hold(seq, f0) if abs(w) < 1e-9 else _lerp_img(_hold(seq, f0), _hold(seq, f0 + 1), w)
        want = [x for x in str(layers).split() if x] or img.names
        if out is None:
            from .core import CopImage
            out = CopImage(img.xres, img.yres)
        for nm in want:
            new = f"{i}_{nm}" if add_time_as == "prefix" else f"{nm}_{i}"
            out.set(new, img.need(nm))
    return out


# ═══════════════════════════════════════════════════════════ Integrate Volume
IV_OPS = ("integral", "transmittance", "minimum", "maximum")
IV_RAMP = ("none", "clamped", "periodic")


def _select_vols(geo, spec):
    """Name / index / wildcard -> list of volume prim indices (sorted by name; same scheme as Geometry to Layer)."""
    from ..volops import volume_prims
    from ..ops import match_names
    vp = volume_prims(geo) if geo is not None else []
    if not vp:
        raise ValueError("No volume prims in the input (create one with Volume, or Convert to volume_sdf / "
                         "volume_fog)")
    t = str(spec).strip()
    if not t:
        return vp[:1]
    names = _prim_names(geo, vp)
    if t.lstrip("-").isdigit():
        k = int(t)
        if not -len(vp) <= k < len(vp):
            raise ValueError(f"There are only {len(vp)} volumes; {k} is out of range")
        return [vp[k]]
    m = sorted(match_names([n for n in names if n], t))
    if not m:
        raise ValueError(f"No volume name matches '{t}'; available: {names}")
    return [vp[names.index(n)] for n in m]


def integrate_volume(geo, density="", operation="integral", dmin=0.0, dmax=1.0,
                     ramp_mode="none", density_scale=1.0, step_size=0.01, max_steps=4096,
                     cutoff=-1.0, sample_jitter=0.0, strat_jitter=0.0, seed=0,
                     layers=None, origin_layer="", dir_layer="", mindepth_layer="",
                     maxdepth_layer="", out_layer="result", xres=256, yres=256):
    """
    Integrate Volume: one view ray per pixel, over the volume:
      integral       Σ density x segment length (line integral)
      transmittance  exp(-line integral)
      minimum / maximum  min / max of the sampled values along the ray (raw values, not through the Density mapping); +inf / -inf if no volume is hit
    Ray: when layers is connected and origin_layer / dir_layer are given, taken per pixel (ray starts at origin, t >= 0);
    otherwise the default orthographic projection -- the pixel center's image coordinates (long side -1 to 1) as (x, y), along the **whole line** in +Z
    (docs: "default orthographic projection spanning -1 to 1, marching forward along the Z-axis";
    the docs don't say where the orthographic camera starts, so it isn't truncated and passes through the whole volume). mindepth / maxdepth layers (Depth Conversion
    = Distance) further limit t to [min, max]; with the default orthographic projection t is the z coordinate.
    Density (applies only to integral / transmittance): v' = (v - Min) / (Max - Min), Ramp Mode Clamped clamps to
    0-1, Periodic takes the fractional part, then x Density Scale. **The Density Ramp curve isn't implemented** (both ramp modes only do
    the clamp / modulo step, equivalent to an identity curve).
    Marching: the ray is first clipped to the volume's bounding box and cut into segments of Step Size, one sample per segment, at the segment center +
    (rnd - 0.5) x Sample Jitter x step; the whole ray's segment start is also shifted by (rnd - 0.5) x Stratification
    Jitter x step (at most half a step at 1). The last segment may be partial and is weighted by its actual length (the integral is exact for constant density).
    Max Step Count limits the segment count; with Transmittance Cutoff >= 0, marching stops once transmittance drops below it (-1 = never stop).
    Multiple volumes (like vel.*) = multiple channels, accumulated separately per channel; Cutoff stops only when all channels have dropped below.
    """
    from .core import CopImage, check_res
    from .pixel import getn, put
    from ..volume import volume_info
    from ..attribsample import sample_volume
    from .coordspace import tex_to_space
    if operation not in IV_OPS:
        raise ValueError(f"Operation must be one of {IV_OPS}")
    if ramp_mode not in IV_RAMP:
        raise ValueError(f"Ramp Mode must be one of {IV_RAMP}")
    st = float(step_size)
    if not st > 0:
        raise ValueError("Integration Step Size must be > 0")
    if operation in ("integral", "transmittance") and float(dmax) == float(dmin):
        raise ValueError("Density Min and Max can't be equal")
    vols = [volume_info(geo, i) for i in _select_vols(geo, density)]
    has_img = layers is not None and len(layers)
    if has_img:
        W, H = layers.xres, layers.yres
    else:
        W, H = check_res(xres, yres)
    n = W * H
    custom = bool(str(origin_layer).strip()) or bool(str(dir_layer).strip())
    if custom:
        if not has_img:
            raise ValueError("View Origin / View Direction layer names are given; connect the layers input")
        O = getn(layers, origin_layer)[..., :3].reshape(n, 3) if str(origin_layer).strip() \
            else np.zeros((n, 3))
        D = getn(layers, dir_layer)[..., :3].reshape(n, 3) if str(dir_layer).strip() \
            else np.tile([0.0, 0.0, 1.0], (n, 1))
        D = D / np.maximum(np.linalg.norm(D, axis=1, keepdims=True), 1e-30)
        tlo, thi = np.zeros(n), np.full(n, np.inf)
    else:
        u = (np.arange(W) + 0.5) / W
        v = (np.arange(H) + 0.5) / H
        U, V = np.meshgrid(u, v)
        X, Y = tex_to_space("image", U, V, W, H)
        O = np.stack([X.ravel(), Y.ravel(), np.zeros(n)], -1)
        D = np.tile([0.0, 0.0, 1.0], (n, 1))
        tlo, thi = np.full(n, -np.inf), np.full(n, np.inf)
    for nm, which in ((mindepth_layer, 0), (maxdepth_layer, 1)):
        if str(nm).strip():
            if not has_img:
                raise ValueError("Min / Max Depth layer names are given; connect the layers input")
            d = getn(layers, nm)[..., 0].ravel()
            if which == 0:
                tlo = np.maximum(tlo, d)
            else:
                thi = np.minimum(thi, d)
    nc = len(vols)
    # clip rays to the union of all volumes' bounding boxes (multi-channel volumes march together)
    lo = np.min([o for _, o, c in vols], 0)
    hi = np.max([o + c * (np.array(vx.shape[::-1]) - 1) for vx, o, c in vols], 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / np.where(np.abs(D) < 1e-30, 1e-30, D)
        t0 = (lo - O) * inv
        t1 = (hi - O) * inv
    tn = np.maximum(np.minimum(t0, t1).max(1), tlo)
    tf = np.minimum(np.maximum(t0, t1).min(1), thi)
    hitbox = tf > tn
    acc = np.zeros((n, nc))
    vmin = np.full((n, nc), np.inf)
    vmax = np.full((n, nc), -np.inf)
    ids = np.arange(n)
    from .pattern import rnd
    start = tn + (rnd(ids, seed, 3) - 0.5) * float(strat_jitter) * st
    alive = hitbox.copy()
    span_r = (float(dmax) - float(dmin)) or 1.0
    for k in range(int(max_steps)):
        idx = np.nonzero(alive)[0]
        if not len(idx):
            break
        # segment ends, clipped to [tn, tf]; segment 0 starts at tn (when stratified jitter shifts forward, the small piece in front belongs to segment 0)
        a = tn[idx] if k == 0 else np.maximum(start[idx] + k * st, tn[idx])
        b = np.minimum(start[idx] + (k + 1) * st, tf[idx])
        ln = b - a
        ok = ln > 0
        mid = (a + b) / 2 + (rnd(idx * 4099 + k, seed, 5) - 0.5) * float(sample_jitter) * ln
        Q = O[idx] + D[idx] * mid[:, None]
        for c, (vx, o, cl) in enumerate(vols):
            val, ins = sample_volume(vx, o, cl, Q)
            got = ok & ins
            if operation in ("minimum", "maximum"):
                vmin[idx[got], c] = np.minimum(vmin[idx[got], c], val[got])
                vmax[idx[got], c] = np.maximum(vmax[idx[got], c], val[got])
            else:
                x = (val - float(dmin)) / span_r
                if ramp_mode == "clamped":
                    x = np.clip(x, 0, 1)
                elif ramp_mode == "periodic":
                    x = x - np.floor(x)
                acc[idx[got], c] += x[got] * float(density_scale) * ln[got]
        done = start[idx] + (k + 1) * st >= tf[idx]
        if float(cutoff) >= 0 and operation in ("integral", "transmittance"):
            done |= (np.exp(-acc[idx]) <= float(cutoff)).all(1)
        alive[idx[done]] = False
    if operation == "integral":
        res = acc
    elif operation == "transmittance":
        res = np.exp(-acc)
    elif operation == "minimum":
        res = vmin
    else:
        res = vmax
    out = layers.copy() if has_img else CopImage(W, H)
    return put(out, out_layer, res.reshape(H, W, nc))


# ═══════════════════════════════════════════════════════════ Configure Stamps
CS_SCALE = ("uniform", "percent_variance", "min_max")
CS_VAR = ("uniform", "variance", "min_max")
CS_COLOR = ("uniform", "variance")
CS_SELECT = ("cycle", "random", "layer_select")


def _sym(ids, seed, salt):
    """Hash random number in [-1, 1)."""
    return rnd(ids, seed, salt) * 2 - 1


def configure_stamps(points, layers=None, plane="xz", world_size=1.0, seed=0,
                     jitter=0.0, jitter_scale="1 1", jitter_layer="", jitter_mask=1.0,
                     scale=1.0, scale_mode="uniform", scale_variance=0.0, scale_min=0.5,
                     scale_max=1.0, scale_layer="", scale_mask=1.0,
                     stretch="1 1", stretch_mode="uniform", stretch_variance=0.0,
                     stretch_min=0.5, stretch_max=1.0, stretch_layer="", stretch_mask=1.0,
                     angle=0.0, angle_mode="uniform", angle_variance=0.0, angle_min=0.0,
                     angle_max=1.0, round_to=0.0, angle_layer="", angle_mask=1.0,
                     direction_layer="", direction_mask=1.0,
                     color="1 1 1", color_mode="uniform", color_seed=0, hue_variance=0.0,
                     saturation_variance=0.0, value_variance=0.0, color_layer="",
                     color_mask=1.0, alpha=1.0, alpha_mode="uniform", alpha_variance=0.0,
                     alpha_layer="", alpha_mask=1.0, stamp_count=1, select_mode="cycle",
                     select_seed=0, select_layer="", use_sort_layer=False, sort_layer=""):
    """
    Configure Stamps: draws nothing, only writes point attributes -- spritescale (2), spriterot (degrees), Cd (3),
    blend (alpha), stamp (integer, which stamp), plus Jitter moving P and the Sort layer moving the out-of-plane axis.
    Layer inputs (taken by layer name from layers) are bilinearly sampled at the point positions; point -> uv uses plane + world (image width =
    World Size, origin centered, consistent with Layer to Points / Scatter Shapes).

    The docs have only a one-sentence description; all formulas below are our own (r is an independent per-point random number in [-1, 1), hashed from Seed /
    Color Seed / Select Seed and the point number, with a different salt per attribute):
      Jitter         P on the plane's two axes += r · Jitter · Jitter Scale (world units)
                     + Jitter Layer (first two channels) x Mask
      Scale          s = Scale x lerp(1, layer value, Mask); Percent Variance: x (1 + Variance · r);
                     Min/Max: x uniform in [Min, Max]
      Stretch        (sx, sy) = Stretch x lerp(1, layer value, Mask) (a 1-channel layer is shared by both axes); Variance:
                     each axis x (1 + Variance · r); Min/Max: each axis x uniform in [Min, Max]
      spritescale    = s · (sx, sy)
      Angle          a = Angle + Angle Layer x 360 x Mask (docs: 0 -> 0°, 1 -> 360°)
                     + atan2(Direction Layer's y, x) (degrees) x Direction Mask;
                     Variance: + Variance · r (degrees); Min/Max: x uniform in [Min, Max] (the docs' words
                     "multiplied against Angle"); Round To > 0: finally rounded to a multiple of it
      Color          Cd = Color x lerp(1, layer value, Mask); Variance: in HSV h += Hue · r (wrapping),
                     s / v += Saturation / Value · r (clamped 0-1)
      Alpha          blend = Alpha x lerp(1, layer value, Mask); Variance: + Variance · r, clamped 0-1
      Stamp          Cycle: point number mod Count; Random: uniform by Select Seed; Layer Select:
                     round(layer value x (Count - 1)), clamped to [0, Count - 1] (docs: 0 -> first, 1 -> last)
      Sort           Use Sort Layer on: the out-of-plane axis += layer value (the docs only say "a small Z offset"; the amount is our own)
    Random from Ramp (color / alpha) isn't implemented.
    """
    from .pixel import getn, _vec
    from .filters import sample
    from .stamp import to_uv, PLANES
    for v, ok, nm in ((scale_mode, CS_SCALE, "Scale Mode"), (stretch_mode, CS_VAR, "Stretch Mode"),
                      (angle_mode, CS_VAR, "Angle Mode"), (color_mode, CS_COLOR, "Stamp Color"),
                      (alpha_mode, CS_COLOR, "Stamp Alpha"), (select_mode, CS_SELECT, "Mode"),
                      (plane, PLANES, "Plane")):
        if v not in ok:
            raise ValueError(f"{nm} must be one of {ok}")
    if points is None:
        raise ValueError("Points must be connected")
    g = points.copy()
    n = g.npoints
    P = np.asarray(g.get(POINT, "P"), np.float64).reshape(n, 3)
    ids = np.arange(n, dtype=np.int64)
    need = [x for x in (jitter_layer, scale_layer, stretch_layer, angle_layer, direction_layer,
                        color_layer, alpha_layer, select_layer,
                        sort_layer if use_sort_layer else "") if str(x).strip()]
    if need and (layers is None or not len(layers)):
        raise ValueError(f"Layer names {need} are given; connect the layers input")
    uv = None
    if need:
        uv = to_uv(P, layers.xres, layers.yres, plane, "world", world_size)

    def lay(name, nc):
        a = sample(getn(layers, name), uv[:, 0], uv[:, 1], "clamp")
        a = np.asarray(a, np.float64).reshape(n, -1)
        return a[:, :nc] if a.shape[1] >= nc else np.repeat(a[:, :1], nc, 1)

    def mix(base, name, mask, nc):
        if not str(name).strip():
            return base
        return base * (1 + (lay(name, nc) - 1) * float(mask))

    # ── Jitter: the plane's two axes (same as stamp.from_uv: xz plane a = x, b = -z)
    ax = {"xz": ((0, 1.0), (2, -1.0)), "xy": ((0, 1.0), (1, 1.0)), "zy": ((2, 1.0), (1, 1.0))}[plane]
    out_ax = {"xz": 1, "xy": 2, "zy": 0}[plane]
    js = _vec(jitter_scale, 2)
    off = np.stack([_sym(ids, seed, 1), _sym(ids, seed, 2)], -1) * float(jitter) * js
    if str(jitter_layer).strip():
        off = off + lay(jitter_layer, 2) * float(jitter_mask)
    for k, (i, sg) in enumerate(ax):
        P[:, i] += sg * off[:, k]
    if use_sort_layer and str(sort_layer).strip():
        P[:, out_ax] += lay(sort_layer, 1)[:, 0]
    g.set(POINT, "P", P.astype(np.float32))

    # ── Scale / Stretch
    sc = mix(np.full((n, 1), float(scale)), scale_layer, scale_mask, 1)[:, 0]
    if scale_mode == "percent_variance":
        sc = sc * (1 + float(scale_variance) * _sym(ids, seed, 5))
    elif scale_mode == "min_max":
        sc = sc * (float(scale_min) + (float(scale_max) - float(scale_min)) * rnd(ids, seed, 6))
    st = mix(np.tile(_vec(stretch, 2), (n, 1)), stretch_layer, stretch_mask, 2)
    if stretch_mode == "variance":
        st = st * (1 + float(stretch_variance) * np.stack([_sym(ids, seed, 7), _sym(ids, seed, 9)], -1))
    elif stretch_mode == "min_max":
        st = st * (float(stretch_min) + (float(stretch_max) - float(stretch_min))
                   * np.stack([rnd(ids, seed, 10), rnd(ids, seed, 11)], -1))
    g.set(POINT, "spritescale", (sc[:, None] * st).astype(np.float32))

    # ── Angle
    an = np.full(n, float(angle))
    if str(angle_layer).strip():
        an = an + lay(angle_layer, 1)[:, 0] * 360.0 * float(angle_mask)
    if str(direction_layer).strip():
        d = lay(direction_layer, 2)
        an = an + np.degrees(np.arctan2(d[:, 1], d[:, 0])) * float(direction_mask)
    if angle_mode == "variance":
        an = an + float(angle_variance) * _sym(ids, seed, 13)
    elif angle_mode == "min_max":
        an = an * (float(angle_min) + (float(angle_max) - float(angle_min)) * rnd(ids, seed, 14))
    if float(round_to) > 0:
        an = np.round(an / float(round_to)) * float(round_to)
    g.set(POINT, "spriterot", an.astype(np.float32))

    # ── Color / Alpha
    cd = mix(np.tile(_vec(color, 3), (n, 1)), color_layer, color_mask, 3)
    if color_mode == "variance":
        from .pixel import rgb_to_hsv, hsv_to_rgb
        hsv = rgb_to_hsv(cd)
        hsv[:, 0] = (hsv[:, 0] + float(hue_variance) * _sym(ids, color_seed, 1)) % 1.0
        hsv[:, 1] = np.clip(hsv[:, 1] + float(saturation_variance) * _sym(ids, color_seed, 2), 0, 1)
        hsv[:, 2] = np.clip(hsv[:, 2] + float(value_variance) * _sym(ids, color_seed, 3), 0, 1)
        cd = hsv_to_rgb(hsv)
    g.set(POINT, "Cd", cd.astype(np.float32))
    al = mix(np.full((n, 1), float(alpha)), alpha_layer, alpha_mask, 1)[:, 0]
    if alpha_mode == "variance":
        al = np.clip(al + float(alpha_variance) * _sym(ids, color_seed, 5), 0, 1)
    g.set(POINT, "blend", al.astype(np.float32))

    # ── Stamp
    cnt = max(1, int(stamp_count))
    if select_mode == "cycle":
        sid = ids % cnt
    elif select_mode == "random":
        sid = np.minimum((rnd(ids, select_seed, 1) * cnt).astype(np.int64), cnt - 1)
    else:
        if not str(select_layer).strip():
            raise ValueError("Layer Select needs a Select Layer")
        sid = np.clip(np.rint(lay(select_layer, 1)[:, 0] * (cnt - 1)), 0, cnt - 1).astype(np.int64)
    g.set(POINT, "stamp", sid.astype(np.int32))
    return g
