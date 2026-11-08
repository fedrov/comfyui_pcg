"""
Camera-space "image -> geometry control data" -- projects an image onto geometry **through a camera**.

Item 3 on the list. Until now `AttribFromMap` / `DisplaceFromMap` / `ScatterFromMap`
were all **UV-space** (their parameters are uv_attrib / uv_from, no cam), so to turn an AI-generated
mask into a point group, the existing route was:

    UVBackproject (cam -> UV texture) -> AttribFromMap -> threshold grouping

Three nodes, and it requires the geometry to **already have UVs**. This module makes it a single wire, and it also works for geometry without UVs
-- it never goes through UV space at all.

This is the control-flow hub for the AI -> procedural direction: AI only decides "where", procedural decides "how".
Paint a region in the viewport (or have a model do it) -> the region becomes a point group -> followed by Blast /
Voronoi Fracture / PolyExtrude / Scatter, all deterministic procedural operators.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Difference from UV Project + Attribute from Map: **visibility**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Treat the camera projection as a kind of UV projection and then connect AttribFromMap -- this route works, but **back faces get
painted too**. Planar projection knows nothing about occlusion: paint a sphere's front red and its back gets painted red as well, and it looks
"about right" (you only notice when you turn it around). Houdini has the same pitfall, which is why its UV Texture SOP
has a perspective from camera option, while back-face culling has to be done separately.

Visibility here is a **four-step ladder**, each step stricter than the previous:

    all       no test, every element is sampled (= pure projection, for when "punching through" is what you want)
    frustum   inside the frame + in front of the camera
    front     plus facing: elements whose normal faces away from the camera are not sampled
    full      plus **occlusion**: elements hidden behind other faces are not sampled (default)

Occlusion uses a z-buffer from rasterizing once from the camera, the same machinery as `render.rasterize` --
so "the rendered image" and "the projection-back test" use the same projection and can't disagree.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The depth bias is **relative** to scale, unlike UV Backproject
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The z-buffer stores the z of the triangle at the **pixel centre**, and an element's anchor almost never falls exactly on a pixel
centre -- the difference is at most the depth change across one pixel, which can be large on slanted surfaces. So a
bias is needed.

`UVBackproject`'s `depth_bias` is in **world units** (default 0.02, suited to objects normalized to around 1).
Here it is a fraction **of the bounding sphere radius** instead, because the scale of imported AI meshes
is completely unpredictable: the same 0.02 marks the whole object visible on a model of radius 0.001, and on a model of radius 1000
not a single point visible. The two nodes' parameters mean different things on purpose; both names state their unit.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Drop the silhouette ring
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The ring of pixels at the object's edge is partially covered: rasterization says "hit", but the colour is mixed with the background; and AI-generated
images are likewise least trustworthy at object edges (the edge is where it negotiates with the background). `silhouette_guard`
shrinks the coverage mask inward by n pixels, and elements landing on the removed ring are judged invisible. The trick is the same as
`backproject._erode`, reused directly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Occlusion is **always** computed with the whole geometry, not limited by group
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`group` limits "which elements are written", not "who occludes whom". If only the selected part were rasterized,
the unselected part would become transparent -- and a point hidden behind a wall in front would be judged visible.
Physically, the thing blocking you doesn't vanish just because you didn't select it.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string
from .groups import resolve
from .cop.core import CopImage, DEFAULT_LAYER
from . import render as _rnd
from . import frommap as _fmp
from . import ops as _ops
from .backproject import _erode

CLASSES = (POINT, VERTEX, PRIM)
VISIBILITY = ("all", "frustum", "front", "full")
OCCLUSION = ("element+depth", "element", "depth")
MISSING = ("keep", "zero", "value")

# Default depth bias: 1% of the bounding sphere radius. See the "depth bias" section of the module header
DEPTH_BIAS = 0.01
# Default facing minimum. 0.1 is the measured break-even point for "zero misjudgements on convex shapes", see visible_mask
FACING_MIN = 0.1


# ═══════════════════════════════════════════════════════════════ anchors
def anchors(geo, cls=POINT, normal_attrib="N"):
    """
    Each element gets a **position** and a **normal**, for projection and the facing test.

        point    P                     / point normal
        vertex   P of its point        / vertex normal (falls back to the point normal)
        prim     centre of the prim    / prim normal

    The vertex and point options project to the same positions (the same point); they differ only in **where it is written**:
    attributes like uv live on vertices, so writing uv needs the vertex option.

    The prim option tests occlusion at the centre: a face's centre being visible doesn't mean the whole face is; large faces
    flip as a whole along occlusion boundaries. For finer results use the point option and then promote.
    """
    if cls not in CLASSES:
        raise ValueError(f"class must be one of {CLASSES}")
    # **Empty geometry has no P attribute at all** (Geometry.__init__ doesn't create it when npoints==0).
    # np.asarray(None) directly gives a 0-d array, and a later len() throws
    # "len() of unsized object" -- two layers removed from the real cause, very hard to recognize
    _P = geo.get(POINT, "P")
    P = (np.zeros((0, 3)) if _P is None
         else np.asarray(_P, np.float64).reshape(-1, 3))
    if cls == PRIM:
        if geo.nprims == 0:
            return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0, np.int64)
        C = np.asarray(_ops.prim_centers(geo), np.float64)
        Nrm = np.asarray(_ops.prim_normals(geo), np.float64)
        return C, Nrm, np.full(len(C), -1, np.int64)

    nm = str(normal_attrib or "N").strip() or "N"
    pn = geo.get(POINT, nm)
    if pn is None or is_string(pn) or np.asarray(pn).shape[1] < 3:
        # Without normals, compute a set on the spot. Otherwise front / full would silently degrade to frustum
        # for lack of normals -- the "option selected but has no effect" kind is the hardest to track down
        pn = _ops.compute_normals(geo, add_to="point").get(POINT, nm) \
            if geo.nprims else None
    if cls == POINT:
        Nrm = np.asarray(pn, np.float64)[:, :3] if pn is not None \
            else np.zeros((len(P), 3))
        return P, Nrm, np.arange(len(P), dtype=np.int64)

    vp = np.asarray(geo.vertex_point, np.int64)
    vn = geo.get(VERTEX, nm)
    if vn is not None and not is_string(vn) and np.asarray(vn).shape[1] >= 3:
        Nrm = np.asarray(vn, np.float64)[:, :3]
    elif pn is not None:
        Nrm = np.asarray(pn, np.float64)[:, :3][vp]
    else:
        Nrm = np.zeros((len(vp), 3))
    return P[vp], Nrm, vp


# ═══════════════════════════════════════════════════════════ projection / visibility
def screen_uv(cam, P):
    """
    World coordinates -> (uv (N,2) in 0..1, z (N,)).

    `render.project` gives pixel coordinates; pixel centre i corresponds to sx == i, so
    uv = (sx + 0.5) / W. **This 0.5 can't be omitted**: without it the whole image shifts by half a pixel,
    which at low resolutions (below 512) is visibly off -- the kind of off that looks "close enough".

    Row 0 of screen y is the **bottom** of the frame (consistent with COP's v pointing up); both sides use the same convention,
    so there is no flip here. Flipping would turn the mask upside down -- invisible on symmetric shapes.
    """
    sx, sy, z = _rnd.project(cam, P)
    W, H = float(cam["xres"]), float(cam["yres"])
    uv = np.stack([(sx + 0.5) / W, (sy + 0.5) / H], 1)
    return uv, z


def visible_mask(geo, cam, P, Nrm, mode="full", facing_min=FACING_MIN,
                 depth_bias=DEPTH_BIAS, silhouette_guard=1,
                 border_margin=0.0, rast=None, owner=None, cls=POINT,
                 occlusion="element+depth"):
    """
    -> (mask (N,) bool, uv (N,2), z (N,), info dict)

    The four-step ladder is described in the module header. The **culling reason** of each step is counted separately, because when "not a single point got projected"
    what you most want to know is which step it got stuck at: outside the frame? back-facing? occluded?

    ━━ Occlusion criterion: **element number OR depth**, not depth alone
    With depth alone, elements at grazing angles are misjudged as occluded: the z-buffer stores the z of the triangle at the
    pixel centre, while an element's anchor is almost never at the pixel centre; at grazing angles the depth change across one pixel
    is unbounded, and no fixed bias is enough.

    The "element number" test is exact: rasterization also gives the **triangle number** visible at each pixel,
    and each point knows which triangles it belongs to. The pixel's triangle contains this point = the point
    lies on the visible surface, **no bias needed at all**. The prim option compares `src` (which prim the triangle comes
    from). The two are combined with **OR**: when the numbers don't match, fall back to the depth comparison. The trick was moved over from
    `backproject._visible`, where it was already validated with the round-trip criterion.

    The measured criterion is "**front-facing elements on a convex shape can never be occluded**". A 24x32 sphere, 256^2 frame,
    guard=0, number of front-facing points misjudged as occluded:

        facing_min   depth    element(+depth)
        0.00           38            2
        0.05           16            0
        0.10            4            0
        0.20            0            0

    Two things. First, element is **strictly better**, and by no small margin: depth alone needs
    facing_min raised to 0.2 (dropping 30% of the front-facing points) to reach zero misjudgements. Second, `facing_min`
    defaults to 0.1 rather than 0 -- samples at grazing angles shouldn't be trusted anyway; there the surface length covered by one pixel
    tends to infinity.
    """
    if mode not in VISIBILITY:
        raise ValueError(f"visibility must be one of {VISIBILITY}")
    uv, z = screen_uv(cam, P)
    n = len(P)
    info = {"total": n, "out_frame": 0, "back_facing": 0, "occluded": 0}
    if n == 0:
        return np.zeros(0, bool), uv, z, info
    m = np.ones(n, bool)
    if mode == "all":
        return m, uv, z, info

    b = float(np.clip(border_margin, 0.0, 0.49))
    near = max(float(cam.get("near", 0.01)), 1e-9)
    inside = ((uv[:, 0] >= b) & (uv[:, 0] <= 1.0 - b)
              & (uv[:, 1] >= b) & (uv[:, 1] <= 1.0 - b) & (z > near))
    info["out_frame"] = int((~inside).sum())
    m &= inside
    if mode == "frustum":
        return m, uv, z, info

    # Facing: cosine of the angle between the normal and the direction "from the element to the camera"
    eye = np.asarray(cam["eye"], np.float64)
    d = eye - P
    ln = np.linalg.norm(d, axis=1, keepdims=True)
    d = d / np.maximum(ln, 1e-12)
    nn = np.linalg.norm(Nrm, axis=1, keepdims=True)
    unit = np.where(nn > 1e-12, Nrm / np.maximum(nn, 1e-12), 0.0)
    facing = np.einsum("ij,ij->i", unit, d)
    # With all-zero normals (no normals available) facing is not tested, rather than judging it back-facing -- point clouds without
    # normals are normal, and culling a whole point cloud is the least useful behaviour
    has_n = (nn[:, 0] > 1e-12)
    ok_face = (~has_n) | (facing >= float(facing_min))
    info["back_facing"] = int((m & ~ok_face).sum())
    m &= ok_face
    if mode == "front":
        return m, uv, z, info

    # Occlusion: rasterize once from the camera and compare z. The **whole geometry** takes part in occlusion, see the module header
    if rast is None:
        rast = _rnd.rasterize(geo, cam)
    W, H = int(cam["xres"]), int(cam["yres"])
    hit = rast["hit"]
    if hit.size == 0 or not (hit >= 0).any():
        return m, uv, z, info               # nothing was rasterized: no occlusion test
    cover = (hit >= 0)
    if int(silhouette_guard) > 0:
        cover = _erode(cover, int(silhouette_guard)) > 0
    xi = np.clip(np.round(uv[:, 0] * W - 0.5), 0, W - 1).astype(np.int64)
    yi = np.clip(np.round(uv[:, 1] * H - 0.5), 0, H - 1).astype(np.int64)
    # Bias scaled by the bounding sphere radius, reasons in the module header
    mn, mx = geo.bbox()
    radius = float(np.linalg.norm(np.asarray(mx, np.float64)
                                  - np.asarray(mn, np.float64))) * 0.5
    bias = max(float(depth_bias) * max(radius, 1e-12), 1e-12)
    front = hit[yi, xi]
    near_enough = (front >= 0) & (z <= rast["z"][yi, xi] + bias)
    same = np.zeros(n, bool)
    if occlusion in ("element", "element+depth"):
        # **Look for its own triangle in a 3x3 neighbourhood, not just that one pixel.**
        # An element's projection almost never lands on a pixel centre; elements exactly on the coverage boundary
        # (the four edges of a plane, the silhouette ring) get rounded into an **uncovered** pixel
        # and are judged invisible. Measured: on a 9x9 plane facing the camera, looking at a single pixel
        # marked 17 points on two edges as "occluded" -- on a board with no occluder at all.
        # The cost of a 1-pixel neighbourhood radius: elements occluded within exactly one pixel may slip through,
        # and that scale is what the silhouette guard is there for anyway.
        own = (np.arange(n, dtype=np.int64) if cls == PRIM
               else (np.asarray(owner, np.int64) if owner is not None
                     else None))
        if own is not None:
            src = rast["src"]
            tri = rast["tri"]
            for dy in (0, -1, 1):
                for dx in (0, -1, 1):
                    px = np.clip(xi + dx, 0, W - 1)
                    py = np.clip(yi + dy, 0, H - 1)
                    f2 = hit[py, px]
                    ok = f2 >= 0
                    ft = np.clip(f2, 0, None)
                    if cls == PRIM:
                        if len(src):
                            same |= ok & (src[ft] == own)
                    else:
                        tv = tri[ft]
                        same |= ok & ((tv[:, 0] == own) | (tv[:, 1] == own)
                                      | (tv[:, 2] == own))
    if occlusion == "depth":
        vis = near_enough
    elif occlusion == "element":
        vis = same
    else:
        vis = same | near_enough
    # In the ring removed by the silhouette guard neither criterion counts. **With guard == 0 this layer is not applied at all**:
    # then cover is just "is this pixel covered", and the 3x3 number test is meant to
    # look one cell outward anyway; applying it would defeat it
    if int(silhouette_guard) > 0:
        vis &= cover[yi, xi]
    info["occluded"] = int((m & ~vis).sum())
    m &= vis
    return m, uv, z, info


# ══════════════════════════════════════════════════════════════ main operator
def project_attribute(geo, cam, image, layer=DEFAULT_LAYER, cls=POINT,
                      name="Cd", group="", visibility="full",
                      facing_min=FACING_MIN, depth_bias=DEPTH_BIAS,
                      silhouette_guard=1, border_margin=0.0,
                      occlusion="element+depth", normal_attrib="N", filter="bilinear", border="clamp",
                      channels="", decode="none", scale=1.0, offset=0.0,
                      blend=1.0, missing="keep", missing_value=0.0,
                      visible_group="", mask_group="", threshold=0.5,
                      threshold_channel=0, uv_name=""):
    """
    Projects image through cam onto geo, writing it as an attribute (optionally also writing two groups and a uv).

    Returns (new geometry, stats dict).

    ━━ The two groups are what this node is really for
    `visible_group` is "the part this camera can see" -- multi-camera coverage checks, processing only the front.
    `mask_group` is "the part where the sampled value passes the threshold" -- **wherever AI paints, that is where it fractures / grows grass /
    changes material**. Followed directly by Blast / Voronoi Fracture / PolyExtrude.

    The threshold tests the **value written into the attribute** (after scale / offset), so the number seen in the panel
    is the same as the criterion.

    ━━ missing: what to do with invisible elements
        keep   keep the attribute's original value (0 if the attribute doesn't exist) -- exactly what multi-camera accumulation needs:
               the second camera shouldn't erase what the first one painted
        zero   write 0
        value  write missing_value
    """
    if geo is None:
        return Geometry(), {"total": 0, "visible": 0}
    if not isinstance(image, CopImage):
        raise TypeError("A COPIMAGE is required (use COP Import to convert an IMAGE)")
    if cls not in CLASSES:
        raise ValueError(f"class must be one of {CLASSES}")
    if missing not in MISSING:
        raise ValueError(f"missing must be one of {MISSING}")
    if occlusion not in OCCLUSION:
        raise ValueError(f"occlusion must be one of {OCCLUSION}")
    nm = str(name).strip()
    if not nm:
        raise ValueError("Attribute name cannot be empty")

    out = geo.copy()
    P, Nrm, owner = anchors(geo, cls, normal_attrib)
    n = len(P)
    if n == 0:
        return out, {"total": 0, "visible": 0, "coverage": 0.0}

    m, uv, z, info = visible_mask(geo, cam, P, Nrm, visibility, facing_min,
                                  depth_bias, silhouette_guard, border_margin,
                                  owner=owner, cls=cls, occlusion=occlusion)
    # Clamp uv before sampling: elements outside the frame are already judged invisible, but **are still sampled once**
    # (with missing=keep the original value is used and the sample discarded); without clamping, border=black
    # would give 0 and wrap would give the pixel from the opposite side -- both harder to explain than clamping
    val = _fmp.sample_layer(image, np.clip(uv, 0.0, 1.0), layer, border,
                            filter, channels, decode)
    val = val * float(scale) + float(offset)
    ncomp = val.shape[1]

    cur = geo.get(cls, nm)
    have = (cur is not None and not is_string(cur)
            and np.asarray(cur).shape[0] == n)
    base = np.asarray(cur, np.float64) if have else np.zeros((n, ncomp))
    if base.shape[1] != ncomp:                 # component counts don't match: broadcast the smaller side
        k = max(base.shape[1], ncomp)
        base = (np.repeat(base, k, 1)[:, :k] if base.shape[1] == 1
                else np.pad(base, ((0, 0), (0, k - base.shape[1]))))
        val = (np.repeat(val, k, 1)[:, :k] if ncomp == 1
               else np.pad(val, ((0, 0), (0, k - ncomp))))
        ncomp = k

    b = float(np.clip(blend, 0.0, 1.0))
    if b < 1.0:
        val = base + (val - base) * b

    if missing == "keep":
        miss = base
    elif missing == "zero":
        miss = np.zeros_like(val)
    else:
        miss = np.full_like(val, float(missing_value))
    written = np.where(m[:, None], val, miss)

    sel = resolve(geo, cls, group)
    if not sel.all():
        written = np.where(sel[:, None], written, base)
        m = m & sel                            # unselected elements don't count as "written"
    out.set(cls, nm, written.astype(np.float32), owned=True)

    if str(uv_name).strip():
        out.set(cls, str(uv_name).strip(), uv.astype(np.float32), owned=True)
    if str(visible_group).strip():
        out.set_group(cls, str(visible_group).strip(), m)
    if str(mask_group).strip():
        ch = int(threshold_channel)
        if not (0 <= ch < written.shape[1]):
            raise IndexError(
                f"threshold_channel {ch} out of range: the written attribute has only "
                f"{written.shape[1]} components")
        out.set_group(cls, str(mask_group).strip(),
                      m & (written[:, ch] >= float(threshold)))

    info.update({"visible": int(m.sum()),
                 "coverage": float(m.sum()) / max(n, 1),
                 "components": int(written.shape[1])})
    return out, info
