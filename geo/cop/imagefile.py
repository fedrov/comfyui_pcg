"""
COP Write File (pcg84): write layers to disk in the formats production needs.

ComfyUI's own Save Image only writes 8-bit sRGB PNG -- height maps get quantized to 256 levels (stair steps
on terrain), normals' −1..1 must be encoded by hand first, ORM must be packed into one layer first, tiled terrain must be cut yourself. This node
does all of that in one go, writing files with pure numpy + zlib, no OpenEXR / OpenCV dependency:

  format   png (8 / 16 bit, grey / grey+α / RGB / RGBA)
           exr (half / float, uncompressed scanlines; channels sorted by name per the EXR rules)
           raw (little-endian uint16 or float32, no header -- terrain software's .r16 / .r32)
  channels Channels lists sources separated by spaces, one output channel per item:
               albedo              one 3-channel layer → RGB
               ao roughness metallic   three single-channel layers → packed into RGB (ORM)
               N.x N.y N.z         take components
               albedo mask         3 + 1 → RGBA
               1  0.5              constants
  encode   linear (as is) / srgb (linear → sRGB, for albedo)
  remap    clamp (clamp to 0..1) / signed (−1..1 → 0..1, for normals) / normalize (stretch the **whole image's**
           min..max to full range, range written to the .json next to it -- when tiling all tiles share one range, so they
           match when spliced back) / range (given In Min..In Max)
  normal   Normal Y = -y negates the second channel (DirectX convention); +y is the OpenGL convention
  tiles    Tiles X × Y; with Shared Edge on, adjacent tiles **share the row / column of pixels on their common edge**
           (terrain tiling convention: tile vertices line up, heights at the seam are bit-identical). This requires
           (width − 1) to be divisible by Tiles X (likewise for height); otherwise an error gives the nearest legal size
  filename relative to ComfyUI/output; {index} becomes Index, {tx} {ty} become the tile indices, {tile} = ty·X + tx;
           write {tx:02} to zero-pad to two digits
  orientation  row 0 of an image file is the top; row 0 of COP is the bottom (v up), so it is flipped on write

The .json next to it (with Sidecar on) records format, channel sources, remap range, tiling and original image size --
a 16-bit height map without this range can't tell you what heights 0 and 65535 correspond to. Value Scale is "layer
value × this = real units" (if 1 terrain unit = 2048 m, enter 2048); range_scaled is then in metres.
"""
from __future__ import annotations

import json
import os
import re
import struct
import zlib

import numpy as np

from .pixel import getn

FORMATS = ("png", "exr", "raw")
DEPTHS = ("8", "16", "32")
ENCODES = ("linear", "srgb")
REMAPS = ("clamp", "signed", "normalize", "range")
NORMAL_Y = ("+y", "-y")


# ═══════════════════════════════════════════════════════════ channels
def gather(img, channels):
    """Assemble (H, W, C) float64 per the Channels spec, C ≤ 4. Returns (array, source of each channel)."""
    toks = str(channels).split()
    if not toks:
        raise ValueError("Channels is empty (e.g. albedo / ao roughness metallic / N)")
    H, W = img.yres, img.xres
    cols, src = [], []
    for t in toks:
        try:
            v = float(t)
            cols.append(np.full((H, W), v))
            src.append(t)
            continue
        except ValueError:
            pass
        name, _, comp = t.partition(".")
        if name not in img:
            raise KeyError(f"no layer '{name}' (available: {img.names})")
        a = getn(img, name)
        if comp:
            k = "xyzw".find(comp) if comp in "xyzw" else "rgba".find(comp)
            if k < 0 or k >= a.shape[2]:
                raise ValueError(f"'{t}': {name} only has {a.shape[2]} channels")
            cols.append(a[..., k])
            src.append(t)
        else:
            for k in range(a.shape[2]):
                cols.append(a[..., k])
                src.append(f"{name}.{'xyzw'[k]}" if a.shape[2] > 1 else name)
    if len(cols) > 4:
        raise ValueError(f"at most 4 channels; Channels expands to {len(cols)}: {src}")
    return np.stack(cols, -1).astype(np.float64), src


def srgb_encode(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def remap(a, mode, lo=0.0, hi=1.0):
    """Returns (remapped array, the [lo, hi] actually used)."""
    if mode == "clamp":
        return np.clip(a, 0.0, 1.0), (0.0, 1.0)
    if mode == "signed":
        return np.clip(a * 0.5 + 0.5, 0.0, 1.0), (-1.0, 1.0)
    if mode == "normalize":
        lo, hi = float(a.min()), float(a.max())
    lo, hi = float(lo), float(hi)
    span = hi - lo if hi != lo else 1.0
    return np.clip((a - lo) / span, 0.0, 1.0), (lo, hi)


# ═══════════════════════════════════════════════════════════ PNG
def _chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(a, bits=8):
    """a: (H, W, C) 0..1, row 0 at the top. C = 1 / 2 / 3 / 4. Returns bytes."""
    a = np.asarray(a, np.float64)
    if a.ndim == 2:
        a = a[..., None]
    H, W, C = a.shape
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[C]
    if bits == 16:
        q = np.round(np.clip(a, 0, 1) * 65535).astype(">u2")
    elif bits == 8:
        q = np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)
    else:
        raise ValueError("PNG only supports 8 / 16 bit")
    raw = q.reshape(H, W * C).view(np.uint8).reshape(H, -1)
    # Up filter on every row (subtract the previous row): far better compression for smooth height / normal maps
    up = raw.astype(np.int16)
    up[1:] -= raw[:-1].astype(np.int16)
    filt = (up % 256).astype(np.uint8)
    # row 0 is also marked Up: per the spec row 0's "previous row" is all zeros, so up[0] is just raw[0]
    rows = np.concatenate([np.full((H, 1), 2, np.uint8), filt], 1)
    ihdr = struct.pack(">IIBBBBB", W, H, bits, ctype, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(rows.tobytes(), 6))
            + _chunk(b"IEND", b""))


# ═══════════════════════════════════════════════════════════ EXR
def _attr(name, typ, data):
    return name.encode() + b"\0" + typ.encode() + b"\0" + struct.pack("<i", len(data)) + data


def encode_exr(a, half=True, names=None):
    """
    a: (H, W, C) linear float, row 0 at the top. Uncompressed scanline EXR.
    Channel names default to R G B A (single channel is Y); EXR requires both the channel list and pixel data to be sorted by name.
    """
    a = np.asarray(a, np.float64)
    if a.ndim == 2:
        a = a[..., None]
    H, W, C = a.shape
    if names is None:
        names = ["Y"] if C == 1 else ["R", "G", "B", "A"][:C]
    order = sorted(range(C), key=lambda k: names[k])
    ptype = 1 if half else 2
    ch = b"".join(names[k].encode() + b"\0" + struct.pack("<iBBBBii", ptype, 0, 0, 0, 0, 1, 1)
                  for k in order) + b"\0"
    box = struct.pack("<iiii", 0, 0, W - 1, H - 1)
    hdr = (struct.pack("<ii", 20000630, 2)
           + _attr("channels", "chlist", ch)
           + _attr("compression", "compression", b"\0")
           + _attr("dataWindow", "box2i", box)
           + _attr("displayWindow", "box2i", box)
           + _attr("lineOrder", "lineOrder", b"\0")
           + _attr("pixelAspectRatio", "float", struct.pack("<f", 1.0))
           + _attr("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0))
           + _attr("screenWindowWidth", "float", struct.pack("<f", 1.0))
           + b"\0")
    dt = np.dtype("<f2") if half else np.dtype("<f4")
    line = W * C * dt.itemsize
    table_at = len(hdr)
    first = table_at + 8 * H
    offs = first + np.arange(H, dtype=np.int64) * (8 + line)
    px = np.stack([a[..., k] for k in order], 1).astype(dt)     # (H, C, W)
    blocks = np.zeros((H, 8 + line), np.uint8)
    blocks[:, 0:4] = np.arange(H, dtype="<i4").view(np.uint8).reshape(H, 4)
    blocks[:, 4:8] = np.frombuffer(struct.pack("<i", line) * H, np.uint8).reshape(H, 4)
    blocks[:, 8:] = px.reshape(H, -1).view(np.uint8).reshape(H, line)
    return hdr + offs.astype("<u8").tobytes() + blocks.tobytes()


def encode_raw(a, bits=16):
    """Single-channel raw: little-endian uint16 (0..1 → 0..65535) or float32. Row 0 at the top."""
    a = np.asarray(a, np.float64)
    if a.ndim == 3:
        if a.shape[2] != 1:
            raise ValueError("raw only writes a single channel (height map); give Channels only one item")
        a = a[..., 0]
    if bits == 16:
        return np.round(np.clip(a, 0, 1) * 65535).astype("<u2").tobytes()
    if bits == 32:
        return a.astype("<f4").tobytes()
    raise ValueError("raw only supports 16 / 32 bit")


# ═══════════════════════════════════════════════════════════ tiles
def tile_slices(H, W, tx, ty, shared):
    """
    Returns [(ty_i, tx_i, row slice, column slice)]. Rows follow the **image file** orientation (row 0 at the top),
    so ty = 0 is the top row of tiles -- consistent with terrain software tile numbering (north up).
    """
    tx, ty = max(1, int(tx)), max(1, int(ty))
    out = []
    if shared:
        if (W - 1) % tx or (H - 1) % ty:
            def near(n, k):
                return (n - 1) // k * k + 1
            raise ValueError(
                f"Shared Edge requires (width − 1) divisible by Tiles X and (height − 1) divisible by Tiles Y; "
                f"currently {W}×{H} split {tx}×{ty}. Nearest legal sizes: "
                f"{near(W, tx)}×{near(H, ty)} or {near(W, tx) + tx}×{near(H, ty) + ty}")
        sw, sh = (W - 1) // tx, (H - 1) // ty
        for j in range(ty):
            for i in range(tx):
                out.append((j, i, slice(j * sh, j * sh + sh + 1),
                            slice(i * sw, i * sw + sw + 1)))
    else:
        if W % tx or H % ty:
            raise ValueError(f"{W}×{H} is not divisible by {tx}×{ty}")
        sw, sh = W // tx, H // ty
        for j in range(ty):
            for i in range(tx):
                out.append((j, i, slice(j * sh, (j + 1) * sh),
                            slice(i * sw, (i + 1) * sw)))
    return out


_TILE_TOK = re.compile(r"(?:[_\-.][A-Za-z]{0,2})?\{(?:tx|ty|tile)(?::\d+)?\}")


def strip_tile_tokens(pattern):
    """
    Name of the index / sidecar: drop {tx} {ty} {tile} together with the separator before them and up to two letters
    ("Height_x{tx}_y{ty}" → "Height", "T_Rock_{tx}_BaseColor" → "T_Rock_BaseColor").
    It used to replace the tile indices with all, giving names like Height_xall_yall.json. If nothing is left, falls back to "all".
    """
    s = _TILE_TOK.sub("", str(pattern))
    head, tail = os.path.split(s)
    return s if tail else os.path.join(head, "all")


def _fmt_name(pattern, **kw):
    """{tx} → 3; {tx:02} → 03 (zero-padded to two digits, matching asset names like SM_Rock_03)."""
    def sub(m):
        k, w = m.group(1), m.group(2)
        if k not in kw:
            return m.group(0)
        v = kw[k]
        return str(v).zfill(int(w)) if w else str(v)
    return re.sub(r"\{(\w+)(?::(\d+))?\}", sub, str(pattern))


# ═══════════════════════════════════════════════════════════ main entry
def write(img, outdir, filename="pcg/tex/{index}", channels="C", fmt="png",
          depth="8", encode="linear", mode="clamp", in_min=0.0, in_max=1.0,
          normal_y="+y", tiles_x=1, tiles_y=1, shared_edge=False, index=0,
          sidecar=True, value_scale=1.0):
    """
    Write one image (or several, tiled). Returns (report dict, preview array (H, W, 3) 0..1, row 0 at the top).
    """
    if fmt not in FORMATS:
        raise ValueError(f"Format must be one of {FORMATS}")
    if encode not in ENCODES:
        raise ValueError(f"Encode must be one of {ENCODES}")
    if mode not in REMAPS:
        raise ValueError(f"Remap must be one of {REMAPS}")
    if normal_y not in NORMAL_Y:
        raise ValueError(f"Normal Y must be one of {NORMAL_Y}")
    bits = int(depth)
    if fmt == "png" and bits == 32:
        raise ValueError("PNG has no 32 bit; use exr or raw for float")
    if fmt == "exr" and bits == 8:
        raise ValueError("EXR is float: 16 = half, 32 = float")
    if fmt == "raw" and bits == 8:
        raise ValueError("raw only supports 16 / 32 bit")
    a, src = gather(img, channels)
    if normal_y == "-y" and a.shape[2] >= 2:
        a[..., 1] = -a[..., 1]
    rng = None
    if fmt == "exr" or (fmt == "raw" and bits == 32):
        # float formats are written as is (linear), only the normal flip is applied; srgb makes no sense in float
        data = a
        if mode != "clamp":
            data, rng = remap(a, mode, in_min, in_max)
    else:
        data, rng = remap(a, mode, in_min, in_max)
        if encode == "srgb":
            k = min(3, data.shape[2])
            data = data.copy()
            data[..., :k] = srgb_encode(data[..., :k])
    data = data[::-1]                                  # COP row 0 at the bottom, file row 0 at the top
    H, W = data.shape[:2]
    files = []
    for j, i, rs, cs in tile_slices(H, W, tiles_x, tiles_y, shared_edge):
        name = _fmt_name(filename, index=int(index), tx=i, ty=j,
                         tile=j * max(1, int(tiles_x)) + i)
        ext = {"png": ".png", "exr": ".exr", "raw": ".r16" if bits == 16 else ".r32"}[fmt]
        rel = name + ext
        full = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        t = data[rs, cs]
        if fmt == "png":
            blob = encode_png(t, bits)
        elif fmt == "exr":
            blob = encode_exr(t, half=(bits == 16))
        else:
            blob = encode_raw(t, bits)
        with open(full, "wb") as f:
            f.write(blob)
        files.append({"file": rel.replace("\\", "/"), "tx": i, "ty": j,
                      "width": int(t.shape[1]), "height": int(t.shape[0])})
    vs = float(value_scale)
    rep = {"format": fmt, "bits": bits, "channels": src, "encode": encode,
           "remap": mode, "range": list(rng) if rng else None,
           # layer value × Value Scale = real units (height map: the layer holds values like 0.07, × 2048 gives metres)
           "value_scale": vs,
           "range_scaled": [rng[0] * vs, rng[1] * vs] if rng else None,
           "decode": ("value = range[0] + pixel / max * (range[1] - range[0]);"
                      " × value_scale"),
           "normal_y": normal_y,
           "source_size": [int(W), int(H)],
           "tiles": [max(1, int(tiles_x)), max(1, int(tiles_y))],
           "shared_edge": bool(shared_edge), "files": files}
    if sidecar:
        side = _fmt_name(strip_tile_tokens(filename), index=int(index))
        with open(os.path.join(outdir, side + ".json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        rep["sidecar"] = (side + ".json").replace("\\", "/")
    pv = data[..., :3] if data.shape[2] >= 3 else np.repeat(data[..., :1], 3, -1)
    return rep, np.clip(pv, 0, 1).astype(np.float32)
