"""
Leaf Card Texture: the colour and cutout of a foliage card, drawn procedurally -- what a tree's leaf cards need so
that a crown reads as leaves instead of a cloud of green quads.

  broadleaf   a twig rising from the bottom centre with leaves on alternate sides (ovate blades on short petioles,
              a lighter midrib, darker edges, each leaf its own shade) and one at the tip
  conifer     a spray: a stem rising from the bottom centre with side shoots, all covered in needles that point
              forward and out

The card's uv runs 0..1 with v up and the twig rooted at (0.5, 0): Tree Generator's cards stand on their branch
the same way (their bottom edge on the branch, v along it). Layers: <prefix>_C (linear colour) and <prefix>_alpha
(1 on the foliage, antialiased); the colour is multiplied by Leaf Color, so with Leaf Color white it is a shading
pattern a tint (the card's Cd, Textures' basecolor_tint) can colour per leaf card.
"""
from __future__ import annotations

import numpy as np

KINDS = ("broadleaf", "conifer")


class _Canvas:
    def __init__(self, n):
        self.n = n
        self.a = np.zeros((n, n), np.float32)
        self.c = np.zeros((n, n, 3), np.float32)
        y, x = np.mgrid[0:n, 0:n].astype(np.float32)
        self.x, self.y = (x + 0.5) / n, (y + 0.5) / n          # row 0 = v 0 (bottom)

    def capsule(self, p0, p1, r0, r1, col):
        """A tapered line from p0 (radius r0) to p1 (radius r1), in uv; drawn over what is there."""
        n = self.n
        p0, p1 = np.asarray(p0, np.float32), np.asarray(p1, np.float32)
        rm = max(r0, r1)
        x0, x1 = int(max(0, (min(p0[0], p1[0]) - rm) * n - 1)), int(min(n, (max(p0[0], p1[0]) + rm) * n + 2))
        y0, y1 = int(max(0, (min(p0[1], p1[1]) - rm) * n - 1)), int(min(n, (max(p0[1], p1[1]) + rm) * n + 2))
        if x0 >= x1 or y0 >= y1:
            return
        X, Y = self.x[y0:y1, x0:x1], self.y[y0:y1, x0:x1]
        d = p1 - p0
        L2 = max(float(d @ d), 1e-12)
        t = np.clip(((X - p0[0]) * d[0] + (Y - p0[1]) * d[1]) / L2, 0, 1)
        dist = np.hypot(X - (p0[0] + t * d[0]), Y - (p0[1] + t * d[1]))
        m = dist < r0 + (r1 - r0) * t
        self.a[y0:y1, x0:x1][m] = 1.0
        self.c[y0:y1, x0:x1][m] = col

    def leaf(self, base, ang, length, width, col, rng):
        """An ovate blade from base along angle ang (radians from +v), with a midrib and darker edges."""
        n = self.n
        ax = np.array([np.sin(ang), np.cos(ang)], np.float32)
        nx = np.array([ax[1], -ax[0]], np.float32)
        tip = base + ax * length
        r = max(length, width)
        x0, x1 = int(max(0, (min(base[0], tip[0]) - r) * n)), int(min(n, (max(base[0], tip[0]) + r) * n + 1))
        y0, y1 = int(max(0, (min(base[1], tip[1]) - r) * n)), int(min(n, (max(base[1], tip[1]) + r) * n + 1))
        if x0 >= x1 or y0 >= y1:
            return
        X, Y = self.x[y0:y1, x0:x1] - base[0], self.y[y0:y1, x0:x1] - base[1]
        s = (X * ax[0] + Y * ax[1]) / length                        # 0 at the base, 1 at the tip
        w = (X * nx[0] + Y * nx[1]) / (0.5 * width)                  # -1..1 across
        sc = np.clip(s, 0, 1)
        hw = np.sin(np.pi * sc) ** 0.75 * (1 - 0.35 * sc) * (1 + 0.035 * np.sin(31 * sc + rng.random() * 6))
        m = (s > 0) & (s < 1) & (np.abs(w) < hw)
        if not m.any():
            return
        rel = np.abs(w) / np.maximum(hw, 1e-3)
        shade = (0.82 + 0.25 * sc) * (1 - 0.28 * rel ** 3)            # darker toward the edge and the base
        rib = np.clip(1 - np.abs(w) * length * n / 1.4, 0, 1) * (s < 0.95)
        veins = np.clip(1 - np.abs(np.sin((s * 6 - np.abs(w) * 2.2) * np.pi)) * 6, 0, 1) * 0.12 * (rel < 0.85)
        f = (shade * (1 + 0.35 * rib + veins))[..., None]
        cc = np.asarray(col, np.float32)[None, None] * f
        self.a[y0:y1, x0:x1][m] = 1.0
        self.c[y0:y1, x0:x1][m] = cc[m]


def leaf_card(kind="broadleaf", resolution=512, leaves=9, leaf_color=(1.0, 1.0, 1.0), stem_color=(0.07, 0.04, 0.02),
              variation=0.25, seed=1):
    """-> (colour (H, W, 3) linear, alpha (H, W)), row 0 = v 0."""
    if kind not in KINDS:
        raise ValueError(f"Leaf Card Texture: Kind must be one of {KINDS}, got {kind!r}")
    res = int(resolution)
    if not 16 <= res <= 4096:
        raise ValueError("Leaf Card Texture: Resolution must be between 16 and 4096")
    rng = np.random.default_rng(int(seed))
    ss = 2 if res <= 2048 else 1                                    # drawn at twice the size, then averaged
    cv = _Canvas(res * ss)
    lc = np.asarray(leaf_color, np.float32)
    stc = np.asarray(stem_color, np.float32)

    def tint():
        v = float(variation)
        return lc * np.array([1 + v * (rng.random() - 0.5) * 0.6, 1 + v * (rng.random() - 0.5),
                              1 + v * (rng.random() - 0.5) * 0.6], np.float32) * (1 + v * (rng.random() - 0.5))

    def stem(n_pts, top, bend):
        t = np.linspace(0, 1, n_pts)
        return np.stack([0.5 + bend * np.sin(t * np.pi * 0.8) * t, 0.02 + top * t], 1)

    nl = int(max(1, leaves))
    if kind == "broadleaf":
        st = stem(12, 0.78, (rng.random() - 0.5) * 0.12)
        for i in range(len(st) - 1):
            cv.capsule(st[i], st[i + 1], 0.012 * (1 - 0.6 * i / len(st)), 0.012 * (1 - 0.6 * (i + 1) / len(st)), stc)
        order = []
        for k in range(nl - 1):
            f = 0.18 + 0.78 * k / max(nl - 2, 1)
            order.append((f, 1 if k % 2 == 0 else -1))
        order.append((1.0, 0))                                       # the leaf at the tip
        leaf_list = []
        for f, side in order:
            i = min(int(f * (len(st) - 1)), len(st) - 2)
            tt = f * (len(st) - 1) - i
            p = st[i] * (1 - tt) + st[i + 1] * tt
            ln = (0.36 - 0.08 * f) * (0.85 + 0.3 * rng.random())
            ang = side * np.radians(48 + 18 * rng.random() - 20 * f) + (rng.random() - 0.5) * 0.2
            pet = p + np.array([np.sin(ang), np.cos(ang)], np.float32) * 0.035
            cv.capsule(p, pet, 0.005, 0.004, stc)
            leaf_list.append((pet, ang, ln))
        for pet, ang, ln in leaf_list[::-1]:                         # the tip first: lower leaves overlap it
            cv.leaf(pet, ang, ln, ln * (0.5 + 0.12 * rng.random()), tint(), rng)
    else:
        st = stem(14, 0.94, (rng.random() - 0.5) * 0.08)
        shoots = [st]
        n_side = max(2, nl)
        for k in range(n_side):
            f = 0.08 + 0.78 * k / max(n_side - 1, 1)
            i = int(f * (len(st) - 1))
            side = 1 if k % 2 == 0 else -1
            ln = 0.46 * (1 - 0.6 * f) * (0.85 + 0.3 * rng.random())
            a = side * np.radians(52 + 10 * rng.random())
            d = np.array([np.sin(a), np.cos(a)], np.float32)
            shoots.append(np.stack([st[i] + d * ln * t for t in np.linspace(0, 1, 6)]))
        # needles first (the stems drawn over them), dense, forward and out, shorter toward each tip
        for sh_ in shoots:
            seg = np.diff(sh_, axis=0)
            L = float(np.linalg.norm(seg, axis=1).sum())
            n_n = int(L / 0.005)
            for j in range(n_n):
                f = (j + rng.random()) / max(n_n, 1)
                pos = f * (len(sh_) - 1)
                i = min(int(pos), len(sh_) - 2)
                p = sh_[i] + (sh_[i + 1] - sh_[i]) * (pos - i)
                d = sh_[i + 1] - sh_[i]
                d = d / max(float(np.linalg.norm(d)), 1e-9)
                for side in (1, -1):
                    a = side * np.radians(50 + 12 * rng.random())
                    nd = np.array([d[0] * np.cos(a) - d[1] * np.sin(a), d[0] * np.sin(a) + d[1] * np.cos(a)])
                    nlen = (0.075 + 0.025 * rng.random()) * (1 - 0.4 * f)
                    cv.capsule(p, p + nd * nlen, 0.005, 0.0022, tint() * (0.7 + 0.3 * f + 0.15 * rng.random()))
        for sh_ in shoots:
            for i in range(len(sh_) - 1):
                cv.capsule(sh_[i], sh_[i + 1], 0.0035, 0.003, stc)
    a, c = cv.a, cv.c
    if ss > 1:
        a = a.reshape(res, ss, res, ss).mean((1, 3))
        c = c.reshape(res, ss, res, ss, 3).sum((1, 3)) / np.maximum(cv.a.reshape(res, ss, res, ss).sum((1, 3)),
                                                                 1e-6)[..., None]
    # colour bled a few texels past the cutout, so mips and bilinear lookups at the edge do not pull in black
    from scipy.ndimage import distance_transform_edt
    inside = a > 0.02
    if inside.any() and not inside.all():
        idx = distance_transform_edt(~inside, return_distances=False, return_indices=True)
        c = c[idx[0], idx[1]]
    return c.astype(np.float32), a.astype(np.float32)
