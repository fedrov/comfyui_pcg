"""
pcg78: Camera To Points, Camera from Points -- converting between camera sequences and points.

━━ Camera To Points
One point per camera, point number = frame number. Attributes written:
    P            camera position
    orient       quaternion (x,y,z,w): local +Z is the view direction, +Y is up (+X = Y x Z, the left of the image).
                 Same convention as N / up, Orient Along Curve and Copy to Points -- copying a camera model built facing +Z
                 onto these points places it correctly; points from Orient Along Curve along a curve
                 go straight into Camera from Points and the camera looks along the curve.
                 Note this is **not** the convention of Houdini camera objects (which look down -Z): a camera model from Houdini
                 facing -Z must be rotated 180 deg about Y before Copy
    N            view direction (= +Z of orient)
    up           the camera's up direction (orthogonalized)
    target       point looked at; distance = |target - P|
    fov  ortho_size  near  far  radius      camera parameters carried over unchanged
    resx  resy   resolution (int)   projection (string)   frame (int)
With Path on, a polyline connecting the points by frame number is added (for viewing the path; Camera from Points only reads points, not this).
The second output is a frustum wireframe: one pyramid (perspective) or box (orthographic) per camera, with depth Frustum Depth.
The four corners of the base project exactly onto the four image corners (verified in the tests with render.project).

━━ Camera from Points
Points -> camera sequence, walking in point number order (curve points from Resample / PolySpline are numbered along the curve).
Where orientation comes from (Orientation):
    auto     orient if present; otherwise N if present; otherwise the target attribute if present; if none, path
    orient   the orient quaternion (+Z is the view direction, +Y is up, see above)
    normal   N is the view direction, the up attribute (Up parameter if missing) sets roll
    target   look at the target attribute; without it look at Target from the parameters (all cameras stare at one point)
    path     follow the path: with Look Ahead = 0 look along the tangent (point tangent = sum of the unit directions of the previous and next segments,
             linearly interpolated within segments and renormalized -- no sudden turns at kinks); with > 0 look at the point
             Look Ahead further along the path (an open path running past its end extends along the last segment), for a steadier camera
With Frames = 0 there is one camera per point; with > 0, Frames cameras are taken evenly **by arc length** along the path (with Loop on the path's ends
are joined, and as with Camera Path the last frame doesn't repeat the first). When a sample falls between two points: position is linearly interpolated,
orient is slerped (q flipped into the same hemisphere first), N / up / target / numeric attributes are linearly interpolated,
resolution and projection come from the nearer point.
With Use Point Attributes on, fov / ortho_size / near / far / radius / resx / resy /
projection / distance on the points override the parameters -- the round trip Camera To Points -> Camera from Points is exact
(in the tests the depth maps rendered by the cameras on both sides match).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM, is_string
from . import render as _rnd
from .xform import quat_to_mat
from .curveframe import mat_to_quat

CAM_ORIENT = ("auto", "orient", "normal", "target", "path")


# ════════════════════════════════════════════════════════ Camera To Points
def _basis(cam):
    """Column basis [-right, up, forward]: +Z is the view direction, +Y is up, so +X = Y x Z is the image's left."""
    r = np.asarray(cam["right"], np.float64)
    u = np.asarray(cam["up"], np.float64)
    f = np.asarray(cam["forward"], np.float64)
    return np.stack([-r, u, f], 1)


def _frustum_corners(cam, depth):
    """The four corners of the frustum at depth depth (bottom-left, bottom-right, top-right, top-left)."""
    e = np.asarray(cam["eye"], np.float64)
    r = np.asarray(cam["right"], np.float64)
    u = np.asarray(cam["up"], np.float64)
    f = np.asarray(cam["forward"], np.float64)
    a = float(cam["xres"]) / float(cam["yres"])
    if cam["projection"] == "perspective":
        h = np.tan(np.radians(float(cam["fov"]) * 0.5)) * depth
    else:
        h = float(cam["ortho_size"]) * 0.5
    w = h * a
    c = e + depth * f
    return np.stack([c - w * r - h * u, c + w * r - h * u,
                     c + w * r + h * u, c - w * r + h * u])


def cameras_to_points(cams, path=True, frustum_depth=0.5):
    """Returns (point geometry, frustum geometry, report)."""
    cams = list(cams)
    if not cams:
        raise ValueError("No cameras")
    n = len(cams)
    P = np.stack([np.asarray(c["eye"], np.float64) for c in cams])
    M = np.stack([_basis(c) for c in cams])
    g = Geometry.from_points(P.astype(np.float32))
    g.set(POINT, "orient", mat_to_quat(M).astype(np.float32), owned=True)
    g.set(POINT, "N", np.stack([c["forward"] for c in cams]).astype(np.float32),
          owned=True)
    g.set(POINT, "up", np.stack([c["up"] for c in cams]).astype(np.float32),
          owned=True)
    tg = np.stack([np.asarray(c.get("target", c["eye"] + c["forward"]),
                              np.float64) for c in cams])
    g.set(POINT, "target", tg.astype(np.float32), owned=True)
    g.set(POINT, "distance", np.linalg.norm(tg - P, axis=1)
          .astype(np.float32), owned=True)
    for k in ("fov", "ortho_size", "near", "far"):
        g.set(POINT, k, np.array([float(c[k]) for c in cams], np.float32),
              owned=True)
    g.set(POINT, "radius", np.array([float(c.get("radius", 1.0)) for c in cams],
                                    np.float32), owned=True)
    g.set(POINT, "resx", np.array([int(c["xres"]) for c in cams], np.int32),
          owned=True)
    g.set(POINT, "resy", np.array([int(c["yres"]) for c in cams], np.int32),
          owned=True)
    g.set_string(POINT, "projection", [str(c["projection"]) for c in cams])
    g.set(POINT, "frame", np.arange(n, dtype=np.int32), owned=True)
    if path and n > 1:
        g.set_topology(np.arange(n, dtype=np.int32),
                       np.array([0, n], np.int32), np.array([False]))
    # Frustum
    d = float(frustum_depth)
    fr = Geometry()
    if d > 0:
        pts, vp, off, fid = [], [], [0], []
        for i, c in enumerate(cams):
            base = sum(len(p) for p in pts)
            far4 = _frustum_corners(c, d)
            if c["projection"] == "perspective":
                pts.append(np.vstack([np.asarray(c["eye"], np.float64)[None], far4]))
                lines = [[0, 1], [0, 2], [0, 3], [0, 4], [1, 2, 3, 4, 1]]
            else:
                near4 = _frustum_corners(c, 0.0)
                pts.append(np.vstack([near4, far4]))
                lines = [[0, 4], [1, 5], [2, 6], [3, 7], [0, 1, 2, 3, 0],
                         [4, 5, 6, 7, 4]]
            for ln in lines:
                vp.extend(base + k for k in ln)
                off.append(len(vp))
                fid.append(i)
        fr = Geometry.from_points(np.vstack(pts).astype(np.float32))
        fr.set_topology(np.asarray(vp, np.int32), np.asarray(off, np.int32),
                        np.zeros(len(off) - 1, bool))
        fr.set(PRIM, "frame", np.asarray(fid, np.int32), owned=True)
    rep = {"cameras": n, "frustum_prims": int(fr.nprims)}
    return g, fr, rep


# ═══════════════════════════════════════════════════════ Camera from Points
def _slerp(a, b, t):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    d = float(a @ b)
    if d < 0:
        b, d = -b, -d
    if d > 1 - 1e-12:
        q = a + (b - a) * t
        return q / np.linalg.norm(q)
    th = np.arccos(min(d, 1.0))
    s = np.sin(th)
    return (np.sin((1 - t) * th) * a + np.sin(t * th) * b) / s


class _Path:
    """A polyline connecting points by point number, with arc-length lookup."""

    def __init__(self, P, loop):
        self.P = P
        self.n = len(P)
        self.loop = bool(loop)            # Loop with one point: one zero-length segment, no different from no Loop
        nxt = np.arange(1, self.n + (1 if self.loop else 0)) % self.n
        self.a = np.arange(len(nxt))
        self.b = nxt
        seg = P[self.b] - P[self.a]
        self.len = np.linalg.norm(seg, axis=1)
        self.cs = np.concatenate([[0.0], np.cumsum(self.len)])
        self.total = float(self.cs[-1])
        self.dir = seg / np.where(self.len > 0, self.len, 1.0)[:, None]

    def locate(self, s):
        """Arc length s -> (segment index k, ratio within segment u)."""
        ns = len(self.len)
        if ns == 0:
            return 0, 0.0
        if self.loop and self.total > 0:
            s = s % self.total
        # When landing exactly on a point, side may be left or right: one gives u = 1 of the previous segment, the other
        # u = 0 of the next, which is the same point (mutation testing confirmed they are equivalent)
        k = int(np.clip(np.searchsorted(self.cs, s, side="right") - 1, 0, ns - 1))
        L = self.len[k]
        u = float((s - self.cs[k]) / L) if L > 0 else 0.0
        return k, u

    def pos(self, s):
        """Only used in path mode, which already guarantees total > 0 (at least one non-zero-length segment)."""
        if not self.loop and s > self.total:
            # Past the end: extend along the direction of the last non-zero-length segment
            d = self.dir[np.nonzero(self.len > 0)[0][-1]]
            return self.P[-1] + (s - self.total) * d
        k, u = self.locate(s)
        return self.P[self.a[k]] * (1 - u) + self.P[self.b[k]] * u

    def vertex_tangents(self):
        """Point tangent: sum of the unit directions of the previous and next segments (endpoints have only one)."""
        T = np.zeros((self.n, 3))
        ns = len(self.len)
        for k in range(ns):
            T[self.a[k]] += self.dir[k]
            T[self.b[k]] += self.dir[k]
        nrm = np.linalg.norm(T, axis=1)
        # The sum is 0: a 180 deg reversal, or zero-length segments on both sides (three duplicate points in a row). Fall back to the first
        # non-zero-length direction after it; if there is none (the tail of an open path) use the last one before it
        nz = np.nonzero(self.len > 0)[0]
        for i in np.nonzero(nrm < 1e-12)[0]:
            after = nz[nz >= i]
            T[i] = self.dir[after[0] if len(after) else nz[-1]]
        nrm = np.linalg.norm(T, axis=1)
        return T / np.where(nrm > 0, nrm, 1.0)[:, None]


def _pick(geo, name, idx, ncomp=None):
    a = geo.get(POINT, name)
    if a is None:
        return None
    if is_string(a):
        return np.asarray(a).reshape(len(a), -1)[idx, 0]
    a = np.asarray(a, np.float64)[idx]
    if ncomp is not None and a.shape[1] < ncomp:
        return None
    return a if ncomp is None else a[:, :ncomp]


def cameras_from_points(geo, orientation="auto", frames=0, loop=False,
                        look_ahead=0.0, projection="perspective", xres=512,
                        yres=512, fov=45.0, ortho_size=2.0, near=0.01, far=0.0,
                        up=(0.0, 1.0, 0.0), target=(0.0, 0.0, 0.0),
                        focus_distance=5.0, use_point_attributes=True, group=""):
    """See the file header. Returns (camera list, report)."""
    from .groups import resolve
    if orientation not in CAM_ORIENT:
        raise ValueError(f"Orientation must be one of {CAM_ORIENT}")
    if projection not in _rnd.PROJECTIONS:
        raise ValueError(f"Projection must be one of {_rnd.PROJECTIONS}")
    idx = np.nonzero(resolve(geo, POINT, group))[0]
    if not len(idx):
        raise ValueError("No points")
    P = np.asarray(geo.get(POINT, "P"), np.float64)[idx]
    Q = _pick(geo, "orient", idx, 4)
    N = _pick(geo, "N", idx, 3)
    U = _pick(geo, "up", idx, 3)
    T = _pick(geo, "target", idx, 3)
    mode = orientation
    if mode == "auto":
        mode = ("orient" if Q is not None else "normal" if N is not None
                else "target" if T is not None else "path")
    if mode == "orient" and Q is None:
        raise KeyError("Points have no orient attribute (4 components)")
    if mode == "normal" and N is None:
        raise KeyError("Points have no N attribute")
    path = _Path(P, loop)
    n = len(P)
    # Sampling: (segment index k, ratio u, arc length s)
    nf = int(frames)
    samples = []
    if nf <= 0:
        ns = len(path.len)
        for i in range(n):
            # The last point of an open path = end of the last segment
            # (with only one point ns = 0, ends() gives 0 at both ends, so any k / u is the same)
            k, u = (i, 0.0) if i < ns else (ns - 1, 1.0)
            samples.append((k, u, float(path.cs[i])))
    else:
        den = nf if path.loop else max(nf - 1, 1)
        for j in range(nf):
            s = path.total * j / den
            k, u = path.locate(s)
            samples.append((k, u, s))
    Tv = None
    if mode == "path":
        if not path.total > 0:
            raise ValueError("path mode needs at least two non-coincident points (for the tangent to be defined)")
        Tv = path.vertex_tangents()

    def ends(k):
        if not len(path.len):
            return 0, 0
        return int(path.a[k]), int(path.b[k])

    def lerp(A, k, u):
        i, j = ends(k)
        return A[i] * (1 - u) + A[j] * u

    def near_i(k, u):
        i, j = ends(k)
        return j if u > 0.5 else i

    upw = np.asarray(up, np.float64)
    attrs = {}
    if use_point_attributes:
        for nm in ("fov", "ortho_size", "near", "far", "radius", "distance",
                   "resx", "resy"):
            a = _pick(geo, nm, idx, 1)
            if a is not None:
                attrs[nm] = a[:, 0]
        pr = _pick(geo, "projection", idx)
        if pr is not None and pr.dtype.kind == "U":
            attrs["projection"] = pr
    cams = []
    for (k, u, s) in samples:
        eye = lerp(P, k, u)
        prj = projection
        if "projection" in attrs:
            v = str(attrs["projection"][near_i(k, u)])
            prj = v if v in _rnd.PROJECTIONS else projection

        def num(nm, dflt):
            return float(lerp(attrs[nm], k, u)) if nm in attrs else float(dflt)
        dist = num("distance", focus_distance)
        if mode == "orient":
            i, j = ends(k)
            q = _slerp(Q[i], Q[j], u)
            Mq = quat_to_mat(q)[0]
            r, uu, f = -Mq[:, 0], Mq[:, 1], Mq[:, 2]
            tgt = eye + f * dist
        else:
            if mode == "normal":
                fwd = lerp(N, k, u)
                tgt = eye + fwd / max(np.linalg.norm(fwd), 1e-300) * dist
            elif mode == "target":
                tgt = lerp(T, k, u) if T is not None else np.asarray(target,
                                                                    np.float64)
            else:
                if float(look_ahead) > 0:
                    tgt = path.pos(s + float(look_ahead))
                else:
                    fwd = lerp(Tv, k, u)
                    tgt = eye + fwd / max(np.linalg.norm(fwd), 1e-300) * dist
            upv = lerp(U, k, u) if U is not None else upw
            _, r, uu, f = _rnd.look_at(eye, tgt, upv)
        cams.append({
            "projection": prj, "eye": eye, "right": r, "up": uu, "forward": f,
            "fov": num("fov", fov), "ortho_size": num("ortho_size", ortho_size),
            "xres": int(round(attrs["resx"][near_i(k, u)])) if "resx" in attrs
            else int(xres),
            "yres": int(round(attrs["resy"][near_i(k, u)])) if "resy" in attrs
            else int(yres),
            "near": num("near", near),
            "far": num("far", far),         # negative is the same as 0; render only honours far > 0
            "radius": num("radius", 1.0),
            "target": np.asarray(tgt, np.float64),
            "distance": float(np.linalg.norm(np.asarray(tgt) - eye)),
        })
    rep = {"cameras": len(cams), "orientation": mode,
           "path_length": path.total}
    return cams, rep
