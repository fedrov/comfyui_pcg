"""
Node-layer contract -- run all 147 nodes through it.

This suite was **restored**: when the sandbox was recycled 23 old suites were lost (the code survived, only the tests weren't
delivered with it). Restoring them verbatim is impossible, but their protective effect can be restored, and the node layer is the
layer with the best protection per effort -- when a shared module breaks, the first and most common symptom is that some node's wrapper no longer fits.

Five things, each run against **all** nodes:

    1. Registration   class mappings / display names / RETURN_TYPES and RETURN_NAMES correspond one to one
    2. Signature      the parameter set of `run()` == the set declared by INPUT_TYPES (checked statically)
    3. Widget spec    defaults within min/max, seeds not named seed, no duplicate names
    4. Real run       feed defaults plus geometry/images "with every attribute", and either it runs,
                    or it raises an error that **explains itself**
    5. Pure function  upstream inputs are not modified; the same input run twice gives the same result

Item 2 is **static**, so it can check even nodes that "can't run" -- and "added a widget but forgot to
update run()'s parameters" is exactly the mistake that is easiest to make when changing a node and hardest to notice on the spot (in ComfyUI it shows up as
a `run() got an unexpected keyword argument`, and only when that node is actually executed).

In item 4, "raises an error that explains itself" is part of the criterion too: the exception type must be one raised
**deliberately** like ValueError / KeyError / RuntimeError, not IndexError /
TypeError / AttributeError -- the latter mean an unanticipated branch was hit.
"""
import os
import sys
# Package root: first search upwards from this file's location, otherwise fall back to the old sandbox path
_R = os.path.dirname(os.path.abspath(__file__))
for _c in (_R, os.path.dirname(_R), os.path.dirname(os.path.dirname(_R)),
           os.path.dirname(os.path.dirname(os.path.dirname(_R))),
           "/tmp/pcgpkg"):
    if os.path.isdir(os.path.join(_c, "comfyui_pcg")):
        sys.path.insert(0, _c)
        break
import inspect                                          # noqa: E402
import numpy as np                                      # noqa: E402
import fakecomfy                                        # noqa: F401,E402

from comfyui_pcg import nodes as N                       # noqa: E402
from comfyui_pcg import expr as EX, foreach as FE, framefor as FF  # noqa: E402
# viewport.py / spreadsheet.py register nodes too. For a while they weren't counted -- so
# the signatures, widget specs and purity of the three nodes Viewport / Display / GeoSpreadsheet
# were **checked by nobody**, and the icon test couldn't see them either (silently falling back to the category default).
from comfyui_pcg import viewport as VP, spreadsheet as SP  # noqa: E402
from comfyui_pcg.geo import build, ops as O, topology as TP         # noqa: E402
from comfyui_pcg.geo.core import (Geometry, POINT, VERTEX, PRIM,    # noqa: E402
                                  DETAIL)
from comfyui_pcg.geo.cop import generate as CG, CopImage            # noqa: E402

OK = []


def check(name, cond, extra=""):
    OK.append(bool(cond))
    tail = "" if (isinstance(extra, str) and not extra) else "   " + str(extra)
    print(("  PASS  " if cond else "  FAIL  ") + name + tail)


MAP = dict(N.NODE_CLASS_MAPPINGS)
NAMES = dict(N.NODE_DISPLAY_NAME_MAPPINGS)
for _m in (EX, FE, FF, VP, SP):
    MAP.update(_m.NODE_CLASS_MAPPINGS)
    NAMES.update(_m.NODE_DISPLAY_NAME_MAPPINGS)
ALL = sorted(MAP)


# ══════════════════════════════════════════════════════════════════ 1 Registration
print("═" * 28, f"Registration ({len(ALL)} nodes)")

check(f"node count ≥ 140", len(ALL) >= 140, len(ALL))
check("every class has a display name", set(MAP) == set(NAMES),
      sorted(set(MAP) ^ set(NAMES)) or "one to one")
check("class names all have the PCG_ prefix (the frontend attaches icons and sections by prefix)",
      all(k.startswith("PCG_") for k in ALL),
      [k for k in ALL if not k.startswith("PCG_")] or "0")
dup = [n for n in set(NAMES.values()) if list(NAMES.values()).count(n) > 1]
check("display names are unique (duplicates can't be told apart in the search box)", not dup, dup or "0")
check("display names all end with (PCG)",
      all(v.endswith("(PCG)") for v in NAMES.values()),
      [v for v in NAMES.values() if not v.endswith("(PCG)")] or "0")

for k in ALL:
    c = MAP[k]
    if not (hasattr(c, "INPUT_TYPES") and hasattr(c, "RETURN_TYPES")
            and hasattr(c, "FUNCTION") and hasattr(c, "CATEGORY")):
        check(f"{k} has all four attributes", False)
bad = [k for k in ALL if not all(hasattr(MAP[k], a) for a in
                                 ("INPUT_TYPES", "RETURN_TYPES", "FUNCTION",
                                  "CATEGORY"))]
check("every class has INPUT_TYPES / RETURN_TYPES / FUNCTION / CATEGORY",
      not bad, bad or "0")
bad = [k for k in ALL if not hasattr(MAP[k], MAP[k].FUNCTION)]
check("the method named by FUNCTION really exists", not bad, bad or "0")
bad = [k for k in ALL if hasattr(MAP[k], "RETURN_NAMES")
       and len(MAP[k].RETURN_NAMES) != len(MAP[k].RETURN_TYPES)]
check("RETURN_NAMES and RETURN_TYPES have the same length", not bad, bad or "0")
bad = [k for k in ALL if not str(MAP[k].CATEGORY).startswith("PCG")]
check("CATEGORY always starts with PCG", not bad, bad or "0")
cats = sorted({str(MAP[k].CATEGORY) for k in ALL})
check(f"spread over {len(cats)} categories", len(cats) >= 10, cats[:6])


# ══════════════════════════════════════════════════════ 2 run() signature consistency
print("═" * 28, "run() signature == INPUT_TYPES")

sig_bad = []
for k in ALL:
    c = MAP[k]
    t = c.INPUT_TYPES()
    decl = (set(t.get("required") or {}) | set(t.get("optional") or {})
            | set(t.get("hidden") or {}))
    # hidden inputs added by the preview layer are consumed by it; the original function should not be required to take them
    decl -= set(getattr(c, "_pcg_injected_hidden", ()))
    # **Must unwrap**. In production the execute function is wrapped as (*args, **kwargs);
    # without unwrapping, `star` below is always true and missing always empty -- this whole criterion would idle,
    # and it is exactly the one meant to catch "added a widget but forgot to add the run() parameter".
    ps = [p for n_, p in
          inspect.signature(inspect.unwrap(
              getattr(c, c.FUNCTION))).parameters.items()
          if n_ != "self"]
    star = any(p.kind == p.VAR_KEYWORD for p in ps)
    have = {p.name for p in ps}
    missing = set() if star else decl - have
    # A parameter that is **required** but not declared in INPUT_TYPES -> this node can never be called
    extra = {p.name for p in ps
             if p.name not in decl and p.default is p.empty
             and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)}
    if missing or extra:
        sig_bad.append((k, sorted(missing), sorted(extra)))
check("every node's run() accepts all inputs declared by INPUT_TYPES",
      not sig_bad, sig_bad or "147/147")
check("  and has no parameter that is \"not declared yet required\" (such a node can never be called)",
      not any(e for _, _, e in sig_bad))
# Negative control: this criterion really does catch something
opt_bad = []
for k in ALL:
    t = MAP[k].INPUT_TYPES()
    ps = inspect.signature(inspect.unwrap(
        getattr(MAP[k], MAP[k].FUNCTION))).parameters
    for nm in (t.get("optional") or {}):
        if nm in ps and ps[nm].default is inspect.Parameter.empty:
            opt_bad.append(f"{k}.{nm}")
check("optional inputs must have defaults in run() (they aren't passed when unconnected)",
      not opt_bad, opt_bad or "0")


# ═════════════════════════════════════════════════════════════ 3 Widget spec
print("═" * 28, "Widget spec")

rng_bad, int_bad, dup_bad, seed_bad, combo_bad = [], [], [], [], []
n_widget = 0
for k in ALL:
    t = MAP[k].INPUT_TYPES()
    seen = set()
    for sec in ("required", "optional"):
        for nm, spec in (t.get(sec) or {}).items():
            if nm in seen:
                dup_bad.append(f"{k}.{nm}")
            seen.add(nm)
            ty = spec[0]
            o = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if not isinstance(ty, str):
                n_widget += 1
                if not len(ty):
                    combo_bad.append(f"{k}.{nm}")
                elif "default" in o and o["default"] not in ty:
                    combo_bad.append(f"{k}.{nm} (default not among the options)")
                continue
            if ty in ("INT", "FLOAT"):
                n_widget += 1
                d = o.get("default", 0)
                lo, hi = o.get("min", -np.inf), o.get("max", np.inf)
                if not (lo <= d <= hi):
                    rng_bad.append(f"{k}.{nm}={d} not in [{lo}, {hi}]")
                if ty == "INT" and not isinstance(d, int):
                    int_bad.append(f"{k}.{nm}={d!r}")
            if ty == "INT" and nm == "seed":
                seed_bad.append(k)
check(f"scanned {n_widget} numeric/dropdown widgets", n_widget > 800, n_widget)
check("defaults all within min/max", not rng_bad, rng_bad[:4] or "0")
check("INT defaults really are int (a float default loses its decimals in the frontend)",
      not int_bad, int_bad[:4] or "0")
check("no duplicate input names within a node", not dup_bad, dup_bad[:4] or "0")
check("dropdown options non-empty, default among the options", not combo_bad, combo_bad[:4] or "0")
# Seeds must not be named seed: ComfyUI automatically attaches control_after_generate to an INT with that name,
# defaulting to randomize, so the value changes on every run -- procedural geometry needs reproducibility
check("**random seeds are not named `seed`** (named seed they get randomize attached automatically, results not reproducible)",
      not seed_bad, seed_bad or "0")
n_rand = sum(1 for k in ALL
             if "rand_seed" in (MAP[k].INPUT_TYPES().get("required") or {}))
check(f"  {n_rand} nodes actually use rand_seed", n_rand >= 8, n_rand)


# ═══════════════════════════════════════════════════════════════ 4 Real run
print("═" * 28, "Real run with defaults")


def rich_geo():
    """
    Geometry "with everything": closed (has volume), with normals, uv, colour, pscale, name /
    piece / class, and point, prim and vertex groups. Most nodes' default parameters point at these names;
    fed a blank grid, half of the nodes would raise "attribute not found" -- that tests nothing.
    """
    g = O.compute_normals(build.box(divisions=(3, 3, 3)), add_to="point")
    g = TP.connectivity(g, PRIM, "class")
    n = g.npoints
    r = np.random.default_rng(0)
    g.set(POINT, "Cd", r.random((n, 3)).astype(np.float32))
    g.set(POINT, "pscale", np.full((n, 1), 0.2, np.float32))
    g.set(POINT, "old", np.arange(n, dtype=np.float32)[:, None])
    g.set(POINT, "sourceprim", np.zeros((n, 1), np.int32))
    g.set(POINT, "sourceprimuv", np.full((n, 2), 0.3, np.float32))
    g.set(VERTEX, "uv",
          np.tile([0.25, 0.75], (g.nvertices, 1)).astype(np.float32))
    g.set(PRIM, "name", np.zeros((g.nprims, 1), np.float32))
    g.set(PRIM, "piece", np.zeros((g.nprims, 1), np.float32))
    g.set(DETAIL, "d", np.array([[1.0]], np.float32))
    g.set_group(POINT, "group1", np.arange(n) % 2 == 0)
    g.set_group(PRIM, "group1", np.arange(g.nprims) % 2 == 0)
    g.set_group(PRIM, "interior", np.arange(g.nprims) < 2)
    g.set_group(VERTEX, "group1", np.arange(g.nvertices) % 3 == 0)
    return g


def rich_cop():
    c = CG.shape(32, 32, "circle", radius=0.3)
    r = np.random.default_rng(1)
    for nm, ch in (("C", 3), ("depth", 1), ("N", 3), ("id", 1), ("Csum", 3),
                   ("Wsum", 1), ("views", 1), ("motion", 2),
                   ("motion_bwd", 2), ("lum", 1),
                   # pcg61: default layer names of the UV family and Triplanar (Render Pass also outputs
                   # these two layers), included so they can run with defaults
                   ("uv", 2), ("P", 3)):
        c.set(nm, r.random((32, 32, ch)).astype(np.float32))
    return c


GEO, COP = rich_geo(), rich_cop()


def rich_vol():
    """
    pcg106: geometry for the Volume / VDB nodes (category PCG/volume): the rich mesh (points with pscale / Cd / N, so the
    point- and curve-driven nodes have input) plus volumes: an SDF VDB "surface" with a narrow band, a fog VDB
    "density", a vector VDB "vel" and its dense components vel.x / .y / .z.
    """
    from comfyui_pcg.geo import vdb as V, vdbsdf as VS
    sdf = VS.platonic("sphere", 0.6, (0, 0, 0), 0.1)
    fog = VS.platonic("sphere", 0.6, (0, 0, 0), 0.1, fog=True)
    vel = V.make((10, 10, 10), (1.6, 1.6, 1.6), (0, 0, 0), (1.0, 0.0, 0.0), V.CLASS_NONE, "vel",
                 True, 0.0, True)
    comps = [V.make((10, 10, 10), (1.6, 1.6, 1.6), (0, 0, 0), c, V.CLASS_NONE, f"vel.{a}", False)
             for a, c in zip("xyz", (1.0, 0.0, 0.0))]
    return O.merge(GEO, sdf, fog, vel, *comps)


VOL = rich_vol()
IMG = np.tile(np.linspace(0, 1, 32, dtype=np.float32)[None, :, None],
              (32, 1, 3))[None]


def _default(spec):
    ty = spec[0]
    o = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if not isinstance(ty, str):
        return ty[0] if len(ty) else ""
    if ty == "GEOMETRY":
        return GEO
    if ty == "COPIMAGE":
        return COP
    if "default" in o:
        return o["default"]
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(ty)


def _mk(key, **ov):
    c = MAP[key]
    kw = {nm: _default(s)
          for nm, s in (c.INPUT_TYPES().get("required") or {}).items()}
    kw.update(ov)
    return getattr(c(), c.FUNCTION)(**kw)


CAM = _mk("PCG_Camera")[0]
CAMSEQ = _mk("PCG_CameraPath")[0]
SUPPLY = {"PCGCAM": CAM, "PCGCAMSEQ": CAMSEQ, "IMAGE": IMG,
          "COPSEQUENCE": [COP, COP], "GEOSEQUENCE": [GEO, GEO],
          "MASK": IMG[..., 0]}
# The state type of loop blocks can only be produced by the paired Begin, and unrolling the graph needs an executor -- that is
# verified in test_framefor.py; only static checks here
LOOP_TYPES = {"PCG_LOOP", "PCG_LOOPACC", "PCG_FRAMELOOP", "PCG_FRAMEACC"}
# These two nodes require "sequence length / texture resolution must match", so the canned inputs must be set up accordingly
OVERRIDE = {"PCG_SequenceMotion": {"cams": CAMSEQ[:2]},
            "PCG_UVBackproject": {"accum": None},
            # pcg100: kernel_cop is an optional kernel image, the canned COP's C has 3 channels --
            # the default Layers (empty = all layers) include 1 / 2 channel layers that don't fit the kernel.
            # Convolve only the C layer, so the "kernel image connected" path also gets run by defaults
            "PCG_COPConvolve": {"layers": "C"},
            # pcg106: the canned volume geometry has no volumes named background / foreground / mask and its points
            # carry no density / divergence attribute -- point the parameters at what exists
            "PCG_VolumePatch": {"background": "surface", "foreground": "density", "mask": "density"},
            "PCG_VolumeFromAttrib": {"attribute": "pscale"},
            "PCG_VolumeVelocityFromSurface": {"divergence_attribute": "pscale"}}

DELIBERATE = (ValueError, KeyError, RuntimeError, MemoryError,
              NotImplementedError)
WANT = {"GEOMETRY": Geometry, "COPIMAGE": CopImage, "INT": int,
        "FLOAT": float, "STRING": str}

ran, refused, crashed, shape_bad, static_only = [], [], [], [], []
for k in ALL:
    c = MAP[k]
    t = c.INPUT_TYPES()
    req = t.get("required") or {}
    tys = {(s[0] if isinstance(s[0], str) else "COMBO") for s in req.values()}
    if tys & LOOP_TYPES:
        static_only.append(k)
        continue
    kw = {}
    vol_node = getattr(c, "CATEGORY", "") == "PCG/volume"
    for nm, s in req.items():
        ty = s[0] if isinstance(s[0], str) else "COMBO"
        kw[nm] = SUPPLY[ty] if ty in SUPPLY else (VOL if vol_node and ty == "GEOMETRY" else _default(s))
    for nm, s in (t.get("optional") or {}).items():
        ty = s[0] if isinstance(s[0], str) else "COMBO"
        if ty in SUPPLY:
            kw[nm] = SUPPLY[ty]
        elif ty in ("GEOMETRY", "COPIMAGE"):
            kw[nm] = VOL if vol_node and ty == "GEOMETRY" else _default(s)
    kw.update(OVERRIDE.get(k, {}))
    kw = {a: b for a, b in kw.items() if b is not None or a not in OVERRIDE
          .get(k, {})}
    try:
        out = getattr(c(), c.FUNCTION)(**kw)
    except DELIBERATE as ex:
        # A deliberate refusal also counts as a pass -- but the error message must explain itself
        if len(str(ex)) < 15:
            crashed.append((k, f"{type(ex).__name__} message too short: {ex}"))
        else:
            refused.append((k, str(ex).split("\n")[0][:60]))
        continue
    except Exception as ex:
        crashed.append((k, f"{type(ex).__name__}: {str(ex)[:70]}"))
        continue
    ran.append(k)
    # In production every node is wrapped by attach_group_reporting / attach_cop_preview,
    # and returns {"ui": ..., "result": (...)}.
    #
    # This used to say `if isinstance(out, dict): continue` -- meaning "skip node
    # expansions". But after wrapping **almost every node** returns a dict, so the whole block below
    # checking "are output count and types right" silently idled, and not one of 151 nodes was checked.
    # Now only real expansions (with "expand") are let through; everything else unpacks result and is checked.
    if isinstance(out, dict):
        if "expand" in out:                         # a real node expansion
            continue
        if "result" not in out:
            shape_bad.append((k, "returns a dict with neither result nor expand"))
            continue
        out = out["result"]
    if not isinstance(out, tuple):
        shape_bad.append((k, f"does not return a tuple: {type(out).__name__}"))
        continue
    if len(out) != len(c.RETURN_TYPES):
        shape_bad.append((k, f"{len(out)} outputs vs declared "
                             f"{len(c.RETURN_TYPES)}"))
        continue
    for v, ty in zip(out, c.RETURN_TYPES):
        if ty in WANT and v is not None and not isinstance(v, WANT[ty]):
            shape_bad.append((k, f"{ty} port gives a {type(v).__name__}"))

check(f"{len(ran)} nodes run directly with defaults", len(ran) >= 130, len(ran))
# The **list** of refusals is pinned too: if a node that used to run starts refusing (or vice versa), that's a regression.
# These genuinely need more context to run; refusing under default parameters is the **correct** behaviour:
#   AttribFade  no gradient without a start group
#   GroupExpand an empty Output Group means rewrite in place, so Group must be a plain group name
#   UVFlatten   a closed surface has no isometric planar unfolding (Theorema Egregium), seams must be given first
#   ImportMesh  the default file name mesh.glb of course doesn't exist. **Refusing is right**, and the error it reports
#               is exactly the one that matters most for this node (listing every path searched) --
#               "relative to what, exactly" is the most common sticking point for this kind of node
#   RegionalPrompt  the default Regions name the splat_* layers -- not in the default COP,
#               it raises and lists the existing layers (pcg56); and without a real CLIP it can't encode anyway
#   COPPremultiply  the default C layer is RGB with no alpha -- it raises asking for an Alpha Layer,
#               rather than pretending alpha = 1 and doing nothing (pcg58)
#   COPDropShadow   likewise: the shadow's shape is the alpha, no alpha means no shadow (pcg58)
#   COPSolvePoisson / COPSelect / COPFlowSolve  the default layer names rhs / A, B / vel are
#               the semantic names of these solvers, not in the test COP -- raising and listing the existing layers
#               beats quietly solving a meaningless equation with C (pcg60)
EXPECT_REFUSE = {"PCG_AttribFade", "PCG_GroupExpand", "PCG_UVFlatten",
                 "PCG_ImportMesh", "PCG_RegionalPrompt", "PCG_COPPremultiply",
                 "PCG_COPDropShadow", "PCG_COPSolvePoisson", "PCG_COPSelect",
                 "PCG_COPFlowSolve",
                 # pcg100 c7: Heat Distort by Layer's noise layer is a required input (in Houdini too),
                 # the default layer name noise isn't in the test COP -- it raises and lists the existing layers
                 "PCG_COPHeatDistortByLayer",
                 # pcg67: start / end points must be specified by the user, there is no sensible default
                 "PCG_FindShortestPath", "PCG_GroupFindPath",
                 # pcg68: needs a string attribute / an edge group, not on the default test geometry
                 "PCG_AttribStringEdit", "PCG_EdgeCollapse",
                 # pcg70: the lattice must be made by Lattice From Bound (with lattice_div), the bridge needs two
                 # groups, template points need name -- none of which the generic test geometry has
                 "PCG_Lattice", "PCG_PolyBridge", "PCG_TransformPieces",
                 # pcg71: the volume input needs real volume prims (the test geometry is a mesh)
                 "PCG_AttribFromVolume",
                 # pcg72: volume editing nodes, the input needs volume prims
                 "PCG_VolumeBlur", "PCG_VolumeMix", "PCG_VolumeResample",
                 "PCG_VolumeReshapeSDF", "PCG_VolumeWrangle",
                 "PCG_VolumeSmoothSDF",          # pcg100 s9
                 # pcg100 s9: by default both inputs are the same closed mesh; in Surface mode the cutting surface's average normal is 0, refused
                 "PCG_BooleanFracture",
                 "PCG_FileMerge",                 # pcg100 s9: the default file geo.$SLICE.npz doesn't exist
                 # pcg74: edge-chain nodes need an edge group, PolyCut a point group, Rewire an
                 # integer attribute
                 "PCG_EdgeEqualize", "PCG_EdgeStraighten", "PCG_CircleFromEdges",
                 "PCG_PolyCut", "PCG_RewireVertices",
                 # pcg75: velocity mode needs the point attribute v
                 "PCG_BallisticPath",
                 # pcg77: tile assembly needs a sequence split by Tile Split with the same rows and columns
                 "PCG_COPTileSplice",
                 # pcg79: needs the user's own group names / cut positions / matrix attributes, not on the test geometry
                 "PCG_GroupCombine", "PCG_PolySplit", "PCG_TransformByAttrib",
                 # pcg82: Soft Peak needs a point group, Edge Transport's network needs roots
                 "PCG_SoftPeak", "PCG_EdgeTransport",
                 # pcg84: the instance table's asset column reads name on points by default, not on the test point cloud --
                 # raising about the missing attribute beats writing a column of empty asset names
                 "PCG_ExportInstances",
                 # pcg100 s8: UV Pelt, like UV Flatten, needs seams cut on the closed test geometry first
                 "PCG_UVPelt",
                 # pcg100 c8: Geometry to Layer / Integrate Volume take volume prims, the test geometry is a mesh
                 "PCG_COPGeoToLayer", "PCG_COPIntegrateVolume"}
try:
    import torch                                        # noqa: F401
except ImportError:
    # Without torch Preview Image can only refuse -- and it refuses clearly (see the previous item)
    EXPECT_REFUSE.add("PCG_PreviewImage")
check("the deliberate refusals are **exactly** the known ones needing more context, not one more or less",
      {k for k, _ in refused} == EXPECT_REFUSE,
      sorted({k for k, _ in refused} ^ EXPECT_REFUSE) or
      sorted(EXPECT_REFUSE))
check("  every refusal carries a long enough explanation (≥15 chars, shorter ones count as crashes)",
      all(len(m) >= 15 for _, m in refused),
      [f"{k}:{m[:30]}" for k, m in refused])
check("not a single node **crashes** (IndexError / TypeError and the like)",
      not crashed, crashed or "0")
check("output counts and types match RETURN_TYPES",
      not shape_bad, shape_bad[:4] or "0")
check(f"the {len(static_only)} static-only ones are loop blocks (their state only comes from the paired Begin)",
      set(static_only) <= {"PCG_ForEachEnd", "PCG_ForEachFrameEnd"},
      static_only)
check("ran + refused + static = all nodes",
      len(ran) + len(refused) + len(static_only) == len(ALL),
      f"{len(ran)}+{len(refused)}+{len(static_only)} vs {len(ALL)}")


# ═════════════════════════════════════════════════════════════ 5 Purity
print("═" * 28, "Purity")


def snap(g):
    """A fingerprint of the geometry. It must be identical after a node runs."""
    parts = [g.vertex_point.tobytes(), g.prim_offset.tobytes(),
             g.prim_closed.tobytes(), str(g.npoints).encode()]
    for cls in (POINT, VERTEX, PRIM, DETAIL):
        for nm in sorted(g.attribs[cls]):
            parts.append(nm.encode())
            parts.append(np.asarray(g.attribs[cls][nm]).tobytes())
    for cls in (POINT, VERTEX, PRIM):
        for nm in sorted(g.groups[cls]):
            parts.append(nm.encode())
            parts.append(np.asarray(g.groups[cls][nm]).tobytes())
    return b"|".join(parts)


def csnap(c):
    return b"|".join([nm.encode() + np.asarray(c.need(nm)).tobytes()
                      for nm in sorted(c.names)])


before_g, before_c = snap(GEO), csnap(COP)
mutated = []
for k in ran:
    c = MAP[k]
    t = c.INPUT_TYPES()
    req = t.get("required") or {}
    kw = {}
    for nm, s in req.items():
        ty = s[0] if isinstance(s[0], str) else "COMBO"
        kw[nm] = SUPPLY[ty] if ty in SUPPLY else _default(s)
    for nm, s in (t.get("optional") or {}).items():
        ty = s[0] if isinstance(s[0], str) else "COMBO"
        if ty in ("GEOMETRY", "COPIMAGE"):
            kw[nm] = _default(s)
    kw.update(OVERRIDE.get(k, {}))
    try:
        getattr(c(), c.FUNCTION)(**kw)
    except Exception:
        continue
    if snap(GEO) != before_g:
        mutated.append(k + " (modified geometry)")
        before_g = snap(GEO)
    if csnap(COP) != before_c:
        mutated.append(k + " (modified image)")
        before_c = csnap(COP)
check("**no node modifies its upstream inputs** (outputs are cached and fed to several downstream nodes; modifying them is a ghost bug)",
      not mutated, mutated or "0")

# Repeatable: the same input run twice gives bit-identical geometry output.
# Nodes with random seeds must too -- a fixed seed should reproduce
unstable = []
for k in ran:
    c = MAP[k]
    if "GEOMETRY" not in c.RETURN_TYPES:
        continue
    t = c.INPUT_TYPES()
    kw = {}
    for nm, s in (t.get("required") or {}).items():
        ty = s[0] if isinstance(s[0], str) else "COMBO"
        kw[nm] = SUPPLY[ty] if ty in SUPPLY else _default(s)
    kw.update(OVERRIDE.get(k, {}))
    try:
        a = getattr(c(), c.FUNCTION)(**kw)
        b = getattr(c(), c.FUNCTION)(**kw)
    except Exception:
        continue
    for x, y, ty in zip(a, b, c.RETURN_TYPES):
        if ty == "GEOMETRY" and isinstance(x, Geometry) and snap(x) != snap(y):
            unstable.append(k)
check("same input run twice gives **bit-identical** geometry output (a fixed seed should reproduce)",
      not unstable, unstable or "0")

# Attribute arrays in the output must be read-only -- in-place modification downstream would pollute upstream caches
writable = []
for k in ran[:60]:
    c = MAP[k]
    t = c.INPUT_TYPES()
    kw = {}
    for nm, s in (t.get("required") or {}).items():
        ty = s[0] if isinstance(s[0], str) else "COMBO"
        kw[nm] = SUPPLY[ty] if ty in SUPPLY else _default(s)
    kw.update(OVERRIDE.get(k, {}))
    try:
        out = getattr(c(), c.FUNCTION)(**kw)
    except Exception:
        continue
    for v in (out if isinstance(out, tuple) else ()):
        if not isinstance(v, Geometry):
            continue
        for cls in (POINT, VERTEX, PRIM, DETAIL):
            for nm, arr in v.attribs[cls].items():
                if isinstance(arr, np.ndarray) and arr.flags.writeable:
                    writable.append(f"{k}.{cls}.{nm}")
check("attribute arrays of output geometry are all **read-only** (in-place modification downstream would pollute upstream caches)",
      not writable, writable[:4] or "0")


# ══════════════════════════════════════════════════════ 6 The two wrapper layers
# comfyui_pcg/__init__.py wraps the execute function of **every** node twice:
#   attach_group_reporting  reports group names / attribute names in the output geometry to the frontend
#   attach_cop_preview      attaches the in-node thumbnail to COP-related nodes
#
# These two layers were at one point **completely untested**: in the dev sandbox comfyui_pcg/__init__.py was a stub
# that bypassed them entirely, so the whole suite ran against unwrapped nodes. Laying it out like the real
# installation blew up a real bug -- see the second item below.
print("═" * 28, "The two wrapper layers")

import comfyui_pcg as _PKG                                     # noqa: E402
from comfyui_pcg.groups_report import attach_group_reporting    # noqa: E402,F401
from comfyui_pcg.coppreview import attach_cop_preview           # noqa: E402

# First confirm we **really** are testing the production configuration. Under the stub __init__ this goes red --
# that's the guard rail: tests must not be made green by "swapping __init__ for a stub".
_wrapped = sum(1 for c in MAP.values()
               if getattr(getattr(c, getattr(c, "FUNCTION", ""), None),
                          "_pcg_group_reporting", False))
check("running the **production configuration**: node execute functions really are wrapped"
      " (the stub __init__ turns this red)",
      _wrapped > 100, f"{_wrapped}/{len(MAP)} wrapped")
check("  the wrapped mapping is the same object __init__ exports",
      set(_PKG.NODE_CLASS_MAPPINGS) >= set(MAP),
      len(_PKG.NODE_CLASS_MAPPINGS))


# ── attach_cop_preview must not swallow the node's own unique_id ─────────────────────
# This is a **bug that really existed**: wrapped() unconditionally did kwargs.pop("unique_id"),
# taking the node id out of the arguments before calling the original function. Fine for nodes that don't need the node id and only got
# a hidden added by the preview layer; but PCG_ForEachFrameEnd has a cop input so it gets wrapped,
# and it **needs** the node id **itself** (to locate the end of the loop body). With it stolen it receives None,
# `expand_body(str(None), ...)` looks for a node called 'None' in the graph,
# and raises KeyError -- meaning the For-Each Frame Block was entirely broken in a real ComfyUI.
class _NeedsUid:
    """A node that declares unique_id itself and also takes COPIMAGE."""
    seen = []

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"img": ("COPIMAGE",)},
                "hidden": {"unique_id": "UNIQUE_ID"}}
    RETURN_TYPES = ("COPIMAGE",)
    FUNCTION = "run"

    def run(self, img, unique_id=None):
        _NeedsUid.seen.append(unique_id)
        return (img,)


class _NoUid:
    """Doesn't declare unique_id, only gets one forcibly added by the preview layer."""
    seen = []

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"img": ("COPIMAGE",)}}
    RETURN_TYPES = ("COPIMAGE",)
    FUNCTION = "run"

    def run(self, img):
        _NoUid.seen.append(True)
        return (img,)


attach_cop_preview({"a": _NeedsUid, "b": _NoUid})
_NeedsUid().run(img=COP, unique_id="probe-7")
check("attach_cop_preview: passes unique_id through **unchanged** when the node declares it itself",
      _NeedsUid.seen == ["probe-7"], _NeedsUid.seen)
_NoUid().run(img=COP, unique_id="probe-9")
check("  when the node doesn't declare it, the preview layer consumes it (otherwise the original function gets an unexpected keyword argument)",
      _NoUid.seen == [True], _NoUid.seen)
check("  in both cases hidden.unique_id is added (without it the frontend can't get the node id)",
      _NeedsUid.INPUT_TYPES()["hidden"]["unique_id"] == "UNIQUE_ID"
      and _NoUid.INPUT_TYPES()["hidden"]["unique_id"] == "UNIQUE_ID")
check("  idempotent: wrapping again doesn't stack",
      (lambda: (attach_cop_preview({"a": _NeedsUid}),
                _NeedsUid.seen.clear(),
                _NeedsUid().run(img=COP, unique_id="again"),
                _NeedsUid.seen == ["again"])[-1])(), _NeedsUid.seen)

# Pin the node that actually broke with its own check
_end = MAP.get("PCG_ForEachFrameEnd")
check("PCG_ForEachFrameEnd's unique_id is not swallowed by the preview layer (regression)",
      "unique_id" in (_end.INPUT_TYPES().get("hidden") or {}),
      sorted((_end.INPUT_TYPES().get("hidden") or {})))


# ── Return shape of attach_group_reporting ──────────────────────────────────
class _Geo1:
    RETURN_TYPES = ("GEOMETRY",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    def run(self):
        return (GEO,)


attach_group_reporting({"g": _Geo1})
_out = _Geo1().run()
check("attach_group_reporting: tuple returns are wrapped as {'ui':..., 'result':...}",
      isinstance(_out, dict) and "result" in _out and "ui" in _out,
      list(_out) if isinstance(_out, dict) else type(_out).__name__)
check("  result holds the output tuple **unchanged**, same count",
      isinstance(_out.get("result"), tuple)
      and len(_out["result"]) == len(_Geo1.RETURN_TYPES)
      and _out["result"][0] is GEO)
check("  ui reports group names and attribute names (the frontend's group dropdown relies on it)",
      "pcg_groups" in _out["ui"] or "pcg_attribs" in _out["ui"],
      list(_out["ui"]))
check("  idempotent: wrapping again doesn't nest result another level",
      (lambda: (attach_group_reporting({"g": _Geo1}),
                isinstance(_Geo1().run().get("result"), tuple))[-1])())

# fakecomfy.unwrap is the single entry point for every suite to unpack such return values; it must accept both
check("fakecomfy.unwrap unpacks a dict, and passes plain tuples through unchanged",
      fakecomfy.unwrap({"ui": {}, "result": (1, 2)}) == (1, 2)
      and fakecomfy.unwrap((3, 4)) == (3, 4)
      and fakecomfy.unwrap({"ui": {}}) == ())

print()
print(f"{sum(OK)}/{len(OK)} passed")
sys.exit(0 if all(OK) else 1)
