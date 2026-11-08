"""
Mesh / point cloud import -- OBJ / PLY / STL / GLB.

The criteria here fall into three kinds, ordered by "can it be proven":

━━ 1. Round-trip identity (the hardest one)
After `write_obj` -> `load`, P and the four topology arrays must be **bit-identical**. Not "looks
the same": what goes wrong most easily in a round trip is **silent degradation** -- coordinates lose a level of precision, ngons get triangulated,
polylines get treated as faces, points get reordered. None of these raise.
**Reverse control**: drop export precision back to `.6f` (how it was written before this batch), and the round trip of a small-scale model
immediately stops being bit-exact -- this control proves both that the criterion works and that the precision change was necessary.

━━ 2. Two paths as references for each other
The same content written as PLY ascii / little-endian / big-endian must parse bit-identically;
the **vectorized fast path** and the **per-face fallback path** of binary face lists must also be bit-identical. The latter matters most:
a silently misaligned fast path still reads out "triangles that look fine", just connected to the wrong points -- apart from comparing
against another path, there is no way to notice.

━━ 3. Format details that fail silently, pinned one by one
  · binary STL headers often say "solid" -- deciding by the first bytes reads it as ascii and gets an **empty mesh**
  · STL is triangle soup; without welding there is zero connectivity, and Subdivide / PolyReduce quietly do nothing
  · the weld tolerance must be **relative** to scale -- an absolute tolerance welds a 1e-4 model into a single point
  · glTF matrix is **column-major**; read as row-major the translation lands elsewhere, and the rotation "still looks like
    a rotation"
  · OBJ vt is **per corner**; writing it to points silently smears out UV seams
  · OBJ negative indices are relative (-1 = the last one); reading them as positive goes out of range or connects the wrong points
  · after the file is rewritten externally, IS_CHANGED must change -- otherwise ComfyUI serves the previous geometry
"""
import os
import shutil
import tempfile
import struct
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import base64                                           # noqa: E402
import json                                             # noqa: E402
import numpy as np                                      # noqa: E402
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX,    # noqa: E402
                                  PRIM)
from comfyui_pcg.geo import (meshio as MI, convert,      # noqa: E402
                             ops as OPS, topology as TOP)
from comfyui_pcg import nodes as N                       # noqa: E402

# A **new** temp dir per run. It used to be hard-coded /tmp/pcg_meshio_test: two regression runs in parallel (sandbox +
# device mirror) rmtree'd each other's files, which happened once in pcg61; and on Windows
# "/tmp/…" lands at the drive root
TMP = tempfile.mkdtemp(prefix="pcg_meshio_")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)
OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn()
        check(name, False, "did not raise")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:110]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def w(name, data, mode="wb"):
    p = os.path.join(TMP, name)
    with open(p, mode) as f:
        f.write(data)
    return p


def topo_snap(g):
    """Bit-exact fingerprint of the topology. dtype goes in too, so int32/int64 don't collide on the same bytes."""
    return (g.npoints, g.nvertices, g.nprims,
            g.vertex_point.tobytes(), str(g.vertex_point.dtype),
            g.prim_offset.tobytes(), str(g.prim_offset.dtype),
            g.prim_closed.tobytes())


def unwrap(res):
    return tuple(res.get("result", ())) if isinstance(res, dict) else res


def P_of(g):
    return np.asarray(g.get(POINT, "P"))


# ═══════════════════════════════════════════════════ 1. OBJ round-trip identity
sec("OBJ round trip (bit-exact)")

# ngon + triangles + polylines mixed together, with coordinates spanning five orders of magnitude
rng = np.random.default_rng(4)
pts = np.concatenate([
    rng.normal(0, 1, (12, 3)),
    rng.normal(0, 1e-4, (6, 3)),
    rng.normal(0, 1e5, (6, 3)),
]).astype(np.float32)
faces = [[0, 1, 2, 3, 4], [4, 5, 6], [6, 7, 8, 9], [10, 11, 12],
         [13, 14, 15, 16, 17, 18], [19, 20, 21, 22]]
g0 = Geometry(len(pts))
g0.set(POINT, "P", pts, owned=True)
flat, offs = [], [0]
for f in faces:
    flat += f
    offs.append(len(flat))
closed = np.array([True, True, True, False, True, False])
g0.set_topology(np.asarray(flat, np.int32), np.asarray(offs, np.int32),
                prim_closed=closed)

p_obj = os.path.join(TMP, "rt.obj")
convert.write_obj(g0, p_obj)
g1, info = MI.load(p_obj)
check("P bit-identical (float32 written with .9g is lossless)",
      np.array_equal(P_of(g1), P_of(g0)),
      f"max diff {np.abs(P_of(g1).astype(np.float64) - P_of(g0)).max():.3g}")
check("  topology bit-identical (ngons not triangulated, polylines not treated as faces)",
      topo_snap(g1) == topo_snap(g0))
check("  face sizes unchanged: 5/3/4/3/6/4",
      np.array_equal(g1.prim_sizes(), [5, 3, 4, 3, 6, 4]),
      g1.prim_sizes())
check("  the two open ones are still open (f / l told apart correctly)",
      np.array_equal(g1.prim_closed, closed))
check("info states format and counts", "obj" in info and "points 24" in info, info)

# **reverse control**: back to .6f (how it was written before this batch), the round trip of small-scale coordinates is no longer bit-exact
lines = [f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}" for p in pts]
for f, cl in zip(faces, closed):
    lines.append(("f " if cl else "l ") + " ".join(str(i + 1) for i in f))
g_old = MI.load(w("rt6.obj", ("\n".join(lines) + "\n").encode()))[0]
check("  [reverse control] the same mesh written with .6f is **not** bit-exact after the round trip",
      not np.array_equal(P_of(g_old), P_of(g0)),
      f"max diff {np.abs(P_of(g_old).astype(np.float64) - P_of(g0)).max():.3g}")
check("  [reverse control] the 1e-4-scale points are quantized the most",
      np.abs(P_of(g_old)[12:18].astype(np.float64)
             - P_of(g0)[12:18]).max() > 1e-8)

# two round trips still identity -- shows there is no accumulated error
convert.write_obj(g1, os.path.join(TMP, "rt2.obj"))
g2 = MI.load(os.path.join(TMP, "rt2.obj"))[0]
check("two round trips still bit-exact (no accumulated error)",
      np.array_equal(P_of(g2), P_of(g0)) and topo_snap(g2) == topo_snap(g0))


# ═══════════════════════════════════════════════════ 2. OBJ details
sec("OBJ details")
OBJ = """# comment line
mtllib x.mtl

v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vt 0.25 0.75
vn 0 0 1
vn 0 1 0
g partA
usemtl red
f 1/1/1 2/2/1 3/3/1
g partB
usemtl blue
f 1/5/2 3/3/2 4/4/2
l 1 2
s off
"""
gA = MI.load(w("d.obj", OBJ.encode()))[0]
check("comments / blank lines / mtllib / s are all skipped without affecting parsing",
      gA.npoints == 4 and gA.nprims == 3)
check("vt lands on **vertices** (per corner), not points",
      gA.has(VERTEX, "uv") and not gA.has(POINT, "uv"))
check("vn also lands on vertices", gA.has(VERTEX, "N"))
uv = np.asarray(gA.get(VERTEX, "uv"), np.float64)
# point 1 (OBJ's v1) uses different vt on two faces: face 0 uses vt1=(0,0), face 1 uses vt5=(.25,.75)
c0 = gA.prim_offset[0]
c1 = gA.prim_offset[1]
check("**UV seam preserved**: the same point has different uv on the two faces",
      not np.allclose(uv[c0], uv[c1]),
      f"{uv[c0]} vs {uv[c1]}")
check("  this is exactly what gets lost when written to points (a point can only have one uv)",
      gA.vertex_point[c0] == gA.vertex_point[c1])
check("the second vn of f 1/5/2 is read (normal indices aren't just the first one)",
      np.allclose(np.asarray(gA.get(VERTEX, "N"), np.float64)[c1],
                  [0, 1, 0]))
check("g / o -> prim name string attribute",
      list(np.asarray(gA.get(PRIM, "name")).ravel()[:2]) == ["partA", "partB"])
check("usemtl -> prim material attribute",
      list(np.asarray(gA.get(PRIM, "material")).ravel()[:2]) == ["red", "blue"])
check("l -> open polyline", not gA.prim_closed[2] and gA.prim_sizes()[2] == 2)

neg = """v 0 0 0
v 1 0 0
v 1 1 0
f -3 -2 -1
"""
pos = """v 0 0 0
v 1 0 0
v 1 1 0
f 1 2 3
"""
gn = MI.load(w("neg.obj", neg.encode()))[0]
gp = MI.load(w("pos.obj", pos.encode()))[0]
check("**negative indices are relative** (-1 = the last one), giving the same mesh as positive indices",
      topo_snap(gn) == topo_snap(gp)
      and np.array_equal(P_of(gn), P_of(gp)))
err("index 0 raises (OBJ is 1-based)",
    lambda: MI.load(w("zero.obj", b"v 0 0 0\nf 0 0 0\n")), "1-based")

crlf = "v 0 0 0\r\nv 1 0 0\r\nv 1 1 0\r\nf 1 2 3\r\n"
check("CRLF (Windows) line endings parse fine",
      MI.load(w("crlf.obj", crlf.encode()))[0].nprims == 1)
vc = "v 0 0 0 1 0 0\nv 1 0 0 0 1 0\nv 1 1 0 0 0 1\nf 1 2 3\n"
gvc = MI.load(w("vc.obj", vc.encode()))[0]
check("v followed by 6 numbers = vertex color (how MeshLab / some 3D generative models write it)",
      gvc.has(POINT, "Cd")
      and np.allclose(np.asarray(gvc.get(POINT, "Cd"), np.float64)[1],
                      [0, 1, 0]))
check("  with only 3 numbers no Cd is written (no attributes made up from nothing)",
      not gp.has(POINT, "Cd"))
noslash = "v 0 0 0\nv 1 0 0\nv 1 1 0\nvn 0 0 1\nf 1//1 2//1 3//1\n"
gns = MI.load(w("noslash.obj", noslash.encode()))[0]
check("f 1//1 without uv: has N, no uv",
      gns.has(VERTEX, "N") and not gns.has(VERTEX, "uv"))
err("a face referencing a nonexistent point raises, and gives the point number",
    lambda: MI.load(w("bad.obj", b"v 0 0 0\nf 1 2 3\n")), "nonexistent point")


# ══════════════════════════════════════════════ 3. PLY: three encodings as references for each other
sec("PLY (three encodings must be bit-identical)")
VERT = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float64)
NRM = np.array([[0, 0, 1]] * 4, np.float64)
COL = np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 255]],
               np.uint8)
FACES = [[0, 1, 2], [0, 2, 3]]

ascii_ply = ["ply", "format ascii 1.0", "element vertex 4",
             "property float x", "property float y", "property float z",
             "property float nx", "property float ny", "property float nz",
             "property uchar red", "property uchar green",
             "property uchar blue", "element face 2",
             "property list uchar int vertex_indices", "end_header"]
for i in range(4):
    ascii_ply.append(" ".join(f"{x:g}" for x in
                              list(VERT[i]) + list(NRM[i]) + list(COL[i])))
for f in FACES:
    ascii_ply.append("3 " + " ".join(str(i) for i in f))
g_asc = MI.load(w("a.ply", ("\n".join(ascii_ply) + "\n").encode()))[0]


def bin_ply(big):
    e = ">" if big else "<"
    hdr = ("ply\nformat binary_%s_endian 1.0\nelement vertex 4\n"
           "property float x\nproperty float y\nproperty float z\n"
           "property float nx\nproperty float ny\nproperty float nz\n"
           "property uchar red\nproperty uchar green\nproperty uchar blue\n"
           "element face 2\nproperty list uchar int vertex_indices\n"
           "end_header\n") % ("big" if big else "little")
    body = b""
    for i in range(4):
        body += np.asarray(list(VERT[i]) + list(NRM[i]),
                           e + "f4").tobytes() + bytes(COL[i])
    for f in FACES:
        body += struct.pack(e + "B3i", 3, *f)
    return hdr.encode() + body


g_le = MI.load(w("le.ply", bin_ply(False)))[0]
g_be = MI.load(w("be.ply", bin_ply(True)))[0]
check("geometry parsed from ascii and little-endian binary is **bit-identical**",
      np.array_equal(P_of(g_asc), P_of(g_le))
      and topo_snap(g_asc) == topo_snap(g_le))
check("  big-endian too (byte order handled right)",
      np.array_equal(P_of(g_be), P_of(g_le))
      and topo_snap(g_be) == topo_snap(g_le))
check("  normals and colors bit-identical too",
      np.array_equal(np.asarray(g_asc.get(POINT, "N")),
                     np.asarray(g_le.get(POINT, "N")))
      and np.array_equal(np.asarray(g_asc.get(POINT, "Cd")),
                         np.asarray(g_le.get(POINT, "Cd"))))
check("uchar colors divided by 255 (0-255 -> 0-1)",
      np.allclose(np.asarray(g_le.get(POINT, "Cd"), np.float64)[0], [1, 0, 0]))

# float colors (0-1) shouldn't be divided by 255 again
fp = ["ply", "format ascii 1.0", "element vertex 1", "property float x",
      "property float y", "property float z", "property float red",
      "property float green", "property float blue", "end_header",
      "0 0 0 0.5 0.25 1.0"]
gfp = MI.load(w("fc.ply", ("\n".join(fp) + "\n").encode()))[0]
check("  float colors (max <= 1) kept as is, not divided by 255",
      np.allclose(np.asarray(gfp.get(POINT, "Cd"), np.float64)[0],
                  [0.5, 0.25, 1.0]))

# ── fast path vs fallback path for face lists: mixed face sizes must fall back, and both paths agree
def mixed_ply(binary):
    rows = [[0, 1, 2], [0, 2, 3, 1], [1, 2, 3]]      # 3 / 4 / 3, deliberately not uniform
    hdr = ("ply\nformat %s 1.0\nelement vertex 4\nproperty float x\n"
           "property float y\nproperty float z\nelement face 3\n"
           "property list uchar int vertex_indices\nend_header\n")
    if binary:
        body = np.asarray(VERT, "<f4").tobytes()
        for r in rows:
            body += struct.pack("<B", len(r)) + np.asarray(r, "<i4").tobytes()
        return (hdr % "binary_little_endian").encode() + body
    txt = hdr % "ascii"
    for v in VERT:
        txt += " ".join(f"{x:g}" for x in v) + "\n"
    for r in rows:
        txt += f"{len(r)} " + " ".join(str(i) for i in r) + "\n"
    return txt.encode()


g_mix_a = MI.load(w("mixa.ply", mixed_ply(False)))[0]
g_mix_b = MI.load(w("mixb.ply", mixed_ply(True)))[0]
check("with **mixed face sizes** the binary vectorized fast path falls back, result bit-identical to ascii",
      topo_snap(g_mix_a) == topo_snap(g_mix_b),
      f"{g_mix_a.prim_sizes()} vs {g_mix_b.prim_sizes()}")
check("  face sizes are 3/4/3 (not all cut to the first face's size)",
      np.array_equal(g_mix_b.prim_sizes(), [3, 4, 3]),
      g_mix_b.prim_sizes())
check("  with uniform face sizes the fast path is taken, result also right",
      np.array_equal(g_le.prim_sizes(), [3, 3]))

# a bigger uniform-face-size file: fast path matches "per face by hand"
NP, NF = 400, 300
rv = rng.normal(0, 1, (NP, 3))
rf = rng.integers(0, NP, (NF, 3))
big_hdr = (f"ply\nformat binary_little_endian 1.0\nelement vertex {NP}\n"
           "property float x\nproperty float y\nproperty float z\n"
           f"element face {NF}\nproperty list uchar int vertex_indices\n"
           "end_header\n").encode()
big_body = np.asarray(rv, "<f4").tobytes()
for r in rf:
    big_body += struct.pack("<B", 3) + np.asarray(r, "<i4").tobytes()
g_big = MI.load(w("big.ply", big_hdr + big_body))[0]
check("300-face uniform file: face list **bit-identical** to what was written",
      np.array_equal(g_big.vertex_point.reshape(-1, 3),
                     rf.astype(np.int32)))
check("  points bit-exact too",
      np.array_equal(P_of(g_big), rv.astype(np.float32)))

# ── point clouds / 3DGS
splat = ["ply", "format ascii 1.0", "element vertex 2",
         "property float x", "property float y", "property float z",
         "property float f_dc_0", "property float f_dc_1",
         "property float f_dc_2", "property float opacity",
         "property float scale_0", "property float rot_0", "end_header",
         "0 0 0 1.0 -0.5 0.25 2.5 0.1 0.7",
         "1 2 3 0.0 0.0 0.0 -1.0 0.2 0.8"]
gs = MI.load(w("splat.ply", ("\n".join(splat) + "\n").encode()))[0]
check("PLY without faces = point cloud (prims 0, points 2)",
      gs.nprims == 0 and gs.npoints == 2)
check("  other splat properties go into point attributes as is",
      all(gs.has(POINT, k) for k in ("opacity", "scale_0", "rot_0",
                                     "f_dc_0")))
check("  f_dc_* -> Cd uses the closed form for the 0th-order spherical harmonic coefficient 0.282095·f + 0.5",
      np.allclose(np.asarray(gs.get(POINT, "Cd"), np.float64)[0],
                  np.clip(np.array([1.0, -0.5, 0.25]) * MI.SH_C0 + 0.5, 0, 1)),
      np.asarray(gs.get(POINT, "Cd"))[0])
check("  points with f_dc all 0 are mid gray (0.5)",
      np.allclose(np.asarray(gs.get(POINT, "Cd"), np.float64)[1], 0.5))
g_nos = MI.load(w("splat2.ply", ("\n".join(splat) + "\n").encode()),
                splat_color=False)[0]
check("  splat_color=False makes no Cd", not g_nos.has(POINT, "Cd"))
g_nox = MI.load(w("splat3.ply", ("\n".join(splat) + "\n").encode()),
                keep_extra=False)[0]
check("  keep_extra=False leaves out those extra attributes",
      not g_nox.has(POINT, "opacity"))

uvply = ["ply", "format ascii 1.0", "element vertex 3", "property float x",
         "property float y", "property float z", "property float s",
         "property float t", "element face 1",
         "property list uchar int vertex_indices", "end_header",
         "0 0 0 0 0", "1 0 0 1 0", "1 1 0 1 1", "3 0 1 2"]
guv = MI.load(w("uv.ply", ("\n".join(uvply) + "\n").encode()))[0]
check("PLY s/t -> uv, expanded to vertices (same convention as OBJ)",
      guv.has(VERTEX, "uv") and not guv.has(POINT, "uv"))

err("PLY without end_header raises",
    lambda: MI.load(w("noend.ply", b"ply\nformat ascii 1.0\n")), "end_header")
err("truncated binary PLY raises, and says how much is missing",
    lambda: MI.load(w("trunc.ply", bin_ply(False)[:-20])), "truncated")
# declares 4 points, gives only 1 line of data. The first version built this from ascii_ply, and the resulting file
# had a second end_header mixed into the header -- it raised an int() parse error; the criterion failed while the implementation was fine
trunc_a = ("ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\n"
           "property float y\nproperty float z\nend_header\n0 0 0\n")
err("PLY ascii declaring more points than the data has raises",
    lambda: MI.load(w("trunca.ply", trunc_a.encode())), "truncated")
err("  truncated binary face list says which face",
    lambda: MI.load(w("truncf.ply", bin_ply(False)[:-8])), "truncated")
err("PLY without x/y/z raises",
    lambda: MI.load(w("noxyz.ply",
                      b"ply\nformat ascii 1.0\nelement vertex 1\n"
                      b"property float a\nend_header\n1\n")), "x/y/z")


# ══════════════════════════════════════════════ 4. STL and that classic trap
sec("STL (binary detection + welding)")
TRI = np.array([[[0, 0, 0], [1, 0, 0], [1, 1, 0]],
                [[0, 0, 0], [1, 1, 0], [0, 1, 0]]], np.float32)


def bin_stl(header=b"solid exported by something"):
    buf = bytearray(header.ljust(80, b"\0") + struct.pack("<I", len(TRI)))
    for t in TRI:
        buf += (np.zeros(3, "<f4").tobytes()
                + t.astype("<f4").tobytes() + struct.pack("<H", 0))
    return bytes(buf)


data = bin_stl()
check("**binary STL whose header says 'solid' is still recognized as binary** (length criterion)",
      MI.sniff(data, "x.stl") == "stl" and MI._is_binary_stl(data))
gst = MI.load(w("b.stl", data))[0]
check("  reads 2 triangles", gst.nprims == 2)
check("  [reverse control] judging by 'starts with solid means ascii' would read 0 faces here",
      len([1 for line in data.decode("latin1").splitlines()
           if line.strip()[:6].lower() == "vertex"]) == 0)
check("weld=auto welds STL points: 6 -> 4", gst.npoints == 4, gst.npoints)
graw = MI.load(w("b2.stl", data), weld="off")[0]
check("  with weld=off it's triangle soup, 6 points", graw.npoints == 6)
c_weld = TOP.connectivity(gst)
c_raw = TOP.connectivity(graw)
check("**connectivity only after welding**: welded is 1 piece, triangle soup is 2 pieces",
      int(np.asarray(c_weld.get(POINT, "class")).max()) == 0
      and int(np.asarray(c_raw.get(POINT, "class")).max()) == 1,
      f"welded {int(np.asarray(c_weld.get(POINT, 'class')).max()) + 1} pieces, "
      f"soup {int(np.asarray(c_raw.get(POINT, 'class')).max()) + 1} pieces")
check("  area unaffected by welding (no wrong points welded)",
      abs(float(np.asarray(OPS.measure_area(gst).get(PRIM, "area")).sum())
          - float(np.asarray(OPS.measure_area(graw).get(PRIM,
                                                        "area")).sum()))
      < 1e-12)

# weld tolerance must be relative to scale
for s in (1e-4, 1.0, 1e4):
    scaled = bytearray(bin_stl())
    arr = np.frombuffer(bytes(scaled), np.dtype([("n", "<3f4"),
                                                 ("v", "<3f4", 3),
                                                 ("a", "<u2")]), 2, 84).copy()
    arr["v"] *= s
    body = bytes(scaled[:84]) + arr.tobytes()
    gsc = MI.load(w(f"s{s}.stl", body))[0]
    check(f"at scale {s:g} welds to 4 points (tolerance relative to the bounding box)",
          gsc.npoints == 4, gsc.npoints)
# reverse control: a fixed absolute tolerance is wrong at both extremes.
#
# **The first version of this was wrong**: the shared vertices in the example were **bit-identical**, and fuse dedups by
# quantized cells -- bit-identical points get welded at any tolerance, so both extremes gave 4;
# the criterion failed while the implementation was fine. Real exported files aren't like that: the same vertex written once from each of two faces
# differs in the last few bits after float32 rounding. So here it's perturbed by **relative 1e-7**,
# which is the case that actually needs a tolerance.
# the duplicates in the triangle soup are [3]≈[0] and [4]≈[2] -- [5] is (0,1,0), it's not a duplicate.
# The first version perturbed [5], turning that unique point into (1,1,0) too, leaving only 3 points
soup6 = TRI.reshape(-1, 3).astype(np.float64)
soup6[3] = soup6[0] * (1 + 1e-7) + 1e-7      # "almost" coincides with point 0
soup6[4] = soup6[2] * (1 + 1e-7) + 1e-7      # "almost" coincides with point 2
SF = [[0, 1, 2], [3, 4, 5]]
for s_, want in ((1e-6, 4), (1.0, 4), (1e4, 4)):
    gw = MI._weld(MI._build(soup6 * s_, SF, True), "on")[0]
    check(f"  relative tolerance at scale {s_:g} welds to {want} points (perturbed duplicates)",
          gw.npoints == want, gw.npoints)
g_abs_small = OPS.fuse(MI._build(soup6 * 1e-6, SF, True), 1e-4)
check("  [reverse control] a fixed absolute tolerance of 1e-4 welds a 1e-6-scale model into 1 point",
      g_abs_small.npoints == 1, g_abs_small.npoints)
g_abs_big = OPS.fuse(MI._build(soup6 * 1e4, SF, True), 1e-4)
check("  [reverse control] the same absolute tolerance welds no points at all at 1e4 scale",
      g_abs_big.npoints == 6, g_abs_big.npoints)

ascii_stl = b"""solid s
 facet normal 0 0 1
  outer loop
   vertex 0 0 0
   vertex 1 0 0
   vertex 1 1 0
  endloop
 endfacet
endsolid s
"""
gas = MI.load(w("a.stl", ascii_stl))[0]
check("ascii STL reads too (1 triangle, 3 points after welding)",
      gas.nprims == 1 and gas.npoints == 3)
err("ascii STL vertex count not a multiple of 3 raises",
    lambda: MI.load(w("badascii.stl",
                      ascii_stl.replace(b"   vertex 1 1 0\n", b""))),
    "multiple of 3")


# ══════════════════════════════════════════════════ 5. glTF / GLB
sec("glTF / GLB")


def gltf(nodes, meshes, accessors, views, blob, scene=True):
    js = {"asset": {"version": "2.0"}, "nodes": nodes, "meshes": meshes,
          "accessors": accessors, "bufferViews": views,
          "buffers": [{"byteLength": len(blob),
                       "uri": "data:application/octet-stream;base64,"
                              + base64.b64encode(blob).decode()}]}
    if scene:
        js["scene"] = 0
        js["scenes"] = [{"nodes": list(range(len(nodes)))}]
    return json.dumps(js).encode()


TRIP = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], "<f4")
IDX = np.array([0, 1, 2], "<u2")
BLOB = TRIP.tobytes() + IDX.tobytes()
ACC = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
       {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"}]
VIEWS = [{"buffer": 0, "byteOffset": 0, "byteLength": TRIP.nbytes},
         {"buffer": 0, "byteOffset": TRIP.nbytes, "byteLength": IDX.nbytes}]
PRIM4 = {"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}

g_gl = MI.load(w("t.gltf", gltf([{"mesh": 0}],
                                [{"primitives": [PRIM4]}], ACC, VIEWS, BLOB)))[0]
check("minimal glTF: 3 points 1 face", g_gl.npoints == 3 and g_gl.nprims == 1)
check("  point coordinates bit-exact",
      np.array_equal(P_of(g_gl), np.asarray(TRIP, np.float32)))

# **column-major**: translation in matrix is in the last row (indices 12..14)
M = [2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 6, 7, 1]
g_m = MI.load(w("m.gltf", gltf([{"mesh": 0, "matrix": M}],
                               [{"primitives": [PRIM4]}], ACC, VIEWS,
                               BLOB)))[0]
want = np.asarray(TRIP, np.float64) * [2, 1, 1] + [5, 6, 7]
check("node matrix is **column-major**: translation lands at (5,6,7)",
      np.allclose(P_of(g_m).astype(np.float64), want),
      P_of(g_m)[0])
check("  [reverse control] read as row-major, the translation would come from the (0,0,0) column, result differs",
      not np.allclose(
          np.asarray(TRIP, np.float64)
          @ np.asarray(M, np.float64).reshape(4, 4)[:3, :3] + [0, 0, 0],
          want))

# TRS: scale first, then rotate, then translate
trs = {"mesh": 0, "scale": [2, 3, 4],
       "rotation": [0, 0.7071067811865476, 0, 0.7071067811865476],  # 90° about Y
       "translation": [1, 2, 3]}
g_trs = MI.load(w("trs.gltf", gltf([trs], [{"primitives": [PRIM4]}], ACC,
                                   VIEWS, BLOB)))[0]
S = np.diag([2.0, 3, 4])
Ry = np.array([[0.0, 0, 1], [0, 1, 0], [-1, 0, 0]])
want_trs = np.asarray(TRIP, np.float64) @ (Ry @ S).T + [1, 2, 3]
check("TRS composition order is T·R·S (matches the glTF spec)",
      np.allclose(P_of(g_trs).astype(np.float64), want_trs, atol=1e-6),
      f"{P_of(g_trs)[1]} vs {want_trs[1]}")

# the same mesh referenced by two nodes = instancing, should produce two copies
g_inst = MI.load(w("inst.gltf", gltf(
    [{"mesh": 0}, {"mesh": 0, "translation": [10, 0, 0]}],
    [{"primitives": [PRIM4]}], ACC, VIEWS, BLOB)))[0]
check("the same mesh referenced by two nodes -> two copies of geometry (glTF instancing)",
      g_inst.npoints == 6 and g_inst.nprims == 2)
check("  the second copy carries its own translation",
      np.allclose(P_of(g_inst)[3:].astype(np.float64)
                  - P_of(g_inst)[:3].astype(np.float64), [10, 0, 0]))

# child node transforms accumulate
g_child = MI.load(w("child.gltf", gltf(
    [{"children": [1], "translation": [1, 0, 0]},
     {"mesh": 0, "translation": [0, 2, 0]}],
    [{"primitives": [PRIM4]}], ACC, VIEWS, BLOB, scene=False)))[0]
check("parent and child node transforms accumulate ((1,0,0) + (0,2,0))",
      np.allclose(P_of(g_child)[0].astype(np.float64), [1, 2, 0]),
      P_of(g_child)[0])

# byteStride: POSITION and NORMAL interleaved in the same view
inter = np.zeros(3, dtype=[("p", "<f4", 3), ("n", "<f4", 3)])
inter["p"] = TRIP
inter["n"] = [[0, 1, 0]] * 3
blob2 = inter.tobytes() + IDX.tobytes()
acc2 = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 0, "byteOffset": 12, "componentType": 5126,
         "count": 3, "type": "VEC3"},
        {"bufferView": 1, "componentType": 5123, "count": 3,
         "type": "SCALAR"}]
views2 = [{"buffer": 0, "byteOffset": 0, "byteLength": inter.nbytes,
           "byteStride": 24},
          {"buffer": 0, "byteOffset": inter.nbytes, "byteLength": IDX.nbytes}]
g_int = MI.load(w("int.gltf", gltf(
    [{"mesh": 0}],
    [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                      "indices": 2, "mode": 4}]}],
    acc2, views2, blob2)))[0]
check("interleaved buffer (byteStride) read correctly: coordinates and normals not mixed up",
      np.array_equal(P_of(g_int), np.asarray(TRIP, np.float32))
      and np.allclose(np.asarray(g_int.get(VERTEX, "N"), np.float64)[0],
                      [0, 1, 0]))

# normalized ushort uv
uv16 = np.array([[0, 0], [65535, 0], [65535, 65535]], "<u2")
blob3 = TRIP.tobytes() + uv16.tobytes() + IDX.tobytes()
acc3 = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 1, "componentType": 5123, "count": 3, "type": "VEC2",
         "normalized": True},
        {"bufferView": 2, "componentType": 5123, "count": 3,
         "type": "SCALAR"}]
views3 = [{"buffer": 0, "byteOffset": 0, "byteLength": TRIP.nbytes},
          {"buffer": 0, "byteOffset": TRIP.nbytes, "byteLength": uv16.nbytes},
          {"buffer": 0, "byteOffset": TRIP.nbytes + uv16.nbytes,
           "byteLength": IDX.nbytes}]
g_uv16 = MI.load(w("uv16.gltf", gltf(
    [{"mesh": 0}],
    [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                      "indices": 2, "mode": 4}]}],
    acc3, views3, blob3)))[0]
check("normalized ushort uv normalized to 0..1 (v then flipped to 1 − v: (1, 0) in the file)",
      np.allclose(np.asarray(g_uv16.get(VERTEX, "uv"), np.float64)[1],
                  [1.0, 1.0]),
      np.asarray(g_uv16.get(VERTEX, "uv"))[1])

# no indices -> sequential indices
g_noidx = MI.load(w("noidx.gltf", gltf(
    [{"mesh": 0}],
    [{"primitives": [{"attributes": {"POSITION": 0}, "mode": 4}]}],
    ACC[:1], VIEWS[:1], TRIP.tobytes())))[0]
check("without indices, taken as triangles in order", g_noidx.nprims == 1)

# the various modes
quad = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], "<f4")
qidx = np.array([0, 1, 2, 3], "<u2")
qblob = quad.tobytes() + qidx.tobytes()
qacc = [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
        {"bufferView": 1, "componentType": 5123, "count": 4,
         "type": "SCALAR"}]
qviews = [{"buffer": 0, "byteOffset": 0, "byteLength": quad.nbytes},
          {"buffer": 0, "byteOffset": quad.nbytes, "byteLength": qidx.nbytes}]


def mode_geo(mode):
    return MI.load(w(f"mode{mode}.gltf", gltf(
        [{"mesh": 0}],
        [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1,
                          "mode": mode}]}], qacc, qviews, qblob)))[0]


g5 = mode_geo(5)
check("mode 5 (TRIANGLE_STRIP) -> 2 triangles", g5.nprims == 2)
# winding alternation has to be tested with a **real strip**. The first version fed the quad's perimeter order (0,1,2,3),
# which is not a strip -- a strip is zigzag (0,1,3,2); the criterion failed while the implementation was right.
zig = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0]], "<f4")
zblob = zig.tobytes() + qidx.tobytes()
g5z = MI.load(w("strip.gltf", gltf(
    [{"mesh": 0}],
    [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1,
                      "mode": 5}]}], qacc,
    [{"buffer": 0, "byteOffset": 0, "byteLength": zig.nbytes},
     {"buffer": 0, "byteOffset": zig.nbytes, "byteLength": qidx.nbytes}],
    zblob)))[0]
n5 = OPS.prim_normals(g5z)
check("  on a real strip the winding is alternately corrected (both face normals point the same way)",
      float(np.dot(n5[0], n5[1])) > 0.99, float(np.dot(n5[0], n5[1])))
# reverse control: without alternation (both faces as i,i+1,i+2) the normals are opposite
zp = np.asarray(zig, np.float64)
na = np.cross(zp[1] - zp[0], zp[2] - zp[0])
nb = np.cross(zp[2] - zp[1], zp[3] - zp[1])
check("  [reverse control] without alternation the two face normals are opposite (so this step isn't redundant)",
      float(np.dot(na, nb)) < 0, float(np.dot(na, nb)))
g6 = mode_geo(6)
check("mode 6 (TRIANGLE_FAN) -> 2 triangles, both connected to point 0", g6.nprims == 2
      and all(0 in list(g6.prim_points(i)) for i in range(2)))
g1l = mode_geo(1)
check("mode 1 (LINES) -> 2 open segments",
      g1l.nprims == 2 and not g1l.prim_closed.any())
g3l = mode_geo(3)
check("mode 3 (LINE_STRIP) -> 1 open polyline, 4 points",
      g3l.nprims == 1 and g3l.prim_sizes()[0] == 4
      and not g3l.prim_closed[0])
g2l = mode_geo(2)
check("mode 2 (LINE_LOOP) -> 1 closed polyline", g2l.prim_closed[0])
g0p = mode_geo(0)
check("mode 0 (POINTS) -> pure point cloud (4 points 0 faces)",
      g0p.npoints == 4 and g0p.nprims == 0)
err("unrecognized mode raises",
    lambda: mode_geo(9), "mode")

# COLOR_0 vec4 -> Cd takes the first three components
c4 = np.array([[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 0.5]], "<f4")
blob4 = TRIP.tobytes() + c4.tobytes() + IDX.tobytes()
acc4 = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC4"},
        {"bufferView": 2, "componentType": 5123, "count": 3,
         "type": "SCALAR"}]
views4 = [{"buffer": 0, "byteOffset": 0, "byteLength": TRIP.nbytes},
          {"buffer": 0, "byteOffset": TRIP.nbytes, "byteLength": c4.nbytes},
          {"buffer": 0, "byteOffset": TRIP.nbytes + c4.nbytes,
           "byteLength": IDX.nbytes}]
g_c4 = MI.load(w("c4.gltf", gltf(
    [{"mesh": 0}],
    [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1},
                      "indices": 2, "mode": 4}]}],
    acc4, views4, blob4)))[0]
check("when COLOR_0 is VEC4, the first three components are taken as Cd",
      np.allclose(np.asarray(g_c4.get(POINT, "Cd"), np.float64)[2],
                  [0, 0, 1]))

# multiple primitives: told apart by name, merge_parts=False takes only the first
two = {"name": "obj", "primitives": [PRIM4, PRIM4]}
g_two = MI.load(w("two.gltf", gltf([{"mesh": 0}], [two], ACC, VIEWS, BLOB)))[0]
check("one mesh with two primitives -> two faces, name carries an index",
      g_two.nprims == 2
      and sorted(set(np.asarray(g_two.get(PRIM, "name")).ravel().tolist()))
      == ["obj.0", "obj.1"])
g_one = MI.load(w("two2.gltf", gltf([{"mesh": 0}], [two], ACC, VIEWS, BLOB)),
                merge=False)[0]
check("  merge_parts=False takes only the first", g_one.nprims == 1)

# GLB container (with 4-byte alignment padding)
def glb(js_bytes, bin_bytes):
    jp = js_bytes + b" " * ((-len(js_bytes)) % 4)
    bp = bin_bytes + b"\0" * ((-len(bin_bytes)) % 4)
    body = (struct.pack("<II", len(jp), 0x4E4F534A) + jp
            + struct.pack("<II", len(bp), 0x004E4942) + bp)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


js_in = json.dumps({
    "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
    "nodes": [{"mesh": 0}], "meshes": [{"primitives": [PRIM4]}],
    "accessors": ACC, "bufferViews": VIEWS,
    "buffers": [{"byteLength": len(BLOB)}]}).encode()
g_glb = MI.load(w("x.glb", glb(js_in, BLOB)))[0]
check("GLB container (JSON + BIN chunks, 4-byte aligned) read correctly",
      g_glb.npoints == 3 and np.array_equal(P_of(g_glb),
                                            np.asarray(TRIP, np.float32)))
check("  magic recognized as glb (independent of extension)",
      MI.sniff(glb(js_in, BLOB), "whatever.txt") == "glb")
err("GLB version other than 2 raises",
    lambda: MI.load(w("v1.glb",
                      b"glTF" + struct.pack("<II", 1, 20) + b"\0" * 8)),
    "glTF 2.0")
err("embedded buffer but no BIN chunk raises",
    lambda: MI.load(w("nobin.glb", glb(js_in, b""))), "BIN")
err("missing external buffer raises, and gives the path it looked at",
    lambda: MI.load(w("ext.gltf", json.dumps({
        "asset": {"version": "2.0"}, "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [PRIM4]}], "accessors": ACC,
        "bufferViews": VIEWS,
        "buffers": [{"byteLength": 9, "uri": "missing.bin"}]}).encode())),
    "not found at")
err("glTF without a mesh raises",
    lambda: MI.load(w("empty.gltf", json.dumps({
        "asset": {"version": "2.0"}, "nodes": [], "meshes": [],
        "accessors": [], "bufferViews": [], "buffers": []}).encode())),
    "no mesh with POSITION")

# if trimesh is present, do a real GLB round trip (write_glb uses trimesh)
try:
    import trimesh                                      # noqa: F401
    has_tm = True
except Exception:
    has_tm = False
if has_tm:
    gtm = Geometry.from_mesh(
        np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32),
        np.array([[0, 1, 2], [0, 2, 3]]))
    convert.write_glb(gtm, os.path.join(TMP, "tm.glb"))
    g_back = MI.load(os.path.join(TMP, "tm.glb"))[0]
    check("a real GLB written by trimesh reads back, face count matches",
          g_back.nprims == 2 and g_back.npoints == 4,
          f"{g_back.npoints} points {g_back.nprims} faces")
    check("  coordinates match the original (to float32 precision)",
          np.allclose(np.sort(P_of(g_back), axis=0),
                      np.sort(P_of(gtm), axis=0), atol=1e-6))
else:
    check("trimesh not installed, skipping real GLB round trip (the pure python path is fully tested)", True)


# ══════════════════════════════════════════ 6. up_axis / scale / winding
sec("up_axis / scale / flip_winding")
g_asis = MI.load(p_obj)[0]
g_zy = MI.load(p_obj, up_axis="z_up_to_y_up")[0]
Pa = P_of(g_asis).astype(np.float64)
Pz = P_of(g_zy).astype(np.float64)
check("z_up_to_y_up is a pure permutation + negation, **bit-exact** with no floating-point error",
      np.array_equal(Pz[:, 0], Pa[:, 0])
      and np.array_equal(Pz[:, 1], Pa[:, 2])
      and np.array_equal(Pz[:, 2], -Pa[:, 1]))
g_back2 = MI.load(os.path.join(TMP, "rt.obj"), up_axis="as_is")[0]
P2 = MI._rot_up(MI._rot_up(P_of(g_back2).astype(np.float64),
                           "z_up_to_y_up"), "y_up_to_z_up")
check("  converting there and back is identity (bit-exact)", np.array_equal(P2, Pa))
check("  normals rotate along (otherwise shading is wrong while the shape looks right)",
      np.allclose(np.asarray(MI.load(w("n.obj", noslash.encode()),
                                     up_axis="z_up_to_y_up")[0]
                             .get(VERTEX, "N"), np.float64)[0], [0, 1, 0]))
err("wrong up_axis raises", lambda: MI.load(p_obj, up_axis="bogus"), "up_axis")

g_sc = MI.load(p_obj, scale=3.0)[0]
check("scale multiplied in", np.allclose(P_of(g_sc).astype(np.float64),
                                   Pa * 3.0, rtol=1e-6))
g_fl = MI.load(p_obj, flip_winding=True)[0]
n_a = OPS.prim_normals(g_asis)
n_f = OPS.prim_normals(g_fl)
check("flip_winding flips the face normals",
      float(np.dot(n_a[1], n_f[1])) < -0.99, float(np.dot(n_a[1], n_f[1])))
check("  points didn't move, only the point order in the prims is reversed",
      np.array_equal(P_of(g_fl), P_of(g_asis))
      and not np.array_equal(g_fl.vertex_point, g_asis.vertex_point))


# ══════════════════════════════════════════════ 7. Format detection / errors
sec("Format detection (magic > extension)")
check("ply magic", MI.sniff(bin_ply(False), "x.obj") == "ply")
check("  recognized as ply even when the extension says obj (renamed extensions are common in AI pipelines)",
      MI.load(w("lie.obj", bin_ply(False)))[0].nprims == 2)
check("glTF json recognized as glb", MI.sniff(b'  {"asset":{}}', "x") == "glb")
check("obj recognized by typical lines",
      MI.sniff(b"# blah\nv 0 0 0\nf 1 1 1\n", "x") == "obj")
check("the format parameter can force-override auto detection",
      MI.load(w("force.ply", bin_ply(False)), fmt="ply")[0].nprims == 2)
err("unrecognizable raises, and gives the first 16 bytes",
    lambda: MI.load(w("junk.dat", b"\x01\x02\x03\x04" * 8)), "Can't recognize")
err("empty file raises", lambda: MI.load(w("empty.obj", b"")), "File is empty")
err("wrong format raises", lambda: MI.load(p_obj, fmt="bogus"), "format must be one of")
err("wrong weld raises", lambda: MI.load(p_obj, weld="bogus"), "weld must be one of")
err("neither path nor data raises", lambda: MI.load(), "Give either path")


# ══════════════════════════════════════════════ 8. In-memory objects (duck typing)
sec("MESH port (duck typing)")


class FakeTrimesh:
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float64)
    faces = np.array([[0, 1, 2]])
    vertex_colors = np.array([[255, 0, 0, 255], [0, 255, 0, 255],
                              [0, 0, 255, 255]], np.uint8)


class FakeTensor:
    """Something with .detach().cpu().numpy() (shaped like a torch tensor)."""
    def __init__(self, a):
        self._a = np.asarray(a)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._a


g_duck = MI.from_object(FakeTrimesh())
check("objects with .vertices / .faces are read in",
      g_duck.npoints == 3 and g_duck.nprims == 1)
check("  0-255 vertex colors divided by 255, and only the first three components taken",
      np.allclose(np.asarray(g_duck.get(POINT, "Cd"), np.float64)[0],
                  [1, 0, 0]))
check("dicts are recognized too (vertices/faces)",
      MI.from_object({"vertices": FakeTrimesh.vertices,
                      "faces": FakeTrimesh.faces}).nprims == 1)
check("  aliases recognized too (verts / v / triangles)",
      MI.from_object({"verts": FakeTrimesh.vertices,
                      "triangles": FakeTrimesh.faces}).nprims == 1
      and MI.from_object({"v": FakeTrimesh.vertices,
                          "f": FakeTrimesh.faces}).nprims == 1)
check("torch-style .detach().cpu().numpy() tensors converted to numpy automatically",
      MI.from_object({"vertices": FakeTensor(FakeTrimesh.vertices),
                      "faces": FakeTensor(FakeTrimesh.faces)}).nprims == 1)
check("list -> merged into one",
      MI.from_object([FakeTrimesh(), FakeTrimesh()]).npoints == 6)
check("points only without faces works too (point cloud)",
      MI.from_object({"vertices": FakeTrimesh.vertices}).nprims == 0)
err("unrecognized vertices raise, and list the names looked for",
    lambda: MI.from_object({"nope": 1}), "vertices / verts")
err("empty list raises", lambda: MI.from_object([]), "meshes passed in is empty")
check("from_object can also weld / swap axes / scale",
      MI.from_object({"vertices": np.vstack([FakeTrimesh.vertices,
                                             FakeTrimesh.vertices]),
                      "faces": np.array([[0, 1, 2], [3, 4, 5]])},
                     weld="on").npoints == 3)


# ══════════════════════════════════════════════ 9. Path resolution / IS_CHANGED
sec("Path resolution / cache invalidation")
err("nonexistent absolute path raises, and gives that path",
    lambda: MI.resolve("/definitely/not/here.obj"), "/definitely/not/here.obj")
err("relative path not found **lists every location tried**",
    lambda: MI.resolve("nope_xyz.obj"), "Locations tried")
err("empty filename raises", lambda: MI.resolve(""), "filename is empty")
check("an existing absolute path is used directly", MI.resolve(p_obj) == p_obj)
check("quoted paths are recognized too (copied from the file explorer)",
      MI.resolve('"' + p_obj + '"') == p_obj)

# **What gets changed is a copy, not rt.obj itself.** The first version appended a line directly to rt.obj,
# so the later "counts returned by the node match the geometry" check got 25 points -- the criterion failed while the implementation was fine.
# Tests sharing one fixture and then modifying it is a pitfall the previous batch already hit.
shutil.copyfile(p_obj, os.path.join(TMP, "touch.obj"))
cwd = os.getcwd()
os.chdir(TMP)
try:
    check("relative path found in the current directory",
          os.path.samefile(MI.resolve("rt.obj"), p_obj))
    tok1 = N.PCG_ImportMesh.IS_CHANGED(filename="touch.obj")
    tok1b = N.PCG_ImportMesh.IS_CHANGED(filename="touch.obj")
    check("IS_CHANGED gives the same value for the same untouched file", tok1 == tok1b, tok1)
    # file rewritten externally (= AI generated mesh.glb again)
    os.utime("touch.obj", (1, 1))
    tok2 = N.PCG_ImportMesh.IS_CHANGED(filename="touch.obj")
    check("**after the file is rewritten IS_CHANGED changes** -- otherwise ComfyUI serves the previous geometry",
          tok2 != tok1, f"{tok1} -> {tok2}")
    with open("touch.obj", "a") as f:
        f.write("v 9 9 9\n")
    check("  also changes when the content gets longer (the size is in the fingerprint)",
          N.PCG_ImportMesh.IS_CHANGED(filename="touch.obj") != tok2)
finally:
    os.chdir(cwd)
no_tok = N.PCG_ImportMesh.IS_CHANGED(filename="does_not_exist_at_all.obj")
check("IS_CHANGED **doesn't throw** when the file doesn't exist (it is called before the cook)",
      isinstance(no_tok, str) and "does_not_exist" in no_tok)


# ══════════════════════════════════════════════════ 10. Nodes
sec("Nodes")
node = N.PCG_ImportMesh()
out = unwrap(node.run(p_obj, "auto", "auto", MI.WELD_REL, "as_is", 1.0,
                      False, True, True, True))
check("returns four: (geo, points, prims, info)",
      len(out) == 4 and isinstance(out[0], Geometry))
check("  counts match the geometry", out[1] == out[0].npoints == 24
      and out[2] == out[0].nprims == 6)
check("  info is a string and states the format", isinstance(out[3], str) and "obj" in out[3])
out2 = unwrap(node.run("this_path_does_not_exist.obj", "auto", "auto", MI.WELD_REL,
                       "as_is", 1.0, False, True, True, True,
                       mesh=FakeTrimesh()))
check("with the mesh port connected, filename is ignored (so a bad path doesn't matter)",
      out2[1] == 3 and "MESH" in out2[3], out2[3])
spec = N.PCG_ImportMesh.INPUT_TYPES()
check("mesh is an optional MESH type (runs without it connected)",
      spec.get("optional", {}).get("mesh") == ("MESH",))
check("format / weld / up_axis combo items are the module constants",
      spec["required"]["format"][0] == list(MI.FORMATS)
      and spec["required"]["weld"][0] == list(MI.WELD_MODES)
      and spec["required"]["up_axis"][0] == list(MI.UP_AXES))
check("under the PCG/convert category (symmetric with Export Mesh)",
      N.PCG_ImportMesh.CATEGORY == "PCG/convert")
check("Import and Export are a pair (both nodes exist)",
      "PCG_ImportMesh" in N.NODE_CLASS_MAPPINGS
      and "PCG_ExportMesh" in N.NODE_CLASS_MAPPINGS)


# ═════════════════════════════════════════ 11. The chain from the pitch actually runs
sec("Import -> Fuse -> Normal -> PolyReduce -> UV (the chain promised in the node docs)")
# make something that looks like an "AI-generated mesh": triangle soup, duplicate points, no UV, no normals
sph = None
from comfyui_pcg.geo import build as BUILD                # noqa: E402
sph = BUILD.sphere(radius=1.0, rows=12, cols=16)
tri = sph.triangles()
soup = np.asarray(sph.get(POINT, "P"))[tri.reshape(-1)]
soup_faces = [[3 * i, 3 * i + 1, 3 * i + 2] for i in range(len(tri))]
stl_buf = bytearray(b"solid ai".ljust(80, b"\0")
                    + struct.pack("<I", len(tri)))
for t in soup.reshape(-1, 3, 3):
    stl_buf += (np.zeros(3, "<f4").tobytes()
                + t.astype("<f4").tobytes() + struct.pack("<H", 0))
p_soup = w("ai.stl", bytes(stl_buf))

g_in, info = MI.load(p_soup)
check(f"read in: triangle soup {len(soup)} points -> welded to {g_in.npoints} points",
      g_in.npoints < len(soup) * 0.5, info)
check("  one single piece after welding (connectivity restored)",
      int(np.asarray(TOP.connectivity(g_in).get(POINT, "class")).max()) == 0)
a_in = float(np.asarray(OPS.measure_area(g_in).get(PRIM, "area")).sum())
a_soup = float(np.asarray(OPS.measure_area(
    MI.load(p_soup, weld="off")[0]).get(PRIM, "area")).sum())
check("  area unchanged (welding didn't change the shape)", abs(a_in - a_soup) < 1e-6 * a_soup,
      f"{a_in:.6f} vs {a_soup:.6f}")
g_n = OPS.compute_normals(g_in, add_to="point")
check("Normal computes (before welding each triangle was isolated, so only face normals were possible)",
      g_n.has(POINT, "N"))
from comfyui_pcg.geo import polyreduce as PRD             # noqa: E402
g_r = PRD.reduce_mesh(g_n, target="percentage", keep_percent=40.0)
check("PolyReduce really reduced (shows the topology is connected -- on triangle soup it has nothing to work with)",
      g_r.nprims < g_in.nprims * 0.6,
      f"{g_in.nprims} -> {g_r.nprims}")
from comfyui_pcg.geo import uvproject as UVP              # noqa: E402
g_uv = UVP.project(g_r, mode="spherical", axis="y")
check("UV Project can lay out uv on the reduced mesh", g_uv.has(VERTEX, "uv"))
convert.write_obj(g_uv, os.path.join(TMP, "out.obj"))
g_final = MI.load(os.path.join(TMP, "out.obj"))[0]
check("export -> import again, points and topology bit-exact (the whole chain closes)",
      np.array_equal(P_of(g_final), P_of(g_uv))
      and topo_snap(g_final) == topo_snap(g_uv))

# the point cloud path: splat -> post-processing after scatter
g_cloud = MI.load(w("cloud.ply", ("\n".join(splat) + "\n").encode()))[0]
check("after coming in, a point cloud goes straight into geometry operators (Transform doesn't care whether there are faces)",
      OPS.transform(g_cloud, translate=(1, 0, 0)).npoints == 2)


shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
