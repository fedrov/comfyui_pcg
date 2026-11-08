"""
Attribute Fade (Houdini semantics, pcg100 s7): fades a point attribute in, holds it and fades it out over **time**.

This plugin's original PCG_AttribFade is a spatial falloff (decreasing from a group by steps / distance), which is not the same as
Houdini's Attribute Fade (audit [C]) -- that node is left alone; this one is new.

Per-point timeline (frames):
    start = Fade Start Frame attribute * Start Frame Retime + Frame Offset   (no attribute = 0)
    t     = Frame − start
    0 <= t < in                    fade in: Fade In Ramp(t / in)
    in <= t < in + hold            hold: 1
    in + hold <= t < in+hold+out   fade out: Fade Out Ramp((t - in - hold) / out)
    t < 0 or t >= in + hold + out  0
    hold = Fade Hold Frames * Hold Frame Scale attribute (none = 1)
Output = original attribute value * fade (if the attribute didn't exist it counts as 1 -- the docs' wording).

Differs from Houdini / unclear in the docs, decided here:
  - The current frame is a parameter (Frame), not the global timeline -- ComfyUI has no $F; drive it from the playbar / a value node.
  - Both ramps give the fade value directly: fade in defaults to 0->1, fade out to 1->0 (the docs don't say whether the fade-out ramp
    is applied reversed).
  - Start Frame Retime is a multiplier: attribute value * Retime = frame. The docs say "0-1 by default uses frames,
    set it to 1, $FPS for seconds", which looks like a (from, to) mapping; multiplier = to / from, only one number is kept here.
  - The second / third inputs correspond by **point number** (point counts must match); the docs only say "read from the second input".
  - Segments with zero duration are skipped (with in = 0 it is 1 from the start).
"""
from __future__ import annotations

import numpy as np

from .core import POINT, is_string
from .groups import resolve
from . import ramp as _ramp

RAMP_MODES = _ramp.MODES


def _attr_from(geo, other, name, what, n, default):
    """Scalar point attribute: read from other if connected (point counts must match), else from geo; neither = default."""
    nm = str(name).strip()
    src = other if other is not None else geo
    a = src.get(POINT, nm) if nm else None
    if a is None:
        # Docs: if the attribute is missing use the default (start 0 / scale 1). Same when an input is connected but lacks the attribute
        return np.full(n, float(default))
    if is_string(a):
        raise ValueError(f"{what} '{nm}' is a string attribute; a numeric one is required")
    if other is not None and src.npoints != n:
        raise ValueError(f"{what}: the connected input has {src.npoints} points, the first input has {n} -- they correspond by point number and must match")
    return np.asarray(a, np.float64)[:, 0]


def fade_value(t, fade_in, hold, fade_out, in_ramp, in_mode, out_ramp, out_mode):
    """t, hold are (N,); returns the (N,) fade."""
    t = np.asarray(t, np.float64)
    hold = np.broadcast_to(np.asarray(hold, np.float64), t.shape)
    fi, fo = max(float(fade_in), 0.0), max(float(fade_out), 0.0)
    hold = np.maximum(hold, 0.0)
    f = np.zeros_like(t)
    m_in = (t >= 0) & (t < fi)
    if m_in.any():
        pos, val = _ramp.parse(in_ramp, 1)
        f[m_in] = _ramp.apply(t[m_in] / fi, pos, val, in_mode)[:, 0]
    m_hold = (t >= fi) & (t < fi + hold)
    f[m_hold] = 1.0
    t2 = t - fi - hold
    m_out = (t2 >= 0) & (t2 < fo)
    if m_out.any():
        pos, val = _ramp.parse(out_ramp, 1)
        f[m_out] = _ramp.apply(t2[m_out] / fo, pos, val, out_mode)[:, 0]
    return f


def attrib_fade_time(geo, group="", fade_attribute="fade", frame=1.0,
                     start_attribute="fadestart", start_retime=1.0,
                     hold_scale_attribute="holdscale", frame_offset=0.0,
                     fade_in=10.0, fade_hold=10.0, fade_out=10.0,
                     fade_in_ramp="0:0 1:1", fade_in_ramp_mode="linear",
                     fade_out_ramp="0:1 1:0", fade_out_ramp_mode="linear",
                     visualize=False, start_geo=None, hold_geo=None):
    """Returns (geometry, report). Only points in group change; if the attribute didn't exist it is created, points outside the group get 1."""
    for m, nm in ((fade_in_ramp_mode, "Fade In"), (fade_out_ramp_mode, "Fade Out")):
        if m not in RAMP_MODES:
            raise ValueError(f"{nm} Ramp interpolation must be one of {RAMP_MODES}")
    n = geo.npoints
    name = str(fade_attribute).strip()
    if not name:
        raise ValueError("Fade attribute name cannot be empty")
    sel = resolve(geo, POINT, group)
    start = (_attr_from(geo, start_geo, start_attribute, "Fade Start Frame", n, 0.0)
             * float(start_retime) + float(frame_offset))
    hscale = _attr_from(geo, hold_geo, hold_scale_attribute, "Hold Frame Scale", n, 1.0)
    f = fade_value(float(frame) - start, fade_in, float(fade_hold) * hscale, fade_out,
                   fade_in_ramp, fade_in_ramp_mode, fade_out_ramp, fade_out_ramp_mode)
    out = geo.copy()
    cur = geo.get(POINT, name)
    if cur is not None and is_string(cur):
        raise ValueError(f"Fade attribute '{name}' is a string and cannot be scaled")
    base = (np.asarray(cur, np.float64) if cur is not None else np.ones((n, 1)))
    res = base.copy()
    res[sel] = base[sel] * f[sel, None]
    out.set(POINT, name, res.astype(cur.dtype if cur is not None and cur.dtype.kind == "f"
                                    else np.float32), owned=True)
    if visualize:
        C = np.ones((n, 3), np.float32)
        oc = geo.get(POINT, "Cd")
        if oc is not None and not is_string(oc) and oc.shape[1] == 3:
            C = np.asarray(oc, np.float32).copy()
        C[sel] = f[sel, None]
        out.set(POINT, "Cd", C, owned=True)
    fs = f[sel]
    rep = {"points": int(sel.sum()),
           "zero": int((fs <= 0).sum()), "full": int((fs >= 1).sum()),
           "fading": int(((fs > 0) & (fs < 1)).sum())}
    return out, rep
