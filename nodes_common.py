"""
The layer shared by the node files: custom socket types (GEOMETRY / COPIMAGE / ...), small
helpers for widget specs (_f / _i / _sec / _names / _group / _dev), and alias imports of all geo modules.

All of this used to sit at the top of nodes.py. Once nodes.py grew past 8000 lines it was split into:

    nodes_common.py   this file (types, widget helpers, module aliases)
    nodes.py          SOP and remaining nodes + the master registry (public entry point unchanged)
    nodes_cop.py      COP nodes from before pcg57 (Noise / Shape / heightfield / terrain / ...)
    nodes_cop2.py     the batch from pcg58 on that fills out Copernicus
    nodes_sop2.py     the batch from pcg67 on that fills SOP gaps (mapping table: tests/sop_map.py)

**nodes.py still re-exports every name from here unchanged** -- old code and tests that write
`from .nodes import GEO, _group` need no change. New code imports from here directly,
not from nodes.py: nodes.py imports nodes_cop / nodes_cop2 at its end,
so importing the other way round would create a cycle.
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

from . import expr as _ex

from .geo import (Geometry, POINT, VERTEX, PRIM, DETAIL,
                  build, ops, wrangle, convert, groups, topology, volume,
                  addsop, facet, divide, fusesop, clip as _clip,
                  scatter as _scat, matchsize, centroid,
                  copyto as _cpt, xfer as _xfr, raysop as _ray,
                  polyexpand2d as _pex, refine as _ref, pointjitter as _pj,
                  convertline as _cvl, attribnoise as _an, measure as _ms,
                  attribops as _ao, attribrandomize as _arn, attribblur as _ablr,
                  attribadjust as _aa, deletesop as _del,
                  groupexpand as _gex, subdivide as _sub,
                  dissolve as _dsv, edgedivide as _edv,
                  polyreduce as _prd,
                  uvproject as _uvp, uvlayout as _uvl,
                  uvflatten as _uvf, uvseams as _uvs,
                  polyfill as _pfl, voronoi as _vor,
                  inside as _ins, volscatter as _vsc,
                  cluster as _clu, hull as _hul, bound as _bnd,
                  convexdecomp as _cdc, fracturedetail as _fdt,
                  peak as _pk, mirror as _mir, explode as _exp,
                  cop as _cop, render as _rnd,
                  frommap as _fmp, trace as _trc,
                  backproject as _bpj, sequence as _seq,
                  promote as _prom, ramp as _rmp, joinsop as _jn,
                  deform as _dfm, ends as _end,
                  triangulate2d as _t2d, voronoi2d as _v2d,
                  geocache as _gcache, channel as _chn,
                  camproject as _cpj, structured as _stx,
                  metrics as _mtr,
                  meshio as _mio,
                  timeops as _tmo,
                  boolean as _bool)

GEO = "GEOMETRY"
# Copernicus image type. **Not ComfyUI's IMAGE**: that is a (B,H,W,3) 0-1
# tensor and cannot hold multiple layers, values outside 0-1 or arbitrary channel counts. Interop goes through COP Import / Export
COP = "COPIMAGE"
# The camera is its own type: Render Pass and UV Backproject must use the **same** camera;
# filling in the parameters twice on both sides will drift sooner or later, and the symptom is the whole texture being offset
CAM = "PCGCAM"
# Sequence types. A plain Python list can travel between nodes without ComfyUI supporting anything --
# the type system only compares strings, so "a list of cameras" and "a list of images" just need their own names
CAMSEQ = "PCGCAMSEQ"
COPSEQ = "COPSEQUENCE"
# Geometry sequence. Main output of For-Each Frame End -- with it, motion vectors can capture
# deformation and not just camera motion
GEOSEQ = "GEOSEQUENCE"
_cgen, _cflt, _ccmp, _cbrg = (_cop.generate, _cop.filters,
                              _cop.composite, _cop.bridge)
_cbk = _cop.backend
_cctl = _cop.control
_chm = _cop.heightmap
_cero = _cop.erosion
_can = _cop.analysis
_ctr = _cop.terrain
_cflw = _cop.flow
_cspl = _cop.splat
_creg = _cop.regions
_clift = _cop.lift
_chyd = _cop.hydro
_ctrn, _clev, _cmrp, _csdf = (_cop.transform, _cop.levels,
                              _cop.morph, _cop.sdf)


def _dev(default="auto"):
    """Backend choice for COP generators. auto = use the GPU if there is one and the image is large enough."""
    order = [default] + [d for d in _cbk.DEVICES if d != default]
    return (order, {"tooltip":
                    "auto=GPU only with CUDA and pixel count >= 256²; "
                    "exact=numpy float64, bit-identical to the geometry side but slowest"})


def _compute():
    """
    "Where to compute" for heavy iterative nodes (reaction-diffusion, ripple, fluid, TV denoise, directional blur, Noise Extra, thermal /
    hydraulic erosion). Not the same thing as a generator's Device: Device decides where the image **lives**,
    Compute decides where this one node **computes** -- the output always goes back to the input's original backend.
    Placed last in the widget list: old workflows lack this entry, take the default on load, and nothing else shifts.
    """
    return (list(_cop.accel.COMPUTES), {"tooltip":
            "auto=compute where the image is if it is on torch; otherwise, with CUDA and pixel count >= 256², move it "
            "to the GPU, compute, and move it back (result matches numpy); cpu=always numpy (yields to the diffusion model "
            "when VRAM is tight); cuda=use it if available"})


CAT = "PCG"

F = ("FLOAT", {"default": 0.0, "min": -1e6, "max": 1e6, "step": 0.01})
I = ("INT", {"default": 10, "min": 0, "max": 1 << 24})


def _f(default=0.0, mn=-1e6, mx=1e6, step=0.01):
    return ("FLOAT", {"default": default, "min": mn, "max": mx, "step": step})


def _i(default=10, mn=0, mx=1 << 24):
    return ("INT", {"default": default, "min": mn, "max": mx})


# Note: do **not** name the random seed widget "seed". ComfyUI attaches a control_after_generate
# control to an INT with that name, defaulting to randomize -- it changes the value after every run,
# the prompt differs from last time, and with auto-queue on it loops forever. Also, procedural geometry needs
# reproducibility, not a new result every time. Always use rand_seed.


def _names(kind, cls, default="", hint=""):
    """
    Marks a "type a name" input field: kind is attrib or group, cls is the element class.
    The frontend (web/pcg_groups.js) uses it to list the names actually present upstream in the context menu --
    both typing and picking are kept, because these fields also accept wildcards (uv* / * ^P).
    """
    return ("STRING", {"default": default, "tooltip": hint,
                       "name_kind": kind, "name_cls": cls})


def _sec(section, spec, gate=False):
    """
    Tags a widget with a section. When the frontend (web/pcg_sections.js) sees options.section
    it groups widgets automatically and adds collapsible section headers -- a generic mechanism; adding sections needs no frontend code.

    gate=True means this widget is the section's toggle (Houdini's Enable);
    the section header shows its state, and the section is collapsed by default when it is off.
    """
    typ = spec[0]
    opts = dict(spec[1]) if len(spec) > 1 and isinstance(spec[1], dict) else {}
    opts["section"] = section
    if gate:
        opts["section_gate"] = True
    return (typ, opts)


def _sec_defaults(cls, gate):
    """
    Values a section should use when its toggle is off: the **defaults** of the other parameters in the section (first item for combos).

    Same convention as Houdini's Enable -- turning the toggle off means the section was never set, not that "the section's
    feature disappears". E.g. with PolyExtrude's Output section off, the output goes back to Houdini's default
    "front + sides, two groups extrudeFront / extrudeSide", rather than outputting nothing.
    Before pcg85, the section toggles of PolyExtrude / Convert / Carve were never read in run(),
    so turning them off did nothing (test_gates.py now checks this statically for every node).
    """
    it = cls.INPUT_TYPES()
    specs = {**it.get("required", {}), **it.get("optional", {})}
    opts = lambda v: v[1] if len(v) > 1 and isinstance(v[1], dict) else {}  # noqa: E731
    section = opts(specs[gate]).get("section")
    out = {}
    for k, v in specs.items():
        o = opts(v)
        if k == gate or o.get("section") != section:
            continue
        out[k] = v[0][0] if isinstance(v[0], (list, tuple)) else o.get("default")
    return out


def _group(hint="Empty = all; accepts group names / indices / 0-10:2 / @P.y > 0"):
    """
    Group parameter. Almost every SOP in Houdini has this field, so it is a shared helper --
    new nodes just write "group": _group() and get the same signature and parsing behaviour.
    """
    # is_group lets the frontend recognise this as a group input; the context menu lists the groups actually present upstream
    return ("STRING", {"default": "", "multiline": False, "tooltip": hint,
                       "is_group": True})
