"""
pcg84: nodes used for writing files / exporting / the asset pipeline, and the bugs fixed there.

The references never rely on the implementation under test:
  COP Write File   PNG read back with PIL (8-bit RGB/RGBA, 16-bit grayscale bit-exact = round(x·65535)); 16-bit RGB read back with
                   a decoder written separately from the PNG spec (all five row filters supported); EXR read back with a parser written separately
                   from the OpenEXR spec (cross-checked again when OpenEXR / OpenCV are installed); raw with np.fromfile.
                   Orientation (COP row 0 at the bottom → file row 0 at the top; negative control: without the flip it doesn't match), sRGB encoding
                   (0.5 → 188), signed, normalize range and value_scale, ORM packing order,
                   Normal Y = −y flips only the second channel, tile shared edges bit-identical, error on invalid sizes
  Export Mesh      parses glb itself: POSITION min/max, indices in range, unit-length normals, tangent ⟂ normal and w = ±1,
                   uv v flipped (glTF origin is top-left), Split / File Attribute, material slots;
                   on a flat grid with uv = (x, −z) the tangent is exactly +X, consistent with COP Bake's tangent layer;
                   OBJ vt / vn / usemtl; meshio reads uv back unchanged; normals recomputed when N contains zero vectors
                   (run once more with 0 errors when Khronos gltf-validator is installed)
  Export Instances the table's transforms applied to the asset = the points laid out by Copy to Points (per point); after the axis swap x −z y
                   A·(Copy to Points result) = new table applied to A·asset; Euler angles R = Rz·Ry·Rx;
                   tiling by x, z puts only each tile's own points in each tile
  PolyReduce       Preserve UVs: every corner's uv is the uv of some wedge on the same point of the original mesh, triangles
                   don't cross UV islands, it really reduced; negative control: without it most corners' uv don't match
  UV Layout        raster: no overlap, all within 0..1, islands are rigid copies of the originals (up to multiples of 90°) × uniform scale;
                   on a bunch of right-triangle islands, sheet utilization is much higher than shelf
  UV Flatten       ARAP: on a hemisphere / 60° cap, area distortion much smaller than plain LSCM; a developable cylinder strip is isometric; multiple islands
                   have consistent texel density (UV area / 3D area equal across islands -- negative control: the old per-island normalization differed by dozens of times)
  Other            Wrangle sprintf / str; IsoSurface multi-line code = single-line expression; Transform group
                   written as a prim attribute expression; in group expressions (N,) vs (N,1) no longer broadcasts to N×N (negative control); ray_cast
                   chunked and unchunked bit-identical; bake edge padding computes only that ring, matching the old whole-image roll result
"""
import json
import os
import struct
import sys
import tempfile
import zlib

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo import wrangle as WR               # noqa: E402
from comfyui_pcg.geo import meshexport as MX            # noqa: E402
from comfyui_pcg.geo import instances as INS            # noqa: E402
from comfyui_pcg.geo import polyreduce as PRD           # noqa: E402
from comfyui_pcg.geo import uvlayout as UVL             # noqa: E402
from comfyui_pcg.geo import uvflatten as UVF            # noqa: E402
from comfyui_pcg.geo import spatial as SP               # noqa: E402
from comfyui_pcg.geo import meshio                      # noqa: E402
from comfyui_pcg.geo.groups import resolve              # noqa: E402
from comfyui_pcg.geo.cop import CopImage                # noqa: E402
from comfyui_pcg.geo.cop import imagefile as IF         # noqa: E402
from comfyui_pcg.geo.cop.pixel import put, getn         # noqa: E402
from comfyui_pcg.geo.core import POINT, PRIM, VERTEX, Geometry  # noqa: E402
from comfyui_pcg import NODE_CLASS_MAPPINGS as MAP      # noqa: E402


def N(name, **kw):
    """Call with the node's defaults, changing only the inputs given in kw (independent of positional order)."""
    c = MAP["PCG_" + name]
    a = {}
    for k, v in (c.INPUT_TYPES().get("required") or {}).items():
        t = v[0]
        o = v[1] if len(v) > 1 and isinstance(v[1], dict) else {}
        if isinstance(t, (list, tuple)):
            a[k] = o.get("default", t[0])
        elif "default" in o:
            a[k] = o["default"]
    a.update(kw)
    r = getattr(c(), c.FUNCTION)(**a)
    return r.get("result", r) if isinstance(r, dict) else r

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag):
    try:
        fn()
    except Exception as e:                               # noqa: BLE001
        check(name, frag in str(e), str(e)[:80])
        return
    check(name, False, "did not raise")


def sec(t):
    print(f"\n── {t}")


def A(g, name, cls=POINT):
    return np.asarray(g.get(cls, name), np.float64)


TMP = tempfile.mkdtemp(prefix="pcg_ex_")


# ═══════════════════════════════════════════════════ Independent readers
def png_decode(path):
    """Decode per the PNG spec (IHDR / IDAT / five row filters), return an (H, W, C) integer array."""
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, hdr = 8, b"", None
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        crc = struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, "CRC"
        if tag == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    W, H, bits, ctype = hdr[0], hdr[1], hdr[2], hdr[3]
    C = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    bpp = C * bits // 8
    stride = W * bpp
    raw = zlib.decompress(idat)
    out = np.zeros((H, stride), np.int64)
    prev = np.zeros(stride, np.int64)
    for y in range(H):
        f = raw[y * (stride + 1)]
        line = np.frombuffer(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)],
                             np.uint8).astype(np.int64)
        cur = np.zeros(stride, np.int64)
        for x in range(stride):
            a = cur[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 0:
                p = 0
            elif f == 1:
                p = a
            elif f == 2:
                p = b
            elif f == 3:
                p = (a + b) // 2
            else:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            cur[x] = (line[x] + p) % 256
        out[y] = cur
        prev = cur
    if bits == 16:
        out = out.reshape(H, W * C, 2)
        out = out[..., 0] * 256 + out[..., 1]
    return out.reshape(H, W, C)


def exr_decode(path):
    """Read an uncompressed scanline EXR per the OpenEXR spec: returns {channel name: (H, W) float}."""
    d = open(path, "rb").read()
    assert struct.unpack("<i", d[:4])[0] == 20000630
    p = 8
    attrs = {}
    while d[p] != 0:
        e = d.index(b"\0", p)
        name = d[p:e].decode()
        e2 = d.index(b"\0", e + 1)
        typ = d[e + 1:e2].decode()
        n = struct.unpack("<i", d[e2 + 1:e2 + 5])[0]
        attrs[name] = (typ, d[e2 + 5:e2 + 5 + n])
        p = e2 + 5 + n
    p += 1
    chl = attrs["channels"][1]
    chans, q = [], 0
    while chl[q] != 0:
        e = chl.index(b"\0", q)
        nm = chl[q:e].decode()
        pt = struct.unpack("<i", chl[e + 1:e + 5])[0]
        chans.append((nm, pt))
        q = e + 17
    assert attrs["compression"][1] == b"\0"
    x0, y0, x1, y1 = struct.unpack("<iiii", attrs["dataWindow"][1])
    W, H = x1 - x0 + 1, y1 - y0 + 1
    offs = struct.unpack(f"<{H}Q", d[p:p + 8 * H])
    out = {nm: np.zeros((H, W)) for nm, _ in chans}
    for y, o in enumerate(offs):
        yy, sz = struct.unpack("<ii", d[o:o + 8])
        b = o + 8
        for nm, pt in chans:
            dt = "<f2" if pt == 1 else "<f4"
            k = W * (2 if pt == 1 else 4)
            out[nm][yy] = np.frombuffer(d[b:b + k], dt)
            b += k
    return out


def glb_parse(path):
    d = open(path, "rb").read()
    magic, ver, total = struct.unpack("<III", d[:12])
    assert magic == 0x46546C67 and ver == 2 and total == len(d)
    jl = struct.unpack("<I", d[12:16])[0]
    js = json.loads(d[20:20 + jl])
    bl = struct.unpack("<I", d[20 + jl:24 + jl])[0]
    binb = d[28 + jl:28 + jl + bl]

    def acc(i):
        a = js["accessors"][i]
        v = js["bufferViews"][a["bufferView"]]
        dt = "<f4" if a["componentType"] == 5126 else "<u4"
        k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        arr = np.frombuffer(binb[v["byteOffset"]:v["byteOffset"] + v["byteLength"]], dt)
        return arr.reshape(a["count"], k) if k > 1 else arr, a
    return js, acc


def cop(W, H, **layers):
    img = CopImage(W, H)
    for k, v in layers.items():
        put(img, k, np.asarray(v, np.float64).reshape(H, W, -1), img if len(img) else None)
    return img


# ═══════════════════════════════════════════════════ 1. COP Write File
sec("COP Write File:PNG / EXR / raw")
from PIL import Image                                    # noqa: E402
rng = np.random.default_rng(3)
Hh, Ww = 6, 11
h = rng.random((Hh, Ww))
c3 = rng.random((Hh, Ww, 3))
img = cop(Ww, Hh, h=h, c=c3, a=rng.random((Hh, Ww)))
IF.write(img, TMP, "t/h16", "h", "png", "16")
p16 = np.asarray(Image.open(os.path.join(TMP, "t/h16.png")))
check("16-bit grayscale: PIL readback bit-exact = round(x·65535), row 0 = topmost COP row",
      p16.shape == (Hh, Ww) and np.array_equal(p16, np.round(h[::-1] * 65535)))
check("  negative control: without the vertical flip it doesn't match", not np.array_equal(p16, np.round(h * 65535)))
IF.write(img, TMP, "t/c8", "c", "png", "8")
p8 = np.asarray(Image.open(os.path.join(TMP, "t/c8.png")).convert("RGB"))
check("8-bit RGB: PIL readback bit-exact = round(x·255)", np.array_equal(p8, np.round(c3[::-1] * 255)))
IF.write(img, TMP, "t/c16", "c a", "png", "16")
d16 = png_decode(os.path.join(TMP, "t/c16.png"))
check("16-bit RGBA (separate decoder): channels in Channels order, a is 4th",
      d16.shape == (Hh, Ww, 4) and np.array_equal(d16[..., :3], np.round(c3[::-1] * 65535))
      and np.array_equal(d16[..., 3], np.round(getn(img, "a")[::-1, :, 0] * 65535)))
IF.write(cop(1, 1, s=[[0.5]]), TMP, "t/s", "s s s", "png", "8", encode="srgb")
sv = np.asarray(Image.open(os.path.join(TMP, "t/s.png")).convert("RGB"))[0, 0]
check("sRGB encoding: linear 0.5 → 188 (1.055·0.5^(1/2.4) − 0.055)", tuple(sv) == (188, 188, 188), sv)
nrm = np.zeros((Hh, Ww, 3))
nrm[..., 0], nrm[..., 1], nrm[..., 2] = 0.3, -0.4, np.sqrt(1 - 0.25)
imn = cop(Ww, Hh, N=nrm)
rep_s, _ = IF.write(imn, TMP, "t/gl", "N", "png", "16", mode="signed")
IF.write(imn, TMP, "t/dx", "N", "png", "16", mode="signed", normal_y="-y")
gl, dx = png_decode(os.path.join(TMP, "t/gl.png")), png_decode(os.path.join(TMP, "t/dx.png"))
check("signed: −1..1 → 0..1; Normal Y = −y flips only the second channel",
      np.allclose(gl[..., 1] / 65535, 0.3, atol=2e-5)
      and np.allclose(dx[..., 1] / 65535, 0.7, atol=2e-5)
      and np.array_equal(gl[..., 0], dx[..., 0]) and np.array_equal(gl[..., 2], dx[..., 2]))
check("  signed sidecar range is [−1, 1] (decoding needs to know 0 is in the middle)", rep_s["range"] == [-1.0, 1.0])
hb = cop(Ww, Hh, h=3.0 + 4.0 * h)                          # values in 3..7: not within 0..1
rep_b, _ = IF.write(hb, TMP, "t/hb", "h", "png", "16", mode="normalize")
db = png_decode(os.path.join(TMP, "t/hb.png"))[..., 0] / 65535
check("  normalize stretches to this image's min/max (values in 3..7 don't get clipped to solid white)",
      np.allclose(rep_b["range"], [3 + 4 * h.min(), 3 + 4 * h.max()])
      and db.min() == 0 and db.max() == 1)
rep, _ = IF.write(img, TMP, "t/hn", "h", "png", "16", mode="normalize", value_scale=2048)
side = json.load(open(os.path.join(TMP, "t/hn.json"), encoding="utf-8"))
dn = png_decode(os.path.join(TMP, "t/hn.png"))[..., 0] / 65535
back = side["range"][0] + dn * (side["range"][1] - side["range"][0])
check("normalize: decoding with the range in the .json = original values (within 16-bit quantization); range_scaled = range × 2048",
      np.abs(back - h[::-1]).max() < 1e-4
      and np.allclose(side["range_scaled"], np.array(side["range"]) * 2048))
IF.write(img, TMP, "t/e", "c a", "exr", "32")
ex = exr_decode(os.path.join(TMP, "t/e.exr"))
check("EXR float (separate parser): channels stored sorted by name, R G B A each bit-exact",
      sorted(ex) == ["A", "B", "G", "R"] and np.allclose(ex["R"], c3[::-1, :, 0], atol=1e-7)
      and np.allclose(ex["A"], getn(img, "a")[::-1, :, 0], atol=1e-7))
IF.write(img, TMP, "t/eh", "h", "exr", "16")
exh = exr_decode(os.path.join(TMP, "t/eh.exr"))
check("EXR half: single channel is named Y, error within half precision", list(exh) == ["Y"]
      and np.abs(exh["Y"] - h[::-1]).max() < 1e-3)
try:
    import OpenEXR                                      # noqa: F401
    f = OpenEXR.File(os.path.join(TMP, "t/e.exr"))
    px = list(f.channels().values())[0].pixels
    check("  official OpenEXR library readback matches", np.allclose(px[..., 0], c3[::-1, :, 0], atol=1e-7))
except ImportError:
    print("  (OpenEXR not installed, skipping official library cross-check)")
IF.write(img, TMP, "t/r", "h", "raw", "16")
r16 = np.fromfile(os.path.join(TMP, "t/r.r16"), "<u2").reshape(Hh, Ww)
check("raw r16: little-endian uint16, row 0 at the top", np.array_equal(r16, np.round(h[::-1] * 65535)))
err("PNG has no 32-bit", lambda: IF.write(img, TMP, "t/x", "h", "png", "32"), "32")
err("more than 4 channels raises", lambda: IF.write(img, TMP, "t/x", "c c", "png", "8"), "4")

sec("COP Write File: tiling")
big = rng.random((17, 25))
rep, _ = IF.write(cop(25, 17, h=big), TMP, "t/tile_{tx}_{ty}", "h", "png", "16",
                  tiles_x=4, tiles_y=2, shared_edge=True)
tiles = {(f["tx"], f["ty"]): png_decode(os.path.join(TMP, f["file"]))[..., 0]
         for f in rep["files"]}
check("Shared Edge: 25×17 split 4×2 → each tile 7×9 (adjacent tiles share a row / column)",
      len(tiles) == 8 and all(t.shape == (9, 7) for t in tiles.values()))
check("  shared edge of left/right neighbours bit-identical, same for top/bottom",
      all(np.array_equal(tiles[(i, j)][:, -1], tiles[(i + 1, j)][:, 0])
          for i in range(3) for j in range(2))
      and all(np.array_equal(tiles[(i, 0)][-1], tiles[(i, 1)][0]) for i in range(4)))
flip = np.round(big[::-1] * 65535)
check("  ty = 0 is the top row (north), top-left of tile (1, 0) = original row 0 column 6",
      tiles[(1, 0)][0, 0] == flip[0, 6] and tiles[(0, 1)][0, 0] == flip[8, 0])
check("  sidecar name drops the tile tokens: t/tile_{tx}_{ty} → t/tile.json (used to be tile_all_all)",
      rep["sidecar"] == "t/tile.json" and os.path.exists(os.path.join(TMP, "t/tile.json")))
check("  token-stripping rule: removes the preceding separator and up to two letters with it; falls back to all if empty",
      [IF.strip_tile_tokens(x) for x in ("a/Height_x{tx}_y{ty}", "T_Rock_{tx}_BaseColor",
                                        "Rock{tx}", "a/{tx}", "t{tile}.v", "R_{tx:02}_N", "H_tx{tx}")]
      == ["a/Height", "T_Rock_BaseColor", "Rock", os.path.join("a", "all"), "t.v", "R_N", "H"])
check("  {tx:02} zero-pads; unknown {xx} left as is",
      IF._fmt_name("T_{tx:02}_{ty}_{zz}", tx=3, ty=1) == "T_03_1_{zz}")
err("  invalid size raises and gives a valid size", lambda: IF.write(
    cop(24, 17, h=big[:, :24]), TMP, "t/x{tx}", "h", "png", "16", tiles_x=4, tiles_y=2,
    shared_edge=True), "25")

# ═══════════════════════════════════════════════════ 2. Export Mesh
sec("Export Mesh:glTF / OBJ")
g = build.grid(4.0, 2.0, 5, 3)                          # zx plane, facing up
P = A(g, "P")
uvv = np.stack([P[g.vertex_point, 0], -P[g.vertex_point, 2]], 1)  # u = x, v = −z
g.set(VERTEX, "uv", uvv.astype(np.float32))
half = (P[:, 0] > 0)[g.vertex_point]
names = np.where(np.repeat(np.add.reduceat(half, g.prim_offset[:-1]) >= 2,
                           g.prim_sizes())[g.prim_offset[:-1]], "right", "left")
g.set(PRIM, "name", names[:, None])
mats = np.array(["M_A" if i % 2 else "M_B" for i in range(g.nprims)])
g.set(PRIM, "material", mats[:, None])
paths = MX.export(g, os.path.join(TMP, "m/grid"), "glb", "name", "", 1.0)
js, acc = glb_parse(paths[0])
check("one file, one node for each of the two Split Attribute values", [n["name"] for n in js["nodes"]]
      == ["left", "right"] or sorted(n["name"] for n in js["nodes"]) == ["left", "right"])
check("  each mesh split into two primitives by material, material name = attribute value",
      all(len(m["primitives"]) == 2 for m in js["meshes"])
      and sorted(m["name"] for m in js["materials"]) == ["M_A", "M_B"])
okp = True
for m in js["meshes"]:
    for pr in m["primitives"]:
        pos, a = acc(pr["attributes"]["POSITION"])
        idx, _ = acc(pr["indices"])
        nn, _ = acc(pr["attributes"]["NORMAL"])
        tt, _ = acc(pr["attributes"]["TANGENT"])
        t0, _ = acc(pr["attributes"]["TEXCOORD_0"])
        okp &= np.allclose(a["min"], pos.min(0)) and np.allclose(a["max"], pos.max(0))
        okp &= idx.max() < len(pos) and len(idx) % 3 == 0
        okp &= np.allclose(np.linalg.norm(nn, axis=1), 1, atol=1e-6)
        okp &= np.allclose((tt[:, :3] * nn).sum(1), 0, atol=1e-6) and set(np.unique(tt[:, 3])) <= {-1.0, 1.0}
        # uv: v is flipped -- u = x, 1 − v = −z
        okp &= np.allclose(t0[:, 0], pos[:, 0], atol=1e-6) and np.allclose(1 - t0[:, 1], -pos[:, 2], atol=1e-6)
        okp &= np.allclose(tt[:, :3], [1, 0, 0], atol=1e-6) and np.allclose(nn, [0, 1, 0], atol=1e-6)
check("  min/max, indices in range, unit-length normals, tangent ⟂ normal and w = ±1, v flipped", okp)
check("  on a plane with uv = (x, −z): tangent exactly +X, normal = +Y", okp)
# cross-check with COP Bake Textures' tangent layer (same corner_frames)
from comfyui_pcg.geo.cop.geoimg import bake_textures   # noqa: E402
g01 = g.copy()
g01.set(VERTEX, "uv", ((uvv - uvv.min(0)) / np.ptp(uvv, axis=0).max()).astype(np.float32))
bimg, _ = bake_textures(g01, None, 64, 64)
tl = getn(bimg, "tangent")[getn(bimg, "mask")[..., 0] > 0.5]
check("  COP Bake's tangent layer is also +X (same scheme as the exported TANGENT)",
      np.allclose(tl, [1, 0, 0], atol=1e-6))
paths = MX.export(g, os.path.join(TMP, "m/{name}"), "glb", "name", "name", 1.0)
check("File Attribute + {name}: one file per value, file name is the value",
      sorted(os.path.basename(p) for p in paths) == ["left.glb", "right.glb"])
rb = meshio.load(os.path.join(TMP, "m/left.glb"))
rb = rb[0] if isinstance(rb, tuple) else rb
uvr = A(rb, "uv", VERTEX)
Pr = A(rb, "P")
check("  meshio readback: uv unchanged (flipped back on read) = (x, −z)",
      np.allclose(uvr[:, 0], Pr[rb.vertex_point, 0], atol=1e-6)
      and np.allclose(uvr[:, 1], -Pr[rb.vertex_point, 2], atol=1e-6))
po = MX.export(g, os.path.join(TMP, "m/grid"), "obj", "name", "", 1.0)
txt = open(po[0], encoding="utf-8").read()
nv = sum(1 for l in txt.splitlines() if l.startswith("v "))
nvt = sum(1 for l in txt.splitlines() if l.startswith("vt "))
faces = [l for l in txt.splitlines() if l.startswith("f ")]
okf = all(int(t.split("/")[0]) <= nv and int(t.split("/")[1]) <= nvt
          for f in faces for t in f.split()[1:])
check("OBJ: v / vt / vn, face references in range, both o and usemtl present",
      nv == g.npoints and len(faces) == g.nprims and okf
      and txt.count("\no ") == 2 and "usemtl M_A" in txt)
ro = meshio.load(po[0])
ro = ro[0] if isinstance(ro, tuple) else ro
check("  meshio reading OBJ back: uv unchanged", np.allclose(A(ro, "uv", VERTEX)[:, 1],
                                          -A(ro, "P")[ro.vertex_point, 2], atol=1e-6))
gz = g.copy()
gz.set(POINT, "N", np.zeros((g.npoints, 3), np.float32))
Nz = MX.corner_normals(gz)
check("N that comes in as zero vectors is recomputed (points newly created by convex hull, boolean)",
      np.allclose(np.linalg.norm(Nz, axis=1), 1) and np.allclose(Nz, [0, 1, 0], atol=1e-6))
import shutil                                            # noqa: E402
import subprocess                                        # noqa: E402
vjs = "/tmp/gv/v.mjs"
if shutil.which("node") and os.path.exists(vjs):
    out = subprocess.run(["node", vjs, os.path.join(TMP, "m/left.glb")],
                         capture_output=True, text=True).stdout
    try:
        vr = json.loads(out)
        check("  Khronos gltf-validator: 0 errors 0 warnings (only info left)", vr["errors"] == 0 and vr["warnings"] == 0,
              vr["messages"][:2])
    except ValueError:
        print("  (gltf-validator output unreadable, skipped)")
else:
    print("  (gltf-validator not installed, skipped)")

# ── Textures (pcg84)
from PIL import Image as _PI                               # noqa: E402
os.makedirs(os.path.join(TMP, "tx/tex"), exist_ok=True)
for m_ in ("M_A", "M_B"):
    for k_ in ("BaseColor", "Normal", "ORM"):
        _PI.new("RGB", (4, 4), (128, 128, 255)).save(os.path.join(TMP, f"tx/tex/T_{m_}_{k_}.png"))
TX = "basecolor = tex/T_{material}_BaseColor.png\n# comment\nnormal = tex/T_{material}_Normal.png\n" \
     "orm = tex/T_{material}_ORM.png"
pt = MX.export(g, os.path.join(TMP, "tx/grid"), "glb", "name", "", 1.0, textures=TX,
               texture_materials="M_A")
jt, _ = glb_parse(pt[0])
mt = {m["name"]: m for m in jt["materials"]}
uris = [jt["images"][jt["textures"][i]["source"]]["uri"] for i in range(len(jt["textures"]))]
ma = mt["M_A"]
pbr = ma["pbrMetallicRoughness"]
check("Textures: matching material slots get baseColor / normal / ORM, uri relative to the glb, {material} replaced by the slot name",
      sorted(uris) == ["tex/T_M_A_BaseColor.png", "tex/T_M_A_Normal.png", "tex/T_M_A_ORM.png"]
      and uris[pbr["baseColorTexture"]["index"]] == "tex/T_M_A_BaseColor.png"
      and uris[ma["normalTexture"]["index"]] == "tex/T_M_A_Normal.png")
check("  the same ORM image is used as occlusion (R) and metallicRoughness (G, B), metallic factor = 1",
      ma["occlusionTexture"]["index"] == pbr["metallicRoughnessTexture"]["index"]
      and uris[ma["occlusionTexture"]["index"]] == "tex/T_M_A_ORM.png"
      and pbr["metallicFactor"] == 1.0)
check("  slots not matching Texture Materials (M_B) only get factors, no images, metallic factor 0",
      "baseColorTexture" not in mt["M_B"]["pbrMetallicRoughness"]
      and "normalTexture" not in mt["M_B"]
      and mt["M_B"]["pbrMetallicRoughness"]["metallicFactor"] == 0.0)
check("  sampler is REPEAT (textures can tile)",
      jt["samplers"][0]["wrapS"] == 10497 and jt["samplers"][0]["wrapT"] == 10497)
check("  spaces in paths are URI-encoded",
      MX._uri("a b/T x.png") == "a%20b/T%20x.png")
check("  slot names are case-insensitive, underscores optional (Base_Color / BaseColour both accepted)",
      MX.parse_textures("Base_Color = a.png\nNORMAL=b.png\nBaseColour = c.png")
      == {"basecolor": "c.png", "normal": "b.png"})
je, _ = glb_parse(MX.export(g, os.path.join(TMP, "tx/em"), "glb", "", "", 1.0,
                            textures="emissive = tex/E_{material}.png")[0])
mE = je["materials"][0]
check("  emissive: attaches emissiveTexture, emissiveFactor = 1 (glTF default is 0, black if not given)",
      "emissiveTexture" in mE and mE["emissiveFactor"] == [1.0, 1.0, 1.0]
      and "baseColorTexture" not in mE["pbrMetallicRoughness"])
gnu = g.copy()
for _c in (VERTEX, POINT):
    gnu.attribs[_c].pop("uv", None)
jn, _ = glb_parse(MX.export(gnu, os.path.join(TMP, "tx/nouv"), "glb", "", "", 1.0, textures=TX)[0])
check("  no textures attached without uv (otherwise glTF references a nonexistent TEXCOORD_0 and the validator errors)",
      "images" not in jn and all("baseColorTexture" not in m["pbrMetallicRoughness"]
                                 for m in jn["materials"]))
err("  misspelled slot name raises", lambda: MX.parse_textures("albedo = x.png"), "basecolor")
err("  missing = raises", lambda: MX.parse_textures("basecolor x.png"), "=")
pt2 = MX.export(g, os.path.join(TMP, "tx/grid"), "obj", "name", "", 1.0, textures=TX)
mtl = open(os.path.join(TMP, "tx/grid.mtl"), encoding="utf-8").read()
objt = open(pt2[0], encoding="utf-8").read()
check("  OBJ: writes mtllib + a .mtl of the same name, map_Kd / norm point to the textures",
      "mtllib grid.mtl" in objt and "newmtl M_A" in mtl and "newmtl M_B" in mtl
      and "map_Kd tex/T_M_B_BaseColor.png" in mtl and "norm tex/T_M_A_Normal.png" in mtl)
if shutil.which("node") and os.path.exists(vjs):
    vr = json.loads(subprocess.run(["node", vjs, pt[0]], capture_output=True, text=True).stdout)
    check("  gltf-validator (reading the external textures too): 0 errors 0 warnings", vr["errors"] == 0
          and vr["warnings"] == 0, vr["messages"][:3])
    os.remove(os.path.join(TMP, "tx/tex/T_M_A_ORM.png"))
    vr = json.loads(subprocess.run(["node", vjs, pt[0]], capture_output=True, text=True).stdout)
    check("    negative control: delete one texture, the validator errors", vr["errors"] > 0, vr["messages"][:1])

# ═══════════════════════════════════════════════════ 3. Export Instances
sec("Export Instances")
pts = Geometry.from_points(rng.normal(size=(20, 3)).astype(np.float32) * 5)
q = rng.normal(size=(20, 4))
q /= np.linalg.norm(q, axis=1, keepdims=True)
pts.set(POINT, "orient", q.astype(np.float32))
pts.set(POINT, "pscale", (0.5 + rng.random((20, 1))).astype(np.float32))
_sc = 0.5 + rng.random((20, 3))
_sc[0, 0] *= -1                 # one mirrored (determinant < 0): split into pure rotation × scale with a negative sign
_sc[1, 2] *= -1
pts.set(POINT, "scale", _sc.astype(np.float32))
pts.set(POINT, "name", np.array([f"a{i % 3}" for i in range(20)])[:, None])
asset = build.box((1.0, 2.0, 0.5), (0.3, 0.1, -0.2), (2, 2, 2))
Pa = A(asset, "P")
cols, rows, _ = INS.table(pts, "name")
copies = N("CopyToPoints", source=asset, points=pts)[0]
Pc = A(copies, "P").reshape(20, len(Pa), 3)
from comfyui_pcg.geo.xform import quat_to_mat          # noqa: E402


def apply(rows, Pa):
    out = []
    for r in rows:
        pos, qq, sc = np.array(r[1:4], float), np.array(r[4:8], float), np.array(r[11:14], float)
        out.append(Pa * sc @ quat_to_mat(qq[None])[0].T + pos)
    return np.array(out)
check("the table's position · quaternion · scale applied to the asset = the points laid out by Copy to Points (per point, incl. the two mirrored ones)",
      np.allclose(apply(rows, Pa), Pc, atol=1e-4))
qn = np.array([r[4:8] for r in rows], float)
check("  quaternions unit length; the two mirrored ones have a negative scale (rotation is still a pure rotation)",
      np.allclose(np.linalg.norm(qn, axis=1), 1, atol=1e-6)
      and sum(1 for r in rows if min(r[11:14]) < 0) == 2)
from comfyui_pcg.geo.instances import parse_axis_map, euler_xyz   # noqa: E402
Am = parse_axis_map("x -z y")
cols2, rows2, _ = INS.table(pts, "name", axis_map="x -z y", unit_scale=100.0)
check("axis swap x −z y + meters→centimeters: new table applied to 100·A·asset (the asset is also in cm in the engine) = 100·A·(Copy to Points result)",
      np.allclose(apply(rows2, (Pa @ Am.T) * 100), (Pc @ Am.T) * 100, atol=1e-2))
R = quat_to_mat(np.array([r[4:8] for r in rows], float))
eu = np.radians(np.array([r[8:11] for r in rows], float))


def rx(a):
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def ry(a):
    return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])


def rz(a):
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
check("Euler angles (degrees) rebuilt via R = Rz·Ry·Rx give the same rotation",
      all(np.allclose(rz(e[2]) @ ry(e[1]) @ rx(e[0]), Rm, atol=1e-6) for e, Rm in zip(eu, R)))
# random rotations + hand-picked ones: Y-only ±180 / 170 / −100, X by 120, gimbal lock (ry = ±90)
Rs = [ry(np.pi), ry(-np.pi * 0.999), ry(np.radians(170)), ry(np.radians(-100)),
      rx(np.radians(120)), rz(0.3) @ ry(np.pi / 2) @ rx(0.2), ry(-np.pi / 2) @ rx(1.0)]
Rs += [quat_to_mat(qq[None] / np.linalg.norm(qq))[0] for qq in rng.normal(size=(200, 4))]
Rs = np.array(Rs)
Es = np.radians(euler_xyz(Rs))
check("  all kinds of rotations (incl. gimbal lock, ±180°) rebuild to the same rotation",
      all(np.allclose(rz(e[2]) @ ry(e[1]) @ rx(e[0]), Rm, atol=1e-6) for e, Rm in zip(Es, Rs)))
check("  Y-only rotations written as (0, ry, 0): 180° is not written as (180, 0, 180)",
      np.allclose(np.degrees(Es[:4]), [[0, 180, 0], [0, -179.82, 0], [0, 170, 0], [0, -100, 0]],
                  atol=0.01), np.round(np.degrees(Es[:4]), 2).tolist())
check("  of the two solutions, pick the one where |rx| and |rz| don't both exceed 90°",
      not ((np.abs(Es[:, 0]) > np.pi / 2 + 1e-9) & (np.abs(Es[:, 2]) > np.pi / 2 + 1e-9)).any())
rep = INS.write(pts, TMP, "i/t_{tx}_{ty}", "csv", "name", "", "x y z", 1.0, 4.0)
okt = True
for f in rep["files"]:
    tx, ty = f["tile"]
    lines = open(os.path.join(TMP, f["file"]), encoding="utf-8").read().splitlines()[1:]
    for l in lines:
        v = l.split(",")
        okt &= int(np.floor(float(v[1]) / 4)) == tx and int(np.floor(float(v[3]) / 4)) == ty
check("tiling by x, z: each tile file has only its own points, totals match, a separate _index.json is written",
      okt and sum(f["count"] for f in rep["files"]) == 20
      and os.path.exists(os.path.join(TMP, rep["index_file"])))
check("  the index is called i/t_index.json", rep["index_file"] == "i/t_index.json")

# ═══════════════════════════════════════════════════ 4. PolyReduce Preserve UVs
sec("PolyReduce:Preserve UVs")
sph = build.sphere(1.0, 24, 16)
sp = N("UVAutoSeams", geo=sph, mode="charts")[0]
sp = UVF.flatten(sp, "seams")
sp = UVL.layout(sp)
isl0 = np.repeat(UVL.islands(sp), sp.prim_sizes())
P0, uv0, vp0 = A(sp, "P"), A(sp, "uv", VERTEX), sp.vertex_point
wed = {}
for c in range(sp.nvertices):
    wed.setdefault(tuple(np.round(P0[vp0[c]], 5)), {})[tuple(np.round(uv0[c], 6))] = isl0[c]


def uv_check(R_):
    PR, uvR, vpR = A(R_, "P"), A(R_, "uv", VERTEX), R_.vertex_point
    bad = mixed = 0
    for f in range(R_.nprims):
        cs = range(R_.prim_offset[f], R_.prim_offset[f + 1])
        ch = set()
        for c in cs:
            d = wed.get(tuple(np.round(PR[vpR[c]], 5)), {})
            k = tuple(np.round(uvR[c], 6))
            if k not in d:
                bad += 1
            else:
                ch.add(d[k])
        mixed += len(ch) > 1
    return bad, mixed
R1 = PRD.reduce_mesh(sp, keep_percent=40.0, preserve_uvs=True)
bad, mixed = uv_check(R1)
check("every corner's uv is the uv of some wedge on the same point of the original mesh; no triangle crosses a UV island",
      bad == 0 and mixed == 0, (bad, mixed))
check("  it really reduced (triangle count < a bit more than half the original)", R1.nprims < 0.6 * 2 * sp.nprims, R1.nprims)
seam_pts = PRD._seam_points(sp)
PR1 = np.round(A(R1, "P"), 5)
kept = {tuple(p) for p in PR1}
check("  points on UV seams all kept, positions unchanged",
      all(tuple(np.round(P0[i], 5)) in kept for i in np.nonzero(seam_pts)[0]))
R0 = PRD.reduce_mesh(sp, keep_percent=40.0)
bad0, _ = uv_check(R0)
check("  negative control: without Preserve UVs, most corners' uv don't match", bad0 > R0.nvertices * 0.3, bad0)

# ═══════════════════════════════════════════════════ 5. UV Layout raster
sec("UV Layout: raster packing")
tris = []
for i in range(24):                                    # 24 disconnected right triangles
    o = np.array([i * 3.0, 0, 0])
    tris.append([o, o + [1 + 0.1 * (i % 5), 0, 0], o + [0, 0, 1 + 0.07 * (i % 7)]])
Pt = np.concatenate(tris).astype(np.float32)
tg = Geometry.from_points(Pt)
tg.set_topology(np.arange(len(Pt), dtype=np.int32), np.arange(0, len(Pt) + 1, 3, dtype=np.int32))
tg.set(VERTEX, "uv", np.stack([Pt[:, 0], -Pt[:, 2]], 1).astype(np.float32))


def coverage(gg, res=512):
    uv = A(gg, "uv", VERTEX) * res
    cnt = np.zeros((res, res), np.int32)
    J, I = np.meshgrid(np.arange(res) + 0.5, np.arange(res) + 0.5)
    for f in range(gg.nprims):
        a, b, c = uv[gg.prim_offset[f]:gg.prim_offset[f] + 3]
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        l1 = ((b[1] - c[1]) * (J - c[0]) + (c[0] - b[0]) * (I - c[1])) / d
        l2 = ((c[1] - a[1]) * (J - c[0]) + (a[0] - c[0]) * (I - c[1])) / d
        cnt += ((l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)).astype(np.int32)
    return (cnt > 0).mean(), (cnt > 1).sum()
ls = UVL.layout(tg, padding=0.005)
lr = UVL.layout(tg, padding=0.005, method="raster", resolution=256)
cs_, ov_s = coverage(ls)
cr_, ov_r = coverage(lr)
uvr_ = A(lr, "uv", VERTEX)
check("raster: no overlap, all within 0..1", ov_r == 0 and uvr_.min() >= 0 and uvr_.max() <= 1,
      (ov_r, float(uvr_.min()), float(uvr_.max())))
L3 = np.linalg.norm(Pt[1::3] - Pt[0::3], axis=1) / np.linalg.norm(Pt[2::3] - Pt[0::3], axis=1)
Lu = np.linalg.norm(uvr_[1::3] - uvr_[0::3], axis=1) / np.linalg.norm(uvr_[2::3] - uvr_[0::3], axis=1)
sc_ = np.linalg.norm(uvr_[1::3] - uvr_[0::3], axis=1) / np.linalg.norm(Pt[1::3] - Pt[0::3], axis=1)
check("  islands are rigid copies of the originals × uniform scale (edge-length ratios unchanged, same scale for every island)",
      np.allclose(L3, Lu, atol=1e-4) and np.ptp(sc_) < 1e-4 * sc_.mean())
check("  right-triangle islands: sheet utilization much higher than shelf (they interlock)", cr_ > 1.3 * cs_ and cr_ > 0.55,
      (round(cs_, 3), round(cr_, 3)))


def _segd(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab), 0, 1)
    return float(np.linalg.norm(p - (a + t * ab)))


def min_gap(uv):
    T = uv.reshape(-1, 3, 2)
    return min(_segd(p, T[j][k], T[j][(k + 1) % 3]) for i in range(len(T))
               for j in range(len(T)) if i != j for p in T[i] for k in range(3))


okg, gaps = True, []
for pad_, G_ in ((0.01, 256), (0.0, 128), (0.005, 256)):
    lr2 = UVL.layout(tg, padding=pad_, method="raster", resolution=G_)
    gap_ = min_gap(A(lr2, "uv", VERTEX))
    dil_ = max(1, int(np.ceil(pad_ * G_)))
    gaps.append(round(gap_ * G_, 2))
    okg &= gap_ >= max(pad_, (2 * dil_ - 0.75) / G_) - 1e-9
# bound: the two dilated masks don't overlap → occupied cells are 2·dil cells apart; points on an island are less than
# half a cell / √2 from the nearest sample (sample spacing is half a cell), so an island may poke 0.35 cells out of its occupied cells, < 0.75 for both sides together
check("  minimum distance between islands ≥ Padding, and ≥ 2·dilation rings − 0.75 pixels (dilated masks"
      " don't overlap, sampling is dense enough)", okg, gaps)

# ═══════════════════════════════════════════════════ 6. UV Flatten: world scale + ARAP
sec("UV Flatten: world scale + ARAP")
sph2 = build.sphere(1.0, 32, 20)
cap = ops.delete_prims(sph2, ops.prim_centers(sph2)[:, 1] > 0.0)    # hemisphere (has a boundary)
cap60 = ops.delete_prims(sph2, ops.prim_centers(sph2)[:, 1] > 0.5)  # 60° spherical cap


def area_ratio(gg):
    Pc_, uvc = A(gg, "P"), A(gg, "uv", VERTEX)
    r = []
    for f in range(gg.nprims):
        cs = np.arange(gg.prim_offset[f], gg.prim_offset[f + 1])
        p = Pc_[gg.vertex_point[cs]]
        t = uvc[cs]
        a3 = sum(0.5 * np.linalg.norm(np.cross(p[k] - p[0], p[k + 1] - p[0])) for k in range(1, len(cs) - 1))
        a2 = sum(0.5 * abs((t[k, 0] - t[0, 0]) * (t[k + 1, 1] - t[0, 1]) - (t[k, 1] - t[0, 1]) * (t[k + 1, 0] - t[0, 0]))
                 for k in range(1, len(cs) - 1))
        r.append((a3, a2))
    r = np.array(r)
    q = r[:, 1] / r[:, 0]
    q /= np.sum(r[:, 1]) / np.sum(r[:, 0])
    w = r[:, 0] / r[:, 0].sum()
    return float(w[(q < 0.8) | (q > 1.25)].sum()), r
f0, _ = area_ratio(UVF.flatten(cap, normalize=False))
f1, r1 = area_ratio(UVF.flatten(cap, normalize=False, arap_iterations=15))
check("hemisphere: after ARAP, the area fraction with distortion outside [0.8, 1.25] is clearly smaller than plain LSCM",
      f1 < 0.6 * f0, (round(f0, 3), round(f1, 3)))
g0_, _ = area_ratio(UVF.flatten(cap60, normalize=False))
g1_, _ = area_ratio(UVF.flatten(cap60, normalize=False, arap_iterations=15))
check("  60° cap: plain LSCM has a ring outside, none after ARAP", g0_ > 0.02 and g1_ < 1e-3,
      (round(g0_, 3), round(g1_, 4)))
check("  with normalize off it's world scale: total UV area = total 3D area",
      abs(r1[:, 1].sum() / r1[:, 0].sum() - 1) < 1e-6)
cyl = build.tube(1.0, 1.0, 2.0, 24, 6)
seam = np.nonzero(np.abs(np.arctan2(A(cyl, "P")[:, 2], A(cyl, "P")[:, 0])) < 1e-6)[0]
from comfyui_pcg.geo.topology import topology            # noqa: E402
t_ = topology(cyl)
ep = t_.edge_points
sel = np.isin(ep[:, 0], seam) & np.isin(ep[:, 1], seam)
cyl.set_edge_group("cut", ep[sel])
fc = UVF.flatten(cyl, "cut", normalize=False, arap_iterations=10)
Pc_, uvc = A(fc, "P"), A(fc, "uv", VERTEX)
nx = fc.next_corner()
e3 = np.linalg.norm(Pc_[fc.vertex_point] - Pc_[fc.vertex_point[nx]], axis=1)
e2 = np.linalg.norm(uvc - uvc[nx], axis=1)
check("  developable cylinder strip: after unwrapping every edge length = 3D edge length (isometric)", np.abs(e2 / e3 - 1).max() < 2e-3,
      float(np.abs(e2 / e3 - 1).max()))
two = ops.merge(build.grid(1.0, 1.0, 3, 3),
                ops.transform(build.grid(4.0, 4.0, 3, 3), (10, 0, 0)))
ft = UVF.flatten(two, normalize=True)
uvt_ = A(ft, "uv", VERTEX)
check("normalize: all islands share one scale, the largest exactly fills 0..1 (not beyond)",
      uvt_.min() >= -1e-6 and abs(uvt_.max() - 1) < 1e-6, (float(uvt_.min()), float(uvt_.max())))
isl = UVL.islands(ft)
_, rr = area_ratio(ft)
dens = [rr[isl == k, 1].sum() / rr[isl == k, 0].sum() for k in np.unique(isl)]
check("two islands 16× different in size: same texel density after unwrapping (UV area / 3D area equal)",
      abs(dens[0] / dens[1] - 1) < 1e-6, dens)
# negative control: scale each island to 0..1 separately (the old way) and measure, density differs 16×
uvt = A(ft, "uv", VERTEX).copy()
isl_c = np.repeat(isl, ft.prim_sizes())
for k in np.unique(isl):
    m = isl_c == k
    uvt[m] = (uvt[m] - uvt[m].min(0)) / np.ptp(uvt[m], axis=0).max()
fo = ft.copy()
fo.set(VERTEX, "uv", uvt.astype(np.float32))
_, ro = area_ratio(fo)
do = [ro[isl == k, 1].sum() / ro[isl == k, 0].sum() for k in np.unique(isl)]
check("  negative control: per-island normalization to 0..1 (the old way) gives 16× density difference",
      abs(max(do) / min(do) - 16) < 1e-3, do)

# ── ARAP alone (_arap: on a planar mesh starting from a skewed start, should converge to isometric)
def _plane_mesh():
    n_ = 7
    gx_, gy_ = np.meshgrid(np.linspace(0, 1, n_), np.linspace(0, 1, n_))
    xy_ = np.column_stack([gx_.ravel(), gy_.ravel()])
    T_ = []
    for j in range(n_ - 1):
        for i in range(n_ - 1):
            a_, b_, c_, d_ = j * n_ + i, j * n_ + i + 1, (j + 1) * n_ + i, (j + 1) * n_ + i + 1
            if j == 0:                   # insert a slightly inward point on each bottom edge: a 176° obtuse angle
                m_ = len(xy_)
                xy_ = np.concatenate([xy_, [[(i + 0.5) / (n_ - 1), 0.002]]])
                T_ += [[a_, b_, m_], [a_, m_, c_], [m_, b_, d_], [m_, d_, c_]]
            else:
                T_ += [[a_, b_, d_], [a_, d_, c_]]
    return xy_, np.array(T_)


def _edge_err(uv, xy_, t_):
    r_ = [np.linalg.norm(uv[t_[:, i]] - uv[t_[:, j]], axis=1)
          / np.linalg.norm(xy_[t_[:, i]] - xy_[t_[:, j]], axis=1) for i, j in ((0, 1), (1, 2), (2, 0))]
    return float(np.abs(np.concatenate(r_) - 1).max())


def _flips(uv, xy_, t_):
    def sa(p):
        a_, b_, c_ = p[t_[:, 0]], p[t_[:, 1]], p[t_[:, 2]]
        return (b_[:, 0] - a_[:, 0]) * (c_[:, 1] - a_[:, 1]) - (b_[:, 1] - a_[:, 1]) * (c_[:, 0] - a_[:, 0])
    return int((np.sign(sa(uv)) != np.sign(sa(xy_))).sum())


xy_p, tri_p = _plane_mesh()
P3_p = np.column_stack([xy_p[:, 0], 0 * xy_p[:, 0], xy_p[:, 1]])
uv_d = np.column_stack([xy_p[:, 0] * 0.6 + 0.2 * xy_p[:, 1] ** 2, xy_p[:, 1] * 1.3])
e_lin = _edge_err(UVF._arap(P3_p, tri_p, uv_d, 100), xy_p, tri_p)
check("ARAP linear exactness: planar mesh (a row of 176° obtuse angles on the bottom edge) from skewed uv converges to isometric",
      e_lin < 1e-6, e_lin)
uv_f = xy_p.copy()
band = (xy_p[:, 0] > 0.3) & (xy_p[:, 0] < 0.55)
uv_f[band, 0] = 1.0 - uv_f[band, 0]                     # fold the middle band over: a patch of triangles flipped
f0_ = _flips(uv_f, xy_p, tri_p)
u_f = UVF._arap(P3_p, tri_p, uv_f, 100)
check("  starting from a flipped start: flips back, isometric (local fit takes only rotations, not reflections)",
      f0_ > 5 and _flips(u_f, xy_p, tri_p) == 0 and _edge_err(u_f, xy_p, tri_p) < 1e-4,
      (f0_, _flips(u_f, xy_p, tri_p)))
k_ = len(xy_p)                                          # add a zero-area triangle (three collinear points)
o_ = 7 * 3 + 3
xy_z = np.concatenate([xy_p, [[0.5, 0.5]]])
tri_z = np.concatenate([tri_p, [[o_ - 7, k_, o_]]])     # o−7, k, o are on the same vertical line
xy_z[k_] = 0.5 * (xy_z[o_ - 7] + xy_z[o_])
P3_z = np.column_stack([xy_z[:, 0], 0 * xy_z[:, 0], xy_z[:, 1]])
uv_z = np.column_stack([xy_z[:, 0] * 0.6 + 0.2 * xy_z[:, 1] ** 2, xy_z[:, 1] * 1.3])
u_z = UVF._arap(P3_z, tri_z, uv_z, 100)
check("  with a zero-area triangle mixed in: it is excluded, the rest still converges to isometric",
      np.isfinite(u_z).all() and _edge_err(u_z, xy_z, tri_p) < 1e-6, _edge_err(u_z, xy_z, tri_p))

# ═══════════════════════════════════════════════════ 7. Other
sec("Wrangle / IsoSurface / groups")
gq = build.grid(2.0, 2.0, 3, 3)
gq.set(PRIM, "piece", np.arange(4, dtype=np.int32)[:, None])
rq = WR.run_wrangle(gq, 's@name = sprintf("UCX_%s_%02d", "SM_Rock", @piece)\ns@one = str(7)', PRIM)
rq2 = WR.run_wrangle(gq, 's@k = sprintf("%s-%03d", "a", 7)', PRIM)
rq3 = WR.run_wrangle(gq, "s@t = itoa(@piece + 10.7)", PRIM)
check("itoa: floats truncated to integers (10.7 → '10')",
      [x for x in np.asarray(rq3.get(PRIM, "t"))[:, 0]] == ["10", "11", "12", "13"])
check("sprintf with all-constant arguments: one string, broadcast to every element",
      [x for x in np.asarray(rq2.get(PRIM, "k"))[:, 0]] == ["a-007"] * 4)
check("sprintf formats per element; str works", [x for x in np.asarray(rq.get(PRIM, "name"))[:, 0]]
      == ["UCX_SM_Rock_00", "UCX_SM_Rock_01", "UCX_SM_Rock_02", "UCX_SM_Rock_03"]
      and np.asarray(rq.get(PRIM, "one"))[0, 0] == "7")
D20 = dict(divisions_x=20, divisions_y=20, divisions_z=20)
g1 = N("IsoSurface", expression="length(@P) - 1", **D20)[0]
g2 = N("IsoSurface", expression="r = length(@P)\n@value = r - 1", **D20)[0]
check("IsoSurface: multi-line code (intermediate variable + @value) = single-line expression", g1.npoints == g2.npoints
      and np.allclose(A(g1, "P"), A(g2, "P")))
err("  multi-line without @value raises", lambda: N("IsoSurface", expression="r = 1\nq = 2", **D20), "@value")
gp = build.grid(2.0, 2.0, 3, 3)
gp.set(PRIM, "part", np.array(["a", "a", "b", "b"])[:, None])
tp = ops.transform(gp, (0, 1, 0), group='@part == "a"')
moved = A(tp, "P")[:, 1] > 0.5
check("Transform group written as a prim attribute expression: moves the points used by those prims",
      moved.sum() == 6 and set(np.nonzero(moved)[0]) == set(np.unique(np.concatenate(
          [gp.prim_points(i) for i in (0, 1)]))))
gf = build.grid(4.0, 4.0, 5, 5)
gf.set(POINT, "f", np.full((25, 1), 0.5, np.float32))
m_ = resolve(gf, POINT, "@P.x > @f * 2")
check("group expression: @P.x > @f * 2 compares per point ((N,) vs (N,1) no longer broadcasts to N×N)",
      m_.shape == (25,) and np.array_equal(m_, A(gf, "P")[:, 0] > 1.0))
err("  raises when the result isn't a single boolean column (e.g. @P > 0 is N×3), instead of silently selecting garbage",
    lambda: resolve(gf, POINT, "@P > 0"), "shape")
check("  negative control: the same expression in plain numpy is 25×25",
      (A(gf, "P")[:, 0] > A(gf, "f") * 2).shape == (25, 25))

sec("ray_cast chunking / bake edge padding")
O = rng.normal(size=(3000, 3)) * 0.3
Dd = rng.normal(size=(3000, 3))
tri_, _, _ = SP.tri_soup(sph)
Ps = A(sph, "P")
a1 = SP.ray_cast(O, Dd, Ps, tri_)
old = SP._RAY_CHUNK
SP._RAY_CHUNK = 257
_orig_rc, _calls = SP.ray_cast, []


def _count_rc(*a, **k):
    _calls.append(len(a[0]))
    return _orig_rc(*a, **k)


SP.ray_cast = _count_rc
a2 = SP.ray_cast(O, Dd, Ps, tri_)
SP.ray_cast = _orig_rc
SP._RAY_CHUNK = old
check("  really chunked: 3000 rays split into 12 calls, each ≤ 257 rays", len(_calls) == 13
      and max(_calls[1:]) <= 257 and sum(_calls[1:]) == 3000, _calls[:3])
check("rays in varied directions cast in chunks (257 per chunk) bit-identical to unchunked",
      np.array_equal(a1[0], a2[0]) and np.array_equal(a1[1], a2[1]) and np.array_equal(a1[2], a2[2]))
from comfyui_pcg.geo.backproject import _dilate           # noqa: E402


def dilate_ref(col, mask, n):
    c, m = col.copy(), mask.copy()
    for _ in range(n):
        s = np.zeros_like(c)
        k = np.zeros(m.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            s += np.roll(np.roll(c, dy, 0), dx, 1) * np.roll(np.roll(m, dy, 0), dx, 1)[..., None]
            k += np.roll(np.roll(m, dy, 0), dx, 1)
        new = (~m) & (k > 0)
        c[new] = s[new] / k[new][:, None]
        m = m | new
    return c, m
col = rng.random((40, 50, 3))
msk = np.zeros((40, 50), bool)
msk[10:20, 12:30] = True
msk[25:33, 5:9] = True
c1, m1 = _dilate(col * msk[..., None], msk, 5)
c2, m2 = dilate_ref(col * msk[..., None], msk, 5)
check("edge padding computes only that ring: when islands don't touch the image border, bit-identical to the old whole-image roll",
      np.array_equal(m1, m2) and np.allclose(c1, c2))

sec("Write File preview: big images are previewed at a fraction")
_big = CopImage(4100, 6)    # (file rows top-down: the preview is the COP image flipped)
_v = np.random.default_rng(3).random((6, 4100, 1)).astype(np.float32)
_big.set("C", _v)
_rep, _pv = IF.write(_big, TMP, "t/big", "C", "png", "8")
_want = np.repeat(_v[::-1, :4098].reshape(2, 3, 1366, 3, 1).mean((1, 3)), 3, -1)
check("4100 px wide: preview 1366 px (a third, box average), the file full size",
      _pv.shape == (2, 1366, 3) and np.allclose(_pv, _want, atol=1e-6) and _rep["source_size"] == [4100, 6])
_small = CopImage(2048, 4)
_small.set("C", _v[:4, :2048])
_rep2, _pv2 = IF.write(_small, TMP, "t/small", "C", "png", "8")
check("  negative control: 2048 px is shown as it is", _pv2.shape == (4, 2048, 3)
      and np.allclose(_pv2[..., 0], _v[:4, :2048, 0][::-1]))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
