"""
numpy functions that break when another custom node rebinds `np.bool` (pcg117).

Some ComfyUI node packs still run old code that used the `np.bool` alias numpy removed in 1.24, and "fix" it with
`np.bool = bool` at import time. That rebinding is global: numpy 2 brought `np.bool` back as the real boolean scalar
type and checks against it internally -- `np.select` raises "invalid entry 0 in condlist: should be boolean ndarray"
for perfectly boolean conditions once `np.bool` is Python's `bool`. Which packs are installed, and in which order they
load, is not ours to control, so the plugin does not call the affected functions; the replacements live here.
"""
from __future__ import annotations

import numpy as np


def select(condlist, choicelist, default=0):
    """
    np.select (first true condition wins, else default) built from np.where alone. Conditions, choices and default
    broadcast together; the result dtype is that of the choices and default, as in np.select.
    """
    conds = [np.asarray(c).astype(np.bool_, copy=False) for c in condlist]
    choices = [np.asarray(c) for c in choicelist]
    if len(conds) != len(choices):
        raise ValueError("select: condlist and choicelist must be the same length")
    dflt = np.asarray(default)
    dt = np.result_type(*choices, dflt) if choices else dflt.dtype
    shape = np.broadcast_shapes(dflt.shape, *(a.shape for a in conds + choices))
    out = np.broadcast_to(dflt.astype(dt, copy=False), shape).copy()
    for c, v in zip(reversed(conds), reversed(choices)):
        out = np.where(c, v, out)
    return out.astype(dt, copy=False)
