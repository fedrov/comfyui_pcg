"""
Tree Generator: a procedural tree as a game asset -- a trunk and branches as tapered tubes (bark, uv in metres) and
leaves as cards (one quad each) -- in two growth forms:

  broadleaf   the trunk ends in the crown; from the crown base up, branches leave it in a spiral (Branches per
              level, Branch Angle from the parent), each level shorter (Length Ratio) and bending up; the last level
              carries the leaves, spread along its outer part
  conifer     the trunk runs to the top; branches leave it in whorls, long at the bottom and short at the top (a
              cone), drooping a little; needle sprays (cards) along them

Everything is driven by a seed, so a forest of variants is a seed attribute away. Point attributes: Cd (bark colour,
leaves darker inside and low in the crown, where less sky reaches), N (bark: radial; leaves: the card's normal bent
toward "out of the crown" by Normal Bend, so the crown shades as one soft volume), uv. Prim attributes: part (bark /
leaf), material (M_Bark / M_Leaf), level (0 trunk, 1.. branches, -1 leaves).
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, PRIM

KINDS = ("broadleaf", "conifer")


def _frame(t):
    t = t / max(np.linalg.norm(t), 1e-9)
    a = np.array([0.0, 1.0, 0.0]) if abs(t[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(t, a)
    u /= np.linalg.norm(u)
    return u, np.cross(t, u)


class _Mesh:
    def __init__(self):
        self.P, self.N, self.Cd, self.uv = [], [], [], []
        self.faces, self.part, self.level = [], [], []
        self.n = 0

    def tube(self, pts, rad, sides, col, level):
        pts = np.asarray(pts, np.float64)
        m = len(pts)
        if m < 2:
            return
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        vlen = np.concatenate([[0.0], np.cumsum(seg)])
        T = np.gradient(pts, axis=0)
        u, w = _frame(T[0])
        base = self.n
        circ = 2 * np.pi * max(float(np.mean(rad)), 1e-3)
        for i in range(m):
            t = T[i] / max(np.linalg.norm(T[i]), 1e-9)
            u = u - t * (u @ t)                                   # parallel transport of the frame
            u /= max(np.linalg.norm(u), 1e-9)
            w = np.cross(t, u)
            for j in range(sides + 1):                            # the seam column twice, for the uv
                a = 2 * np.pi * j / sides
                d = np.cos(a) * u + np.sin(a) * w
                self.P.append(pts[i] + rad[i] * d)
                self.N.append(d)
                self.Cd.append(col)
                self.uv.append((j / sides * circ, vlen[i]))
        self.n += m * (sides + 1)
        for i in range(m - 1):
            for j in range(sides):
                a0 = base + i * (sides + 1) + j
                b0 = base + (i + 1) * (sides + 1) + j
                self.faces.append((a0, a0 + 1, b0 + 1, b0))
                self.part.append("bark")
                self.level.append(level)

    def card(self, c, n, up, size, col, crown_n, bend):
        n = n / max(np.linalg.norm(n), 1e-9)
        x = np.cross(up, n)
        if np.linalg.norm(x) < 1e-6:
            x = np.array([1.0, 0.0, 0.0])
        x /= np.linalg.norm(x)
        y = np.cross(n, x)
        sn = (1 - bend) * n + bend * crown_n
        sn /= max(np.linalg.norm(sn), 1e-9)
        base = self.n
        for cx, cy, uu, vv in ((-0.5, 0.0, 0, 0), (0.5, 0.0, 1, 0), (0.5, 1.0, 1, 1), (-0.5, 1.0, 0, 1)):
            self.P.append(c + (cx * x + cy * y) * size)
            self.N.append(sn)
            self.Cd.append(col)
            self.uv.append((uu, vv))
        self.n += 4
        self.faces.append((base, base + 1, base + 2, base + 3))
        self.part.append("leaf")
        self.level.append(-1)

    def geometry(self):
        g = Geometry.from_mesh(np.asarray(self.P, np.float32).reshape(-1, 3),
                               np.asarray(self.faces, np.int64).reshape(-1, 4))
        g.set(POINT, "N", np.asarray(self.N, np.float32))
        g.set(POINT, "Cd", np.clip(np.asarray(self.Cd, np.float32), 0, 1))
        uv = np.asarray(self.uv, np.float32)
        g.set(POINT, "uv", np.c_[uv, np.zeros(len(uv), np.float32)])
        part = np.asarray(self.part)
        g.set_string(PRIM, "part", part)
        g.set_string(PRIM, "material", np.where(part == "bark", "M_Bark", "M_Leaf"))
        g.set(PRIM, "level", np.asarray(self.level, np.int32))
        return g


def _rot(v, axis, ang):
    axis = axis / max(np.linalg.norm(axis), 1e-9)
    return v * np.cos(ang) + np.cross(axis, v) * np.sin(ang) + axis * (axis @ v) * (1 - np.cos(ang))


def _curve(p0, d, length, steps, rng, gnarl, rise):
    """A bending branch: from p0 along d, curving toward up by rise, wobbling by gnarl."""
    pts = [np.asarray(p0, np.float64)]
    d = d / max(np.linalg.norm(d), 1e-9)
    st = length / steps
    for _ in range(steps):
        d = d + np.array([0.0, rise, 0.0]) / steps + rng.normal(0, gnarl / steps ** 0.5, 3)
        d /= max(np.linalg.norm(d), 1e-9)
        pts.append(pts[-1] + d * st)
    return np.array(pts)


def tree(kind="broadleaf", height=10.0, trunk_radius=0.25, crown_base=0.35, crown_width=6.0, branch_levels=2,
         branches=5, branch_angle=45.0, length_ratio=0.6, gnarl=0.3, leaves=300, leaf_size=0.7,
         leaf_color=(0.26, 0.40, 0.13), bark_color=(0.24, 0.18, 0.13), sides=6, normal_bend=0.8, seed=1, segments=8):
    """-> (Geometry, report)"""
    if kind not in KINDS:
        raise ValueError(f"Tree Generator: Kind must be one of {KINDS}, got {kind!r}")
    if height <= 0 or trunk_radius <= 0:
        raise ValueError("Tree Generator: Height and Trunk Radius must be positive")
    rng = np.random.default_rng(int(seed))
    sides = int(max(3, sides))
    lc, bc = np.asarray(leaf_color, np.float64), np.asarray(bark_color, np.float64)
    M = _Mesh()
    H = float(height)
    # the trunk: to the crown base and a little into it (broadleaf), to the top (conifer)
    top = H * (0.62 if kind == "broadleaf" else 1.0)
    tsteps = int(max(2, segments))
    bsteps = max(1, int(round(tsteps * 5 / 8)))                       # the first branch level, then fewer
    trunk = _curve((0, 0, 0), np.array([0, 1.0, 0]), top, tsteps, rng, 0.04 * gnarl, 0.0)
    trad = trunk_radius * np.linspace(1.0, 0.55 if kind == "broadleaf" else 0.08, tsteps + 1)
    trad[0] *= 1.25                                                   # a flare at the root
    n0 = M.n
    M.tube(trunk, trad, sides, bc * (0.9 + 0.2 * rng.random()), 0)
    for k in range(n0, n0 + sides + 1):                              # the root ring flat on the ground
        M.P[k] = np.array([M.P[k][0], 0.0, M.P[k][2]])
    crown_c = np.array([0.0, H * (0.5 + 0.5 * crown_base), 0.0])
    crown_r = max(crown_width * 0.5, 0.5)
    tips = []                                     # (point, direction, length) where leaves go

    def along(pts, f):
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        x = f * s[-1]
        i = min(int(np.searchsorted(s, x)), len(s) - 1)
        i0 = max(i - 1, 0)
        t = 0.0 if s[i] == s[i0] else (x - s[i0]) / (s[i] - s[i0])
        p = pts[i0] * (1 - t) + pts[i] * t
        d = pts[min(i0 + 1, len(pts) - 1)] - pts[i0]
        return p, d / max(np.linalg.norm(d), 1e-9)

    golden = np.pi * (3 - np.sqrt(5))
    if kind == "conifer":
        whorls = max(4, 2 * int(branches) + 2)
        for k in range(whorls):
            f = crown_base + (1 - crown_base) * (k + 0.5) / whorls * 0.95
            p, _ = along(trunk, f)
            ln = crown_r * (1.0 - (f - crown_base) / (1 - crown_base)) ** 0.9 + 0.3
            n_br = max(3, int(round(5 - 1.5 * f)))
            for b in range(n_br):
                a = 2 * np.pi * b / n_br + k * 0.9 + rng.normal(0, 0.15)
                d = np.array([np.cos(a), -0.15 - 0.2 * rng.random(), np.sin(a)])
                pts = _curve(p, d, ln, max(1, bsteps - 2), rng, 0.15 * gnarl, 0.25)
                M.tube(pts, np.linspace(trunk_radius * 0.25 * (1 - f) + 0.02, 0.015, len(pts)), max(3, sides // 2),
                       bc, 1)
                tips.append((pts, ln))
    else:
        parents = [(trunk, top, trunk_radius * 0.6, 0)]
        for lev in range(1, int(max(1, branch_levels)) + 1):
            nxt = []
            for pts, ln, rad, _ in parents:
                nb = int(branches) if lev > 1 else int(branches) + 2
                for b in range(nb):
                    f = (crown_base + (1 - crown_base) * (b + 0.5) / nb) if lev == 1 else 0.35 + 0.6 * (b + 0.5) / nb
                    p, d = along(pts, f)
                    ang = np.radians(branch_angle) * (0.8 + 0.4 * rng.random())
                    side = _rot(np.cross(d, [0.3, 0.1, 0.7]) if abs(d[1]) < 0.99 else np.array([1.0, 0, 0]), d,
                                golden * (b + lev * 7) + rng.normal(0, 0.3))
                    nd = _rot(d, side, ang)
                    bl = (crown_r * 1.1 if lev == 1 else ln * length_ratio) * (0.75 + 0.5 * rng.random())
                    if lev == 1:
                        bl *= 1.0 - 0.5 * (f - crown_base) / max(1 - crown_base, 1e-6)
                    bp = _curve(p, nd, bl, bsteps if lev == 1 else max(1, bsteps - 2), rng, 0.25 * gnarl, 0.35)
                    br = max(rad * 0.6, 0.015)
                    M.tube(bp, np.linspace(br, br * 0.35, len(bp)), max(3, sides - 2 * lev), bc, lev)
                    nxt.append((bp, bl, br * 0.5, lev))
            parents = nxt
        tips = [(pts, ln) for pts, ln, _, _ in parents]
    # leaves on the outer part of the last branches, spread evenly by count
    n_leaf = int(max(0, leaves))
    if tips and n_leaf:
        per = np.full(len(tips), n_leaf // len(tips))
        per[: n_leaf - per.sum()] += 1
        for (pts, ln), k in zip(tips, per):
            for _ in range(int(k)):
                f = 0.35 + 0.65 * rng.random() if kind == "broadleaf" else 0.1 + 0.9 * rng.random()
                p, d = along(pts, f)
                if kind == "broadleaf":
                    c = p + rng.normal(0, 0.35 * leaf_size, 3)
                    n = rng.normal(0, 1, 3) + (c - crown_c) / crown_r + np.array([0, 0.6, 0])
                    up = d
                else:
                    c = p + rng.normal(0, 0.12 * leaf_size, 3)
                    n = np.array([0.0, 1.0, 0.0]) + rng.normal(0, 0.25, 3)
                    up = d
                out = c - crown_c
                cn = out / max(np.linalg.norm(out), 1e-9) + np.array([0, 0.6, 0])
                cn /= np.linalg.norm(cn)
                depth = np.clip(np.linalg.norm(out * [1, 0.8, 1]) / crown_r, 0, 1.2)
                shade = 0.55 + 0.4 * min(depth, 1.0) + 0.1 * np.clip((c[1] - crown_c[1]) / crown_r, -1, 1)
                col = lc * shade * (0.85 + 0.3 * rng.random())
                M.card(c, n, up, leaf_size * (0.8 + 0.4 * rng.random()),
                       col, cn, float(np.clip(normal_bend, 0, 1)))
    g = M.geometry()
    part = np.asarray(M.part)
    rep = {"kind": kind, "points": g.npoints, "faces": g.nprims, "triangles": int(2 * g.nprims),
           "bark_faces": int((part == "bark").sum()), "leaf_cards": int((part == "leaf").sum()),
           "height": round(float(np.asarray(g.get(POINT, "P"))[:, 1].max()), 3)}
    return g, rep
