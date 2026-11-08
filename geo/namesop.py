"""
Name SOP (Houdini semantics, pcg100 s7): write a string attribute (default name) onto the elements of groups, or conversely name by the
groups an element belongs to (the inverse of Partition), then apply a From -> To string replacement to existing values.

This plugin used to point Name at the Format mode of PCG_Enumerate (piece_%d numbering); that is Enumerate, not Name
(audit [C]) -- Enumerate is left untouched, a separate node is added here.

The Number of Namings multiparm is written as multi-line text, one entry per line:
    group : name          group syntax is the same as the Group parameter (group name / wildcard / index / @expr)
    # group : name        leading # = this entry's Enable is off
The docs do not say who wins when the groups of two namings overlap: entries are written in multiparm order, **later entries overwrite earlier ones**.
"""
from __future__ import annotations

import numpy as np

from .core import POINT, PRIM, VERTEX, is_string
from .groups import resolve
from .ops import match_names

NAME_CLASSES = ("prim", "point", "vertex")
_CLS = {"point": POINT, "prim": PRIM, "vertex": VERTEX}


def parse_namings(text):
    out = []
    for ln, raw in enumerate(str(text).splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            raise ValueError(f"Namings line {ln} must be written as 'group : name', got '{s}'")
        g, _, nm = s.rpartition(":")
        out.append((ln, g.strip(), nm.strip()))
    return out


def _replace(vals, frm, to, global_):
    """The docs do not say whether From supports wildcards: plain substring replacement; Global off = replace only the first occurrence."""
    if not frm:
        return vals
    cnt = -1 if global_ else 1
    return np.array([v.replace(frm, to, cnt) for v in vals.tolist()], dtype=object).astype(str)


def name_sop(geo, attribute="name", cls="prim", name_from_group=False, group_mask="*",
             namings="", global_replace=True, from_="", to=""):
    """Returns (geometry, report). Elements that are not named keep their original value (empty string if the attribute did not exist)."""
    if cls not in NAME_CLASSES:
        raise ValueError(f"Class must be one of {NAME_CLASSES}")
    c = _CLS[cls]
    nm = str(attribute).strip()
    if not nm:
        raise ValueError("Attribute cannot be empty")
    n = geo.count(c)
    cur = geo.get(c, nm)
    rep = {}
    if cur is not None and not is_string(cur):
        # Numeric attribute with the same name: replaced by a string attribute (old values are dropped, unnamed elements are empty strings), noted in the report.
        # The docs do not cover this case; raising would stop an entire network where "upstream casually created a numeric name", not worth it
        rep["warning"] = f"'{nm}' on {cls} was a numeric attribute and has been replaced by a string attribute"
        cur = None
    vals = (np.asarray(cur).astype(str)[:, 0] if cur is not None
            else np.full(n, "", dtype=object).astype(str))
    vals = vals.astype(object)
    named = np.zeros(n, bool)
    if name_from_group:
        # Docs: behaviour is undefined when an element is in several groups -- here groups are sorted by name and later ones overwrite earlier ones
        gs = match_names(sorted(geo.groups[c].keys()), group_mask)
        for g in gs:
            m = np.asarray(geo.groups[c][g], bool)
            vals[m] = g
            named |= m
        rep["groups"] = gs
    else:
        rows = parse_namings(namings)
        for ln, g, v in rows:
            m = resolve(geo, c, g)                 # empty group = everything (resolve's convention)
            vals[m] = v
            named |= m
        rep["namings"] = len(rows)
    vals = _replace(np.asarray(vals, dtype=object).astype(str), str(from_), str(to),
                    bool(global_replace))
    out = geo.copy()
    out.set_string(c, nm, vals.reshape(-1, 1))
    rep["named"] = int(named.sum())
    return out, rep
