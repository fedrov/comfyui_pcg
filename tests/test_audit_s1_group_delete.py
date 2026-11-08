"""
pcg100 audit pack s1_group_delete: parameters added after checking the SideFX docs.

  Group Promote      point / prim / edge / vertex, twelve directions, Keep Original, Entirely Contained,
                     Sharing an Edge, Boundary (starting from a primitive group) + the two Unshared options, Output as Attribute
  Delete             Entity: Edges, Delete by Pattern, Select _ of _, Degenerate tab, Random tab,
                     Delete Unused Groups
  Blast by Attribute new node: Threshold / Range / Width, Invert, Output: Blast / Group
  Dissolve           Operation, Bridge (bridged / delete), Recompute Normals
  Normal             Group Type, Override Normal, Compute Normals, Keep Zero, Unit Length, Reverse
  Clip               Orient Plane with: Transform, Snapping Tolerance, Fill Polygons,
                     Split Connectivity, Clip Attribute, Clipped Primitives / Filled Polygons groups
  Mirror             Group, Clip Primitives and Mirror, Orient: Transform, Distance, Reverse Normals

References are all numbers that can be worked out by hand (point numbers, prim counts, areas, volumes). "Bit-identical to before the change at defaults" uses
digests computed by the same set of calls before the change (commit a9e114d), hard-coded in GOLDEN; `--digests` prints the current digests.
"""
import hashlib
import os
import sys

_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))), "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
sys.path.insert(0, _R)
import fakecomfy                                        # noqa: F401,E402
import numpy as np                                      # noqa: E402

from comfyui_pcg import NODE_CLASS_MAPPINGS as M       # noqa: E402
from comfyui_pcg import panel as PANEL                  # noqa: E402
from comfyui_pcg.geo import build, ops                  # noqa: E402
from comfyui_pcg.geo.core import Geometry, POINT, VERTEX, PRIM, DETAIL  # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


def sec(t):
    print(f"\n── {t}")


def run(nid, **over):
    kw = {}
    for part in ("required", "optional"):
        for k, spec in M[nid].INPUT_TYPES().get(part, {}).items():
            if isinstance(spec[0], (list, tuple)):
                kw[k] = spec[0][0]
            elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                kw[k] = spec[1]["default"]
    kw.update(over)
    r = getattr(M[nid](), M[nid].FUNCTION)(**kw)
    return r["result"][0] if isinstance(r, dict) else r[0]


def raises(fn, match="", exc=(ValueError, KeyError)):
    """Raised, and it is **our own** human-readable error (match is a fragment of the error text)."""
    try:
        fn()
    except exc as e:
        return match in str(e)
    return False


def names(nid):
    it = M[nid].INPUT_TYPES()
    return [k for part in ("required", "optional") for k in it.get(part, {})]


def P_(g):
    return np.asarray(g.get(POINT, "P"), np.float64)


def volume(g):
    P, T = P_(g), g.triangles()
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    return float((a * np.cross(b, c)).sum() / 6.0)


def areas(g):
    """Area of each primitive (Newell, also correct for bridged faces with holes)."""
    return np.linalg.norm(ops.prim_normals(g, normalize=False).astype(np.float64), axis=1)


def closed_manifold(g):
    """Every edge is used by exactly two primitives, in opposite directions."""
    seen = {}
    for k in range(g.nprims):
        pts = g.prim_points(k)
        for i in range(len(pts)):
            e = (int(pts[i]), int(pts[(i + 1) % len(pts)]))
            seen[e] = seen.get(e, 0) + 1
    return all(v == 1 for v in seen.values()) and all((b, a) in seen for (a, b) in seen)


def grp(g, cls, name):
    m = g.groups[cls].get(name)
    return None if m is None else np.nonzero(np.asarray(m))[0].tolist()


def egrp(g, name):
    v = g.edge_groups.get(name)
    return None if v is None else sorted(map(tuple, np.asarray(v).tolist()))


def digest(g):
    h = hashlib.sha1()
    h.update(np.ascontiguousarray(g.vertex_point).tobytes())
    h.update(np.ascontiguousarray(g.prim_offset).tobytes())
    h.update(np.ascontiguousarray(g.prim_closed).tobytes())
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for k in sorted(g.attribs[cls]):
            v = g.attribs[cls][k]
            h.update(f"{cls}/{k}/{v.dtype}/{v.shape}".encode())
            h.update(np.ascontiguousarray(v).tobytes() if v.dtype.kind != "O"
                     else repr(v.tolist()).encode())
    for cls in (POINT, VERTEX, PRIM):
        for k in sorted(g.groups[cls]):
            h.update(f"g/{cls}/{k}".encode())
            h.update(np.ascontiguousarray(g.groups[cls][k]).tobytes())
    for k in sorted(g.edge_groups):
        h.update(f"e/{k}".encode())
        h.update(np.ascontiguousarray(g.edge_groups[k]).tobytes())
    return h.hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════ Shared geometry
def grid3():
    """3×3 points, 4 quads: [0,3,4,1] [1,4,5,2] [3,6,7,4] [4,7,8,5], normal +Y."""
    return build.grid(2.0, 2.0, 3, 3)


def grid4():
    """4×4 points, 9 unit quads; prim 4 is in the middle."""
    return build.grid(3.0, 3.0, 4, 4)


def rich():
    """A box with all kinds of attributes and groups -- for regression, so that every data path carries something."""
    g = build.box((1, 1, 1), (0.25, 0.1, 0.0), (2, 2, 2))
    g = ops.compute_normals(g, "point")
    g.set_group(POINT, "pg", np.arange(g.npoints) % 2 == 0)
    g.set_group(PRIM, "fg", np.arange(g.nprims) < 3)
    g.set(PRIM, "idx", np.arange(g.nprims, dtype=np.int32)[:, None])
    g.set(VERTEX, "uvw", (np.arange(g.nvertices * 3, dtype=np.float32) * 0.01).reshape(-1, 3))
    g.set_edge_group("eg", [(0, 1), (1, 3)])
    return g


def old_cases():
    """Calls that only use parameters that **existed before the change**; key -> output geometry."""
    g, r = grid3(), rich()
    r4 = grid4()
    r4.set_edge_group("e", [(5, 6), (5, 9)])
    out = {}

    def old(nid, **kw):
        # Only pass explicitly given parameters + defaults of the old required ones: independent of whether the new widgets exist
        it = M[nid].INPUT_TYPES()
        base = {}
        for part in ("required", "optional"):
            for k, spec in it.get(part, {}).items():
                if k not in OLD_NAMES[nid]:
                    continue
                if isinstance(spec[0], (list, tuple)):
                    base[k] = spec[0][0]
                elif len(spec) > 1 and isinstance(spec[1], dict) and "default" in spec[1]:
                    base[k] = spec[1]["default"]
        base.update(kw)
        res = getattr(M[nid](), M[nid].FUNCTION)(**base)
        return res["result"][0] if isinstance(res, dict) else res[0]

    out["gp_pt2prim"] = old("PCG_GroupPromote", geo=r, name="pg", direction="point_to_prim", new_name="x")
    out["gp_prim2pt"] = old("PCG_GroupPromote", geo=r, name="fg", direction="prim_to_point", new_name="")
    out["gp_expr"] = old("PCG_GroupPromote", geo=r, name="0-5", direction="point_to_prim", new_name="y")
    out["del_group"] = old("PCG_Delete", geo=r, entity="prim", group="fg")
    out["del_nth"] = old("PCG_Delete", geo=r, use_number=True)
    out["del_range"] = old("PCG_Delete", geo=r, entity="point", use_number=True, number_mode="range",
                           number_start=1, number_end=4)
    out["del_vol"] = old("PCG_Delete", geo=r, entity="prim", use_volume=True, operation="keep_selected", keep_points=True)
    out["del_nrm_expr"] = old("PCG_Delete", geo=r, entity="prim", use_normal=True, use_expression=True, expression="@idx > 1")
    out["dis_none"] = old("PCG_Dissolve", geo=r4, edge_group="")
    out["dis_e"] = old("PCG_Dissolve", geo=r4, edge_group="e", output_boundary_group="bd")
    out["dis_e_raw"] = old("PCG_Dissolve", geo=r4, edge_group="e", remove_inline_points=False,
                           delete_lone_points=True)
    for add in ("point", "vertex", "prim", "detail"):
        out["nrm_" + add] = old("PCG_Normal", geo=r, add_to=add)
    out["nrm_grp"] = old("PCG_Normal", geo=r, add_to="point", group="pg", weighting="by_vertex_angle")
    out["nrm_vgrp"] = old("PCG_Normal", geo=g, add_to="vertex", group="0-3", cusp_angle=20.0)
    for kp in ("below", "above", "both"):
        out["clip_" + kp] = old("PCG_Clip", geo=r, keep=kp, use_out_groups=True)
    out["clip_dir"] = old("PCG_Clip", geo=r, dir_x=1.0, dir_y=0.5, distance=0.1, use_origin=True,
                          origin_x=0.2, group="fg")
    out["mir_mirror"] = old("PCG_Mirror", geo=r, mode="mirror", mirror_group="m")
    out["mir_append"] = old("PCG_Mirror", geo=r, mode="append", original_group="o", mirror_group="m")
    out["mir_nofuse"] = old("PCG_Mirror", geo=r, mode="append", fuse_result=False, normal_x=0.3,
                            normal_y=1.0, origin_y=-0.2)
    return {k: digest(v) for k, v in out.items()}


OLD_NAMES = {
    "PCG_GroupPromote": ["geo", "name", "direction", "new_name"],
    "PCG_Delete": ["geo", "entity", "operation", "group", "keep_points", "use_number", "number_mode",
                   "number_start", "number_end", "number_step", "use_volume", "volume_type", "center_x",
                   "center_y", "center_z", "size_x", "size_y", "size_z", "radius", "volume_invert",
                   "use_normal", "direction_x", "direction_y", "direction_z", "spread_angle",
                   "normal_attribute", "normal_invert", "use_expression", "expression"],
    "PCG_Dissolve": ["geo", "edge_group", "remove_inline_points", "inline_tolerance",
                     "delete_lone_points", "output_boundary_group"],
    "PCG_Normal": ["geo", "add_to", "cusp_angle", "group", "weighting"],
    "PCG_Clip": ["geo", "group", "keep", "dir_x", "dir_y", "dir_z", "distance", "use_origin", "origin_x",
                 "origin_y", "origin_z", "use_out_groups", "above_group", "below_group", "seam_group"],
    "PCG_Mirror": ["geo", "mode", "origin_x", "origin_y", "origin_z", "normal_x", "normal_y", "normal_z",
                   "snap_tolerance", "fuse_result", "original_group", "mirror_group", "vector_attributes"],
    "PCG_Blast": ["geo", "group", "cls", "keep_selected"],
}
# Digests from running old_cases() before the change (a9e114d)
GOLDEN = {
    "gp_pt2prim": "76834e183fa9a778",
    "gp_prim2pt": "aa77d6382ba3a08f",
    "gp_expr": "d703503ed7298761",
    "del_group": "b8e56cbfdf520fdd",
    "del_nth": "15ba82c36226c50d",
    "del_range": "bb498879c567e285",
    "del_vol": "102e14080c9b86ab",
    "del_nrm_expr": "7bdce7dffcee960f",
    "dis_none": "5369824e00cada49",
    "dis_e": "ca3dd1b19ad1e97b",
    "dis_e_raw": "d0e5eb9e61deb434",
    "nrm_point": "1d347ddac69573db",
    "nrm_vertex": "d6ec258ec5db1258",
    "nrm_prim": "b5730083676169b5",
    "nrm_detail": "2a81bdd8c2a8de23",
    "nrm_grp": "1d347ddac69573db",
    "nrm_vgrp": "dcd57a834365a788",
    "clip_below": "d7c5ce0f7f2979a7",
    "clip_above": "03f67b729fea2534",
    "clip_both": "d93c45b4ab2fcb9c",
    "clip_dir": "02a873c82c0ee8af",
    "mir_mirror": "8c26313e4679ef4e",
    "mir_append": "4a9738526d05c786",
    "mir_nofuse": "3f84bfc8658d163b",
}

if "--digests" in sys.argv:
    import json
    print(json.dumps(old_cases(), indent=1))
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════ Regression
sec("bit-identical to before the change at defaults")
now = old_cases()
check(f"output digests of all {len(GOLDEN)} old calls unchanged", len(GOLDEN) >= 24 and now == GOLDEN,
      {k: (GOLDEN.get(k), v) for k, v in now.items() if GOLDEN.get(k) != v})
r = rich()
check("all new widgets at defaults = not passing them (Normal / Clip / Mirror / Delete / Dissolve / GroupPromote)",
      all(digest(run(n, geo=r, **kw)) == now[k] for n, kw, k in [
          ("PCG_Normal", dict(add_to="vertex"), "nrm_vertex"),
          ("PCG_Clip", dict(keep="both", use_out_groups=True), "clip_both"),
          ("PCG_Mirror", dict(mode="append", original_group="o", mirror_group="m"), "mir_append"),
          ("PCG_Delete", dict(use_number=True), "del_nth"),
          ("PCG_GroupPromote", dict(name="pg", direction="point_to_prim", new_name="x"), "gp_pt2prim")]))
for nid, old in OLD_NAMES.items():
    check(f"{nid}: old parameter names and order unchanged, new ones appended after them", names(nid)[:len(old)] == old, names(nid)[:len(old)])
it = lambda n, k: [list(v[k][0]) for v in M[n].INPUT_TYPES().values() if k in v][0]   # noqa: E731
check("old menu tokens still in place (new options only appended at the end)",
      it("PCG_GroupPromote", "direction")[:2] == ["point_to_prim", "prim_to_point"]
      and it("PCG_Delete", "entity")[:2] == ["point", "prim"]
      and it("PCG_Delete", "number_mode")[:2] == ["every_nth", "range"]
      and it("PCG_Mirror", "mode") == ["mirror", "append"]
      and it("PCG_Clip", "keep") == ["below", "above", "both"]
      and it("PCG_Dissolve", "bridge")[0] == "leave" and it("PCG_Dissolve", "operation")[0] == "selected"
      and it("PCG_Normal", "group_type")[0] == "guess" and it("PCG_Clip", "orient")[0] == "direction"
      and it("PCG_Mirror", "operation")[0] == "mirror_all" and it("PCG_Mirror", "orient")[0] == "direction")


# ═══════════════════════════════════════════════════════════════ Group Promote
sec("Group Promote: twelve directions")
G = grid3()
G.set_group(POINT, "sq", [0, 1, 3, 4])        # the four points of prim 0
G.set_group(POINT, "mid", [4])
G.set_group(PRIM, "f0", [0])
G.set_group(PRIM, "f01", [0, 1])
G.set_group(VERTEX, "v01", [0, 1])            # the first two vertices of prim 0: points 0, 3
G.set_edge_group("e14", [(1, 4)])
G.set_edge_group("ring0", [(0, 3), (3, 4), (1, 4), (0, 1)])


def gp(name, direction, **kw):
    return run("PCG_GroupPromote", geo=G, name=name, direction=direction, new_name="out", **kw)


check("point -> prim: default (Entirely Contained) only prim 0, which has all four points",
      grp(gp("sq", "point_to_prim"), PRIM, "out") == [0])
check("  off = touching one point is enough: all four prims use point 4",
      grp(gp("sq", "point_to_prim", only_full=False), PRIM, "out") == [0, 1, 2, 3])
check("  Sharing an Edge: prims with an edge whose two ends are both in the group = 0 / 1 / 2, prim 3 only touches a corner",
      grp(gp("sq", "point_to_prim", only_full=False, share_edge=True), PRIM, "out") == [0, 1, 2])
check("  single-point group + Sharing an Edge: no edge has both ends in it -> empty",
      grp(gp("mid", "point_to_prim", only_full=False, share_edge=True), PRIM, "out") == [])
check("point -> edge: default both ends in = the four edges of prim 0",
      egrp(gp("sq", "point_to_edge"), "out") == [(0, 1), (0, 3), (1, 4), (3, 4)])
check("  single-point group gives none by default; Entirely Contained off = the four edges going out of point 4",
      egrp(gp("mid", "point_to_edge"), "out") == []
      and egrp(gp("mid", "point_to_edge", only_full=False), "out") == [(1, 4), (3, 4), (4, 5), (4, 7)])
check("point -> vertex: point 4 has one vertex in each of the four prims", grp(gp("mid", "point_to_vertex"), VERTEX, "out") == [2, 5, 11, 12],
      grp(gp("mid", "point_to_vertex"), VERTEX, "out"))
check("prim -> point / vertex / edge: the four points, four vertices, four edges of prim 0",
      grp(gp("f0", "prim_to_point"), POINT, "out") == [0, 1, 3, 4]
      and grp(gp("f0", "prim_to_vertex"), VERTEX, "out") == [0, 1, 2, 3]
      and egrp(gp("f0", "prim_to_edge"), "out") == [(0, 1), (0, 3), (1, 4), (3, 4)])
check("edge -> point: endpoints", grp(gp("e14", "edge_to_point"), POINT, "out") == [1, 4])
check("edge -> prim: by default all of a prim's own edges must be in -> one edge isn't enough; off = prims 0, 1 on either side of the edge",
      grp(gp("e14", "edge_to_prim"), PRIM, "out") == []
      and grp(gp("e14", "edge_to_prim", only_full=False), PRIM, "out") == [0, 1])
check("  only prim 0 has all four edges in (prims 1, 2 have only one each)",
      grp(gp("ring0", "edge_to_prim"), PRIM, "out") == [0]
      and grp(gp("ring0", "edge_to_prim", only_full=False), PRIM, "out") == [0, 1, 2])
check("edge -> vertex: vertices adjacent to it in the prims on either side (2, 3 of prim 0; 4, 5 of prim 1)",
      grp(gp("e14", "edge_to_vertex"), VERTEX, "out") == [2, 3, 4, 5], grp(gp("e14", "edge_to_vertex"), VERTEX, "out"))
check("vertex -> point / prim / edge: vertices 0, 1 -> points 0, 3 / prim 0 / edge (0,3)",
      grp(gp("v01", "vertex_to_point"), POINT, "out") == [0, 3]
      and grp(gp("v01", "vertex_to_prim"), PRIM, "out") == [0]
      and egrp(gp("v01", "vertex_to_edge"), "out") == [(0, 3)])
G1v = G.copy()
G1v.set_group(VERTEX, "v5", [5])                # only one vertex (the one in prim 1 that points to point 4)
check("  vertex -> prim: one vertex is enough", grp(run("PCG_GroupPromote", geo=G1v, name="v5", direction="vertex_to_prim",
                                              new_name="out"), PRIM, "out") == [1])
G1 = G.copy()
G1.set_group(VERTEX, "v02", [0, 2])           # two non-adjacent vertices
check("  vertex -> edge needs two **adjacent** vertices in the same prim: two diagonal ones -> empty",
      egrp(run("PCG_GroupPromote", geo=G1, name="v02", direction="vertex_to_edge", new_name="out"), "out") == [])

sec("Group Promote:Boundary / Keep Original / Output as Attribute")
check("prim group -> boundary edges: two prims side by side, minus the shared middle edge leaves 6",
      egrp(gp("f01", "prim_to_edge", only_boundary=True), "out")
      == [(0, 1), (0, 3), (1, 2), (2, 5), (3, 4), (4, 5)])
check("  Include Unshared Edges off: only the two shared with prims outside the group remain",
      egrp(gp("f01", "prim_to_edge", only_boundary=True, include_unshared=False), "out") == [(3, 4), (4, 5)])
check("  without Boundary it's all 7 (negative control)", len(egrp(gp("f01", "prim_to_edge"), "out")) == 7)
check("prim group -> boundary points: 6 / with Unshared off only 3, 4, 5",
      grp(gp("f01", "prim_to_point", only_boundary=True), POINT, "out") == [0, 1, 2, 3, 4, 5]
      and grp(gp("f01", "prim_to_point", only_boundary=True, include_unshared=False), POINT, "out") == [3, 4, 5])
check("prim group -> boundary vertices: only the vertices of **prims in the group** (the 8 of prims 0, 1); vertices of outside prims on the same points don't count",
      grp(gp("f01", "prim_to_vertex", only_boundary=True), VERTEX, "out") == list(range(8)))
G9 = grid4()
G9.set_group(PRIM, "all", np.ones(9, bool))
G9.set_group(PRIM, "c", [4])
b9 = run("PCG_GroupPromote", geo=G9, name="all", direction="prim_to_vertex", new_name="out", only_boundary=True)
check("  whole 3×3 grid -> boundary vertices: 12 outer points, corner points 1 vertex, edge points 2 -> 4 + 8×2 = 20",
      len(grp(b9, VERTEX, "out")) == 20, len(grp(b9, VERTEX, "out")))
check("  prim group -> prims adjacent to the boundary: in a 3×3 the outer 8, the middle prim 4 has no boundary edge",
      grp(run("PCG_GroupPromote", geo=G9, name="all", direction="prim_to_prim", new_name="out", only_boundary=True),
          PRIM, "out") == [0, 1, 2, 3, 5, 6, 7, 8])
check("  Primitives -> Primitives without Boundary is just a rename",
      grp(run("PCG_GroupPromote", geo=G9, name="c", direction="prim_to_prim", new_name="out"), PRIM, "out") == [4])
line = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], np.float32), [[0, 1, 2]], closed=False)
line.set_group(PRIM, "c", [0])
lp = lambda **kw: egrp(run("PCG_GroupPromote", geo=line, name="c", direction="prim_to_edge", new_name="out",   # noqa: E731
                           only_boundary=True, **kw), "out")
check("  open curve edges are governed by Include All Unshared Curve Edges: not counted by default, both counted when on",
      lp() == [] and lp(include_curve_unshared=True) == [(0, 1), (1, 2)]
      and lp(include_curve_unshared=True, include_unshared=False) == [(0, 1), (1, 2)])
check("  Boundary starting from a point group: raises, doesn't guess", raises(lambda: gp("sq", "point_to_prim", only_boundary=True), "Boundary"))
k1, k0 = gp("sq", "point_to_prim"), gp("sq", "point_to_prim", keep_original=False)
check("Keep Original Group: original group kept by default; off removes it, other groups untouched",
      "sq" in k1.groups[POINT] and "sq" not in k0.groups[POINT] and "mid" in k0.groups[POINT])
check("  an edge group as the original can be deleted too",
      "e14" not in gp("e14", "edge_to_point", keep_original=False).edge_groups
      and "e14" in gp("e14", "edge_to_point").edge_groups)
at = gp("sq", "point_to_prim", only_full=False, share_edge=True, as_attribute=True)
check("Output as Integer Attribute: 0/1 integer attribute on prims, no group created",
      "out" not in at.groups[PRIM] and at.get(PRIM, "out").dtype.kind == "i"
      and at.get(PRIM, "out")[:, 0].tolist() == [1, 1, 1, 0])
check("  target Edges can't be written (no edge attributes): raises", raises(lambda: gp("sq", "point_to_edge", as_attribute=True), "no edge attributes"))
at2 = run("PCG_GroupPromote", geo=G, name="sq", direction="point_to_prim", new_name="f01", as_attribute=True)
check("  the target name already had a group of the same name: becomes an attribute, group removed (docs: the group is deleted after converting to an attribute)",
      "f01" not in at2.groups[PRIM] and at2.get(PRIM, "f01")[:, 0].tolist() == [1, 0, 0, 0])
check("New Name empty = use the original group name", grp(run("PCG_GroupPromote", geo=G, name="sq", direction="point_to_prim",
                                         new_name=""), PRIM, "sq") == [0])


# ═══════════════════════════════════════════════════════════════ Delete
sec("Delete:Pattern / Select _ of _ / Edges")
pts = Geometry.from_points(np.stack([np.arange(10), np.zeros(10), np.zeros(10)], 1).astype(np.float32))


def left(g):
    return P_(g)[:, 0].round().astype(int).tolist()


dl = lambda **kw: left(run("PCG_Delete", geo=pts, entity="point", use_number=True, **kw))   # noqa: E731
check("Delete by Pattern `0 2 5-7`: deletes these five", dl(number_mode="pattern", number_pattern="0 2 5-7") == [1, 3, 4, 8, 9])
check("  `0-8:3` with step / `* ^3-5` exclusion", dl(number_mode="pattern", number_pattern="0-8:3") == [1, 2, 4, 5, 7, 8, 9]
      and dl(number_mode="pattern", number_pattern="* ^3-5") == [3, 4, 5])
check("  the default `!*` and the empty string both select nothing (not everything)",
      dl(number_mode="pattern") == list(range(10)) and dl(number_mode="pattern", number_pattern="") == list(range(10)))
check("  group names / expressions are not number patterns: raises", raises(lambda: dl(number_mode="pattern", number_pattern="@P.x>3"))
      and raises(lambda: dl(number_mode="pattern", number_pattern="mygroup")))
check("  pattern mode doesn't read Start / End (negative control: range mode with the same parameters gives a different result)",
      dl(number_mode="pattern", number_pattern="0", number_start=5) == list(range(1, 10))
      and dl(number_mode="range", number_pattern="0", number_start=5) == [0, 1, 2, 3, 4])
check("Delete by Range + Select 1 of 3: within range 2..9, delete the first of every three",
      dl(number_mode="range", number_start=2, select_num=1, select_of=3) == [0, 1, 3, 4, 6, 7, 9])
check("  Select 2 of 3: delete the first two of every three", dl(number_mode="range", number_start=2, select_num=2, select_of=3) == [0, 1, 4, 7])
check("  1 of 1 = the whole range (previous behavior)", dl(number_mode="range", number_start=2, number_end=6) == [0, 1, 7, 8, 9])
de = lambda **kw: run("PCG_Delete", geo=G, entity="edge", **kw)       # noqa: E731
e1 = de(group="e14")
check("Entity = Edges: deletes the two endpoints of edge (1,4) -> 7 points left, all four prims use point 4 so all are gone",
      e1.npoints == 7 and e1.nprims == 0)
e2 = de(group="e14", operation="keep_selected")
check("  Delete Non-Selected: only the two endpoints of this edge remain", sorted(map(tuple, P_(e2).tolist())) == [(0.0, 0.0, -1.0), (0.0, 0.0, 0.0)])
check("  Group empty does nothing; other tabs turned on raise (edges have no definition of number / position)",
      digest(de(group="")) == digest(G) and raises(lambda: de(group="e14", use_number=True))
      and raises(lambda: de(group="e14", use_random=True)))

sec("Delete: Degenerate tab")
Pd = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1],            # 0 a normal unit quad
               [3, 0, 0], [4, 0, 0], [5, 0, 0],                        # 2 collinear triangle (area 0, three distinct points)
               [6, 0, 0], [6.01, 0, 0], [6.01, 0, 0.01], [6, 0, 0.01],  # 3 small quad with edge length 0.01 (area 1e-4)
               [8, 0, 0], [8.0005, 0, 0],                               # 4 polyline of length 0.0005
               [9, 0, 0], [10, 0, 0]], np.float32)                      # 5 polyline of length 1
faces = [[0, 1, 2, 3], [0, 0, 1], [4, 5, 6], [7, 8, 9, 10], [11, 12], [13, 14]]
dg = Geometry.from_mesh(Pd, faces)
dg.set_topology(dg.vertex_point, dg.prim_offset, np.array([1, 1, 1, 1, 0, 0], bool))
dg.set(PRIM, "id", np.arange(6, dtype=np.int32)[:, None])
dd = lambda **kw: run("PCG_Delete", geo=dg, entity="prim", use_degenerate=True, **kw).get(PRIM, "id")[:, 0].tolist()   # noqa: E731
check("Delete Degenerate Primitives: the prim [0,0,1] with fewer than 3 points after removing repeated references", dd() == [0, 2, 3, 4, 5])
check("  all three toggles off = nothing selected", dd(degenerate=False) == [0, 1, 2, 3, 4, 5])
check("Delete Zero-Area Faces, Tolerance 0.005: the two with area < 0.005²; the 1e-4 small quad **stays** (area is compared with the square of the tolerance)",
      dd(degenerate=False, zero_area=True, degenerate_tolerance=0.005) == [0, 3, 4, 5])
check("  Tolerance 0.02: 0.02² = 4e-4 > 1e-4, the small quad is deleted too", dd(degenerate=False, zero_area=True, degenerate_tolerance=0.02) == [0, 4, 5])
check("  zero area doesn't touch open polylines", 4 in dd(degenerate=False, zero_area=True, degenerate_tolerance=10.0)
      and dd(degenerate=False, zero_area=True, degenerate_tolerance=10.0) == [4, 5])
check("Treat Open Faces as Closed: polylines with perimeter < 0.001 (the 0.0005 one); long ones stay, closed faces untouched",
      dd(degenerate=False, open_faces=True, degenerate_tolerance=0.001) == [0, 1, 2, 3, 5])
check("  perimeter only counts the segments that exist: the 0.0005 two-point line isn't counted as there-and-back 0.001 (Tolerance 0.0008 still deletes it)",
      dd(degenerate=False, open_faces=True, degenerate_tolerance=0.0008) == [0, 1, 2, 3, 5])
check("  only open ones: the closed small quad with perimeter 0.04 isn't governed by this option at Tolerance 0.05",
      dd(degenerate=False, open_faces=True, degenerate_tolerance=0.05) == [0, 1, 2, 3, 5])
check("  Tolerance 0.0001 < 0.0005: not deleted", dd(degenerate=False, open_faces=True, degenerate_tolerance=0.0001) == [0, 1, 2, 3, 4, 5])
check("  the three options are unioned", dd(zero_area=True, open_faces=True, degenerate_tolerance=0.005) == [0, 3, 5])
check("  meaningless with Entity = Points: raises", raises(lambda: run("PCG_Delete", geo=dg, entity="point", use_degenerate=True), "Degenerate"))
two = Geometry.from_mesh(Pd[:4], [[0, 1], [0, 0]], closed=False)
two.set(PRIM, "id", np.arange(2, dtype=np.int32)[:, None])
check("  open lines: two distinct points are not degenerate, the same point referenced twice is",
      run("PCG_Delete", geo=two, entity="prim", use_degenerate=True).get(PRIM, "id")[:, 0].tolist() == [0])

sec("Delete: Random tab / Delete Unused Groups")
big = Geometry.from_points(np.stack([np.arange(2000), np.zeros(2000), np.zeros(2000)], 1).astype(np.float32))
big.set(POINT, "id", (np.arange(2000) // 2).astype(np.int32)[:, None])
big.set(POINT, "fid", np.arange(2000, dtype=np.float32)[:, None])
rnd = lambda **kw: set(left(run("PCG_Delete", geo=big, entity="point", use_random=True, **kw)))   # noqa: E731
n30 = 2000 - len(rnd(percent=30.0))
check("Percent 30: deletes about 30% (600 ± 60 of 2000)", abs(n30 - 600) < 60, n30)
check("  0 = delete none, 100 = delete all", len(rnd(percent=0.0)) == 2000 and len(rnd(percent=100.0)) == 0)
check("  larger Percent deletes more, and the smaller set is a subset of the larger one (same random number, only the threshold differs)",
      rnd(percent=60.0) < rnd(percent=30.0))
check("  a different Global Seed gives a different set; the same seed is reproducible", rnd(percent=30.0, rand_seed=7) != rnd(percent=30.0)
      and rnd(percent=30.0, rand_seed=7) == rnd(percent=30.0, rand_seed=7))
sa = rnd(percent=50.0, use_seed_attribute=True, seed_attribute="id")
check("  Seed Attribute: two points with the same id share the same fate (id = number // 2)",
      all(((2 * i) in sa) == ((2 * i + 1) in sa) for i in range(1000)) and 300 < len(sa) < 1700 and len(sa) % 2 == 0)
check("  not read when Use Seed Attribute is off (negative control)",
      rnd(percent=50.0, seed_attribute="id") == rnd(percent=50.0, seed_attribute="nope") != sa)
check("  seed attribute missing / not an integer: raises",
      raises(lambda: rnd(use_seed_attribute=True, seed_attribute="nope"))
      and raises(lambda: rnd(use_seed_attribute=True, seed_attribute="fid")))
check("  Delete Non-Selected: Percent is the fraction kept", abs(len(rnd(percent=30.0, operation="keep_selected")) - 600) < 60)
ug = lambda **kw: run("PCG_Delete", geo=G, entity="prim", group="f0", **kw)          # noqa: E731
check("Delete Unused Groups: after deleting prim 0, f0 which only held it is empty -> removed; f01 still has members, point groups unaffected",
      "f0" not in ug(delete_unused_groups=True).groups[PRIM] and "f01" in ug(delete_unused_groups=True).groups[PRIM]
      and "sq" in ug(delete_unused_groups=True).groups[POINT] and "f0" in ug().groups[PRIM])
uge = run("PCG_Delete", geo=G, entity="point", group="1", delete_unused_groups=True)
check("  emptied edge / vertex groups removed too (delete point 1: e14 gone; v01 on prim 0 gone too)",
      "e14" not in uge.edge_groups and "v01" not in uge.groups[VERTEX] and "mid" in uge.groups[POINT])
uged = de(group="e14", delete_unused_groups=True)
check("  Entity = Edges also cleans up: all prims gone, no prim group left; unchecked keeps the empty groups",
      not uged.groups[PRIM] and "f0" in e1.groups[PRIM] and "sq" in uged.groups[POINT])
pe = pts.copy()
pe.set_group(POINT, "emptyp", np.zeros(10, bool))
check("  also cleans up when this class has no elements at all (Entity = Primitives on a point cloud)",
      "emptyp" not in run("PCG_Delete", geo=pe, entity="prim", delete_unused_groups=True).groups[POINT]
      and "emptyp" in run("PCG_Delete", geo=pe, entity="prim").groups[POINT])
check("  empty groups are cleaned even when nothing was deleted (groups that were empty to begin with)",
      "empty" not in run("PCG_Delete", geo=(lambda g: (g.set_group(PRIM, "empty", np.zeros(4, bool)), g)[1])(G.copy()),
                         delete_unused_groups=True).groups[PRIM])


# ═══════════════════════════════════════════════════════════════ Blast by Attribute
sec("Blast by Attribute (new node)")
bp = pts.copy()
bp.set(POINT, "v", (np.arange(10) * 0.125).astype(np.float32)[:, None])     # 0, 0.125 … 1.125, all exactly representable
bp.set_string(POINT, "s", ["a"] * 10)
ba = lambda **kw: left(run("PCG_BlastByAttribute", geo=bp, attribute="v", **kw))   # noqa: E731
check("Threshold 0.5: the four with values **below** 0.5 deleted, exactly 0.5 stays", ba(threshold=0.5) == [4, 5, 6, 7, 8, 9])
check("  Invert: reversed, those four are kept", ba(threshold=0.5, invert=True) == [0, 1, 2, 3])
check("Range [0.25, 0.5]: both ends inclusive", ba(mode="range", min=0.25, max=0.5) == [0, 1, 5, 6, 7, 8, 9])
check("Width: center 0.5, width 0.25 -> [0.375, 0.625]", ba(mode="width", center=0.5, width=0.25) == [0, 1, 2, 6, 7, 8, 9])
check("  each mode only reads its own numbers (negative control: threshold mode unchanged by min / center)",
      ba(threshold=0.5, min=0.9, max=0.95, center=3.0) == ba(threshold=0.5))
check("elements outside Group don't take part, Invert doesn't touch them: group 0-4 + Invert -> only 4 deleted",
      ba(threshold=0.5, invert=True, group="0-4") == [0, 1, 2, 3, 5, 6, 7, 8, 9])
og = run("PCG_BlastByAttribute", geo=bp, attribute="v", output="group", threshold=0.5, output_group="low")
check("Output = Group: nothing deleted, matches go into the group", og.npoints == 10 and grp(og, POINT, "low") == [0, 1, 2, 3])
gb = grid3()
gb.set(PRIM, "w", np.array([0.0, 1.0, 2.0, 3.0], np.float32)[:, None])
b1 = run("PCG_BlastByAttribute", geo=gb, cls="prim", attribute="w", threshold=3.0)
b2 = run("PCG_BlastByAttribute", geo=gb, cls="prim", attribute="w", threshold=3.0, remove_unused_points=False)
check("Run Over = Primitives: deletes three prims; Remove Unused Points on = 4 points left, off = all 9 remain",
      b1.nprims == 1 and b1.npoints == 4 and b2.nprims == 1 and b2.npoints == 9)
check("  attribute missing / string / vector attribute / empty name: raises",
      all(raises(lambda a=a: run("PCG_BlastByAttribute", geo=bp, attribute=a), m)
          for a, m in (("nope", "has no attribute"), ("s", "string attribute"), ("P", "components"), ("", "is empty"))))
import sop_map                                           # noqa: E402
check("sop_map: Blast by Attribute points to the new node", sop_map.M["Blast by Attribute"][1] == "PCG_BlastByAttribute")


# ═══════════════════════════════════════════════════════════════ Dissolve
sec("Dissolve:Operation / Bridge / Recompute Normals")
strip = build.grid(3.0, 1.0, 4, 2)             # a row of three quads
Ps = P_(strip)
# two interior edges: the ones at x = -0.5 and x = +0.5
e_of = lambda x: tuple(np.nonzero(np.isclose(Ps[:, 0], x))[0].tolist())      # noqa: E731
strip.set_edge_group("a", [e_of(-0.5)])
ds = lambda g=strip, **kw: run("PCG_Dissolve", geo=g, remove_inline_points=False, **kw)   # noqa: E731
sa_, sn_ = ds(edge_group="a"), ds(edge_group="a", operation="non_selected")
check("Dissolve Selected: dissolve a, the two left prims merge into 2×1, the right one unchanged",
      sa_.nprims == 2 and sorted(areas(sa_).round(4).tolist()) == [1.0, 2.0]
      and P_(sa_)[sa_.prim_points(int(np.argmax(areas(sa_))))][:, 0].max() == 0.5)
check("Dissolve Non-Selected: dissolve the edges **other than** a -> the two right prims merge, a remains",
      sn_.nprims == 2 and sorted(areas(sn_).round(4).tolist()) == [1.0, 2.0]
      and P_(sn_)[sn_.prim_points(int(np.argmax(areas(sn_))))][:, 0].min() == -0.5)
check("  group empty + Non-Selected = all interior edges -> one 3×1 prim; Selected does nothing",
      ds(edge_group="", operation="non_selected").nprims == 1 and ds(edge_group="").nprims == 3)
g9 = grid4()
c4 = set(g9.prim_points(4).tolist())
t9 = __import__("comfyui_pcg.geo.topology", fromlist=["topology"]).topology(g9)
ring_e = [tuple(e) for e, c in zip(t9.edge_points.tolist(), t9.edge_count.tolist())
          if c == 2 and not (set(e) <= c4)]
g9.set_edge_group("ring", ring_e)
check("(setup) exactly 8 shared edges between the 8 outer prims", len(ring_e) == 8)
lv, br, dl_ = ds(g9, edge_group="ring"), ds(g9, edge_group="ring", bridge="bridged"), ds(g9, edge_group="ring", bridge="delete")
check("Bridge = leave (previous behavior): the piece with a hole stays as is, 9 prims", lv.nprims == 9)
ar = sorted(areas(br).round(4).tolist())
big_i = int(np.argmax(areas(br)))
check("Create Bridged Polygons: the outer ring merges into **one** prim, area 9 - 1 = 8, the middle prim still there", br.nprims == 2 and ar == [1.0, 8.0], ar)
check("  bridged prim = outer loop 12 + hole 4 + one extra vertex each way along the bridge = 18 vertices, normal still +Y",
      len(br.prim_points(big_i)) == 18
      and np.allclose(ops.prim_normals(br)[big_i], [0, 1, 0], atol=1e-6), len(br.prim_points(big_i)))
bpnt = br.prim_points(big_i).tolist()
check("  only one bridge: exactly two points appear twice each", sorted(np.bincount(bpnt).tolist())[-3:] == [1, 2, 2])
brb = ds(g9, edge_group="ring", bridge="bridged", output_boundary_group="bd")
check("  Boundary Edge Group still given: 12 outer edges + 4 hole edges, the bridge doesn't count", len(egrp(brb, "bd")) == 16)


def ring_grid(n, hole, flip=None):
    """n×n grid, all interior edges selected except those around prim number hole -> one big piece with one hole."""
    g = build.grid(float(n), float(n), n + 1, n + 1)
    if flip is not None:
        g = ops.reverse_prims(g, group=str(flip))
    c = set(g.prim_points(hole).tolist())
    tt = __import__("comfyui_pcg.geo.topology", fromlist=["topology"]).topology(g)
    g.set_edge_group("r", [tuple(e) for e, k in zip(tt.edge_points.tolist(), tt.edge_count.tolist())
                           if k == 2 and not (set(e) <= c)])
    return g


okb = []
for n_, h_ in ((5, 12), (5, 6), (5, 18), (4, 5), (4, 10), (6, 14)):
    o_ = ds(ring_grid(n_, h_), edge_group="r", bridge="bridged")
    bi = int(np.argmax(areas(o_)))
    pp = o_.prim_points(bi).tolist()
    L = (len(pp) - 4 * n_ - 4) // 2             # number of bridge segments
    cntp = np.bincount(pp)
    okb.append(o_.nprims == 2 and abs(areas(o_)[bi] - (n_ * n_ - 1)) < 1e-4
               and len(pp) == 4 * n_ + 4 + 2 * L and L >= 1
               # No spikes: no a b a; the L+1 points on the bridge appear twice each, the rest once
               and all(pp[i - 1] != pp[(i + 1) % len(pp)] for i in range(len(pp)))
               and int((cntp == 2).sum()) == L + 1 and cntp.max() == 2
               and np.allclose(ops.prim_normals(o_)[bi], [0, 1, 0], atol=1e-6))
check("  bigger pieces (4×4 / 5×5 / 6×6, hole at different positions): all interior points removed, only outer loop + hole + one bridge left, area n² - 1",
      all(okb), okb)
rng, rng2 = np.random.default_rng(0), np.random.default_rng(1)
okr, okc, oku = [], [], []
for _ in range(60):
    n_ = int(rng.integers(3, 6))
    g0 = build.grid(float(n_), float(n_), n_ + 1, n_ + 1)
    F_ = np.asarray(g0.vertex_point).reshape(-1, 4)
    inner_ = [k for k in range(len(F_)) if np.abs(P_(g0)[F_[k]][:, [0, 2]]).max() < n_ / 2 - 0.5]
    perm, rot = rng.permutation(len(F_)), rng.integers(0, 4, len(F_))
    gr = Geometry.from_mesh(np.asarray(g0.get(POINT, "P")), [np.roll(F_[p_], -r_).tolist() for p_, r_ in zip(perm, rot)])
    hole = int(np.nonzero(perm == inner_[int(rng.integers(0, len(inner_)))])[0][0])
    ch_ = set(gr.prim_points(hole).tolist())
    tt = __import__("comfyui_pcg.geo.topology", fromlist=["topology"]).topology(gr)
    gr.set_edge_group("r", [tuple(e) for e, k in zip(tt.edge_points.tolist(), tt.edge_count.tolist())
                            if k == 2 and not (set(e) <= ch_)])
    gr.set(VERTEX, "cid", np.arange(gr.nvertices, dtype=np.int32)[:, None])
    o_ = ds(gr, edge_group="r", bridge="bridged")
    bi = int(np.argmax(areas(o_)))
    pp = o_.prim_points(bi).tolist()
    L = (len(pp) - 4 * n_ - 4) // 2
    cntp = np.bincount(pp)
    okr.append(o_.nprims == 2 and abs(areas(o_)[bi] - (n_ * n_ - 1)) < 1e-4 and L >= 1 and len(pp) == 4 * n_ + 4 + 2 * L
               and all(pp[i - 1] != pp[(i + 1) % len(pp)] for i in range(len(pp)))
               and int((cntp == 2).sum()) == L + 1 and cntp.max() == 2)
    # Which original vertex each vertex attribute comes from: that vertex's outgoing edge in the original prim must be exactly its outgoing edge in the new prim
    cid = o_.get(VERTEX, "cid")[int(o_.prim_offset[bi]):int(o_.prim_offset[bi + 1]), 0]
    nx0 = gr.next_corner()
    okc.append(all(int(gr.vertex_point[c_]) == pp[i] and int(gr.vertex_point[nx0[c_]]) == pp[(i + 1) % len(pp)]
                   for i, c_ in enumerate(cid.tolist())))
    # The same geometry again: leave one edge with one end on the outer rim and one inside unselected
    onb_ = np.zeros(gr.npoints, bool)
    onb_[tt.edge_points[tt.edge_count == 1].reshape(-1)] = True
    cand = [e for e in egrp(gr, "r") if onb_[e[0]] != onb_[e[1]] and not (set(e) & ch_)]
    if not cand:                                # 3×3: all interior points are hole corners, no such edge
        continue
    ke = cand[int(rng2.integers(0, len(cand)))]     # a separate random source, so the sequence above isn't disturbed
    gr.set_edge_group("r", [e for e in egrp(gr, "r") if e != ke])
    o2 = ds(gr, edge_group="r", bridge="bridged")
    p2 = o2.prim_points(int(np.argmax(areas(o2)))).tolist()
    d2 = {(p2[i], p2[(i + 1) % len(p2)]) for i in range(len(p2))}
    oku.append(o2.nprims == 2 and abs(areas(o2).max() - (n_ * n_ - 1)) < 1e-4 and ke in d2 and ke[::-1] in d2)
check("  same 60 runs, each leaving one edge unselected: it's always still there (including when it sits right at the loop's seam)",
      all(oku) and len(oku) >= 30, (int(np.sum(oku)), len(oku)))
check("  prim order and each prim's starting vertex shuffled 60 times (spikes land at the loop's seam): results are always a clean outer loop + one hole + one bridge",
      all(okr), int(np.sum(okr)))
check("  the vertex kept after removing a spike is the one whose outgoing edge still exists (vertex attributes follow the right vertex)", all(okc), int(np.sum(okc)))
gk = ring_grid(4, 5)
tk = __import__("comfyui_pcg.geo.topology", fromlist=["topology"]).topology(gk)
onb = np.zeros(gk.npoints, bool)
onb[tk.edge_points[tk.edge_count == 1].reshape(-1)] = True
hp = set(gk.prim_points(5).tolist())
keep_e = [e for e in egrp(gk, "r") if onb[e[0]] != onb[e[1]] and not (set(e) & hp)][0]   # one end on the outer rim, one inside
gk.set_edge_group("r", [e for e in egrp(gk, "r") if e != keep_e])
ok_ = ds(gk, edge_group="r", bridge="bridged")
pk = ok_.prim_points(int(np.argmax(areas(ok_)))).tolist()
dirs = {(pk[i], pk[(i + 1) % len(pk)]) for i in range(len(pk))}
check("  the piece has an **unselected** edge: not removed as a spike, kept once in each direction (it isn't to be dissolved)",
      ok_.nprims == 2 and abs(areas(ok_).max() - 15.0) < 1e-4
      and keep_e in dirs and keep_e[::-1] in dirs)
check("  one prim has reversed winding: can't be stitched into one face, kept as is per leave (doesn't force a face with the wrong area)",
      all(ds(ring_grid(3, 4, flip=f_), edge_group="r", bridge="bridged").nprims == 9 for f_ in (0, 1, 3)))
bxa = build.box()
bxa.set_edge_group("all", __import__("comfyui_pcg.geo.topology", fromlist=["topology"]).topology(bxa).edge_points)
check("  a whole closed box selected: no boundary, no bridged face possible, the 6 prims stay as they are",
      ds(bxa, edge_group="all", bridge="bridged").nprims == 6)
check("Delete Polygons: the piece with a hole is deleted entirely, only the middle prim remains", dl_.nprims == 1 and np.isclose(areas(dl_)[0], 1.0))
check("  pieces without holes: same result in all three modes (negative control)",
      digest(ds(edge_group="a", bridge="bridged")) == digest(sa_) == digest(ds(edge_group="a", bridge="delete")))
sN = strip.copy()
sN.set(POINT, "N", np.tile([1.0, 0.0, 0.0], (sN.npoints, 1)).astype(np.float32))
check("Recompute Normals: the point N carried along (deliberately wrong here) recomputed to +Y; unchecked carries it as is",
      np.allclose(ds(sN, edge_group="a", recompute_normals=True).get(POINT, "N"), [0, 1, 0], atol=1e-6)
      and np.allclose(ds(sN, edge_group="a").get(POINT, "N"), [1, 0, 0]))
check("  no N is not created", not ds(edge_group="a", recompute_normals=True).has(POINT, "N"))


# ═══════════════════════════════════════════════════════════════ Normal
sec("Normal:Override / Compute / Unit / Reverse / Keep Zero / Group Type")
B = build.box()
N0 = np.asarray(run("PCG_Normal", geo=B).get(POINT, "N"), np.float64)
o1 = run("PCG_Normal", geo=B, normal_name="myN")
check("Override Normal: written to myN, N not created, values equal to the default N",
      not o1.has(POINT, "N") and np.array_equal(np.asarray(o1.get(POINT, "myN"), np.float64), N0))
check("  empty = N", run("PCG_Normal", geo=B, normal_name=" ").has(POINT, "N"))
for add_ in ("vertex", "prim", "detail"):
    o_ = run("PCG_Normal", geo=B, add_to=add_, normal_name="myN")
    check(f"  Add Normals to = {add_} also writes to myN", o_.has(add_, "myN") and not o_.has(add_, "N")
          and np.array_equal(o_.get(add_, "myN"), run("PCG_Normal", geo=B, add_to=add_).get(add_, "N")))
check("  same for a point cloud without prims (takes another branch)",
      run("PCG_Normal", geo=pts, normal_name="myN").has(POINT, "myN") and not run("PCG_Normal", geo=pts, normal_name="myN").has(POINT, "N"))
Bo = B.copy()
Bo.set(POINT, "N", np.tile([0.0, 0.0, 1.0], (8, 1)).astype(np.float32))
Bo.set(POINT, "myN", np.tile([1.0, 0.0, 0.0], (8, 1)).astype(np.float32))
ob = np.asarray(run("PCG_Normal", geo=Bo, normal_name="myN", group="0-3").get(POINT, "myN"), np.float64)
check("  with Group: outside the group the original value of **myN** is kept, not N's",
      np.allclose(ob[:4], N0[:4], atol=1e-6) and np.allclose(ob[4:], [1, 0, 0]))
check("Compute Normals off: does nothing if there's no N", not run("PCG_Normal", geo=B, compute_normals=False).has(POINT, "N"))
B2 = B.copy()
B2.set(POINT, "N", (N0 * 2.5).astype(np.float32))
u1 = np.asarray(run("PCG_Normal", geo=B2, compute_normals=False, make_unit=True).get(POINT, "N"), np.float64)
u0 = np.asarray(run("PCG_Normal", geo=B2, compute_normals=False).get(POINT, "N"), np.float64)
check("Make Normals Unit Length (Compute off): N 2.5 times as long gets normalized; unchecked keeps it as is",
      np.allclose(np.linalg.norm(u1, axis=1), 1.0, atol=1e-6) and np.allclose(u1, N0, atol=1e-6)
      and np.allclose(u0, N0 * 2.5, atol=1e-6))
check("  Compute off + only Reverse checked: only negated, not normalized along the way",
      np.allclose(run("PCG_Normal", geo=B2, compute_normals=False, reverse=True).get(POINT, "N"), -N0 * 2.5, atol=1e-6))
ug_ = np.asarray(run("PCG_Normal", geo=B2, compute_normals=False, make_unit=True, group="0-3").get(POINT, "N"), np.float64)
check("  only those in Group change: 0-3 normalized, 4-7 still 2.5",
      np.allclose(np.linalg.norm(ug_, axis=1), [1, 1, 1, 1, 2.5, 2.5, 2.5, 2.5], atol=1e-5))
r1 = np.asarray(run("PCG_Normal", geo=B, reverse=True).get(POINT, "N"), np.float64)
check("Reverse Normals: everything multiplied by -1", np.allclose(r1, -N0, atol=1e-7) and np.abs(N0).max() > 0.5)
r2 = np.asarray(run("PCG_Normal", geo=B2, reverse=True, group="0-3").get(POINT, "N"), np.float64)
check("  with Group: those in the group recomputed then negated, those outside keep the input value",
      np.allclose(r2[:4], -N0[:4], atol=1e-6) and np.allclose(r2[4:], N0[4:] * 2.5, atol=1e-6))
check("  Detail flips too", np.allclose(run("PCG_Normal", geo=grid3(), add_to="detail", reverse=True).get(DETAIL, "N"), [0, -1, 0]))
iso = Geometry.from_mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 0, -1], [5, 5, 5]], np.float32), [[0, 1, 2]])
iso.set(POINT, "N", np.tile([0.0, 0.0, 1.0], (4, 1)).astype(np.float32))
z0 = run("PCG_Normal", geo=iso).get(POINT, "N")
z1 = run("PCG_Normal", geo=iso, keep_zero=True).get(POINT, "N")
check("Keep Original Normal Where Computed Normal Is Zero: an isolated point computes to 0; checked keeps the input (0,0,1)",
      np.allclose(z0[3], 0) and np.allclose(z1[3], [0, 0, 1]) and np.allclose(z1[:3], [0, 1, 0]) and np.allclose(z0[:3], [0, 1, 0]))
iso2 = iso.copy()
iso2.set(POINT, "N", np.tile([0.0, 0.0, 2.0], (4, 1)).astype(np.float32))
check("  with Compute on, Make Unit has no effect (docs: it's grayed out then): the kept (0,0,2) is not normalized",
      np.allclose(run("PCG_Normal", geo=iso2, keep_zero=True, make_unit=True).get(POINT, "N")[3], [0, 0, 2]))
Gn = grid3()
Gn.set(POINT, "N", np.tile([1.0, 0.0, 0.0], (9, 1)).astype(np.float32))    # deliberately wrong, to see which points get recomputed
Gn.set_edge_group("e14", [(1, 4)])
redo = lambda **kw: np.nonzero(np.asarray(run("PCG_Normal", geo=Gn, **kw).get(POINT, "N"))[:, 1] > 0.5)[0].tolist()   # noqa: E731
check("Group Type = Guess (previous behavior): `0` parsed in the Add Normals to class = point 0", redo(group="0") == [0])
check("  Primitives: `0` is prim 0, expanded to its four points", redo(group="0", group_type="prim") == [0, 1, 3, 4])
check("  Edges: endpoints of the edge group", redo(group="e14", group_type="edge") == [1, 4])
check("  Vertices: points 0, 3 that vertices 0, 1 point to", redo(group="0 1", group_type="vertex") == [0, 3])
check("  Points explicitly = Guess's result on points", redo(group="0", group_type="point") == [0])
Gp = grid3()
Gp.set(PRIM, "N", np.tile([1.0, 0.0, 0.0], (4, 1)).astype(np.float32))
check("  point group expanded to prims (Add Normals to = Primitives): only prim 0 uses point 0; all prims use point 4",
      np.nonzero(np.asarray(run("PCG_Normal", geo=Gp, add_to="prim", group="0", group_type="point").get(PRIM, "N"))[:, 1] > 0.5)[0].tolist() == [0]
      and np.asarray(run("PCG_Normal", geo=Gp, add_to="prim", group="4", group_type="point").get(PRIM, "N"))[:, 1].min() > 0.5)


# ═══════════════════════════════════════════════════════════════ Clip
sec("Clip: Fill Polygons / Split Connectivity / output groups")
cl = lambda g=B, **kw: run("PCG_Clip", geo=g, **kw)       # noqa: E731
c0, cf = cl(), cl(fill=True)
check("(baseline) box clipped at y = 0, keeping the lower half: 4 sides + bottom, open, not closed", c0.nprims == 5 and not closed_manifold(c0))
check("Fill: one face added -> closed manifold, volume exactly half, 0.5", cf.nprims == 6 and closed_manifold(cf) and abs(volume(cf) - 0.5) < 1e-6, volume(cf))
check("  the fill face is last, normal +Y (the cut of the lower half faces up), no new points",
      np.allclose(ops.prim_normals(cf)[-1], [0, 1, 0], atol=1e-6) and cf.npoints == c0.npoints and np.isclose(areas(cf)[-1], 1.0))
ca = cl(fill=True, keep="above")
check("  keeping the upper half: cut faces -Y, volume 0.5", closed_manifold(ca) and abs(volume(ca) - 0.5) < 1e-6
      and np.allclose(ops.prim_normals(ca)[-1], [0, -1, 0], atol=1e-6))
cb = cl(fill=True, keep="both", use_out_groups=True, clipped_group="cut", fill_group="cap")
check("  Keep All: one fill on each side (10 -> 12 prims), total volume still 1; the two cuts face up and down",
      cb.nprims == 12 and abs(volume(cb) - 1.0) < 1e-6
      and sorted(ops.prim_normals(cb)[-2:, 1].round(4).tolist()) == [-1.0, 1.0])
check("  Filled Polygons group = those two; Clipped Primitives = the 8 pieces of the 4 cut sides; above / below groups 5 + 1 each",
      grp(cb, PRIM, "cap") == [10, 11] and len(grp(cb, PRIM, "cut")) == 8
      and len(grp(cb, PRIM, "above")) == 6 and len(grp(cb, PRIM, "below")) == 6
      and not (set(grp(cb, PRIM, "cut")) & set(grp(cb, PRIM, "cap"))))
cg = cl(use_out_groups=True, clipped_group="cut", fill_group="cap")
check("  without Fill the Filled group is empty; keeping the lower half, Clipped = the 4 sides, bottom not counted",
      grp(cg, PRIM, "cap") == [] and len(grp(cg, PRIM, "cut")) == 4
      and all(P_(cg)[cg.prim_points(i)][:, 1].max() > -0.4 for i in grp(cg, PRIM, "cut")))
check("  with Create Groups off neither new group is created (negative control)",
      not cl(clipped_group="cut", fill_group="cap", fill=True).groups[PRIM])
cs = cl(keep="both", split_connectivity=True)
check("Split Connectivity: the 4 points on the seam get one copy above and one below (12 -> 16 points), prim count unchanged",
      cs.npoints == 16 and cs.nprims == 10 and cl(keep="both").npoints == 12)
ptsets = [set(cs.prim_points(i).tolist()) for i in range(cs.nprims)]
up = [i for i in range(cs.nprims) if P_(cs)[cs.prim_points(i)][:, 1].max() > 0.1]
dn = [i for i in range(cs.nprims) if i not in up]
check("  the upper and lower halves (5 prims each) no longer share any point",
      len(up) == 5 and len(dn) == 5 and not (set().union(*[ptsets[i] for i in up]) & set().union(*[ptsets[i] for i in dn])))
check("  when off they are shared (negative control)", len(set().union(*[set(cl(keep="both").prim_points(i).tolist()) for i in range(10)])) == 12)
Gs = grid3()
right = [i for i in range(4) if P_(Gs)[Gs.prim_points(i)][:, 0].min() >= 0]
gs = cl(Gs, keep="both", split_connectivity=True, dir_x=1.0, dir_y=0.0, group=" ".join(map(str, right)))
check("  points only shared with prims outside the group aren't split (group = the two right prims, plane right through the middle column of points): still 9 points",
      len(right) == 2 and gs.npoints == 9 and gs.nprims == 4)
left_ = [i for i in range(4) if i not in right]
check("  group = the two left prims (both below): the right prims are outside the group, don't count as above, no split",
      cl(Gs, keep="both", split_connectivity=True, dir_x=1.0, dir_y=0.0, group=" ".join(map(str, left_))).npoints == 9)
check("  same plane, no group restriction: the 3 points of the middle column get one copy above and below -> 12 points",
      cl(Gs, keep="both", split_connectivity=True, dir_x=1.0, dir_y=0.0).npoints == 12)
csf = cl(keep="both", split_connectivity=True, fill=True)
ptsets = [set(csf.prim_points(i).tolist()) for i in range(csf.nprims)]
capA, capB = ptsets[10], ptsets[11]
check("  Split + Fill: each cut uses its own side's points (no shared points), both halves closed, volume 0.5 each",
      csf.nprims == 12 and not (capA & capB) and abs(volume(csf) - 1.0) < 1e-6 and closed_manifold(csf))
check("  Split only takes effect with Keep All (negative control)", digest(cl(split_connectivity=True)) == digest(c0))
# Ring-shaped cut: outer tube r=1 + reversed inner tube r=0.5, the cross-section is an annulus
to, ti = build.tube(1.0, 1.0, 2.0, 16, 2), ops.reverse_prims(build.tube(0.5, 0.5, 2.0, 16, 2))
pipe = ops.merge(to, ti)
cp = cl(pipe, fill=True, use_out_groups=True, fill_group="cap")
poly = lambda r_: 0.5 * 16 * r_ * r_ * np.sin(2 * np.pi / 16)          # noqa: E731
capi = grp(cp, PRIM, "cap")
check("cut with a hole (tube wall): filled as **one** face, area = outer 16-gon - inner 16-gon, normal +Y",
      len(capi) == 1 and abs(areas(cp)[capi[0]] - (poly(1.0) - poly(0.5))) < 1e-5
      and np.allclose(ops.prim_normals(cp)[capi[0]], [0, 1, 0], atol=1e-6) and not cp.has(DETAIL, "clip_fill_skipped"),
      (len(capi), float(areas(cp)[capi[0]]) if capi else None, poly(1.0) - poly(0.5)))
check("  16 + 16 points + each end of the bridge repeated once = 34 vertices", len(cp.prim_points(capi[0])) == 34)
cpp = cp.prim_points(capi[0])
dup = np.nonzero(np.bincount(cpp) == 2)[0]
check("  the bridge goes between the closest pair of points: two points at the same angle on the inner and outer rings, 0.5 apart",
      len(dup) == 2 and abs(np.linalg.norm(P_(cp)[dup[0]] - P_(cp)[dup[1]]) - 0.5) < 1e-5)
nest = ops.merge(build.tube(3.0, 3.0, 2.0, 16, 2), ops.reverse_prims(build.tube(2.0, 2.0, 2.0, 16, 2)), to, ti,
                 build.tube(0.3, 0.3, 2.0, 16, 2, center=(10, 0, 0)))
cn = cl(nest, fill=True, use_out_groups=True, fill_group="cap")
check("  two nested tubes + a solid one beside them: each hole goes to **the innermost ring enclosing it**, the one beside is untouched -> three faces, each with its own area",
      np.allclose(sorted(areas(cn)[grp(cn, PRIM, "cap")].tolist()),
                  sorted([poly(3.0) - poly(2.0), poly(1.0) - poly(0.5), poly(0.3)]), atol=1e-4)
      and not cn.has(DETAIL, "clip_fill_skipped"),
      sorted(areas(cn)[grp(cn, PRIM, "cap")].round(4).tolist()))
ch = cl(ti, fill=True)
check("  only an inward-facing wall ring (a hole with no outer contour): not filled, detail clip_fill_skipped = 1",
      ch.nprims == cl(ti).nprims and int(ch.get(DETAIL, "clip_fill_skipped")[0, 0]) == 1)
# Two boxes sharing a vertical edge: the cut is two squares touching at one point
bb2 = ops.fuse(ops.merge(build.box(), build.box((1, 1, 1), (1.0, 0.0, 1.0))), 1e-4)
c8 = cl(bb2, fill=True, use_out_groups=True, fill_group="cap")
check("  two cuts touching at one point: split at the touching point, each filled separately -> two squares of area 1, total volume 2 × 0.5",
      len(grp(c8, PRIM, "cap")) == 2 and np.allclose(areas(c8)[grp(c8, PRIM, "cap")], 1.0, atol=1e-6)
      and abs(volume(c8) - 1.0) < 1e-6 and not c8.has(DETAIL, "clip_fill_skipped")
      and all(len(c8.prim_points(i)) == 4 for i in grp(c8, PRIM, "cap")))
solid_in = ops.merge(build.tube(3.0, 3.0, 2.0, 16, 2), to, ti)      # a tube running through a big solid cylinder: two outer contours nested, no hole separating them
cs_ = cl(solid_in, fill=True, use_out_groups=True, fill_group="cap")
check("  a hole inside two outer contours at once: goes to the **inner** one (smaller area)",
      np.allclose(sorted(areas(cs_)[grp(cs_, PRIM, "cap")].tolist()), sorted([poly(3.0), poly(1.0) - poly(0.5)]), atol=1e-4),
      sorted(areas(cs_)[grp(cs_, PRIM, "cap")].round(4).tolist()))
ring4 = ops.fuse(ops.merge(*[build.box((1, 1, 1), (x_, 0.0, z_)) for x_, z_ in ((0, 0), (1, 1), (2, 0), (1, -1))]), 1e-4)
c4r = cl(ring4, fill=True, use_out_groups=True, fill_group="cap")
check("  four boxes touching corner to corner in a ring (four cuts touching pairwise): total fill area 4, volume 4 × 0.5, none skipped",
      abs(areas(c4r)[grp(c4r, PRIM, "cap")].sum() - 4.0) < 1e-5 and abs(volume(c4r) - 2.0) < 1e-5
      and not c4r.has(DETAIL, "clip_fill_skipped"), (areas(c4r)[grp(c4r, PRIM, "cap")].round(3).tolist(), volume(c4r)))
plate = ops.merge(build.tube(3.0, 3.0, 2.0, 16, 2),
                  ops.reverse_prims(build.tube(0.5, 0.5, 2.0, 16, 2, center=(2.3, 0, 0))),
                  ops.reverse_prims(build.tube(0.5, 0.5, 2.0, 16, 2, center=(-2.3, 0, 0))))
c2h = cl(plate, fill=True, use_out_groups=True, fill_group="cap")
pp2 = c2h.prim_points(grp(c2h, PRIM, "cap")[0]).tolist()
dbl = set(np.nonzero(np.bincount(pp2) == 2)[0].tolist())
brs = {tuple(sorted((pp2[i], pp2[(i + 1) % len(pp2)]))) for i in range(len(pp2))
       if pp2[i] in dbl and pp2[(i + 1) % len(pp2)] in dbl}
check("  two holes in one outer contour: one face, area = big - 2 × small, 16 × 3 + 4 = 52 vertices",
      len(grp(c2h, PRIM, "cap")) == 1 and len(pp2) == 52
      and abs(areas(c2h)[grp(c2h, PRIM, "cap")[0]] - (poly(3.0) - 2 * poly(0.5))) < 1e-4)
check("  both bridges attach to their own closest pair of points (hole centers ±2.3, radius 0.5 -> 3 - 2.8 = 0.2 from the outer ring)",
      len(brs) == 2 and all(abs(np.linalg.norm(P_(c2h)[a_] - P_(c2h)[b_]) - 0.2) < 1e-4 for a_, b_ in brs),
      [float(np.linalg.norm(P_(c2h)[a_] - P_(c2h)[b_])) for a_, b_ in brs])
# A ring of edges on the plane, with prims on both sides below it (a downward cone + a downward tube wall sharing this ring): not an opening
rp = np.array([[1, 0, 0], [0, 0, 1], [-1, 0, 0], [0, 0, -1]], np.float32)
tent = Geometry.from_mesh(np.concatenate([rp, rp + [0, -2, 0], [[0, -1, 0]]]).astype(np.float32),
                          [[i, (i + 1) % 4, 8] for i in range(4)]
                          + [[i, 4 + i, 4 + (i + 1) % 4, (i + 1) % 4] for i in range(4)])
ct = cl(tent, fill=True)
check("  edges on the plane with (lower) prims on both sides: not an opening, not filled and not counted as skipped",
      ct.nprims == 8 and not ct.has(DETAIL, "clip_fill_skipped"))
two_t = ops.merge(to, build.tube(0.5, 0.5, 2.0, 16, 2, center=(5, 0, 0)))
c2 = cl(two_t, fill=True, use_out_groups=True, fill_group="cap")
check("  two separate cuts: each filled separately (areas of the two 16-gons respectively)",
      sorted(areas(c2)[grp(c2, PRIM, "cap")].round(5).tolist()) == sorted([round(poly(0.5), 5), round(poly(1.0), 5)]))
gopen = cl(grid3(), fill=True, dir_x=1.0, dir_y=0.0)
check("  an open patch has no closed cut after clipping: Fill adds nothing", gopen.nprims == cl(grid3(), dir_x=1.0, dir_y=0.0).nprims == 2)
# Where the plane already has a face, don't fill again
half = cl(fill=True)                                    # the already-capped lower half box, cap at y = 0
again = cl(half, fill=True, keep="both")
check("  the cut plane already has a face (clipping the same plane again): not filled twice", again.nprims == half.nprims)

sec("Clip:Orient Plane with / Snapping Tolerance / Clip Attribute")
tr = cl(orient="transform", rotate_z=-90.0, translate_x=0.25, fill=True)
dr = cl(dir_x=1.0, dir_y=0.0, use_origin=True, origin_x=0.25, fill=True)
check("Transform: Rotate Z -90 turns (0,1,0) into +X, Translate X 0.25 -> keeps x ≤ 0.25, volume 0.75",
      abs(P_(tr)[:, 0].max() - 0.25) < 1e-6 and abs(volume(tr) - 0.75) < 1e-6 and np.allclose(P_(tr), P_(dr), atol=1e-6))
check("  Direction mode doesn't read Translate / Rotate (negative control); Transform mode doesn't read Direction / Origin",
      digest(cl(rotate_z=-90.0, translate_x=0.25)) == digest(c0)
      and digest(cl(orient="transform", dir_x=1.0, dir_y=0.0, use_origin=True, origin_y=0.3)) == digest(c0))
check("  rotation order is X then Y: Rotate (90, 90, 0) turns +Y into +X (Houdini's Rx Ry Rz)",
      abs(P_(cl(orient="transform", rotate_x=90.0, rotate_y=90.0))[:, 0].max()) < 1e-6
      and abs(P_(cl(orient="transform", rotate_x=90.0, rotate_y=90.0))[:, 1].max() - 0.5) < 1e-6)
rx = P_(cl(orient="transform", rotate_x=90.0))
check("  Rotate X 90: +Y turns into +Z -> keeps z ≤ 0 (X / Y fields not swapped)",
      abs(rx[:, 2].max()) < 1e-6 and abs(rx[:, 1].max() - 0.5) < 1e-6 and abs(rx[:, 0].max() - 0.5) < 1e-6)
check("  Distance also moves along the normal in Transform mode", abs(P_(cl(orient="transform", translate_y=0.1, distance=0.2))[:, 1].max() - 0.3) < 1e-6)
s0 = cl(keep="above", distance=0.45)
s1 = cl(keep="above", distance=0.45, snap_tolerance=0.1)
check("Snapping Tolerance: plane y = 0.45, top face 0.05 away -- without snapping clipping gives 4 narrow strips + the top face",
      s0.nprims == 5 and np.isclose(P_(s0)[:, 1].max(), 0.5))
check("  tolerance 0.1: top face points snapped onto the plane, sides all below -> only the top face lying on the plane remains, y all 0.45",
      s1.nprims == 1 and s1.npoints == 4 and np.allclose(P_(s1)[:, 1], 0.45, atol=1e-6))
check("  tolerance 0.01 < 0.05: out of reach, same as no snapping", digest(cl(keep="above", distance=0.45, snap_tolerance=0.01)) == digest(s0))
check("  tolerance 0.06: just reaches 0.05 (compared with the tolerance itself, not half of it)",
      cl(keep="above", distance=0.45, snap_tolerance=0.06).nprims == 1)
twob = ops.merge(build.box(), build.box((1, 1, 1), (5.0, 0.0, 0.0)))
sg = cl(twob, keep="above", distance=0.45, snap_tolerance=0.1, group="0-5")
check("  only points of the prims being clipped move: Group = the first box, the second box's top face still at y = 0.5",
      np.isclose(P_(sg)[P_(sg)[:, 0] > 2][:, 1].max(), 0.5) and np.isclose(P_(sg)[P_(sg)[:, 0] < 2][:, 1].max(), 0.45)
      and sg.nprims == 7)
Ga = grid3()
Ga.set(POINT, "u", P_(Ga)[:, 2:3].astype(np.float32))    # single-component attribute = z
ua = cl(Ga, clip_attribute="u", dir_x=1.0, dir_y=0.0, distance=0.5)
check("Clip Attribute = u (single component, used as X): clipping u at 0.5 along +X -> geometrically z ≤ 0.5, x unchanged",
      np.isclose(P_(ua)[:, 2].max(), 0.5) and np.isclose(P_(ua)[:, 0].max(), 1.0) and np.isclose(P_(ua)[:, 0].min(), -1.0)
      and ua.nprims == 4 and np.isclose(float(np.asarray(ua.get(POINT, "u")).max()), 0.5))
check("  the same plane clipping by P gives x ≤ 0.5 (negative control)", np.isclose(P_(cl(Ga, dir_x=1.0, dir_y=0.0, distance=0.5))[:, 0].max(), 0.5))
Ga.set_string(POINT, "s", ["a"] * 9)
check("  attribute missing / is a string: raises", raises(lambda: cl(Ga, clip_attribute="nope"), "Clip Attribute")
      and raises(lambda: cl(Ga, clip_attribute="s"), "string attribute"))
ue = cl(Ga, clip_attribute="u", dir_x=1.0, dir_y=0.0, distance=0.5, use_out_groups=True)
check("  seam edge group also found by this attribute: the two at z = 0.5", len(egrp(ue, "clipseam")) == 2
      and all(np.allclose(P_(ue)[list(e)][:, 2], 0.5) for e in egrp(ue, "clipseam")))


# ═══════════════════════════════════════════════════════════════ Mirror
sec("Mirror:Group / Clip and Mirror / Orient / Distance / Reverse Normals")
Bx = build.box((1, 1, 1), (1.0, 0.0, 0.0))             # x ∈ [0.5, 1.5]
mi = lambda g=Bx, **kw: run("PCG_Mirror", geo=g, **kw)   # noqa: E731
bb = lambda g: np.round(np.concatenate([P_(g).min(0), P_(g).max(0)]), 5).tolist()   # noqa: E731
check("(baseline) mirror mode: mirrored about x = 0, x ∈ [-1.5, -0.5], volume +1", bb(mi())[0::3] == [-1.5, -0.5] and abs(volume(mi()) - 1) < 1e-6)
check("Distance 0.25: plane moved to x = 0.25 -> x ∈ [-1, 0]", bb(mi(distance=0.25))[0::3] == [-1.0, 0.0])
mt = mi(orient="transform", rotate_z=90.0, translate_y=1.0)
check("Transform: Rotate Z 90 turns (1,0,0) into +Y, through y = 1 -> y ∈ [1.5, 2.5], x unchanged",
      bb(mt) == [0.5, 1.5, -0.5, 1.5, 2.5, 0.5], bb(mt))
check("  Direction mode doesn't read Translate / Rotate; Transform mode doesn't read Origin / Direction (negative control)",
      digest(mi(rotate_z=90.0, translate_y=1.0)) == digest(mi())
      and digest(mi(orient="transform", origin_x=3.0, normal_x=0.0, normal_y=1.0)) == digest(mi()))
check("Reverse Normals off: mirrored copy doesn't flip winding -> volume -1 (faces inward); point positions identical",
      abs(volume(mi(reverse_normals=False)) + 1) < 1e-6 and np.allclose(P_(mi(reverse_normals=False)), P_(mi())))
m1 = mi(group="0", mirror_group="m")
check("Group = prim 0, mirror mode: output is only this prim's mirrored copy (4 points)",
      m1.nprims == 1 and m1.npoints == 4 and grp(m1, PRIM, "m") == [0]
      and np.allclose(np.sort(P_(m1), 0), np.sort(P_(Bx)[Bx.prim_points(0)] * [-1, 1, 1], 0)))
m2 = mi(group="0", mode="append", mirror_group="m", original_group="o")
check("  append mode: the whole original's 6 prims + this prim's mirror",
      m2.nprims == 7 and grp(m2, PRIM, "m") == [6] and grp(m2, PRIM, "o") == [0, 1, 2, 3, 4, 5] and m2.npoints == 12)
Bz = build.box((1, 1, 1), (0.0, 0.0, 1.0))
check("Transform: Rotate Y 90 turns (1,0,0) into -Z -> mirrored about z = 0 (X / Y fields not swapped)",
      bb(mi(Bz, orient="transform", rotate_y=90.0)) == [-0.5, -0.5, -1.5, 0.5, 0.5, -0.5])
By = build.box((1, 1, 1), (0.25, 0.0, 0.0))            # x ∈ [-0.25, 0.75], straddling the plane
cm = mi(By, operation="clip_and_mirror", mode="append")
check("Clip Primitives and Mirror (append): clip off the x < 0 part then mirror -> x ∈ [-0.75, 0.75], closed, volume 1.5",
      bb(cm)[0::3] == [-0.75, 0.75] and closed_manifold(cm) and abs(volume(cm) - 1.5) < 1e-6 and cm.nprims == 10,
      (bb(cm), volume(cm), cm.nprims))
ma = mi(By, mode="append")
check("  Mirror All (negative control): no clipping, original and mirror interpenetrate in the middle, 12 prims, x ∈ [-0.75, 0.75], volume 2",
      ma.nprims == 12 and abs(volume(ma) - 2.0) < 1e-6)
cmm = mi(By, operation="clip_and_mirror")
check("  mirror mode: only the mirrored copy of the clipped half, x ∈ [-0.75, 0], 5 prims",
      bb(cmm)[0::3] == [-0.75, 0.0] and cmm.nprims == 5)
mg = mi(By, group=str(0), mode="append", fuse_result=False)
check("  Mirror All + Group, no clipping: the box straddling the plane keeps its 6 prims + 1 mirrored prim, all of area 1",
      mg.nprims == 7 and np.allclose(areas(mg), 1.0, atol=1e-6))
Byg = By.copy()
side_x = [i for i in range(6) if np.ptp(P_(By)[By.prim_points(i)][:, 0]) > 0.5]     # the four prims spanning the plane
Byg.set_group(PRIM, "one", [side_x[0]])
cg_ = mi(Byg, operation="clip_and_mirror", mode="append", group="one", fuse_result=False)
check("  with Group: only the one prim in the group is clipped and mirrored; the other 5 prims unchanged (6 + 1 = 7 prims)",
      cg_.nprims == 7 and bb(cg_)[0::3] == [-0.75, 0.75]
      and sorted(np.round(areas(cg_), 4).tolist()) == [0.75, 0.75, 1.0, 1.0, 1.0, 1.0, 1.0])


# ═══════════════════════════════════════════════════════════════ Panel
sec("panel spec")
for k in ("PCG_GroupPromote", "PCG_Delete", "PCG_BlastByAttribute", "PCG_Blast", "PCG_Dissolve", "PCG_Normal",
          "PCG_Clip", "PCG_Mirror"):
    check(f"{k}: spec self-check passes", not PANEL.check_layout(k, M[k].INPUT_TYPES()), PANEL.check_layout(k, M[k].INPUT_TYPES()))
import comfyui_pcg.panel_specs as PS                     # noqa: E402
for k in ("PCG_GroupPromote", "PCG_Delete", "PCG_BlastByAttribute", "PCG_Dissolve", "PCG_Normal", "PCG_Clip", "PCG_Mirror"):
    sp = PS.SPECS[k]
    ws = [n for n in names(k) if n != "geo"]
    check(f"{k}: every widget is in order, nothing extra", sorted(sp["order"]) == sorted(ws), set(sp["order"]) ^ set(ws))
    bad = []
    for n in ws:
        spec = [v[n] for v in M[k].INPUT_TYPES().values() if n in v][0]
        if isinstance(spec[0], (list, tuple)):
            menu = sp["inputs"].get(n, {}).get("menu")
            if menu is None or sorted(menu) != sorted(spec[0]):
                bad.append(n)
    check(f"{k}: every token of every combo has a Houdini label", not bad, bad)

print(f"\n{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
