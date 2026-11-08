"""
Geometry quality metrics + scoring and selection -- the missing half of the loop. Item 4 on the list.

Up to this batch the whole chain was **one-way**: procedural -> control image -> diffusion -> texture / mesh ->
back to geometry. Run ten variants, and picking one is still done by eye. And for "maximizing streamline",
picking by eye is the ceiling -- ten per round is fine, two hundred per round is impossible.

Two things are missing: **computable criteria**, and the machinery to **pick by those criteria**.

    For-Each (N seeds) -> Geo Metrics -> scores written to detail
    -> Select Best (pick by expression) -> the best one + the sorted top K + a report

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Criteria come in two kinds: **structural** ones are computed here, **aesthetic** ones over there
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This module only handles the former -- primitive count, closedness, non-manifold edges, degenerate primitives, connected pieces, triangle quality,
UV utilization and overlap, genus. These **have definite answers**: a box's Euler characteristic is 2,
not "about 2". So they can go into tests, and can safely serve as hard thresholds for automatic filtering.

Aesthetic scores (CLIP / aesthetic / human preference) belong to the image side; not done here, nor should they be. They come
in like this: inside the loop, write that score as a **detail attribute** on the geometry (Attribute Create's
detail mode will do), and the `Select Best` expression reads it with `detail("score")`.
That way both kinds of criteria are weighted in the same expression:

    detail("score") * 2 - nonmanifold_edges * 0.1 - degenerate_prims

**Why a detail attribute rather than another "score sequence" wire**: the score travels with the geometry;
For-Each's GEOSEQUENCE already carries it out, no new accumulator needed; and
"this geometry's score" and "this geometry" always match up -- two parallel lists get misaligned sooner or later,
and after misalignment what's picked is **a different variant**, which still looks quite plausible.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Self-intersection is **not implemented**, rather than implemented crudely
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Does the mesh self-intersect" is one of the most wanted criteria, but the correct approach is pairwise triangle intersection (with a BVH),
plus a pile of degenerate cases. An approximation like "sample a few rays and see" would **quietly give a high score
when it misses** -- in automatic filtering, a criterion that misses is worse than no criterion: without it people still know
to look themselves; with it they stop looking. So it's explicitly not done here, and the README's known limitations say so too.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UV coverage / overlap are **by texel count**, not analytic area
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`uv_area` is analytic (sum of triangle areas, exact); but "how much lands in 0-1" and "is there any
overlap" need the **geometric union and intersection**, and analytic algorithms are heavy. Here texels are counted on a res x res grid:
coverage = covered cells / all cells, overlap = cells covered 2+ times / covered cells.

So the precision of these two numbers is 1/res, and they **vary with res**. When written to metrics,
`uv_res` is written out too, so two runs at different resolutions with mismatched numbers aren't mistaken for a geometry change.

Overlap counts **distinct prims**, not distinct triangles. A quad fan-triangulated into two triangles
shares a diagonal that passes exactly through a run of texel centers, and the point-in-triangle test is
closed on the edges -- counting by triangle, a **completely non-overlapping** planar projection reports 1.6% overlap
(measured 0.015625 = 4 diagonals x 64 texels / 128^2). A criterion that raises alarms on clean input
is worse than none in automatic filtering. Counting by prim, the two triangles of the same primitive no longer
"overlap" each other, and a clean projection reports 0.

One honest edge case remains: if an edge shared by two **different primitives** passes exactly through a texel center, that texel
is counted for both. This needs the edge's slope to line up exactly with the texel grid; rare, but not impossible -- so
"overlap 0" reads as "no noticeable overlap", not "mathematically proven not to overlap".
"""
from __future__ import annotations

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from . import topology as _topo
from . import measure as _ms

# normalization factor for a triangle's "quality": an equilateral triangle scores 1
_Q = 4.0 * np.sqrt(3.0)
# tolerance relative to the bounding box diagonal. Absolute values are wrong across models at different scales (this pitfall has been hit three times)
REL_TOL = 1e-6
DEFAULT_UV_RES = 128
# UV rasterization handles at most this many "triangle x texel" candidate pairs at once; beyond that, in batches
MAX_PAIRS = 1 << 22


def _scale(geo):
    """Bounding box diagonal. Every relative tolerance uses it as the yardstick."""
    if geo.npoints == 0:
        return 1.0
    mn, mx = geo.bbox()
    d = float(np.linalg.norm(np.asarray(mx, np.float64)
                             - np.asarray(mn, np.float64)))
    return d if d > 1e-30 else 1.0


# ═══════════════════════════════════════════════════════════ topology
def topo_metrics(geo):
    """Edges / closedness / Euler characteristic / normal orientation consistency."""
    out = {"edges": 0, "boundary_edges": 0, "nonmanifold_edges": 0,
           "flipped_edges": 0, "closed": 0.0, "manifold": 1.0,
           "euler": 0.0, "genus": float("nan")}
    if geo.nprims == 0 or geo.nvertices == 0:
        return out
    t = _topo.topology(geo)
    cnt = np.asarray(t.edge_count)
    out["edges"] = int(t.nedges)
    out["boundary_edges"] = int((cnt == 1).sum())
    out["nonmanifold_edges"] = int((cnt >= 3).sum())
    out["manifold"] = float(out["nonmanifold_edges"] == 0)
    out["closed"] = float(out["boundary_edges"] == 0
                          and out["nonmanifold_edges"] == 0)
    # Euler characteristic V - E + F. On a closed orientable manifold genus = (2 - chi)/2:
    # sphere chi=2 genus 0, torus chi=0 genus 1. One of the handiest hard criteria for "is the shape right"
    out["euler"] = float(geo.npoints - t.nedges + geo.nprims)
    if out["closed"] and out["manifold"]:
        out["genus"] = (2.0 - out["euler"]) / 2.0

    # Orientation consistency: the two half-edges on a manifold edge must point in **opposite directions**.
    # Same direction = the two primitives have opposite winding = one normal faces in, one out. In shading this shows up as
    # a black patch, and in boolean / volume as completely wrong results, yet the geometry itself "looks fine"
    vp = np.asarray(geo.vertex_point, np.int64)
    twin = np.asarray(t.he_twin, np.int64)
    he = np.nonzero(twin >= 0)[0]
    if len(he):
        bad = vp[he] == vp[twin[he]]
        out["flipped_edges"] = int(bad.sum() // 2)
    return out


def component_count(geo):
    if geo.npoints == 0:
        return 0
    g = _topo.connectivity(geo, POINT, "__mcls")
    v = g.get(POINT, "__mcls")
    return int(np.asarray(v).max()) + 1 if v is not None and len(v) else 0


# ═══════════════════════════════════════════════════════════ size
def size_metrics(geo):
    out = {"points": int(geo.npoints), "prims": int(geo.nprims),
           "vertices": int(geo.nvertices),
           "triangles": int(len(geo.triangles())),
           "area": 0.0, "volume": 0.0,
           "bbox_x": 0.0, "bbox_y": 0.0, "bbox_z": 0.0, "bbox_diagonal": 0.0,
           "centroid_x": 0.0, "centroid_y": 0.0, "centroid_z": 0.0,
           "edge_min": 0.0, "edge_max": 0.0, "edge_mean": 0.0}
    if geo.npoints == 0:
        return out
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    mn, mx = P.min(0), P.max(0)
    out["bbox_x"], out["bbox_y"], out["bbox_z"] = [float(v) for v in (mx - mn)]
    out["bbox_diagonal"] = float(np.linalg.norm(mx - mn))
    c = P.mean(0)
    out["centroid_x"], out["centroid_y"], out["centroid_z"] = \
        [float(v) for v in c]
    if geo.nprims:
        out["area"] = float(_ms.prim_areas(geo).sum())
        # Signed volume: for closed meshes it's the true volume (divergence theorem); on open surfaces it's meaningless --
        # so with closed=0 this number is only for reference; don't use it as a criterion
        out["volume"] = float(_ms.prim_volumes(geo, origin=c).sum())
        L = _topo.edge_lengths(geo)
        if len(L):
            out["edge_min"] = float(L.min())
            out["edge_max"] = float(L.max())
            out["edge_mean"] = float(L.mean())
    return out


def quality_metrics(geo):
    """
    Triangle quality q = 4*sqrt(3)*A / (a^2+b^2+c^2): equilateral triangle 1, flatter approaches 0.

    This normalization is standard practice, with the advantage of **an analytic reference**: equilateral must be 1, so tests don't need
    a guessed tolerance. Degenerate primitives (area below REL_TOL of scale squared) get their own count, because they break
    normals, subdivision and boolean alike, while q is merely "very small", without telling zero area from very flat.
    """
    out = {"tri_quality_min": 1.0, "tri_quality_mean": 1.0,
           "degenerate_prims": 0, "duplicate_points": 0}
    s = _scale(geo)
    if geo.nprims:
        a = _ms.prim_areas(geo)
        out["degenerate_prims"] = int((a <= (s * s) * REL_TOL).sum())
    tri = geo.triangles()
    if len(tri):
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
        ar = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1)
        ss = (np.einsum("ij,ij->i", B - A, B - A)
              + np.einsum("ij,ij->i", C - B, C - B)
              + np.einsum("ij,ij->i", A - C, A - C))
        q = np.where(ss > 0, _Q * ar / np.maximum(ss, 1e-300), 0.0)
        out["tri_quality_min"] = float(q.min())
        out["tri_quality_mean"] = float(q.mean())
    if geo.npoints:
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        tol = max(s * REL_TOL, 1e-12)
        q = np.round(P / tol).astype(np.int64)
        out["duplicate_points"] = int(geo.npoints
                                      - len(np.unique(q, axis=0)))
    return out


# ═══════════════════════════════════════════════════════════════ UV
def uv_triangles(geo, uv_attrib="uv"):
    """
    -> ((T,3,2) uv of each triangle, (T,) which prim it belongs to). Returns
    (None, None) when there's no uv.

    The prim number must come along: overlap is computed per **primitive**, not per triangle (see the module header for why).
    """
    name = str(uv_attrib or "uv").strip() or "uv"
    tri, cor = geo.triangles(with_corners=True)
    if not len(tri):
        return None, None
    src = np.asarray(geo.vertex_prim(), np.int64)[cor[:, 0]]
    v = geo.get(VERTEX, name)
    if v is not None and not is_string(v) and np.asarray(v).shape[1] >= 2:
        return np.asarray(v, np.float64)[:, :2][cor], src
    p = geo.get(POINT, name)
    if p is not None and not is_string(p) and np.asarray(p).shape[1] >= 2:
        return np.asarray(p, np.float64)[:, :2][tri], src
    return None, None


def uv_metrics(geo, uv_attrib="uv", res=DEFAULT_UV_RES):
    """
    uv_area is analytic; coverage / overlap count texels on a res x res grid,
    with precision 1/res, so `uv_res` is written into the result too (see the module header for why).
    """
    out = {"has_uv": 0.0, "uv_area": 0.0, "uv_flipped": 0,
           "uv_out_of_range": 0, "uv_coverage": 0.0, "uv_overlap": 0.0,
           "uv_res": int(res)}
    T, src = uv_triangles(geo, uv_attrib)
    if T is None or not len(T):
        return out
    out["has_uv"] = 1.0
    # signed area: negative = uv flipped; bakes come out mirrored, and that isn't visible in the viewport
    e1 = T[:, 1] - T[:, 0]
    e2 = T[:, 2] - T[:, 0]
    sa = 0.5 * (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    out["uv_area"] = float(np.abs(sa).sum())
    out["uv_flipped"] = int((sa < 0).sum())
    out["uv_out_of_range"] = int((((T < -1e-9) | (T > 1 + 1e-9))
                                  .any(axis=(1, 2))).sum())
    cov, ovl = _uv_raster(T, src, int(res))
    out["uv_coverage"] = cov
    out["uv_overlap"] = ovl
    return out


def _uv_raster(T, src, res):
    """
    Count how many **primitives** cover each texel on a res x res grid.
    -> (coverage, fraction covered by 2+ primitives).

    For each triangle, candidate texels are taken from its bounding box, and the cell **center** is used for the point-in-triangle test. Batching is
    because a triangle covering all of 0-1 has res^2 candidates by itself -- unbatched, one big triangle
    can eat all the memory (hit on the rasterization side; its batching is copied here).
    """
    res = max(4, int(res))
    cnt = np.zeros(res * res, np.int32)
    pairs = []
    lo = np.clip(np.floor(T.min(1) * res).astype(np.int64), 0, res - 1)
    hi = np.clip(np.ceil(T.max(1) * res).astype(np.int64), 0, res)
    bw = np.maximum(hi[:, 0] - lo[:, 0], 0)
    bh = np.maximum(hi[:, 1] - lo[:, 1], 0)
    area = bw * bh
    live = np.nonzero(area > 0)[0]
    if not len(live):
        return 0.0, 0.0
    cum = np.cumsum(area[live])
    total = int(cum[-1])
    nb = max(1, int(np.ceil(total / float(MAX_PAIRS))))
    bounds = np.searchsorted(cum, np.linspace(0, total, nb + 1)[1:])
    start = 0
    for stop in bounds:
        stop = int(min(max(stop + 1, start + 1), len(live)))
        idx = live[start:stop]
        n = area[idx]
        flat = np.concatenate([np.arange(k) for k in n]) if len(idx) else \
            np.zeros(0, np.int64)
        tid = np.repeat(idx, n)
        w = np.repeat(bw[idx], n)
        px = np.repeat(lo[idx, 0], n) + (flat % w)
        py = np.repeat(lo[idx, 1], n) + (flat // w)
        cx = (px + 0.5) / res
        cy = (py + 0.5) / res
        a, b, c = T[tid, 0], T[tid, 1], T[tid, 2]
        d = ((b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0])
             + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1]))
        ok = np.abs(d) > 1e-15
        d = np.where(ok, d, 1.0)
        w0 = ((b[:, 1] - c[:, 1]) * (cx - c[:, 0])
              + (c[:, 0] - b[:, 0]) * (cy - c[:, 1])) / d
        w1 = ((c[:, 1] - a[:, 1]) * (cx - c[:, 0])
              + (a[:, 0] - c[:, 0]) * (cy - c[:, 1])) / d
        inside = ok & (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
        if inside.any():
            # deduplicate (texel, primitive) before accumulating -- the diagonal shared by two triangles of the same primitive
            # hits a run of texel centers at once; without dedup even a clean projection reports overlap
            pairs.append(np.stack([py[inside] * res + px[inside],
                                   src[tid[inside]]], 1))
        start = stop
        if start >= len(live):
            break
    if pairs:
        pr = np.unique(np.concatenate(pairs), axis=0)
        np.add.at(cnt, pr[:, 0], 1)
    covered = int((cnt > 0).sum())
    over = int((cnt > 1).sum())
    return covered / float(res * res), (over / covered if covered else 0.0)


# ══════════════════════════════════════════════════════════ summary
def metrics(geo, uv=True, quality=True, uv_attrib="uv",
            res=DEFAULT_UV_RES):
    """Geometry -> a dict of **scalars only**. Keys are all valid identifiers, usable directly in expressions."""
    if geo is None:
        geo = Geometry()
    out = {}
    out.update(size_metrics(geo))
    out.update(topo_metrics(geo))
    out["components"] = component_count(geo)
    if quality:
        out.update(quality_metrics(geo))
    if uv:
        out.update(uv_metrics(geo, uv_attrib, res))
    out["groups"] = int(sum(len(v) for v in geo.groups.values()))
    out["attribs"] = int(sum(len(v) for v in geo.attribs.values()))
    return out


def write_detail(geo, m, prefix=""):
    """Write the metrics as detail attributes, so downstream expressions / Wrangle can read them with detail()."""
    g = geo.copy()
    for k, v in m.items():
        if isinstance(v, float) and not np.isfinite(v):
            continue                       # nan written to an attribute only becomes a mystery downstream
        g.set(DETAIL, f"{prefix}{k}", [[float(v)]], dtype=np.float32)
    return g


# ═══════════════════════════════════════════════════════ scoring / selection
MODES = ("max", "min")


def score_one(geo, expr, m=None, index=0, total=1, **kw):
    """
    One geometry -> one score. Available in the expression:

      - all metrics (`prims` / `closed` / `uv_overlap` / `genus` ...)
      - `i` / `n`: which one, and how many in total
      - Wrangle's function library (fit / clamp / min / max / sin ...)
      - **geometry-reading functions**: `detail("score")` / `npoints()` / `prim("area", 0, 0)`
        -- this is how aesthetic scores come in (written as a detail attribute inside the loop)

    The geometry-reading functions are the same set Switch / Wrangle use (`expr.geo_funcs`), so
    expressions can be copied over unchanged, with no second set to remember.
    """
    from .. import expr as _ex
    m = metrics(geo, **kw) if m is None else m
    ns = dict(m)
    ns["i"] = float(index)
    ns["index"] = float(index)
    ns["n"] = float(total)
    ns.update(_ex.geo_funcs(geo, 1))
    return float(_ex._eval(str(expr), ns,
                           "Available variables: {} (all metrics of this geometry)"))


def select(seq, expr="1.0", mode="max", top_k=1, **kw):
    """
    Sequence -> (the best one, the sorted top K, indices, scores, per-item reports).

    **On equal scores the lower index wins** (stable): otherwise two runs on the same input could pick
    different variants, and "the random numbers didn't change but the result did" is the hardest kind of bug to track down.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not seq:
        raise ValueError("The sequence is empty -- connect the geometry sequence output of For-Each End")
    n = len(seq)
    rows = []
    for i, g in enumerate(seq):
        m = metrics(g, **kw)
        s = score_one(g, expr, m, i, n)
        rows.append({"index": i, "score": s, "metrics": m})
    # stable sort + index as secondary key: on tied scores the lower index always wins
    order = sorted(range(n), key=lambda i: (-rows[i]["score"], i)
                   if mode == "max" else (rows[i]["score"], i))
    k = max(1, min(int(top_k or 1), n))
    best = order[0]
    return (seq[best], [seq[i] for i in order[:k]], best,
            rows[best]["score"], rows, order)
