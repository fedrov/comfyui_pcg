"""
Render Pass -- camera + rasterization, rendering geometry into COP layers (depth / normal / uv / id ...).

This is **the most important piece** between PCG and diffusion models: the ControlNet side relies entirely on depth, normals,
line art and segmentation maps as conditions, and PCG **computes these analytically**, rather than MiDaS guessing them. Having exact
3D information but only being able to feed a shaded preview throws away the biggest advantage.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Why write a rasterizer instead of reusing the existing ray_cast
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`spatial.ray_cast` is already fast and robust, and the first version was written with it: one ray per pixel, returning
the hit triangle + distance + barycentric coordinates, exactly enough for interpolation. But measured:

    sphere of 5888 triangles, 512^2
      perspective (varying directions -> DDA)        0.58s
      orthographic (same direction -> projected buckets)    4.41s     <- actually slower

The cost of ray intersection is O(pixels x acceleration structure), while rasterization is **O(covered pixels)** -- places on screen
not covered do not take part at all. Rendering should use rasterization anyway, especially when video needs per-frame renders.

This does not violate the principle "do not write intersection twice": a rasterizer is not a second ray intersector, it is **a different class
of algorithm** (screen-space scan conversion). And precisely because there are two independent implementations, tests can **use ray_cast
as a per-pixel reference** -- harder evidence than any self-verification.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fully vectorized: candidate pair expansion + two-pass z reduction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Loop over triangles, vectorize within each one's bounding box" is the easiest to write, but 5888 Python iterations
eat up the advantage. Instead:

    1. compute each triangle's screen bounding box -> how many candidate pixels it contributes
    2. expand all at once into flat (triangle, pixel) candidate pairs (the `_gather_blocks` machinery)
    3. compute all barycentric coordinates in one go, filtering out those inside the box but outside the triangle
    4. reduce the z-buffer in **two passes**: first `np.minimum.at` for each pixel's minimum z,
       then pick the candidate pairs with `z == zbuf[pix]` and scatter their triangle numbers in

Why step 4 needs two passes: `minimum.at` only gives the minimum, not who is the minimum. Filtering back by float **exact
equality** is safe -- it compares the same number produced by the same computation, not approximations computed along two
different paths.

The total number of candidate pairs is capped (`max_pairs`); beyond that, triangles are processed in batches -- one big triangle covering the screen
can contribute 262144 candidate pairs by itself; without a gate, large scenes would eat all memory.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Perspective interpolation must divide by w, not interpolate linearly
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Screen-space barycentric coordinates are not linear in **depth**. Interpolating uv / positions with them directly skews nearby textures
(the classic wobble of every early 3D game). The correct way is to interpolate `attr/w` and `1/w` and divide.

Here **every** per-vertex interpolated quantity is perspective-corrected, including depth itself: z is recovered from linear interpolation
of `1/z`. An orthographic camera has w = 1 everywhere, so the same code automatically degenerates to ordinary linear interpolation, no branch needed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Row order aligns with COP by construction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Screen row y = 0 is the **bottom of the frame** (ndc_y = -1), exactly matching COP's "row 0 is the bottom, v points up".
So the render goes straight into a CopImage without flipping -- one less flip point.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Near-plane clipping (pcg80)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Triangles crossing the near plane are cut in camera space along z = near (Sutherland-Hodgman against one plane):
one vertex in front -> a small triangle is cut out; two in front -> a quad is cut out and split into two triangles.
The new vertices are exactly on the near plane, so their projection is well defined.

**The output conventions have not changed at all**: hit is still the index of the **original triangle**, and bary is still the barycentric coordinates relative to
the original triangle's three vertices -- each clipped vertex records its barycentric coordinates lambda in the original triangle (points on edges are linear combinations of
the two ends), and the perspective-corrected barycentrics b interpolated in the sub-triangle are multiplied back: bary = sum b_k lambda_k. Barycentrics are linear
in 3D, so this step is exact; downstream (attribute interpolation, face normals, motion vectors, back-projection) needs no change at all.

Before pcg80, triangles crossing the near plane were dropped entirely: for a large face like the ground, with the camera standing on it there is always
a vertex behind it, and the whole ground disappeared (found while making a shot moving along a track through a scene). Tests compare per pixel against
spatial.ray_cast: with the camera standing on a large ground plane, looking out from inside a box, hit triangles and depths
agree with ray intersection.
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, is_string
from .divide import _gather_blocks

PROJECTIONS = ("perspective", "orthographic")
NORMAL_SPACES = ("camera", "world")
NORMAL_SOURCES = ("auto", "point", "face")
PASSES = ("depth", "mask", "normal", "position", "uv", "id", "facing",
          "shade")
MAX_PAIRS = 1 << 24


# ════════════════════════════════════════════════════════════════ camera
def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    """Right-handed orthonormal basis (right, up, forward). forward points in the viewing direction."""
    eye = np.asarray(eye, np.float64).reshape(3)
    target = np.asarray(target, np.float64).reshape(3)
    f = target - eye
    n = np.linalg.norm(f)
    if n < 1e-12:
        f = np.array([0.0, 0.0, -1.0])
    else:
        f = f / n
    u0 = np.asarray(up, np.float64).reshape(3)
    r = np.cross(f, u0)
    if np.linalg.norm(r) < 1e-9:
        # Line of sight parallel to up -- switch to another up rather than spitting out NaN. Top/bottom views are common camera positions
        u0 = np.array([0.0, 0.0, 1.0]) if abs(f[1]) > 0.9 \
            else np.array([0.0, 1.0, 0.0])
        r = np.cross(f, u0)
    r = r / np.linalg.norm(r)
    u = np.cross(r, f)
    return eye, r, u, f


def orbit_eye(target, distance, elev_deg, azim_deg):
    """Orbit camera position: elevation + azimuth + distance. Feels the same as the Viewport."""
    t = np.asarray(target, np.float64).reshape(3)
    e = np.radians(float(elev_deg))
    a = np.radians(float(azim_deg))
    d = float(distance)
    return t + d * np.array([np.cos(e) * np.sin(a), np.sin(e),
                             np.cos(e) * np.cos(a)])


def frame_distance(radius, fov_deg, margin=1.15):
    """Distance needed for a sphere of radius radius to just fit the frame."""
    half = np.radians(max(float(fov_deg), 1e-3) * 0.5)
    return float(radius * float(margin) / max(np.sin(half), 1e-6))


def camera(geo=None, projection="perspective", eye=(0.0, 0.0, 5.0),
           target=(0.0, 0.0, 0.0), up=(0.0, 1.0, 0.0), fov=45.0,
           ortho_size=2.0, xres=512, yres=512, near=0.01, far=0.0,
           orbit=False, elev=25.0, azim=35.0, distance=5.0,
           frame_geometry=False, margin=1.15):
    """
    Build a camera. With `frame_geometry` the distance / orthographic size are set automatically from the geometry's bounding sphere --
    this is the most common mode: "frame this object and render a depth map".
    """
    if projection not in PROJECTIONS:
        raise ValueError(f"Projection must be one of {PROJECTIONS}")
    tgt = np.asarray(target, np.float64).reshape(3)
    radius = 1.0
    if geo is not None and geo.npoints:
        mn, mx = geo.bbox()
        mn = np.asarray(mn, np.float64)
        mx = np.asarray(mx, np.float64)
        ctr = (mn + mx) * 0.5
        # **The true bounding sphere radius**, not half the bounding box diagonal. Using the diagonal,
        # a unit sphere would be treated as a sphere of radius sqrt(3), filling only 48% of the frame after framing --
        # and in orthographic mode coverage drops from pi/4 to 0.26; the composition is visibly too empty
        Pw = np.asarray(geo.get(POINT, "P"), np.float64)
        radius = max(float(np.linalg.norm(Pw - ctr, axis=1).max()), 1e-6)
        if frame_geometry:
            tgt = ctr
    dist = float(distance)
    osize = float(ortho_size)
    if frame_geometry:
        if projection == "perspective":
            dist = frame_distance(radius, fov, margin)
        else:
            dist = radius * 3.0
            osize = radius * 2.0 * float(margin)
    ey = orbit_eye(tgt, dist, elev, azim) if (orbit or frame_geometry) \
        else np.asarray(eye, np.float64).reshape(3)
    if not (orbit or frame_geometry):
        # In look_at mode the Distance parameter does not affect the camera position; record the real camera-to-target distance --
        # this used to hold the unused parameter value (found when Camera To Points round trips did not match)
        dist = float(np.linalg.norm(ey - tgt))
    ey, r, u, f = look_at(ey, tgt, up)
    return {"projection": projection, "eye": ey, "right": r, "up": u,
            "forward": f, "fov": float(fov), "ortho_size": osize,
            "xres": int(xres), "yres": int(yres), "near": float(near),
            "far": float(far) if float(far) > 0 else 0.0,
            "radius": radius, "target": tgt, "distance": dist}


def project(cam, P):
    """
    World coordinates -> (screen x, screen y, camera-space z).

    Screen row y = 0 is the **bottom of the frame** (consistent with COP's v pointing up), so no flip here.
    For orthographic, z is still the distance along forward, it just does not take part in the division.
    """
    P = np.asarray(P, np.float64).reshape(-1, 3)
    d = P - cam["eye"]
    x = d @ cam["right"]
    y = d @ cam["up"]
    z = d @ cam["forward"]
    W, H = cam["xres"], cam["yres"]
    if cam["projection"] == "perspective":
        half = np.tan(np.radians(cam["fov"] * 0.5))
        aspect = W / float(H)
        zz = np.where(np.abs(z) < 1e-12, 1e-12, z)
        ndx = (x / zz) / (half * aspect)
        ndy = (y / zz) / half
    else:
        half = cam["ortho_size"] * 0.5
        aspect = W / float(H)
        ndx = x / (half * aspect)
        ndy = y / half
    sx = (ndx + 1.0) * 0.5 * W - 0.5
    sy = (ndy + 1.0) * 0.5 * H - 0.5
    return sx, sy, z


# ════════════════════════════════════════════════════════════════ rasterization
def rasterize(geo, cam, group="", cull="none", max_pairs=MAX_PAIRS, soup=None):
    """
    z-buffer rasterization. Returns a dict:

        hit   (H,W) int64   index of the hit triangle, -1 if no hit
        z     (H,W)         camera-space z (perspective-corrected interpolation), 0 if no hit
        bary  (H,W,3)       barycentric weights (perspective-corrected, sum to 1)
        tri   (T,3)         point numbers of the triangles
        cor   (T,3)         corner numbers of the triangles (needed to interpolate vertex attributes)
        src   (T,)          which prim each triangle comes from

    soup: an earlier tri_soup(geo, group) result to reuse (cutting ngons costs seconds on millions of faces, and a
    lit render rasterizes the same geometry several times).
    """
    from .spatial import tri_soup
    W, H = int(cam["xres"]), int(cam["yres"])
    hit = np.full((H, W), -1, np.int64)
    zb = np.zeros((H, W))
    bary = np.zeros((H, W, 3))
    out = {"hit": hit, "z": zb, "bary": bary,
           "tri": np.zeros((0, 3), np.int64),
           "cor": np.zeros((0, 3), np.int64), "src": np.zeros(0, np.int64)}
    if geo is None or geo.nprims == 0 or geo.npoints == 0:
        return out
    tri, src, cor = soup if soup is not None else tri_soup(geo, group)
    out["tri"], out["src"], out["cor"] = tri, src, cor
    if not len(tri):
        return out

    P = np.asarray(geo.get(POINT, "P"), np.float64)
    sx, sy, z = project(cam, P)
    near = max(cam["near"], 1e-9)
    zt = z[tri]
    live = np.ones(len(tri), bool)
    if cam["far"] > 0:
        live &= (zt < cam["far"]).any(1)
    ins = zt > near
    cnt = ins.sum(1)
    plain = np.nonzero(live & (cnt == 3))[0]
    rtri, rsrc, lam = tri[plain], plain, None
    cut = np.nonzero(live & (cnt > 0) & (cnt < 3))[0]
    if len(cut):
        NP, rt, rs, lam = _clip_near(P, tri, zt, ins, cnt, cut, near)
        nx, ny, nz = project(cam, NP)
        sx, sy, z = (np.concatenate([sx, nx]), np.concatenate([sy, ny]),
                     np.concatenate([z, nz]))
        rt = np.where(rt < 0, -1 - rt, rt + len(P))   # negative = original point, positive = new vertex
        rtri = np.concatenate([rtri, rt])
        rsrc = np.concatenate([rsrc, rs])
    A, B, C = rtri[:, 0], rtri[:, 1], rtri[:, 2]
    keep = np.ones(len(rtri), bool)
    if cull in ("back", "front"):
        # Clipped sub-triangle vertices are all in front of the near plane with the same winding as the original triangle, so the sign of the screen area
        # still tells front from back
        area = ((sx[B] - sx[A]) * (sy[C] - sy[A])
                - (sy[B] - sy[A]) * (sx[C] - sx[A]))
        keep &= (area > 0) if cull == "back" else (area < 0)
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return out
    rast = (rtri, rsrc, lam, len(plain))

    x0 = np.maximum(np.floor(np.minimum.reduce(
        [sx[A[idx]], sx[B[idx]], sx[C[idx]]])).astype(np.int64), 0)
    x1 = np.minimum(np.ceil(np.maximum.reduce(
        [sx[A[idx]], sx[B[idx]], sx[C[idx]]])).astype(np.int64) + 1, W)
    y0 = np.maximum(np.floor(np.minimum.reduce(
        [sy[A[idx]], sy[B[idx]], sy[C[idx]]])).astype(np.int64), 0)
    y1 = np.minimum(np.ceil(np.maximum.reduce(
        [sy[A[idx]], sy[B[idx]], sy[C[idx]]])).astype(np.int64) + 1, H)
    bw = np.maximum(x1 - x0, 0)
    bh = np.maximum(y1 - y0, 0)
    area = bw * bh
    live = area > 0
    idx, x0, y0, bw, bh, area = (idx[live], x0[live], y0[live], bw[live],
                                 bh[live], area[live])
    if not len(idx):
        return out

    # Batch by candidate pair count -- one triangle covering the screen has W x H candidate pairs by itself
    cum = np.cumsum(area)
    total = int(cum[-1])
    nbatch = max(1, int(np.ceil(total / float(max(max_pairs, 1024)))))
    bounds = np.searchsorted(cum, np.linspace(0, total, nbatch + 1)[1:])
    start = 0
    for stop in bounds:
        stop = int(min(max(stop + 1, start + 1), len(idx)))
        _raster_batch(out, cam, rast, sx, sy, z,
                      idx[start:stop], x0[start:stop], y0[start:stop],
                      bw[start:stop], bh[start:stop], area[start:stop], W, H)
        start = stop
        if start >= len(idx):
            break
    return out


def _clip_near(P, tri, zt, ins, cnt, cut, near):
    """
    Cut triangles crossing the near plane. Returns (new vertices (K,3), sub-triangles (S,3), corresponding original triangle numbers (S,),
    lambda (S,3,3): barycentric coordinates of each sub-triangle vertex in the original triangle). Sub-triangle vertex numbers: negative
    -1 - p is original point p, non-negative is the index of a new vertex (the caller adds the offset).
    """
    k = cut
    one = cnt[k] == 1
    # Rotate so the "odd one out" vertex comes first: with one in front it is the one in front, with two in front it is
    # the one behind. Rotating (not swapping) preserves winding
    r = np.where(one, np.argmax(ins[k], 1), np.argmin(ins[k], 1))
    c0, c1, c2 = r, (r + 1) % 3, (r + 2) % 3
    rows = np.arange(len(k))
    i0, i1, i2 = tri[k, c0], tri[k, c1], tri[k, c2]
    z0, z1, z2 = zt[k, c0], zt[k, c1], zt[k, c2]
    t01 = (z0 - near) / (z0 - z1)
    t02 = (z0 - near) / (z0 - z2)
    P01 = P[i0] + t01[:, None] * (P[i1] - P[i0])
    P02 = P[i0] + t02[:, None] * (P[i2] - P[i0])
    E = np.eye(3)
    e0, e1, e2 = E[c0], E[c1], E[c2]
    l01 = (1 - t01)[:, None] * e0 + t01[:, None] * e1
    l02 = (1 - t02)[:, None] * e0 + t02[:, None] * e2
    n = len(k)
    NP = np.concatenate([P01, P02])
    v01, v02 = rows, n + rows
    tris, src, lams = [], [], []
    o = np.nonzero(one)[0]
    if len(o):              # one vertex in front: (i0, P01, P02)
        tris.append(np.stack([-1 - i0[o], v01[o], v02[o]], 1))
        src.append(k[o])
        lams.append(np.stack([e0[o], l01[o], l02[o]], 1))
    w = np.nonzero(~one)[0]
    if len(w):              # two vertices in front: quad (P01, i1, i2, P02) split into two
        tris.append(np.stack([v01[w], -1 - i1[w], -1 - i2[w]], 1))
        tris.append(np.stack([v01[w], -1 - i2[w], v02[w]], 1))
        src += [k[w], k[w]]
        lams.append(np.stack([l01[w], e1[w], e2[w]], 1))
        lams.append(np.stack([l01[w], e2[w], l02[w]], 1))
    return NP, np.concatenate(tris), np.concatenate(src), np.concatenate(lams)


def _raster_batch(out, cam, rast, sx, sy, z, idx, x0, y0, bw, bh, area, W, H):
    tri, rsrc, lam, nplain = rast
    # Each block gets 0..area-1 -- local indices within the bounding box
    flat = _gather_blocks(np.zeros(len(area), np.int64), area)
    tid = np.repeat(idx, area)
    bwr = np.repeat(bw, area)
    px = np.repeat(x0, area) + (flat % bwr)
    py = np.repeat(y0, area) + (flat // bwr)

    a, b, c = tri[tid, 0], tri[tid, 1], tri[tid, 2]
    ax, ay = sx[a], sy[a]
    bx, by = sx[b], sy[b]
    cx, cy = sx[c], sy[c]
    den = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    ok = np.abs(den) > 1e-12
    den = np.where(ok, den, 1.0)
    qx = px.astype(np.float64)
    qy = py.astype(np.float64)
    w1 = ((qx - ax) * (cy - ay) - (qy - ay) * (cx - ax)) / den
    w2 = ((bx - ax) * (qy - ay) - (by - ay) * (qx - ax)) / den
    w0 = 1.0 - w1 - w2
    eps = -1e-9
    ok &= (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
    if not ok.any():
        return
    tid, px, py = tid[ok], px[ok], py[ok]
    w0, w1, w2 = w0[ok], w1[ok], w2[ok]
    a, b, c = a[ok], b[ok], c[ok]

    # Perspective correction: interpolate 1/z, then invert. For orthographic z does not take part in the division, but these formulas are still right --
    # there screen barycentrics are linear anyway, and inverting the linear interpolation of 1/z gives back the same z
    if cam["projection"] == "perspective":
        iz = w0 / z[a] + w1 / z[b] + w2 / z[c]
        zz = 1.0 / np.where(np.abs(iz) < 1e-30, 1e-30, iz)
        # Corrected barycentrics: each divided by its own z, then multiplied by the interpolated z
        b0 = w0 * zz / z[a]
        b1 = w1 * zz / z[b]
        b2 = w2 * zz / z[c]
    else:
        zz = w0 * z[a] + w1 * z[b] + w2 * z[c]
        b0, b1, b2 = w0, w1, w2

    pix = py * W + px
    zbuf = out["z"].reshape(-1)
    hitf = out["hit"].reshape(-1)
    bar = out["bary"].reshape(-1, 3)
    # First pass: minimum z per pixel. **Existing hits must take part in the comparison too** -- when batching,
    # a later batch must not unconditionally overwrite an earlier one
    best = np.full(W * H, np.inf)
    np.minimum.at(best, pix, zz)
    best = np.minimum(best, np.where(hitf >= 0, zbuf, np.inf))
    # Second pass: pick the candidates exactly equal to the minimum z and scatter their triangle numbers in.
    # Float exact equality is safe -- it compares the same number from the same computation
    win = zz <= best[pix]
    wpix = pix[win]
    zbuf[wpix] = zz[win]
    tw = tid[win]
    hitf[wpix] = rsrc[tw]                      # sub-triangle -> original triangle
    bw_ = np.stack([b0[win], b1[win], b2[win]], 1)
    if lam is not None:
        cl = tw >= nplain
        if cl.any():                           # convert sub-triangle barycentrics back to the original triangle's
            bw_[cl] = np.einsum("mk,mkj->mj", bw_[cl], lam[tw[cl] - nplain])
    bar[wpix] = bw_


# ════════════════════════════════════════════════════════════════ channels
def _interp(rast, values_per_point):
    """Perspective-corrected interpolation of point attributes. values (npoints, C) -> (H,W,C)."""
    hit, bary, tri = rast["hit"], rast["bary"], rast["tri"]
    H, W = hit.shape
    V = np.asarray(values_per_point, np.float64)
    if V.ndim == 1:
        V = V[:, None]
    out = np.zeros((H, W, V.shape[1]))
    m = hit >= 0
    if not m.any():
        return out
    t = hit[m]
    w = bary[m]
    out[m] = (V[tri[t, 0]] * w[:, 0:1] + V[tri[t, 1]] * w[:, 1:2]
              + V[tri[t, 2]] * w[:, 2:3])
    return out


def _interp_corner(rast, values_per_corner):
    """Interpolate attributes per corner (vertex class) -- that is where uv lives."""
    hit, bary, cor = rast["hit"], rast["bary"], rast["cor"]
    H, W = hit.shape
    V = np.asarray(values_per_corner, np.float64)
    if V.ndim == 1:
        V = V[:, None]
    out = np.zeros((H, W, V.shape[1]))
    m = hit >= 0
    if not m.any():
        return out
    t = hit[m]
    w = bary[m]
    out[m] = (V[cor[t, 0]] * w[:, 0:1] + V[cor[t, 1]] * w[:, 1:2]
              + V[cor[t, 2]] * w[:, 2:3])
    return out


def _face_normals(geo, rast):
    from .ops import prim_normals
    FN = np.asarray(prim_normals(geo), np.float64)
    hit = rast["hit"]
    out = np.zeros(hit.shape + (3,))
    m = hit >= 0
    out[m] = FN[rast["src"][hit[m]]]
    return out


def _id_values(geo, attrib):
    """prim attribute -> one integer id per face. String attributes are numbered by order of appearance."""
    a = geo.get(PRIM, attrib)
    if a is None:
        return None
    if is_string(a):
        _, inv = np.unique(np.asarray(a)[:, 0], return_inverse=True)
        return inv.reshape(-1).astype(np.float64)
    return np.asarray(a[:, 0], np.float64)


def render(geo, cam, group="", passes=("depth", "mask", "normal"),
           normal_space="camera", normal_source="auto", id_attrib="name",
           uv_attrib="uv", cull="none", device="numpy"):
    """
    Render a set of channels into a CopImage.

    Channels are all **raw values, unclamped**: depth is camera-space distance (meters), normal is a signed
    unit vector, uv is the original uv. Packing into 0-1 is `Control Image`'s job -- that step is tied to
    ControlNet's conventions and should not be mixed into rendering.
    """
    from .cop import CopImage, backend as _bk
    if normal_space not in NORMAL_SPACES:
        raise ValueError(f"Normal Space must be one of {NORMAL_SPACES}")
    if normal_source not in NORMAL_SOURCES:
        raise ValueError(f"Normal Source must be one of {NORMAL_SOURCES}")
    want = [p for p in passes if p]
    bad = [p for p in want if p not in PASSES]
    if bad:
        raise ValueError(f"Unknown channel {bad} -- choose from {PASSES}")

    rast = rasterize(geo, cam, group, cull)
    H, W = int(cam["yres"]), int(cam["xres"])
    hit = rast["hit"]
    m = (hit >= 0)
    xp = _bk.get(device, W * H, max(1, len(want)), 3)
    img = CopImage(W, H)

    if "mask" in want:
        img.set("mask", xp.asarray(m.astype(np.float32)[:, :, None]))
    if "depth" in want:
        img.set("depth", xp.asarray(rast["z"][:, :, None]))
    if "position" in want and geo is not None:
        img.set("P", xp.asarray(_interp(
            rast, np.asarray(geo.get(POINT, "P"), np.float64))))
    if "normal" in want:
        N = None
        src = normal_source
        if src in ("auto", "point"):
            pn = geo.get(POINT, "N") if geo is not None else None
            if pn is not None and pn.shape[1] >= 3:
                N = _interp(rast, np.asarray(pn[:, :3], np.float64))
            elif src == "point":
                from .ops import compute_normals
                N = _interp(rast, np.asarray(compute_normals(
                    geo, add_to="point").get(POINT, "N")[:, :3], np.float64))
        if N is None:
            N = _face_normals(geo, rast)
        ln = np.linalg.norm(N, axis=-1, keepdims=True)
        N = N / np.where(ln < 1e-12, 1.0, ln)
        if normal_space == "camera":
            # Convert to camera space: ControlNet's normal maps are in this space.
            # **The third axis is -forward**, i.e. +Z points at the viewer -- the common convention for normal maps
            # is "a face pointing straight at the camera = (0,0,1) = that classic light blue after packing". With
            # +forward, faces pointing at the camera would become 0.0 (pure yellow), the whole map's blue channel inverted,
            # and **no error raised**; the output's bump directions are just all wrong
            R = np.stack([cam["right"], cam["up"], -cam["forward"]], 0)
            N = N @ R.T
        N = np.where(m[:, :, None], N, 0.0)
        img.set("N", xp.asarray(N))
    if "uv" in want and geo is not None:
        name = str(uv_attrib).strip() or "uv"
        uvv = geo.get(VERTEX, name)
        if uvv is not None:
            UV = _interp_corner(rast, np.asarray(uvv[:, :2], np.float64))
        else:
            up = geo.get(POINT, name)
            if up is None:
                raise KeyError(
                    f"Geometry has no '{name}' attribute (neither vertex nor point) --"
                    f" the uv channel needs a UV Project (PCG) first.")
            UV = _interp(rast, np.asarray(up[:, :2], np.float64))
        img.set("uv", xp.asarray(np.where(m[:, :, None], UV, 0.0)))
    if "id" in want and geo is not None:
        vals = _id_values(geo, str(id_attrib).strip() or "name")
        if vals is None:
            have = sorted(geo.attribs[PRIM].keys())
            raise KeyError(
                f"No '{id_attrib}' attribute on prim -- the id channel needs pieces first "
                f"(Voronoi Fracture / Convex Decompose / Connectivity all write it). "
                f"Existing: {have or '(none)'}")
        idmap = np.full((H, W), -1.0)
        idmap[m] = vals[rast["src"][hit[m]]]
        img.set("id", xp.asarray(idmap[:, :, None]))
    if "facing" in want:
        # How much the face points at the camera: |N.forward|. Used for rim light / silhouette masks
        N = np.asarray(img.get("N"), np.float64) if "N" in img else \
            _face_normals(geo, rast)
        if normal_space == "camera" and "N" in img:
            fwd = np.array([0.0, 0.0, 1.0])
        else:
            fwd = cam["forward"]
        img.set("facing", xp.asarray(np.abs(N @ fwd)[:, :, None]))
    if "shade" in want:
        N = np.asarray(img.get("N"), np.float64) if "N" in img else None
        if N is None:
            N = _face_normals(geo, rast)
            if normal_space == "camera":
                R = np.stack([cam["right"], cam["up"], -cam["forward"]], 0)
                N = N @ R.T
        # A light coming from the camera direction, just to "take a look at the shape". Not a final render
        lit = np.clip((N @ np.array([0.3, 0.5, 1.0]))
                      / np.linalg.norm([0.3, 0.5, 1.0]), 0.0, 1.0)
        lit = 0.15 + 0.85 * lit
        img.set("C", xp.asarray(np.repeat(
            np.where(m, lit, 0.0)[:, :, None], 3, axis=2)))
    return img
