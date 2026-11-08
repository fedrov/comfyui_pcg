"""
Camera-space "image -> geometry control data".

Checks are ordered by "can it be proven"; the first three kinds are analytic:

━━ 1. The projection itself has a closed form
Under an orthographic camera screen coordinates are a **linear function** of world coordinates, so uv can be compared point by point with the formula,
with error pinned at 1e-15 rather than "close enough". The two places most likely to go silently wrong each get a check +
a negative control:

  · **Half a pixel**. uv = (sx + 0.5) / W. Drop the 0.5 and the whole image shifts half a pixel --
    visible at low resolution, but easily mistaken for "aliasing". Check: a point at a pixel center
    must give (i+0.5)/W.
  · **v points up**. Flip it wrong and the mask is upside down, which symmetric shapes do not reveal. Check: a +Y point
    must give v > 0.5.

━━ 2. Round trip: render the position channel out, project it back, it must restore **the same** P
Render the geometry's world coordinates into a position image, then project it back onto the geometry with this node --
the attribute that comes back should equal each point's own P. For a plane + orthographic camera screen space is linear,
bilinear reconstruction is **exact**, so this can be held to float32 precision (1e-6) rather than
"looks about right". This one check verifies projection, sampling, uv convention and visibility at once.

━━ 3. Occlusion has an indisputable example
Two parallel boards, camera facing them. Points on the back board **must** all be judged occluded, the front board **must**
be fully visible. Plus two more:
  · with visibility=front the back board is "visible" -- showing it really is the occlusion level that removes it
  · with group selecting only the back board, it is still judged occluded -- **occlusion is always computed on the whole geometry**

━━ 4. Convex invariant (the strength of the check itself)
On a convex body a front-facing element can never be occluded. Measured on a sphere: depth-only mode at facing_min=0.1 still misjudges 4
front-facing points, element+depth gives 0 -- so the "element id" criterion is not redundant; this is
a **negative control**, not just a remark.

Incidentally, the design "search the id criterion in a 3x3 neighbourhood" has its own negative control too: for a board
facing the camera, looking only at the **one** pixel the projection lands on, points on its four edges get rounded to pixels outside
the coverage, so a completely unoccluded board has a ring of points judged "occluded" (17 measured).
"""
import os
import sys
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import numpy as np                                      # noqa: E402
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX,    # noqa: E402
                                  PRIM)
from comfyui_pcg.geo import (camproject as CP, render as R,    # noqa: E402
                             build, ops as OPS)
from comfyui_pcg.geo.cop.core import CopImage             # noqa: E402
from comfyui_pcg import nodes as N                        # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def err(name, fn, frag, kind=Exception):
    try:
        fn()
        check(name, False, "no error raised")
    except kind as ex:
        check(name, frag in str(ex), f"{type(ex).__name__}: {str(ex)[:100]}")


def sec(t):
    print("\n" + "═" * 28 + " " + t)


def unwrap(res):
    return tuple(res.get("result", ())) if isinstance(res, dict) else res


def img_from(fn, W=64, H=64, C=1):
    """f(u, v) -> image. u/v are taken at **pixel centers**."""
    u = (np.arange(W) + 0.5) / W
    v = (np.arange(H) + 0.5) / H
    U, V = np.meshgrid(u, v)                    # row 0 = smallest v = bottom of the frame
    a = np.stack([fn(U, V)] * C, -1).astype(np.float32)
    im = CopImage(W, H)
    im.set("C", a)
    return im


# orthographic camera: screen coordinates are a linear function of world coordinates, every check can be written in closed form
ORTHO_SIZE, RES = 4.0, 64
CAM = R.camera(None, projection="orthographic", eye=(0, 0, 10),
               target=(0, 0, 0), up=(0, 1, 0), ortho_size=ORTHO_SIZE,
               xres=RES, yres=RES, near=0.01)


def uv_analytic(P):
    """Orthographic, facing -Z, up=+Y: ndx = x/(S/2), ndy = y/(S/2), uv = (nd+1)/2."""
    P = np.asarray(P, np.float64).reshape(-1, 3)
    half = ORTHO_SIZE * 0.5
    return np.stack([(P[:, 0] / half + 1.0) * 0.5,
                     (P[:, 1] / half + 1.0) * 0.5], 1)


# ══════════════════════════════════════════════════ 1. Closed-form projection
sec("Projection (closed form)")
pts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [-1.5, 0.75, 0],
                [1.9, -1.9, 0], [0.3, -0.7, 2.0]], np.float64)
uv, z = CP.screen_uv(CAM, pts)
e = np.abs(uv - uv_analytic(pts)).max()
check("uv identical to the formula point by point (orthographic projection is linear)", e < 1e-15,
      f"max diff {e:.2e}")
check("  z is the distance along the view direction (camera at +Z 10, a point at z=0 gives 10)",
      abs(z[0] - 10.0) < 1e-12, z[0])
check("  points behind the camera have negative z",
      CP.screen_uv(CAM, np.array([[0, 0, 20.0]]))[1][0] < 0)

# **Half a pixel**: for a world point at a pixel center, uv must be exactly (i+0.5)/W
half = ORTHO_SIZE * 0.5
for i, j in ((0, 0), (17, 40), (63, 63), (32, 31)):
    wx = ((i + 0.5) / RES * 2 - 1) * half
    wy = ((j + 0.5) / RES * 2 - 1) * half
    got = CP.screen_uv(CAM, np.array([[wx, wy, 0.0]]))[0][0]
    check(f"world point at pixel center ({i},{j}) gives uv=({(i + 0.5) / RES:.5f},"
          f"{(j + 0.5) / RES:.5f})",
          abs(got[0] - (i + 0.5) / RES) < 1e-15
          and abs(got[1] - (j + 0.5) / RES) < 1e-15, got)
sx, sy, _ = R.project(CAM, np.array([[0.0, 0.0, 0.0]]))
check("  [negative control] without that 0.5 the center point would give 0.5-1/(2W) (half a pixel off)",
      abs(sx[0] / RES - (0.5 - 0.5 / RES)) < 1e-12, sx[0] / RES)

check("**v points up**: a +Y point gives v > 0.5",
      CP.screen_uv(CAM, np.array([[0, 1.0, 0]]))[0][0, 1] > 0.5)
check("  a -Y point gives v < 0.5",
      CP.screen_uv(CAM, np.array([[0, -1.0, 0]]))[0][0, 1] < 0.5)
check("  same for u: +X gives u > 0.5",
      CP.screen_uv(CAM, np.array([[1.0, 0, 0]]))[0][0, 0] > 0.5)


# ═══════════════════════════════════════════ 2. Sampling (bilinear is exact)
sec("Sampling (bilinear is exact inside the image)")
# **Normals must face the camera.** build.grid(plane="xy")'s winding makes normals point to -Z, while the camera is at
# +Z -- without flipping, the whole board is back-facing and front / full modes see no point at all. This is not a bug,
# it is this grid's winding convention; the test flips it so that not every check ends up testing "nothing visible"
grid = OPS.reverse_prims(build.grid(size_x=3.0, size_z=3.0, rows=21, cols=21,
                                    plane="xy"))


def bilin(U, V):
    return 0.3 + 0.7 * U - 0.4 * V + 1.1 * U * V


g_s, info = CP.project_attribute(grid, CAM, img_from(bilin), layer="C",
                                 name="m", visibility="all")
P = np.asarray(grid.get(POINT, "P"), np.float64)
uvp = uv_analytic(P)
want = bilin(uvp[:, 0], uvp[:, 1])
got = np.asarray(g_s.get(POINT, "m"), np.float64)[:, 0]
# the half pixel at the edge is the clamp zone (bilinear has no samples on both sides there); following frommap's old rule
# that ring is excluded before comparing
inner = ((uvp[:, 0] > 0.5 / RES) & (uvp[:, 0] < 1 - 0.5 / RES)
         & (uvp[:, 1] > 0.5 / RES) & (uvp[:, 1] < 1 - 0.5 / RES))
e = np.abs(got[inner] - want[inner]).max()
check("bilinear function reconstructed **exactly** (projection + sampling + uv convention verified together)",
      e < 5e-6, f"max diff {e:.2e}, {int(inner.sum())} points")
check("  [negative control] flipping v makes the error jump from 1e-6 to O(1)",
      np.abs(got[inner] - bilin(uvp[inner, 0], 1 - uvp[inner, 1])).max() > 0.1)
check("scale / offset applied at the output",
      np.allclose(np.asarray(CP.project_attribute(
          grid, CAM, img_from(bilin), layer="C", name="m", visibility="all",
          scale=2.0, offset=1.0)[0].get(POINT, "m"), np.float64)[:, 0],
          got * 2.0 + 1.0, atol=1e-6))
check("channels can pick channels",
      np.asarray(CP.project_attribute(
          grid, CAM, img_from(bilin, C=3), layer="C", name="m",
          visibility="all", channels="0,2")[0].get(POINT, "m")).shape[1] == 2)


# ════════════════════════════════════════ 3. Round trip: render out and project back
sec("Round trip (render the position channel, projecting back must restore P)")
# the position channel's written **layer name is "P"**, not "position"
pos_img = R.render(grid, CAM, passes=("position", "mask"))
AN = CP.anchors(grid, POINT)


def loop_err(guard):
    """Round-trip error + visibility mask. guard is the width of the silhouette guard."""
    g, _ = CP.project_attribute(grid, CAM, pos_img, layer="P", name="Pback",
                                visibility="full", facing_min=0.0,
                                silhouette_guard=guard)
    m, _, _, _ = CP.visible_mask(grid, CAM, AN[0], AN[1], mode="full",
                                 facing_min=0.0, silhouette_guard=guard,
                                 owner=AN[2])
    pb = np.asarray(g.get(POINT, "Pback"), np.float64)
    return (np.abs(pb[m] - P[m]).max() if m.any() else np.inf), m


e1, m1 = loop_err(1)
check("rendered world coordinates projected back == the point's own P (bilinear is exact for plane + orthographic)",
      e1 < 2e-5, f"max diff {e1:.2e}, {int(m1.sum())}/{len(P)} visible points")
check("  what is visible is the board's interior", m1.mean() > 0.8, f"{m1.mean() * 100:.1f}%")

# **This check is the reason the silhouette guard exists.** With the guard off, bilinear sampling for the ring of points
# at the board's edge picks up pixels **outside the coverage** (where the position channel is 0), so the error
# jumps from 1e-6 to O(1). The first version of this check used guard=0 and failed -- the check was right,
# the parameter was wrong, and the way it failed demonstrates the guard's purpose very clearly
e0, m0 = loop_err(0)
check("  [negative control] with the silhouette guard off edge points pick up background, error jumps to O(1)",
      e0 > 0.1, f"guard=0 max diff {e0:.3g} (guard=1 is {e1:.1e})")
check("  the guard only trims one ring at the edge, it does not eat most of the board",
      0.8 < m1.mean() / max(m0.mean(), 1e-9) < 1.0,
      f"{m0.mean() * 100:.1f}% -> {m1.mean() * 100:.1f}%")

# the same round trip on a sphere: on a curved surface bilinear is no longer exact; the error is on the order of the **pixel footprint**, not 0.
# written as a check to pin down "the order of magnitude is right" -- if it jumps to 0.1 the projection is wrong, not the interpolation coarse
sph = build.sphere(radius=1.0, rows=24, cols=32)
scam = R.camera(sph, xres=256, yres=256, orbit=True, elev=0, azim=0,
                distance=4)
sp_img = R.render(sph, scam, passes=("position",))
g_sp, _ = CP.project_attribute(sph, scam, sp_img, layer="P",
                               name="Pb", visibility="full")
Ps = np.asarray(sph.get(POINT, "P"), np.float64)
Pb2 = np.asarray(g_sp.get(POINT, "Pb"), np.float64)
vg = g_sp.get_group(POINT, "vis")
m_sp, _, _, _ = CP.visible_mask(sph, scam, *CP.anchors(sph, POINT)[:2],
                                owner=CP.anchors(sph, POINT)[2])
es = np.abs(Pb2[m_sp] - Ps[m_sp]).max()
px = 2.0 * 1.0 / 256                       # size of one pixel in the world (approx.)
check("round-trip error on a sphere is on the order of **one pixel footprint** (bilinear no longer exact on curved surfaces)",
      es < 5 * px, f"{es:.4f} vs pixel {px:.4f}")


# ══════════════════════════════════════════════ 4. Visibility ladder
sec("Visibility ladder")
img_half = img_from(lambda U, V: (U >= 0.5).astype(np.float64))
counts = {}
for mode in CP.VISIBILITY:
    _, i = CP.project_attribute(sph, scam, img_half, layer="C", name="m",
                                visibility=mode, facing_min=0.0)
    counts[mode] = i["visible"]
check("the ladder tightens **strictly**: all >= frustum >= front >= full",
      counts["all"] >= counts["frustum"] >= counts["front"]
      >= counts["full"], counts)
check("  every level really removes some (not decoration)",
      counts["all"] > counts["front"] > counts["full"], counts)
check("  all mode = every element", counts["all"] == sph.npoints)

_, i_full = CP.project_attribute(sph, scam, img_half, layer="C", name="m",
                                 visibility="full", facing_min=0.0)
check("**conservation**: visible + out of frame + back-facing + occluded == total (the three reasons do not overlap)",
      i_full["visible"] + i_full["out_frame"] + i_full["back_facing"]
      + i_full["occluded"] == i_full["total"], i_full)
check("  coverage is the visible fraction",
      abs(i_full["coverage"] - i_full["visible"] / i_full["total"]) < 1e-12)

# out of frame
far_cam = R.camera(None, projection="orthographic", eye=(100, 0, 10),
                   target=(100, 0, 0), ortho_size=1.0, xres=32, yres=32)
_, i_out = CP.project_attribute(grid, far_cam, img_half, layer="C", name="m",
                                visibility="frustum")
check("with the camera pointing elsewhere everything is out of frame",
      i_out["visible"] == 0 and i_out["out_frame"] == grid.npoints, i_out)
_, i_bm = CP.project_attribute(grid, CAM, img_half, layer="C", name="m",
                               visibility="frustum", border_margin=0.25)
_, i_b0 = CP.project_attribute(grid, CAM, img_half, layer="C", name="m",
                               visibility="frustum", border_margin=0.0)
check("border_margin excludes a ring around the frame",
      i_bm["visible"] < i_b0["visible"] * 0.7,
      f"{i_b0['visible']} -> {i_bm['visible']}")


# ══════════════════════════════════════════════ 5. Occlusion (two boards)
sec("Occlusion (indisputable example: two parallel boards)")
front = OPS.reverse_prims(build.grid(size_x=2.0, size_z=2.0, rows=9, cols=9,
                                     plane="xy"))
back = OPS.transform(front, translate=(0, 0, -2))
two = OPS.merge(front, back)
nf = front.npoints
Pt, Nt, own_t = CP.anchors(two, POINT)
# guard=0: the board's edge points are exactly the ring the guard would trim; this check is about
# "is the occlusion decision right" and should not have the guard mixed in
m_front, _, _, i2 = CP.visible_mask(two, CAM, Pt, Nt, "full", 0.0,
                                    silhouette_guard=0, owner=own_t)
check("front board **entirely** visible", bool(m_front[:nf].all()),
      f"{int(m_front[:nf].sum())}/{nf}")
check("back board **entirely** occluded", not bool(m_front[nf:].any()),
      f"{int(m_front[nf:].sum())}/{two.npoints - nf} visible")
# -- the 3x3 neighbourhood design decision gets its own negative control
#
# an element's projected point almost never lands on a pixel center. For a board facing the camera, the points **on its four edges**
# have uv exactly on the coverage boundary and after rounding end up in an uncovered pixel -- looking only at
# that one pixel, a board with no occluder at all would have a ring of points judged "occluded".
uvf, zf = CP.screen_uv(CAM, Pt[:nf])
rf = R.rasterize(two, CAM)
xf = np.clip(np.round(uvf[:, 0] * RES - 0.5), 0, RES - 1).astype(np.int64)
yf = np.clip(np.round(uvf[:, 1] * RES - 0.5), 0, RES - 1).astype(np.int64)
hit1 = rf["hit"][yf, xf]
tv1 = rf["tri"][np.clip(hit1, 0, None)]
own1 = own_t[:nf]
single = (hit1 >= 0) & ((tv1[:, 0] == own1) | (tv1[:, 1] == own1)
                        | (tv1[:, 2] == own1))
check("  [negative control] looking at only **one** pixel, this unoccluded board misses a ring of points",
      int((~single).sum()) > 10,
      f"missed {int((~single).sum())}/{nf}, all on the edge")
check("  the missed ones really are all on the board's edge",
      bool((np.abs(np.abs(Pt[:nf][~single]) - 1.0).min(1) < 1e-6).all()))
check("  the 3x3 neighbourhood recovers all of them (and lets none of the back board in)",
      bool(m_front[:nf].all()) and not bool(m_front[nf:].any()))

m_fr, _, _, _ = CP.visible_mask(two, CAM, Pt, Nt, "front", 0.0)
check("  [negative control] with visibility=front the back board is 'visible' -- "
      "so it really is the occlusion level that removes it", bool(m_fr[nf:].all()))

# group does not affect occlusion
two2 = two.copy()
sel = np.zeros(two.npoints, bool)
sel[nf:] = True
two2.set_group(POINT, "onlyback", sel)
g_bk, i_bk = CP.project_attribute(two2, CAM, img_half, layer="C", name="m",
                                  group="onlyback", visibility="full",
                                  facing_min=0.0, visible_group="vis")
check("**with group selecting only the back board, it is still judged occluded** (occlusion uses the whole geometry)",
      i_bk["visible"] == 0, i_bk)
AB = CP.anchors(back, POINT)
check("  [negative control] actually deleting the front board makes it visible",
      CP.visible_mask(back, CAM, AB[0], AB[1], "full", 0.0,
                      silhouette_guard=0, owner=AB[2])[0].all())

# convex invariant + negative control of element vs depth
Psp, Nsp, own_sp = CP.anchors(sph, POINT)
mf1, _, _, _ = CP.visible_mask(sph, scam, Psp, Nsp, "front", 0.1)
bad = {}
for occ in CP.OCCLUSION:
    mm, _, _, _ = CP.visible_mask(sph, scam, Psp, Nsp, "full", 0.1,
                                  silhouette_guard=0, owner=own_sp,
                                  occlusion=occ)
    bad[occ] = int((mf1 & ~mm).sum())
check("**convex invariant**: in element+depth mode no front-facing point is misjudged as occluded",
      bad["element+depth"] == 0, bad)
check("  [negative control] depth-only mode cannot do it (one pixel's span of the z-buffer at grazing angles is large enough)",
      bad["depth"] > 0, bad)
check("  element alone can do it too (the id criterion itself is exact)",
      bad["element"] == 0, bad)
g0, i_g0 = CP.project_attribute(sph, scam, img_half, layer="C", name="m",
                                silhouette_guard=0)
g2, i_g2 = CP.project_attribute(sph, scam, img_half, layer="C", name="m",
                                silhouette_guard=3)
check("silhouette_guard shrinks inward, visible count decreases monotonically",
      i_g2["visible"] < i_g0["visible"],
      f"{i_g0['visible']} -> {i_g2['visible']}")
check("increasing depth_bias only reduces occluded (monotonic)",
      CP.project_attribute(sph, scam, img_half, layer="C", name="m",
                           occlusion="depth", depth_bias=0.5)[1]["occluded"]
      <= CP.project_attribute(sph, scam, img_half, layer="C", name="m",
                              occlusion="depth",
                              depth_bias=0.0)[1]["occluded"])

# scale-independent: scale the whole geometry up 1000x, the visible set is **exactly the same**
big = OPS.transform(sph, scale=(1000, 1000, 1000))
bcam = R.camera(big, xres=256, yres=256, orbit=True, elev=0, azim=0,
                distance=4000)
mb, _, _, _ = CP.visible_mask(big, bcam, *CP.anchors(big, POINT)[:2],
                              owner=CP.anchors(big, POINT)[2])
ms, _, _, _ = CP.visible_mask(sph, scam, Psp, Nsp, owner=own_sp)
check("after scaling up 1000x the visible set is exactly the same (depth_bias is relative to scale)",
      np.array_equal(mb, ms),
      f"{int((mb != ms).sum())} differ")
# when scaling down 1000x **near must scale too** -- it is an absolute amount in world units; the default 0.01
# is bigger than the whole object, and rasterization drops every triangle as crossing the near plane. The first version did not scale it,
# 166 points differed, and the cause was not depth_bias
small = OPS.transform(sph, scale=(1e-3, 1e-3, 1e-3))
scam2 = R.camera(small, xres=256, yres=256, orbit=True, elev=0, azim=0,
                 distance=4e-3, near=1e-5)
AS = CP.anchors(small, POINT)
mss, _, _, _ = CP.visible_mask(small, scam2, AS[0], AS[1], owner=AS[2])
check("  scaling down 1000x likewise (the near plane is absolute and must scale along)",
      np.array_equal(mss, ms), f"{int((mss != ms).sum())} differ")
scam3 = R.camera(small, xres=256, yres=256, orbit=True, elev=0, azim=0,
                 distance=4e-3)
check("  [negative control] without scaling the near plane (default 0.01 is bigger than the whole object) everything is lost",
      CP.visible_mask(small, scam3, AS[0], AS[1], owner=AS[2])[0].sum()
      < ms.sum() * 0.9)


# ══════════════════════════════════════════════════ 6. Groups
sec("The two groups (what this node is really for)")
# horizontal ramp f(u) = u, threshold 0.5 <=> u >= 0.5 <=> world x >= 0 (analytic under orthographic)
ramp = img_from(lambda U, V: U)
g_gr, i_gr = CP.project_attribute(grid, CAM, ramp, layer="C", name="m",
                                  visibility="all", mask_group="painted",
                                  visible_group="seen", threshold=0.5)
painted = g_gr.get_group(POINT, "painted")
seen = g_gr.get_group(POINT, "seen")
want_painted = uv_analytic(P)[:, 0] >= 0.5
check("mask_group is exactly the points with u >= 0.5 (= world x >= 0)",
      np.array_equal(painted, want_painted),
      f"{int((painted != want_painted).sum())} differ")
check("  equivalent to half of world space (analytic under orthographic projection)",
      np.array_equal(painted, P[:, 0] >= -1e-12))
check("visible_group in all mode is the full set", seen.all())
g_gr2, _ = CP.project_attribute(grid, CAM, ramp, layer="C", name="m",
                                visibility="all", mask_group="p",
                                threshold=0.5, scale=0.0, offset=1.0)
check("the threshold tests the **value written to the attribute** (after scale/offset)",
      g_gr2.get_group(POINT, "p").all())
g_gr3, _ = CP.project_attribute(grid, CAM, ramp, layer="C", name="m",
                                visibility="all", mask_group="p",
                                threshold=0.5, scale=0.0, offset=0.0)
check("  [negative control] pushing the value to 0 empties the group",
      not g_gr3.get_group(POINT, "p").any())
g_bd, _ = CP.project_attribute(two, CAM, ramp, layer="C", name="m",
                               visibility="full", facing_min=0.0,
                               visible_group="vis", mask_group="p")
check("occluded elements do **not** enter mask_group (even if the sampled value passes the threshold)",
      not g_bd.get_group(POINT, "p")[nf:].any())
err("threshold_channel out of range raises",
    lambda: CP.project_attribute(grid, CAM, ramp, layer="C", name="m",
                                 mask_group="p", threshold_channel=5),
    "out of range")


# ══════════════════════════════════════════════ 7. missing / blend
sec("missing / blend")
base = grid.copy()
base.set(POINT, "m", np.full((grid.npoints, 1), 9.0), dtype=np.float32)
occ_cam = R.camera(None, projection="orthographic", eye=(0, 0, -10),
                   target=(0, 0, 0), ortho_size=ORTHO_SIZE, xres=RES,
                   yres=RES)          # seen from the back: all back-facing -> nothing visible
for miss, want in (("keep", 9.0), ("zero", 0.0), ("value", -3.0)):
    g_m, i_m = CP.project_attribute(base, occ_cam, ramp, layer="C", name="m",
                                    visibility="front", missing=miss,
                                    missing_value=-3.0)
    v = np.asarray(g_m.get(POINT, "m"), np.float64)[:, 0]
    check(f"missing={miss}: invisible elements get {want}",
          i_m["visible"] == 0 and np.allclose(v, want), f"{v[0]}")
g_b, _ = CP.project_attribute(base, CAM, ramp, layer="C", name="m",
                              visibility="all", blend=0.5)
v_full, _ = CP.project_attribute(base, CAM, ramp, layer="C", name="m",
                                 visibility="all", blend=1.0)
check("blend=0.5 is the midpoint of old and new values",
      np.allclose(np.asarray(g_b.get(POINT, "m"), np.float64),
                  (9.0 + np.asarray(v_full.get(POINT, "m"), np.float64)) / 2,
                  atol=1e-6))
check("blend=0 keeps the old value entirely",
      np.allclose(np.asarray(CP.project_attribute(
          base, CAM, ramp, layer="C", name="m", visibility="all",
          blend=0.0)[0].get(POINT, "m"), np.float64), 9.0))
g_sel = base.copy()
half_sel = np.zeros(grid.npoints, bool)
half_sel[: grid.npoints // 2] = True
g_sel.set_group(POINT, "half", half_sel)
g_h, _ = CP.project_attribute(g_sel, CAM, ramp, layer="C", name="m",
                              visibility="all", group="half")
vh = np.asarray(g_h.get(POINT, "m"), np.float64)[:, 0]
check("elements outside the group keep their old value", np.allclose(vh[~half_sel], 9.0))
check("  those inside the group were changed", not np.allclose(vh[half_sel], 9.0))


# ══════════════════════════════════════════════ 8. The three classes
sec("point / vertex / prim")
g_v, i_v = CP.project_attribute(grid, CAM, ramp, layer="C", cls=VERTEX,
                                name="uvm", visibility="all")
check("vertex mode writes a vertex attribute, length nvertices",
      g_v.get(VERTEX, "uvm") is not None
      and len(g_v.get(VERTEX, "uvm")) == grid.nvertices)
check("  a vertex's anchor is its point (projection matches point mode)",
      np.allclose(np.asarray(g_v.get(VERTEX, "uvm"), np.float64)[:, 0],
                  np.asarray(CP.project_attribute(
                      grid, CAM, ramp, layer="C", name="m",
                      visibility="all")[0].get(POINT, "m"),
                      np.float64)[grid.vertex_point, 0], atol=1e-6))
g_p, i_p = CP.project_attribute(grid, CAM, ramp, layer="C", cls=PRIM,
                                name="pm", visibility="all")
check("prim mode writes a prim attribute, length nprims",
      len(g_p.get(PRIM, "pm")) == grid.nprims)
cen = np.asarray(OPS.prim_centers(grid), np.float64)
check("  a prim's anchor is its center (value equals the analytic value at the center)",
      np.allclose(np.asarray(g_p.get(PRIM, "pm"), np.float64)[:, 0],
                  uv_analytic(cen)[:, 0], atol=5e-6))
g_uv, _ = CP.project_attribute(grid, CAM, ramp, layer="C", cls=VERTEX,
                               name="m", visibility="all", uv_name="camuv")
check("non-empty uv_name also writes screen uv (2 components)",
      g_uv.get(VERTEX, "camuv") is not None
      and g_uv.get(VERTEX, "camuv").shape[1] == 2)
check("  the written uv matches the formula",
      np.allclose(np.asarray(g_uv.get(VERTEX, "camuv"), np.float64),
                  uv_analytic(P)[grid.vertex_point], atol=1e-6))

# point cloud: no normals, front / full should not drop all of it
cloud = Geometry(5)
cloud.set(POINT, "P", np.array([[0, 0, 0], [0.5, 0.5, 0], [-0.5, 0.5, 0],
                                [0.5, -0.5, 0], [-0.5, -0.5, 0]], np.float32),
          owned=True)
_, i_c = CP.project_attribute(cloud, CAM, ramp, layer="C", name="m",
                              visibility="full")
check("**a point cloud without normals is not dropped entirely** (point clouds without normals are the norm)",
      i_c["visible"] == 5, i_c)


# ══════════════════════════════════════════════════ 9. Errors
sec("Errors")
err("bad class", lambda: CP.project_attribute(grid, CAM, ramp, cls="bogus"),
    "class must be one of")
err("bad visibility",
    lambda: CP.project_attribute(grid, CAM, ramp, visibility="bogus"),
    "visibility must be one of")
err("bad occlusion",
    lambda: CP.project_attribute(grid, CAM, ramp, occlusion="bogus"),
    "occlusion must be one of")
err("bad missing",
    lambda: CP.project_attribute(grid, CAM, ramp, missing="bogus"),
    "missing must be one of")
err("empty attribute name",
    lambda: CP.project_attribute(grid, CAM, ramp, name="  "), "cannot be empty")
err("says so clearly when the image is not a COPIMAGE",
    lambda: CP.project_attribute(grid, CAM, np.zeros((4, 4, 3))), "COPIMAGE")
err("missing layer raises",
    lambda: CP.project_attribute(grid, CAM, ramp, layer="nope"), "nope")
check("None geometry returns empty geometry instead of raising",
      CP.project_attribute(None, CAM, ramp)[0].npoints == 0)
empty = Geometry(0)
check("empty geometry does not raise either", CP.project_attribute(empty, CAM, ramp)[1]["total"] == 0)


# ══════════════════════════════════════════════════ 10. Node
sec("Node")
node = N.PCG_AttribFromCamera()
out = unwrap(node.run(
    grid, CAM, ramp, "C", **{"class": "point"}, name="m", channels="",
    decode="none", filter="bilinear", border="clamp", scale=1.0, offset=0.0,
    blend=1.0, visibility="all", occlusion="element+depth",
    facing_min=CP.FACING_MIN, depth_bias=CP.DEPTH_BIAS, silhouette_guard=1,
    border_margin=0.0, normal_attrib="N", missing="keep", missing_value=0.0,
    visible_group="", mask_group="painted", threshold=0.5,
    threshold_channel=0, uv_name="", group=""))
check("returns (geo, visible, coverage, info)", len(out) == 4)
check("  visible is INT, coverage is FLOAT",
      isinstance(out[1], int) and isinstance(out[2], float))
check("  coverage is 1.0 in all mode", out[2] == 1.0, out[2])
check("  info contains four numbers (visible / out of frame / back-facing / occluded)",
      all(k in out[3] for k in ("visible", "out of frame", "back-facing", "occluded")), out[3])
check("  the group was really created",
      out[0].get_group(POINT, "painted") is not None)
spec = N.PCG_AttribFromCamera.INPUT_TYPES()["required"]
check("cam is a required input (cannot project without it)", spec["cam"] == ("PCGCAM",))
check("dropdown items are the module's constants",
      spec["visibility"][0] == list(CP.VISIBILITY)
      and spec["occlusion"][0] == list(CP.OCCLUSION)
      and spec["missing"][0] == list(CP.MISSING)
      and spec["class"][0] == list(CP.CLASSES))
check("facing_min default is 0.1 (the measured zero-misjudgement knee)",
      spec["facing_min"][1]["default"] == 0.1)
check("in the PCG/attribute category (together with Attribute from Map)",
      N.PCG_AttribFromCamera.CATEGORY == "PCG/attribute")


# ═══════════════════════════════════ 11. The chain from the pitch: shatter wherever the AI paints
sec("Render Pass -> (AI) -> mask_group -> Blast")
box = build.box(size=(2.0, 2.0, 2.0), divisions=(6, 6, 6))
bcam2 = R.camera(box, xres=128, yres=128, orbit=True, elev=20, azim=30,
                 distance=6)
# pretend this is a mask from a diffusion model: right half of the frame
paint = img_from(lambda U, V: (U > 0.5).astype(np.float64), 128, 128)
g_mask, i_mask = CP.project_attribute(box, bcam2, paint, layer="C",
                                      cls=PRIM, name="paint",
                                      filter="closest",
                                      mask_group="tofracture",
                                      visible_group="seen")
sel = g_mask.get_group(PRIM, "tofracture")
seen2 = g_mask.get_group(PRIM, "seen")
check("projecting onto prims gives a usable primitive group",
      sel is not None and 0 < int(sel.sum()) < box.nprims,
      f"{int(sel.sum())}/{box.nprims} prims")
check("  selected prims are **necessarily** visible (invisible ones cannot get in)",
      bool((sel & ~seen2).sum() == 0))
cen_b = np.asarray(OPS.prim_centers(g_mask), np.float64)
uvb, _ = CP.screen_uv(bcam2, cen_b)
# the mask is quantized **per pixel**: closest mode takes floor(u·W), so a prim center exactly at u=0.5
# asks pixel 64, whose center is 0.504 -- which is painted. The check leaves
# a one-pixel margin; without it, it would test not "is the projection right" but "who owns the boundary pixel"
tol = 1.0 / 128
check("  selected prim centers are all in the right half of the frame (u >= 0.5, one-pixel margin)",
      bool((uvb[sel][:, 0] >= 0.5 - tol).all()), uvb[sel][:, 0].min())
kept = OPS.delete_prims(g_mask, ~sel)
check("prim count left after blasting this group matches",
      kept.nprims == box.nprims - int(sel.sum()),
      f"{kept.nprims} vs {box.nprims - int(sel.sum())}")
# back-facing prims are not selected -- exactly where "treat it as a UV projection" goes wrong
n_b = np.asarray(OPS.prim_normals(g_mask), np.float64)
eye = np.asarray(bcam2["eye"], np.float64)
d_b = eye - cen_b
d_b /= np.linalg.norm(d_b, axis=1, keepdims=True)
facing_b = np.einsum("ij,ij->i", n_b, d_b)
check("**not a single prim facing away from the camera is selected** -- exactly where using the camera as a UV projection goes wrong",
      bool((facing_b[sel] > 0).all()), facing_b[sel].min())
g_naive, _ = CP.project_attribute(box, bcam2, paint, layer="C", cls=PRIM,
                                  name="paint", filter="closest",
                                  visibility="all", mask_group="naive")
naive = g_naive.get_group(PRIM, "naive")
check("  [negative control] visibility=all (= plain projection) also paints back faces",
      bool((facing_b[naive] < 0).any()),
      f"{int((facing_b[naive] < 0).sum())} back faces painted")


print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
