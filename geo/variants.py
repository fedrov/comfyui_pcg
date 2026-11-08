"""
Variants and attributes (pcg68, SOP gap batch C): Attribute from Pieces, Enumerate (incl. Name),
Color (incl. Attribute Adjust Color), Attribute Fill, Attribute String Edit,
Cluster Points (incl. Cluster).

━━ Random numbers: the same hash as Attribute Randomize, taken by "key", not by index
The key defaults to the element index; with a piece attribute it is **the piece's key** (string piece names are folded to integers with crc32 --
Python's built-in hash() is salted at every start, so the same name gives different numbers across runs and cannot be used).
So with "random per piece" all elements of a piece get the same number, and upstream point deletion or reordering does not affect existing pieces'
results.

━━ Every node only touches the selected elements
Elements outside group keep their original values; when the attribute did not exist before, it is created with default values (0 / empty string /
white).
"""
from __future__ import annotations

import itertools
import re
import zlib

import numpy as np

from .core import Geometry, POINT, VERTEX, PRIM, DETAIL, is_string
from .groups import resolve
from .attribrandomize import _rand01
from . import ramp as _ramp
from .topology import topology
from .ops import match_names

CLASSES = ("point", "prim", "vertex")
AFP_MODES = ("random", "cycle", "by_attribute", "patches", "noise", "vexpression")
ENUM_MODES = ("elements", "pieces")
ENUM_ORDERS = ("first_appearance", "sorted")
COLOR_MODES = ("constant", "random", "random_by_attribute",
               "ramp_by_attribute", "adjust")
FILL_METHODS = ("harmonic", "nearest", "diffuse", "eikonal", "poisson", "diffusion",
                "extrapolate")
FILL_WEIGHTS = ("uniform", "inverse_length")
STREDIT_MODES = ("substring", "wildcard", "regex")


# ═══════════════════════════════════════════════════════════ small helpers
def _cls(c):
    c = str(c).lower()
    if c not in CLASSES:
        raise ValueError(f"Class must be one of {CLASSES}")
    return c


def _stable_int(values):
    """Any key (string / number) -> a stable int64. Strings use crc32, stable across processes."""
    v = np.asarray(values).reshape(-1)
    if v.dtype.kind in "US":
        return np.array([zlib.crc32(str(x).encode("utf-8")) for x in v],
                        np.int64)
    return np.round(v.astype(np.float64) * 1000).astype(np.int64)


def element_keys(geo, cls, attribute=""):
    """
    The "piece key" of each element: without an attribute it is the element's own index; with one it is that attribute's value
    (strings as is, vectors joined into a string). If not found on the prim class, falls back to the point attribute of its first point.
    """
    n = geo.count(cls)
    name = str(attribute).strip()
    if not name:
        return np.arange(n)
    a = geo.get(cls, name)
    if a is None and cls == PRIM and geo.nprims:
        pa = geo.get(POINT, name)
        if pa is not None:
            a = pa[geo.vertex_point[geo.prim_offset[:-1].astype(np.int64)]]
    if a is None and cls == VERTEX:
        pa = geo.get(POINT, name)
        if pa is not None:
            a = pa[geo.vertex_point]
    if a is None:
        raise KeyError(f"No {cls} attribute '{name}'")
    if is_string(a) or a.shape[1] == 1:
        return a[:, 0]
    return np.array([str(r.tolist()) for r in a])


def _groups_of(keys):
    """Keys -> (group number per element, number of groups), group numbers in order of first occurrence."""
    _, first, inv = np.unique(keys, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(first, kind="stable")
    rank = np.empty(len(first), np.int64)
    rank[order] = np.arange(len(first))
    return rank[inv], len(first)


def _write(geo, cls, name, values, mask, default):
    """Write values (n,C) to the elements selected by mask; the rest keep their original values (default if none)."""
    n = geo.count(cls)
    values = np.asarray(values)
    if values.ndim == 1:
        values = values[:, None]
    cur = geo.get(cls, name)
    if values.dtype.kind in "US":
        base = (np.asarray(cur).astype(str) if cur is not None and is_string(cur)
                and cur.shape[1] == 1 else np.full((n, 1), str(default)))
        w = max(base.dtype.itemsize, values.astype(str).dtype.itemsize) // 4
        base = base.astype(f"<U{max(w, 1)}")
        base[mask] = values[mask].astype(str)
        geo.set_string(cls, name, base)
        return
    if cur is not None and not is_string(cur) and cur.shape[1] == values.shape[1]:
        base = np.asarray(cur).astype(values.dtype).copy()
    else:
        base = np.zeros((n, values.shape[1]), values.dtype)
        base[:] = default
    base[mask] = values[mask]
    geo.set(cls, name, base, owned=True)


# ═══════════════════════════════════════════════════ Attribute from Pieces
def _parse_weights(spec, n):
    toks = [t for t in str(spec).replace(",", " ").split() if t]
    if not toks:
        return np.ones(n)
    w = np.array([float(t) for t in toks])
    if len(w) != n:
        raise ValueError(f"Weights has {len(w)} entries but there are {n} variants -- they must correspond one to one")
    if (w < 0).any() or w.sum() <= 0:
        raise ValueError("Weights cannot be negative, nor all 0")
    return w


# ── pcg100 s7: parts added against the SideFX docs (Weight Method, Piece Filter, Shuffle / Offset,
# Override Ptnum, Patches / Noise / VEXpression, Map Attribute's three mappings, Copy Attributes)
AFP_WEIGHT_METHODS = ("auto", "uniform", "piece_weights", "weight_attribute")
AFP_MAP_FROM = ("weighted_unit", "automatic", "explicit", "string")
AFP_PROMOTIONS = ("max", "min", "mean", "mode", "median", "sum", "sum_squares",
                  "rms", "first", "last")
_AFP_STR_OK = ("max", "min", "mode", "median", "first", "last")


def _piece_weights(spec, names):
    """
    Piece Weights (in Houdini a Piece / Weight multiparm) written as one line of text:
      all numbers     correspond one to one in library order (same as the old Weights)
      name:weight     only listed pieces take part, unlisted ones get weight 0 -- Houdini's multiparm also only has
                  the listed entries (only Autofill fills in all pieces); the docs do not say how unlisted pieces count
    """
    toks = [t for t in str(spec).replace(",", " ").split() if t]
    if not toks:
        return np.ones(len(names))
    named = [":" in t for t in toks]
    if not any(named):
        return _parse_weights(spec, len(names))
    if not all(named):
        raise ValueError("Piece Weights must be either all numbers (in order) or all name:weight")
    idx = {s: i for i, s in enumerate(names)}
    w = np.zeros(len(names))
    for t in toks:
        nm, _, val = t.rpartition(":")
        if nm not in idx:
            raise KeyError(f"Piece '{nm}' in Piece Weights does not exist; available: {list(idx)[:20]}")
        w[idx[nm]] = float(val)
    if (w < 0).any() or w.sum() <= 0:
        raise ValueError("Piece Weights cannot be negative, nor all 0")
    return w


def _name_index(names, numeric):
    """Piece name text -> piece index. Numeric piece names compare by value ('1' and 1.0 are the same piece)."""
    if numeric:
        vals = np.asarray(names, np.float64)

        def look(tok):
            try:
                hit = np.nonzero(np.isclose(vals, float(tok)))[0]
            except ValueError:
                return -1
            return int(hit[0]) if len(hit) else -1
        return look
    idx = {s: i for i, s in enumerate(names)}
    return lambda tok: idx.get(tok, -1)


def _parse_rules(text):
    """Each line "name[ name...] : condition"; empty lines and lines starting with # are skipped. Split at the first colon."""
    rules = []
    for ln, raw in enumerate(str(text).splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            raise ValueError(f"Rules line {ln} is missing a colon: write it as 'name : condition', got '{s}'")
        left, _, right = s.partition(":")
        pcs = left.split()
        if not pcs:
            raise ValueError(f"Rules line {ln} has no piece name before the colon")
        rules.append((ln, pcs, right.strip()))
    return rules


def _worley_cell(S, seed):
    """The "cell of the nearest feature point" of Worley noise: (N,3) -> (N,3) int. One Patches patch = one cell."""
    from .attribnoise import _cell_hash, _to01
    i = np.floor(S).astype(np.int64)
    best = np.full(len(S), np.inf)
    cell = i.copy()
    for corner in itertools.product((-1, 0, 1), repeat=3):
        c = i + np.array(corner, np.int64)
        fp = c.astype(np.float64) + np.stack(
            [_to01(_cell_hash(c, seed, k)) for k in range(1, 4)], 1)
        d = np.linalg.norm(S - fp, axis=1)
        better = d < best
        best = np.where(better, d, best)
        cell[better] = c[better]
    return cell


def _reduce_piece(vals, method, name):
    """All values of a piece (m,C) -> (C,), by Promotion Method."""
    m = len(vals)
    if is_string(vals):
        if method not in _AFP_STR_OK:
            raise ValueError(f"String attribute '{name}' cannot be combined with {method} (only {_AFP_STR_OK})")
        s = np.asarray(vals).astype(str)[:, 0]
        if method == "first":
            return s[:1]
        if method == "last":
            return s[-1:]
        srt = np.sort(s)
        if method == "max":
            return srt[-1:]
        if method == "min":
            return srt[:1]
        if method == "median":
            return srt[m // 2:m // 2 + 1]
        u, c = np.unique(s, return_counts=True)
        i = int(np.argmax(c))                            # on ties np.unique is already sorted -> the smallest
        return u[i:i + 1]
    v = np.asarray(vals, np.float64)
    if method == "max":
        return v.max(0)
    if method == "min":
        return v.min(0)
    if method == "mean":
        return v.mean(0)
    if method == "mode":
        u, c = np.unique(v, axis=0, return_counts=True)
        return u[np.argmax(c)]                           # docs: ties take the smallest (lexicographic)
    if method == "median":
        return np.sort(v, 0)[m // 2]                     # docs: with an even count take the larger median
    if method == "sum":
        return v.sum(0)
    if method == "sum_squares":
        return (v * v).sum(0)
    if method == "rms":
        return np.sqrt((v * v).mean(0))
    if method == "first":
        return v[0]
    return v[-1]


def _copy_piece_attribs(library, lcls, grp, k, pattern, allow_p, method, skip):
    """
    Copy Attributes: the attributes matching pattern on each library piece are combined into one value by Promotion Method.
    Returns {name: (k, C) array} (by library piece index).
    Sources: attributes of the piece's class (prim, or point when the library has only points), plus the point attributes of the points these prims use
    (points are not looked at when the prim already has the same name). The docs only say "aggregated over each piece",
    not which classes are read; this is our own choice. P only counts when Allow P Attribute is on.
    """
    out = {}
    cands = list(library.attribs[lcls].keys())
    if lcls == PRIM:
        cands += [n for n in library.attribs[POINT] if n not in library.attribs[PRIM]]
    names = [n for n in match_names(cands, pattern)
             if (allow_p or n != "P") and n not in skip]
    if not names:
        return out
    members = [np.nonzero(grp == j)[0] for j in range(k)]
    pmembers = None
    if lcls == PRIM:
        vprim = library.vertex_prim()
        vpt = library.vertex_point
        pmembers = []
        for j in range(k):
            vs = np.nonzero(np.isin(vprim, members[j]))[0]
            pts = vpt[vs]
            _, first = np.unique(pts, return_index=True)
            pmembers.append(pts[np.sort(first)])          # points in order of first occurrence among vertices
    for n in names:
        on_prim = n in library.attribs[lcls]
        a = library.get(lcls if on_prim else POINT, n)
        mem = members if on_prim else pmembers
        rows = [_reduce_piece(a[mem[j]], method, n) for j in range(k)]
        if is_string(a):
            out[n] = np.array(rows).astype(str).reshape(k, 1)
        else:
            t = np.asarray(rows, np.float64).reshape(k, -1)
            keep_int = a.dtype.kind in "iu" and method not in ("mean", "rms")
            out[n] = t.astype(np.int32) if keep_int else t.astype(np.float32)
    return out


def attrib_from_pieces(geo, library=None, cls="point", group="",
                       piece_attribute="", library_attribute="name",
                       weight_attribute="weight", count=4, weights="",
                       mode="random", input_attribute="", seed=0,
                       output="variant", index_output="",
                       weight_method="auto", piece_filter="", shuffle=False,
                       offset=0, use_id_attribute=False, id_attribute="id",
                       copy_attributes="", allow_p=False, promotion="first",
                       location_attribute="P", element_size=1.0,
                       element_scale=(1.0, 1.0, 1.0), noise_offset=(0.0, 0.0, 0.0),
                       noise_type="perlin", max_octaves=1, roughness=0.5,
                       map_from="weighted_unit", rules="", unmatched_piece="",
                       unmatched_group=""):
    """
    Mirrors Houdini's Attribute from Pieces: pick a **variant** for each element (or each piece) and
    write it as an attribute -- it is Copy to Points' piece attribute, so "five kinds of rock scattered over a slope by weight" is
    Scatter -> Attribute from Pieces -> Copy to Points (piece = variant).

    Where the variants come from:
      library given   each value of library_attribute on library is a variant (in order of first
                     occurrence); weights are read from library's weight_attribute (the value on that piece's first
                     prim, all 1 if absent)
      not given       the integers 0 .. count−1, with weights written in weights ("3 1 1 1")
    weight_method (Houdini's Weight Method; auto = the old rules above):
      uniform           every piece the same
      piece_weights     weights text: numbers in order, or name:weight
      weight_attribute  the average of library's weight_attribute over **all** prims of the piece (wording from the docs)
    piece_filter keeps only the listed pieces (space-separated piece names); shuffle shuffles the piece order with rand_seed;
    offset shifts the order (the last ones move to the front). The order affects cycle, Automatic Ranges and the index output.
    mode:
      random        random by weight (one number per element / per piece, see the file header)
      cycle         rotate in turn: element k (or piece k) uses variant k mod N;
                    with use_id_attribute the id attribute's value replaces the index (Override Ptnum)
      by_attribute  Map Attribute. map_from:
                      weighted_unit old behaviour: the value of input_attribute (0~1, averaged per piece) looked up in
                                    the cumulative distribution of the weights
                      automatic     the attribute's [min, max] split into N equal ranges, one piece each (docs:
                                    equal-sized ranges), weights ignored
                      explicit      rules, one "name : min max" per line
                      string        rules, one "name : pattern" per line (string attribute, * ? wildcards)
      patches       cells of Worley noise: points in the same cell get the same piece (random by weight)
      noise         noise value (n+1)/2 quantized into pieces by the cumulative weight distribution
      vexpression   rules, one "name : expression" per line (wrangle syntax); the first line that is non-zero wins
    When a rule line lists several piece names one is picked at random (docs: space-separated list ... chosen randomly).
    Elements matching nothing get unmatched_piece (empty = no piece assigned: strings get "", integers −1, index −1),
    and if unmatched_group is given those elements go into that group.
    copy_attributes: combine each library piece's attributes into one value by promotion and write it onto the elements that picked that piece.
    With piece_attribute given, picking is per piece: elements of the same piece get the same variant.
    output writes the variant (a string attribute if the library uses strings); index_output writes the index separately.
    Returns (geometry, report: how many times each variant was used).
    """
    cls = _cls(cls)
    if mode not in AFP_MODES:
        raise ValueError(f"Mode must be one of {AFP_MODES}")
    if weight_method not in AFP_WEIGHT_METHODS:
        raise ValueError(f"Weight Method must be one of {AFP_WEIGHT_METHODS}")
    if map_from not in AFP_MAP_FROM:
        raise ValueError(f"Map Pieces From must be one of {AFP_MAP_FROM}")
    if promotion not in AFP_PROMOTIONS:
        raise ValueError(f"Promotion Method must be one of {AFP_PROMOTIONS}")
    out = geo.copy()
    n = geo.count(cls)
    has_lib = library is not None and (library.npoints or library.nprims)
    lcls = grp = None
    if has_lib:
        lcls = PRIM if library.nprims else POINT
        lk = element_keys(library, lcls, library_attribute)
        grp, k = _groups_of(lk)
        _, first = np.unique(grp, return_index=True)   # where each variant first occurs
        variants = lk[first]
        wname = str(weight_attribute).strip()
        wa = library.get(lcls, wname) if wname else None
        if weight_method == "auto":
            w = (np.asarray(wa, np.float64)[first, 0] if wa is not None
                 else np.ones(k))
        elif weight_method == "weight_attribute":
            if wa is None or is_string(wa):
                raise KeyError(f"Weight Method = Weight Attribute, but the library's {lcls} has no numeric attribute '{wname}'")
            w = (np.bincount(grp, weights=np.asarray(wa, np.float64)[:, 0], minlength=k)
                 / np.bincount(grp, minlength=k))
        if (weight_method in ("auto", "weight_attribute")
                and ((w < 0).any() or w.sum() <= 0)):
            raise ValueError("Weights on library cannot be negative, nor all 0")
    else:
        k = int(count)
        if k < 1:
            raise ValueError("Count must be at least 1 (without a library the variants are 0 .. Count−1)")
        variants = np.arange(k)
        if weight_method == "weight_attribute":
            raise ValueError("Weight Method = Weight Attribute needs library connected (the weights live on the pieces' prims)")
        if weight_method == "auto":
            w = _parse_weights(weights, k)
    numeric = np.asarray(variants).dtype.kind not in "US"
    vnames = [str(v) for v in np.asarray(variants)]
    if weight_method == "uniform":
        w = np.ones(k)
    elif weight_method == "piece_weights":
        w = _piece_weights(weights, vnames)

    # ── piece order: Piece Filter -> Shuffle -> Offset
    perm = np.arange(k)
    toks = str(piece_filter).split()
    if toks:
        look = _name_index(vnames, numeric)
        keep = sorted({look(t) for t in toks} - {-1})
        if not keep:
            raise ValueError(f"Piece Filter '{piece_filter}' selected no pieces; available: {vnames[:20]}")
        perm = np.asarray(keep, np.int64)
    if shuffle:
        perm = perm[np.argsort(_rand01(np.arange(len(perm)), seed, 31), kind="stable")]
    if int(offset):
        perm = np.roll(perm, int(offset))
    if len(perm) != k or not np.array_equal(perm, np.arange(k)):
        variants = np.asarray(variants)[perm]
        w = np.asarray(w, np.float64)[perm]
        vnames = [vnames[i] for i in perm]
    kk = len(perm)
    if not (np.asarray(w) > 0).any():
        # weights all 0 after filtering: only an error for modes that actually read weights (cycle / Automatic / Rules ignore weights)
        if mode in ("random", "patches", "noise") or (
                mode == "by_attribute" and map_from == "weighted_unit"):
            raise ValueError("The pieces left by Piece Filter all have weight 0")
        w = np.ones(kk)
    cdf = np.cumsum(w) / w.sum()

    sel = resolve(geo, cls, group)
    unit, nunits = _groups_of(element_keys(geo, cls, piece_attribute)) \
        if str(piece_attribute).strip() else (np.arange(n), n)
    ukeys = (_stable_int(element_keys(geo, cls, piece_attribute))
             if str(piece_attribute).strip() else np.arange(n, dtype=np.int64))
    ids = geo.get(cls, "id")
    if not str(piece_attribute).strip() and ids is not None and \
            not is_string(ids):
        ukeys = np.asarray(ids, np.float64)[:, 0]
    # one representative key per unit (element or piece)
    _, ufirst = np.unique(unit, return_index=True)
    rep = np.asarray(ukeys, np.float64)[ufirst]
    rep_id = None
    if use_id_attribute:
        iname = str(id_attribute).strip()
        ia = geo.get(cls, iname) if iname else None
        if ia is None or is_string(ia):
            raise KeyError(f"Override Ptnum: {cls} has no numeric attribute '{iname}'")
        rep_id = np.asarray(ia, np.float64)[ufirst, 0]
        rep = rep_id
    rules_mode = (mode == "vexpression"
                  or (mode == "by_attribute" and map_from in ("explicit", "string")))

    def _unit_pos():
        from .attribnoise import _sample_positions
        Pe = _sample_positions(geo, cls, location_attribute)
        c = np.maximum(np.bincount(unit, minlength=nunits), 1)[:, None]
        Pu = np.stack([np.bincount(unit, weights=Pe[:, d], minlength=nunits)
                       for d in range(3)], 1) / c
        sz = float(element_size) * np.asarray(element_scale, np.float64)
        if (np.abs(sz) < 1e-12).any():
            raise ValueError("Size x Scale cannot be 0")
        return (Pu - np.asarray(noise_offset, np.float64)) / sz

    if mode == "random":
        u = _rand01(rep, seed, 17)
        pick = np.searchsorted(cdf, u, side="right")
    elif mode == "cycle":
        if rep_id is not None:
            pick = np.floor(rep_id).astype(np.int64) % kk
        else:
            pick = np.arange(nunits) % kk
    elif mode == "patches":
        from .attribnoise import _cell_hash, _to01
        cell = _worley_cell(_unit_pos(), seed)
        pick = np.searchsorted(cdf, _to01(_cell_hash(cell, seed, 7)), side="right")
    elif mode == "noise":
        from .attribnoise import fractal_noise, NOISE_TYPES
        if noise_type not in NOISE_TYPES:
            raise ValueError(f"Noise Type must be one of {NOISE_TYPES}")
        oc = max(1, int(max_octaves))
        v = fractal_noise(_unit_pos(), noise_type, "standard" if oc > 1 else "none",
                          oc, 2.0, float(roughness), seed)
        pick = np.searchsorted(cdf, np.clip((v + 1.0) / 2.0, 0.0, 1 - 1e-12),
                               side="right")
    elif not rules_mode:
        name = str(input_attribute).strip()
        a = geo.get(cls, name) if name else None
        if a is None or is_string(a):
            raise KeyError(f"by_attribute needs a scalar {cls} attribute (Input "
                           f"Attribute); '{name}' not found")
        raw = np.asarray(a, np.float64)[:, 0]
        c = np.maximum(np.bincount(unit, minlength=nunits), 1)
        if map_from == "weighted_unit":
            v = np.clip(raw, 0.0, 1.0)
            s = np.bincount(unit, weights=v, minlength=nunits)
            pick = np.searchsorted(cdf, np.clip(s / c, 0, 1 - 1e-12), side="right")
        else:                                        # automatic: split the attribute's value range evenly
            vu = np.bincount(unit, weights=raw, minlength=nunits) / c
            us = np.unique(unit[sel])
            lo, hi = (vu[us].min(), vu[us].max()) if len(us) else (0.0, 0.0)
            pick = (np.floor((vu - lo) / (hi - lo) * kk).astype(np.int64)
                    if hi > lo else np.zeros(nunits, np.int64))
    else:
        rl = _parse_rules(rules)
        look = _name_index(vnames, numeric)
        if mode == "vexpression":
            from .wrangle import eval_value
        else:
            name = str(input_attribute).strip()
            a = geo.get(cls, name) if name else None
            if a is None:
                raise KeyError(f"Map Attribute: no {cls} attribute '{name}'")
            if map_from == "string":
                if not is_string(a):
                    raise ValueError(f"Map Pieces From = String, but '{name}' is not a string attribute")
                sv = np.asarray(a).astype(str)[ufirst, 0]
            else:
                if is_string(a):
                    raise ValueError(f"Explicit Ranges needs a numeric attribute; '{name}' is a string")
                c = np.maximum(np.bincount(unit, minlength=nunits), 1)
                vu = np.bincount(unit, weights=np.asarray(a, np.float64)[:, 0],
                                 minlength=nunits) / c
        pick = np.full(nunits, -1, np.int64)
        import fnmatch
        for row, (ln, pcs, cond) in enumerate(rl):
            ix = [look(p) for p in pcs]
            if -1 in ix:
                bad = pcs[ix.index(-1)]
                raise KeyError(f"Piece '{bad}' on Rules line {ln} is not among the available pieces: {vnames[:20]}")
            if mode == "vexpression":
                hit = np.asarray(eval_value(geo, cond, cls, 1), np.float64)[ufirst, 0] != 0
            elif map_from == "string":
                pats = cond.split() or [""]
                hit = np.array([any(fnmatch.fnmatchcase(s, p) for p in pats) for s in sv],
                               bool)
            else:
                try:
                    lo, hi = (float(x) for x in cond.replace(",", " ").split())
                except ValueError:
                    raise ValueError(f"Rules line {ln} must be written as 'name : min max', got '{cond}'")
                hit = (vu >= lo) & (vu <= hi)
            take = hit & (pick < 0)
            if len(ix) > 1:
                r = np.minimum((_rand01(rep, seed, 41 + row) * len(ix)).astype(np.int64),
                               len(ix) - 1)
                choice = np.asarray(ix, np.int64)[r]
            else:
                choice = np.full(nunits, ix[0], np.int64)
            pick = np.where(take, choice, pick)
    if not rules_mode:
        pick = np.clip(pick, 0, kk - 1)
    idx = pick[unit]
    matched = idx >= 0
    um = str(unmatched_piece).strip()
    um_idx = _name_index(vnames, numeric)(um) if um else -1
    nm = str(output).strip() or "variant"
    if numeric:
        um_val = (int(float(um)) if um else -1) if rules_mode else 0
        vals = np.where(matched, np.asarray(variants)[np.maximum(idx, 0)].astype(np.float64),
                        um_val).astype(np.int32)
        _write(out, cls, nm, vals, sel, 0)
    else:
        vals = np.where(matched, np.asarray(variants)[np.maximum(idx, 0)].astype(str), um)
        _write(out, cls, nm, vals, sel, "")
    if str(index_output).strip():
        _write(out, cls, str(index_output).strip(),
               np.where(matched, idx, um_idx).astype(np.int32), sel, -1)
    if rules_mode and str(unmatched_group).strip():
        out.set_group(cls, str(unmatched_group).strip(), sel & ~matched)
    if str(copy_attributes).strip():
        if not has_lib:
            raise ValueError("Copy Attributes needs library connected (attributes come from the library's pieces)")
        tab = _copy_piece_attribs(library, lcls, grp, k, copy_attributes, allow_p,
                                  promotion, {nm})
        src = np.where(matched, perm[np.maximum(idx, 0)], 0)
        for an, t in tab.items():
            _write(out, cls, an, t[src], sel & matched,
                   "" if t.dtype.kind in "US" else 0)
    used = np.bincount(idx[sel & matched], minlength=kk)
    rep_ = {vnames[i]: int(used[i]) for i in range(kk)}
    res = {"variants": kk, "units": int(nunits), "counts": rep_}
    if rules_mode:
        res["unmatched"] = int((sel & ~matched).sum())
    return out, res


# ═══════════════════════════════════════════════════════════ Enumerate
_FMT = re.compile(r"%0?\d*d")


def enumerate_(geo, cls="point", group="", mode="elements",
               piece_attribute="", name="index", start=0, step=1, fmt="",
               order="first_appearance"):
    """
    Mirrors Houdini's Enumerate (and Name -- the string-format mode):

      elements  each selected element gets its index; with piece_attribute **each piece counts
                from the start on its own** (the n-th point in the m-th brick)
      pieces    each element gets the index of its **piece** (pieces by first occurrence / sorted by value)
    Value = start + step x index. With fmt given (e.g. "piece_%d", "%03d") it is written as a string
    -- exactly the Name SOP use. fmt must contain exactly one %d-style placeholder.
    """
    cls = _cls(cls)
    if mode not in ENUM_MODES:
        raise ValueError(f"Mode must be one of {ENUM_MODES}")
    if order not in ENUM_ORDERS:
        raise ValueError(f"Order must be one of {ENUM_ORDERS}")
    f = str(fmt)
    if f and len(_FMT.findall(f)) != 1:
        raise ValueError(f"Format '{f}' needs exactly one %d (%03d for zero padding)")
    out = geo.copy()
    n = geo.count(cls)
    sel = resolve(geo, cls, group)
    idx = np.nonzero(sel)[0]
    val = np.zeros(n, np.int64)
    has_piece = bool(str(piece_attribute).strip())
    if mode == "pieces" or has_piece:
        keys = element_keys(geo, cls, piece_attribute) if has_piece \
            else np.zeros(n, np.int64)
        ks = keys[idx]
        if order == "sorted":
            uniq, inv = np.unique(ks, return_inverse=True)
            g = inv.reshape(-1)
        else:
            g, _ = _groups_of(ks)
        if mode == "pieces":
            val[idx] = g
        else:
            # index within the piece: after a stable sort by group number, each group counts from 0
            o = np.argsort(g, kind="stable")
            gs = g[o]
            first = np.searchsorted(gs, gs, side="left")
            r = np.empty(len(o), np.int64)
            r[o] = np.arange(len(o)) - first
            val[idx] = r
    else:
        val[idx] = np.arange(len(idx))
    v = int(start) + int(step) * val
    nm = str(name).strip() or "index"
    if f:
        s = np.array([f % int(x) for x in v])
        _write(out, cls, nm, s, sel, "")
    else:
        _write(out, cls, nm, v.astype(np.int32), sel, -1)
    return out


# ═══════════════════════════════════════════════════════════ Color
def _rgb_to_hsv(rgb):
    from .cop.pixel import rgb_to_hsv
    return rgb_to_hsv(rgb)


def _hsv_to_rgb(hsv):
    from .cop.pixel import hsv_to_rgb
    return hsv_to_rgb(hsv)


def color(geo, cls="point", group="", mode="constant", rgb=(1, 1, 1), seed=0,
          attribute="", ramp="0:0,0,1 0.5:0,1,0 1:1,0,0", ramp_mode="linear",
          auto_range=True, in_min=0.0, in_max=1.0, hue_shift=0.0,
          saturation=1.0, value=1.0, random_hue=0.0, random_saturation=0.0,
          random_value=0.0, name="Cd"):
    """
    Mirrors Houdini's Color SOP, plus Attribute Adjust Color (adjust mode):

      constant             one uniform color
      random               one random color per element (taken by id / index, see the file header)
      random_by_attribute  **same attribute value, same color** -- coloring fragments by name / piece / class,
                           the most common Color use in Houdini
      ramp_by_attribute    scalar attribute -> color ramp (ramp as one line of text, same as Measure).
                           auto_range uses the attribute's own min / max, otherwise in_min / max
      adjust               adjust HSV on the existing color: rotate hue by hue_shift degrees, saturation x,
                           value x, each with an extra random amount on top (random_* are amplitudes; with
                           attribute given it is random per piece -- the same offset for the same piece)
    """
    cls = _cls(cls)
    if mode not in COLOR_MODES:
        raise ValueError(f"Mode must be one of {COLOR_MODES}")
    out = geo.copy()
    n = geo.count(cls)
    sel = resolve(geo, cls, group)
    nm = str(name).strip() or "Cd"
    att = str(attribute).strip()
    if mode == "constant":
        C = np.tile(np.asarray(rgb, np.float64).reshape(1, 3), (n, 1))
    elif mode in ("random", "random_by_attribute"):
        if mode == "random_by_attribute" and not att:
            raise ValueError("random_by_attribute needs an attribute name (e.g. name)")
        if mode == "random":
            ids = geo.get(cls, "id")
            key = (np.asarray(ids, np.float64)[:, 0] if ids is not None and
                   not is_string(ids) else np.arange(n, dtype=np.float64))
        else:
            key = _stable_int(element_keys(geo, cls, att)).astype(np.float64)
        C = np.stack([_rand01(key, seed, 101 + c) for c in range(3)], 1)
    elif mode == "ramp_by_attribute":
        a = geo.get(cls, att) if att else None
        if a is None or is_string(a):
            raise KeyError(f"ramp_by_attribute needs a numeric {cls} attribute; "
                           f"'{att}' not found")
        v = np.asarray(a, np.float64)
        v = np.linalg.norm(v, axis=1) if v.shape[1] > 1 else v[:, 0]
        lo, hi = (v[sel].min(), v[sel].max()) if auto_range and sel.any() \
            else (float(in_min), float(in_max))
        t = (v - lo) / (hi - lo) if hi > lo else np.zeros(n)
        pos, val = _ramp.parse(ramp, 3)
        C = _ramp.apply(t, pos, val, ramp_mode)
    else:
        cur = geo.get(cls, nm)
        C = (np.asarray(cur, np.float64)[:, :3] if cur is not None and
             not is_string(cur) and cur.shape[1] >= 3
             else np.ones((n, 3)))
        hsv = _rgb_to_hsv(C)
        key = (_stable_int(element_keys(geo, cls, att)).astype(np.float64)
               if att else np.arange(n, dtype=np.float64))
        rh = _rand01(key, seed, 201) - 0.5
        rs = _rand01(key, seed, 202) - 0.5
        rv = _rand01(key, seed, 203) - 0.5
        hsv[:, 0] = (hsv[:, 0] + float(hue_shift) / 360.0
                     + float(random_hue) / 360.0 * 2 * rh) % 1.0
        hsv[:, 1] = np.clip(hsv[:, 1] * float(saturation)
                            * (1 + float(random_saturation) * 2 * rs), 0, 1)
        hsv[:, 2] = np.maximum(hsv[:, 2] * float(value)
                               * (1 + float(random_value) * 2 * rv), 0)
        C = _hsv_to_rgb(hsv)
    _write(out, cls, nm, C.astype(np.float32), sel, 1.0)
    return out


# ═══════════════════════════════════════════════════════════ Attribute Fill
def _edge_graph(geo, weights):
    t = topology(geo)
    E = t.edge_points.astype(np.int64)
    if not len(E):
        return E, np.zeros(0)
    if weights == "inverse_length":
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        ln = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
        w = 1.0 / np.maximum(ln, 1e-12)
    else:
        w = np.ones(len(E))
    return E, w


def _components(n, E):
    lab = np.arange(n, dtype=np.int64)
    if len(E):
        a, b = E[:, 0], E[:, 1]
        for _ in range(200):
            prev = lab
            m = np.minimum(lab[a], lab[b])
            lab = lab.copy()
            np.minimum.at(lab, a, m)
            np.minimum.at(lab, b, m)
            lab = lab[lab]
            if np.array_equal(lab, prev):
                break
    return lab


# ── pcg100 s7: the four Modes of Houdini's Attribute Fill (Eikonal / Poisson / Diffusion / Extrapolate)
FILL_EXTRAP = ("scalar", "parallel_transport")


def _cg_solve(A, b, free, tol=1e-10, x0=None):
    """Symmetric positive definite system A(x) = b on free, conjugate gradient. Components outside free stay 0."""
    y = np.where(free, x0 if x0 is not None else 0.0, 0.0)
    r = np.where(free, b - A(y), 0.0)
    p = r.copy()
    rr = r @ r
    bn = max(np.sqrt(b @ b), 1e-300)
    for _ in range(max(10 * int(free.sum()), 100)):
        if np.sqrt(rr) <= tol * bn:
            break
        Ap = A(p)
        al = rr / max(p @ Ap, 1e-300)
        y = y + al * p
        r = r - al * Ap
        rn = r @ r
        p = r + (rn / rr) * p
        rr = rn
    return y


def _point_scalar(geo, name, what, n):
    a = geo.get(POINT, name)
    if a is None or is_string(a):
        raise KeyError(f"{what}: no numeric point attribute '{name}'")
    return np.asarray(a, np.float64)[:, 0]


def _rotate_between(v, a, b):
    """Rotate v by "the minimal rotation taking a to b" (Rodrigues). a, b unit vectors."""
    k = np.cross(a, b)
    s = np.linalg.norm(k)
    c = float(np.clip(a @ b, -1.0, 1.0))
    if s < 1e-12:
        return v.copy()                    # same direction (when opposite the rotation axis is not unique; no rotation -- degenerate case)
    k = k / s
    return v * c + np.cross(k, v) * s + k * (k @ v) * (1.0 - c)


def _fill_houdini(geo, X, name, a, known_group, method, speed_attribute,
                  match_attribute, weight_attribute, min_edge_length, min_speed,
                  diffusion_time, unreachable_time, extrapolation, tangential_only,
                  global_rotation):
    n = geo.npoints
    E = topology(geo).edge_points.astype(np.int64)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    ln = (np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1) if len(E) else np.zeros(0))
    has_grp = bool(str(known_group).strip())
    if has_grp:
        known = resolve(geo, POINT, known_group)
    elif method == "eikonal":
        raise ValueError("Eikonal needs a Boundary Group (source points with arrival time = 0)")
    elif method == "diffusion":
        known = np.zeros(n, bool)          # no group = no fixed sources, diffuse as a whole
    else:
        known = np.any(X != 0, axis=1) if X is not None else np.zeros(n, bool)
    if method in ("poisson", "extrapolate") and not known.any():
        raise ValueError("No known points (Boundary Group is empty / attribute is 0 everywhere)")
    if method == "eikonal" and not known.any():
        raise ValueError("Boundary Group selected no points")
    sp = None
    if str(speed_attribute).strip() and method in ("eikonal", "diffusion"):
        sp = np.maximum(_point_scalar(geo, speed_attribute.strip(), "Speed Attribute", n),
                        float(min_speed))
    rep = {"mode": method, "known": int(known.sum())}

    if method == "eikonal":
        # Combinatorial Eikonal: shortest arrival time along edges. Time from i to j = edge length / speed of i
        # (docs: speed is how fast it is "leaving this point"). Not Fast Marching; shortcuts cutting diagonally across triangles
        # are not possible -- the result on a mesh is the distance along edges
        from .paths import _adj_directed, dijkstra
        s = np.ones(n) if sp is None else sp
        src = np.concatenate([E[:, 0], E[:, 1]])
        dst = np.concatenate([E[:, 1], E[:, 0]])
        cost = np.concatenate([ln, ln]) / s[src]
        dist, _, _ = dijkstra(_adj_directed(n, src, dst, cost), np.nonzero(known)[0].tolist())
        T = np.asarray(dist, np.float64)
        bad = ~np.isfinite(T)
        T[bad] = float(unreachable_time)
        rep["unreachable"] = int(bad.sum())
        out = geo.copy()
        if a is not None and not is_string(a) and a.shape[1] > 1:
            T = np.repeat(T[:, None], a.shape[1], 1)
        out.set(POINT, name, np.asarray(T, np.float32).reshape(n, -1), owned=True)
        return out, rep

    lab = _components(n, E)
    has_known = np.zeros(n, bool)
    has_known[np.unique(lab[known])] = True
    reach = has_known[lab]

    if method == "extrapolate":
        from .paths import _adjacency, dijkstra
        _, prev, root = dijkstra(_adjacency(n, E, np.maximum(ln, 1e-12)),
                                 np.nonzero(known)[0].tolist())
        prev, root = np.asarray(prev), np.asarray(root)
        unk = ~known & (root >= 0)
        rep["filled"] = int(unk.sum())
        rep["unreachable"] = int((~known & (root < 0)).sum())
        Y = X.copy()
        vec = X.shape[1] == 3
        if extrapolation == "scalar" or not vec:
            if extrapolation != "scalar":
                raise ValueError("Parallel Transport only makes sense for 3-component vector attributes")
            Y[unk] = X[root[unk]]
        else:
            N = geo.get(POINT, "N")
            if N is None:
                from .ops import compute_normals
                N = compute_normals(geo, "point").get(POINT, "N")
            N = np.asarray(N, np.float64)
            N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            # at the source points split into tangential + normal; the tangential part is parallel transported step by step along the shortest path (the minimal
            # rotation between neighbouring point normals), the normal component is copied directly as Scalar (docs: with Tangential Only off the normal goes as Scalar)
            nc = np.einsum("ij,ij->i", X, N)
            T = X - nc[:, None] * N
            order = np.argsort(np.asarray(_dist_order(prev, n)), kind="stable")
            for i in order:
                if not unk[i]:
                    continue
                p = prev[i]
                # the minimal rotation takes N[p] to N[i]; the rotated tangent vector stays perpendicular to N[i], no reprojection needed
                T[i] = _rotate_between(T[p], N[p], N[i])
            Y = T.copy()
            if not tangential_only:
                Y[unk] = T[unk] + nc[root[unk]][:, None] * N[unk]
            if float(global_rotation):
                th = np.radians(float(global_rotation))
                c, s = np.cos(th), np.sin(th)
                # rotate only the tangential part, around each point's normal
                Tn = Y - np.einsum("ij,ij->i", Y, N)[:, None] * N
                Y = Y + (Tn * (c - 1.0) + np.cross(N, Tn) * s)
            keep = ~unk                       # source points and unreachable points keep their original values
            Y[keep] = X[keep]
        out = geo.copy()
        out.set(POINT, name, Y.astype(a.dtype), owned=True)
        return out, rep

    # Poisson / Diffusion: edge weight 1 / max(edge length, Minimum Edge Length).
    # 1/l is the "flux continuity" weight on a 1D chain -- on unevenly spaced points the Poisson solution is linear in arc length
    lm = np.maximum(ln, float(min_edge_length))
    a_, b_ = E[:, 0], E[:, 1]
    if method == "poisson":
        w = 1.0 / np.maximum(lm, 1e-300)
        G = None
        if str(match_attribute).strip():
            ga = geo.get(POINT, match_attribute.strip())
            if ga is None or is_string(ga):
                raise KeyError(f"Attribute to Match: no numeric point attribute '{match_attribute}'")
            G = np.asarray(ga, np.float64)
            if G.shape[1] not in (1, X.shape[1]):
                raise ValueError(f"Attribute to Match has {G.shape[1]} components, needs 1 or {X.shape[1]}")
            G = np.broadcast_to(G, X.shape)
            om = np.ones(n)
            if str(weight_attribute).strip():
                om = np.clip(_point_scalar(geo, weight_attribute.strip(), "Weight Attribute", n),
                             0.0, 1.0)
            omg = 0.5 * (om[a_] + om[b_])  # the guide strength on an edge is the average of both ends (the docs do not say how it maps to edges)
        unk = ~known & reach
        free = unk
        deg = np.bincount(a_, weights=w, minlength=n) + np.bincount(b_, weights=w, minlength=n)

        def nbr_sum(x):
            return (np.bincount(a_, weights=w * x[b_], minlength=n)
                    + np.bincount(b_, weights=w * x[a_], minlength=n))

        def A(v):
            v = np.where(free, v, 0.0)
            return np.where(free, deg * v - nbr_sum(v), 0.0)
        Y = X.copy()
        for c in range(X.shape[1]):
            xk = np.where(known, X[:, c], 0.0)
            b = nbr_sum(xk)
            if G is not None:
                # min Σ w (x_i − x_j − ω (g_i − g_j))²: the normal equations' right-hand side gets an extra term Σ_j w ω (g_i − g_j)
                d = w * omg * (G[a_, c] - G[b_, c])
                b = b + np.bincount(a_, weights=d, minlength=n) - np.bincount(b_, weights=d, minlength=n)
            b = np.where(free, b, 0.0)
            y = _cg_solve(A, b, free)
            Y[:, c] = np.where(free, y, X[:, c])
        Y[~known & ~reach] = 0.0             # docs: points not connected to the Boundary Group get the default value
        rep["filled"] = int(unk.sum())
        rep["unreachable"] = int((~known & ~reach).sum())
        out = geo.copy()
        out.set(POINT, name, Y.astype(a.dtype), owned=True)
        return out, rep

    # Diffusion: one implicit step (I + t L) x = x0, the rate on an edge = average Speed of both ends (clamped to Minimum Speed),
    # edge weight = rate / edge length² (on a uniform 1D grid this is the standard finite difference of ∂x/∂t = k ∂²x/∂s²).
    # Boundary Group points are fixed (sources). For multiple steps loop this node (wording from the docs)
    k_e = np.ones(len(E)) if sp is None else 0.5 * (sp[a_] + sp[b_])
    w = np.maximum(k_e, float(min_speed)) / np.maximum(lm * lm, 1e-300)
    t = float(diffusion_time)
    free = ~known
    deg = np.bincount(a_, weights=w, minlength=n) + np.bincount(b_, weights=w, minlength=n)

    def nbr_sum(x):
        return (np.bincount(a_, weights=w * x[b_], minlength=n)
                + np.bincount(b_, weights=w * x[a_], minlength=n))

    def A(v):
        v = np.where(free, v, 0.0)
        return np.where(free, v + t * (deg * v - nbr_sum(v)), 0.0)
    Y = X.copy()
    for c in range(X.shape[1]):
        b = np.where(free, X[:, c] + t * nbr_sum(np.where(known, X[:, c], 0.0)), 0.0)
        y = _cg_solve(A, b, free, x0=X[:, c])
        Y[:, c] = np.where(free, y, X[:, c])
    rep["filled"] = int(free.sum())
    out = geo.copy()
    out.set(POINT, name, Y.astype(a.dtype), owned=True)
    return out, rep


def _dist_order(prev, n):
    """Depth of each point on the shortest-path tree (parents processed before children)."""
    depth = np.full(n, -1, np.int64)
    prev = np.asarray(prev)
    for i in range(n):
        if depth[i] >= 0:
            continue
        chain = []
        j = i
        while j >= 0 and depth[j] < 0:
            chain.append(j)
            j = prev[j]
        base = depth[j] if j >= 0 else -1
        for m in reversed(chain):
            base += 1
            depth[m] = base
    return depth


def attrib_fill(geo, attribute, known_group="", method="harmonic",
                weights="uniform", iterations=50, tolerance=1e-10,
                speed_attribute="", match_attribute="", weight_attribute="",
                min_edge_length=1e-6, min_speed=1e-3, diffusion_time=1.0,
                unreachable_time=-1.0, extrapolation="scalar", tangential_only=True,
                global_rotation=0.0):
    """
    Mirrors Houdini's Attribute Fill: a point attribute is only meaningful on some points (known), and is
    filled along the **topology** onto the remaining points.

    Known points = known_group; when empty, "points where the attribute is not all 0".
    method:
      harmonic  harmonic interpolation: unknown points satisfy "equal to the weighted average of the neighbours" (graph Laplacian = 0,
                known points as boundary conditions), solved by conjugate gradient to tolerance. The result is smooth with no
                overshoot (extrema only at known points) -- the proper meaning of "fill", not blurring
      nearest   the value of the nearest known point along edges (multi-source Dijkstra, edge length as distance) -- partitioning
      diffuse   iterations rounds of weighted averaging (known points pinned). With enough iterations it converges to harmonic;
                with few iterations it is a soft transition seeping out only one ring
    weights: uniform (1 per edge) or inverse_length (short edges weigh more).
    Points not connected to any known point keep their original values and are counted in the report. Returns (geometry, report).

    The last four modes are Houdini's Mode (pcg100 s7, see _fill_houdini):
      eikonal      shortest arrival time along edges (edge length / Speed of the starting point), does not read input values
      poisson      harmonic fill with edge weight 1/edge length, optionally with Attribute to Match + Weight Attribute;
                   unconnected points get 0 (docs: the default value)
      diffusion    one implicit step (I + t L) x = x0, Boundary Group being the fixed sources
      extrapolate  Scalar (= nearest) / Parallel Transport (tangential part parallel transported along the shortest path)
    """
    if method not in FILL_METHODS:
        raise ValueError(f"Method must be one of {FILL_METHODS}")
    if weights not in FILL_WEIGHTS:
        raise ValueError(f"Weights must be one of {FILL_WEIGHTS}")
    if extrapolation not in FILL_EXTRAP:
        raise ValueError(f"Extrapolation Type must be one of {FILL_EXTRAP}")
    name = str(attribute).strip()
    a = geo.get(POINT, name) if name else None
    if method == "eikonal":
        # Eikonal does not read input values (docs), so the attribute may not exist yet
        if not name:
            raise ValueError("Attribute cannot be empty")
        return _fill_houdini(geo, None, name, a, known_group, method, speed_attribute,
                             match_attribute, weight_attribute, min_edge_length, min_speed,
                             diffusion_time, unreachable_time, extrapolation,
                             tangential_only, global_rotation)
    if a is None or is_string(a):
        raise KeyError(f"No numeric point attribute '{name}'")
    X = np.asarray(a, np.float64).copy()
    if method in ("poisson", "diffusion", "extrapolate"):
        return _fill_houdini(geo, X, name, a, known_group, method, speed_attribute,
                             match_attribute, weight_attribute, min_edge_length, min_speed,
                             diffusion_time, unreachable_time, extrapolation,
                             tangential_only, global_rotation)
    n = geo.npoints
    if str(known_group).strip():
        known = resolve(geo, POINT, known_group)
    else:
        known = np.any(X != 0, axis=1)
    if not known.any():
        raise ValueError("No known points (Known Group is empty / attribute is 0 everywhere)")
    E, w = _edge_graph(geo, weights)
    lab = _components(n, E)
    has_known = np.zeros(n, bool)
    has_known[np.unique(lab[known])] = True
    reach = has_known[lab]
    unk = ~known & reach
    rep = {"known": int(known.sum()), "filled": int(unk.sum()),
           "unreachable": int((~known & ~reach).sum())}
    if not unk.any():
        return geo.copy(), rep
    if method == "nearest":
        from .paths import _adjacency, dijkstra
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        ln = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
        _, _, root = dijkstra(_adjacency(n, E, np.maximum(ln, 1e-12)),
                              np.nonzero(known)[0].tolist())
        root = np.asarray(root)
        ok = unk & (root >= 0)
        X[ok] = X[root[ok]]
    else:
        a_, b_ = E[:, 0], E[:, 1]
        deg = np.bincount(a_, weights=w, minlength=n) + \
            np.bincount(b_, weights=w, minlength=n)

        def nbr_sum(x):
            return (np.bincount(a_, weights=w * x[b_], minlength=n)
                    + np.bincount(b_, weights=w * x[a_], minlength=n))
        for c in range(X.shape[1]):
            x = X[:, c].copy()
            if method == "diffuse":
                for _ in range(int(iterations)):
                    avg = nbr_sum(x) / np.where(deg > 0, deg, 1)
                    x = np.where(unk & (deg > 0), avg, x)
            else:
                # solve L_UU x_U = W_UK x_K: put the known values into x, unknown positions start at 0
                xk = np.where(known, x, 0.0)
                b = np.where(unk, nbr_sum(xk), 0.0)

                def A(v):
                    v = np.where(unk, v, 0.0)
                    return np.where(unk, deg * v - nbr_sum(v), 0.0)
                y = np.where(unk, x, 0.0)
                r = b - A(y)
                p = r.copy()
                rr = r @ r
                bn = max(np.sqrt(b @ b), 1e-300)
                for _ in range(max(10 * int(unk.sum()), 100)):
                    if np.sqrt(rr) <= tolerance * bn:
                        break
                    Ap = A(p)
                    al = rr / max(p @ Ap, 1e-300)
                    y = y + al * p
                    r = r - al * Ap
                    rn = r @ r
                    p = r + (rn / rr) * p
                    rr = rn
                x = np.where(unk, y, x)
            X[:, c] = x
    out = geo.copy()
    out.set(POINT, name, X.astype(a.dtype), owned=True)
    return out, rep


# ═══════════════════════════════════════════════════ Attribute String Edit
def _wild_to_regex(pat, case):
    parts = [re.escape(p) for p in pat.split("*")]
    return re.compile("^" + "(.*?)".join(parts) + "$",
                      0 if case else re.IGNORECASE)


def string_edit(geo, cls="prim", attributes="name", group="", find="",
                replace="", mode="substring", case_sensitive=True):
    """
    Mirrors Houdini's Attribute String Edit: find and replace on string attributes.

      substring  replace occurrences of find with replace (all occurrences)
      wildcard   match the whole string against a pattern with *, and fill what each * captured, in order, into the * in replace:
                 find "piece*_old" + replace "chunk*" turns piece12_old into chunk12
      regex      regular expression replacement (re.sub, use \\1 in replace to reference groups)
    attributes can list several names and supports wildcards (the uv* style). Non-matching values stay untouched.
    Only distinct values are processed (np.unique), so 100k points with the same name are computed once. Returns (geometry, report).
    """
    cls = _cls(cls) if cls != "detail" else DETAIL
    if mode not in STREDIT_MODES:
        raise ValueError(f"Mode must be one of {STREDIT_MODES}")
    from .ops import match_names
    out = geo.copy()
    names = [k for k in match_names(list(geo.attribs[cls].keys()), attributes)
             if is_string(geo.get(cls, k))]
    if not names:
        raise KeyError(f"No {cls} string attribute matching '{attributes}'")
    f, rpl = str(find), str(replace)
    if mode == "wildcard":
        rx = _wild_to_regex(f, case_sensitive)
        nstar = f.count("*")
        if rpl.count("*") > nstar:
            raise ValueError(f"Replace has more * than Find ({rpl.count('*')} > "
                             f"{nstar}); the extra ones have nothing to fill in")
    elif mode == "regex":
        try:
            rx = re.compile(f, 0 if case_sensitive else re.IGNORECASE)
        except re.error as ex:
            raise ValueError(f"Find is not a valid regular expression: {ex}")

    def edit(s):
        if mode == "substring":
            if not f:
                return s
            if case_sensitive:
                return s.replace(f, rpl)
            return re.sub(re.escape(f), lambda _: rpl, s, flags=re.IGNORECASE)
        if mode == "regex":
            return rx.sub(rpl, s)
        m = rx.match(s)
        if not m:
            return s
        caps = list(m.groups())
        res = []
        for ch in rpl:
            res.append(caps.pop(0) if ch == "*" and caps else ch)
        return "".join(res)

    sel = resolve(geo, cls, group) if cls != DETAIL else None
    changed = 0
    for k in names:
        v = np.asarray(geo.get(cls, k)).astype(str)
        col = v[:, 0]
        uniq, inv = np.unique(col, return_inverse=True)
        new = np.array([edit(u) for u in uniq])
        res = new[inv.reshape(-1)]
        if sel is not None:
            res = np.where(sel, res, col)
        changed += int((res != col).sum())
        out.set_string(cls, k, res[:, None])
    return out, {"attributes": names, "changed": changed}


# ═══════════════════════════════════════════════════════════ Cluster Points
def _assign(X, C):
    m = len(X)
    best = np.full(m, np.inf)
    lab = np.zeros(m, np.int64)
    for s in range(0, m, 65536):
        xs = X[s:s + 65536]
        d = ((xs[:, None, :] - C[None]) ** 2).sum(2)
        lab[s:s + 65536] = d.argmin(1)
        best[s:s + 65536] = d.min(1)
    return lab, best


def _lloyd(X, C, iterations):
    """
    Lloyd iteration: assign -> take means, until assignments stop changing or iterations run out. When a cluster is emptied, the point
    farthest from its own center becomes the new center (otherwise a cluster would be lost). Returns (labels, centers, squared distance of each point
    to its center, iteration count).
    """
    k = len(C)
    lab, best = _assign(X, C)
    it = 0
    for it in range(1, int(iterations) + 1):
        cnt = np.bincount(lab, minlength=k)
        newC = np.zeros_like(C)
        for c in range(X.shape[1]):
            newC[:, c] = np.bincount(lab, weights=X[:, c], minlength=k)
        empty = cnt == 0
        newC[~empty] /= cnt[~empty, None]
        for e in np.nonzero(empty)[0]:
            far = int(best.argmax())
            newC[e] = X[far]
            best[far] = 0.0
        lab2, best = _assign(X, newC)
        C = newC
        if np.array_equal(lab2, lab) and not empty.any():
            lab = lab2
            break
        lab = lab2
    return lab, C, best, it


CLUSTER_OUTPUTS = ("cluster_points", "average_points", "both", "boxes")
CLUSTER_COLORS = ("points", "colored_points", "colored_particles")


def cluster_points(geo, clusters=8, attribute="P", group="", iterations=30,
                   seed=0, name="cluster", output="cluster_points", color_output="points",
                   cluster_filter="", weight=1.0, controls=(), build_clusters=True,
                   copy_attribs=False, max_samples=10, size_attrib="scale",
                   pad_min=(0.0, 0.0, 0.0), pad_max=(0.0, 0.0, 0.0)):
    """
    Mirrors Houdini's Cluster Points (and the old Cluster SOP): k-means splits the points into
    clusters clusters, writing the integer attribute name. Clusters by the values of attribute (P by default, or e.g. Cd
    for color patches).

    Initialized with k-means++ (drawn weighted by squared distance to the already chosen centers; reproducible with a fixed seed), then
    Lloyd iterations until assignments stop changing or iterations run out. When a cluster is emptied, the point farthest from its own center
    becomes the new center -- otherwise a cluster would be lost.
    Returns (geometry, center point cloud (with name and count), report: iteration count, total squared error).
    """
    if output not in CLUSTER_OUTPUTS:
        raise ValueError(f"Output must be one of {CLUSTER_OUTPUTS}")
    if color_output not in CLUSTER_COLORS:
        raise ValueError(f"Color Output must be one of {CLUSTER_COLORS}")
    post = dict(output=output, color_output=color_output, cluster_filter=cluster_filter,
                copy_attribs=copy_attribs, max_samples=max_samples, size_attrib=size_attrib,
                pad_min=pad_min, pad_max=pad_max, seed=seed)
    nm = str(name).strip() or "cluster"
    sel = np.nonzero(resolve(geo, POINT, group))[0]
    if not build_clusters:
        lab, k = _existing_clusters(geo, nm, sel)
        main, _, rep = _cluster_post(geo, lab, k, nm, **post)
        # the center point output looks the same as when building clusters (P = cluster mean, cluster, count); empty clusters have count 0 and P at the origin
        P = np.asarray(geo.get(POINT, "P"), np.float64)
        ok = lab >= 0
        cnt = np.bincount(lab[ok], minlength=k)
        Pc = np.stack([np.bincount(lab[ok], weights=P[ok, c], minlength=k)
                       for c in range(3)], 1) / np.maximum(cnt, 1)[:, None]
        cen = Geometry.from_points(Pc.reshape(-1, 3))
        cen.set(POINT, nm, np.arange(k, dtype=np.int32)[:, None], owned=True)
        cen.set(POINT, "count", cnt[:, None].astype(np.int32), owned=True)
        return main, cen, rep
    k = int(clusters)
    if k < 1:
        raise ValueError("Clusters must be at least 1")
    an = str(attribute).strip() or "P"
    a = geo.get(POINT, an)
    if a is None or is_string(a):
        raise KeyError(f"No numeric point attribute '{an}'")
    X = np.asarray(a, np.float64)[sel]
    # Control Attributes + Weight: each attribute is multiplied by its own weight and concatenated into one feature vector ("linear weights").
    # With a single attribute and weight 1 it is the old behaviour (no multiplication, bitwise unchanged)
    if float(weight) != 1.0:
        X = X * float(weight)
    for cn, cw in controls:
        cn = str(cn).strip()
        if not cn:
            continue
        c = geo.get(POINT, cn)
        if c is None or is_string(c):
            raise KeyError(f"No numeric point attribute '{cn}' (Control Attribute)")
        X = np.concatenate([X, np.asarray(c, np.float64)[sel] * float(cw)], 1)
    m = len(X)
    out = geo.copy()
    if m == 0:
        return out, Geometry(), {"iterations": 0}
    k = min(k, m)
    rng = np.random.default_rng(int(seed))
    C = [X[rng.integers(m)]]
    d2 = ((X - C[0]) ** 2).sum(1)
    for _ in range(1, k):
        tot = d2.sum()
        i = int(rng.integers(m)) if tot <= 0 else \
            int(np.searchsorted(np.cumsum(d2), rng.random() * tot))
        C.append(X[min(i, m - 1)])
        d2 = np.minimum(d2, ((X - C[-1]) ** 2).sum(1))
    C = np.array(C)

    lab, C, best, it = _lloyd(X, C, int(iterations))
    full = np.full(geo.npoints, -1, np.int32)
    full[sel] = lab
    cur = geo.get(POINT, name)
    if cur is not None and not is_string(cur) and cur.shape[1] == 1:
        keep = np.asarray(cur, np.int32)[:, 0].copy()
        keep[sel] = lab
        full = keep
    out.set(POINT, str(name).strip() or "cluster", full[:, None], owned=True)
    # center point cloud: P averaged per cluster (equal to C when clustering by P)
    P = np.asarray(geo.get(POINT, "P"), np.float64)[sel]
    cnt = np.bincount(lab, minlength=k)
    Pc = np.stack([np.bincount(lab, weights=P[:, c], minlength=k)
                   for c in range(3)], 1) / np.maximum(cnt, 1)[:, None]
    cen = Geometry.from_points(Pc)
    cen.set(POINT, str(name).strip() or "cluster",
            np.arange(k, dtype=np.int32)[:, None], owned=True)
    cen.set(POINT, "count", cnt[:, None].astype(np.int32), owned=True)
    sse = float(best.sum())
    rep = {"iterations": it, "sse": sse, "clusters": int(k)}
    if _plain(post):
        return out, cen, rep
    pure = np.full(geo.npoints, -1, np.int64)               # points outside the group belong to no cluster
    pure[sel] = lab
    main, _, _ = _cluster_post(geo, pure, k, nm, **post)
    return main, cen, rep


def _plain(post):
    """All new parameters at defaults -> the main output is just the old "original points with a cluster attribute", no further processing."""
    return (post["output"] == "cluster_points" and post["color_output"] == "points"
            and not str(post["cluster_filter"]).strip())


def _existing_clusters(geo, nm, sel):
    """Build Clusters off: use the cluster attribute already on the geometry directly (points outside the group get −1)."""
    cur = geo.get(POINT, nm)
    if cur is None or is_string(cur):
        raise KeyError(f"With Build Clusters off the points must already have the integer attribute '{nm}'")
    lab = np.full(geo.npoints, -1, np.int64)
    lab[sel] = np.rint(np.asarray(cur, np.float64)[sel, 0]).astype(np.int64)
    k = int(lab.max()) + 1 if (lab >= 0).any() else 0
    return lab, k


def _cluster_post(geo, lab, k, nm, output, color_output, cluster_filter, copy_attribs,
                  max_samples, size_attrib, pad_min, pad_max, seed):
    """
    The Output / Color Output / Cluster Filter / Averaging part. Returns (main output, center points, report).

        cluster_points  original points + cluster attribute (old behaviour)
        average_points  one point per cluster: P = mean of the cluster's points, size_attrib = bounding-box size + padding on both ends
        both            the two merged, groups clusterpoints / averagepoints
        boxes           one bounding box per cluster (+ padding), prim attribute cluster
    Cluster Filter picks cluster numbers with the same syntax as point numbers ("3 4", "3-6"); once picked, points outside the group (−1) are not output either.
    Colored Points / Colored Particles give each cluster a random Cd (we have no particle system, so both modes give the same result).
    """
    from .ops import merge
    from .build import box
    lab = np.asarray(lab, np.int64)
    out = geo.copy()
    full = lab.astype(np.int32)
    cur = geo.get(POINT, nm)
    if cur is not None and not is_string(cur) and cur.shape[1] == 1:
        keep = np.asarray(cur, np.int32)[:, 0].copy()
        keep[lab >= 0] = full[lab >= 0]
        full = keep
    out.set(POINT, nm, full[:, None], owned=True)
    P = np.asarray(geo.get(POINT, "P"), np.float64)
    want = np.ones(max(k, 0), bool)
    if str(cluster_filter).strip():
        want = resolve(Geometry(max(k, 0)), POINT, cluster_filter)
    colored = color_output != "points"
    pal = np.random.default_rng([int(seed) & 0xFFFFFFFF, 0xC0105]).random((max(k, 1), 3))

    ids = [c for c in range(k) if want[c] and (lab == c).any()]
    if colored:
        cd = np.where((lab >= 0)[:, None], pal[np.maximum(lab, 0)], 1.0)
        out.set(POINT, "Cd", cd.astype(np.float32), owned=True)
    if str(cluster_filter).strip():
        from .ops import delete_points
        keep = (lab >= 0) & want[np.clip(lab, 0, max(k - 1, 0))] if k else np.zeros(
            len(lab), bool)
        out = delete_points(out, keep)
    rep = {"clusters": int(k), "output_clusters": len(ids)}
    if output == "cluster_points":
        return out, None, rep

    pmin = np.asarray(pad_min, np.float64)
    pmax = np.asarray(pad_max, np.float64)
    avg = Geometry.from_points(np.array([P[lab == c].mean(0) for c in ids]).reshape(-1, 3))
    avg.set(POINT, nm, np.array(ids, np.int32).reshape(-1, 1))
    lo = np.array([P[lab == c].min(0) for c in ids]).reshape(-1, 3) - pmin
    hi = np.array([P[lab == c].max(0) for c in ids]).reshape(-1, 3) + pmax
    if str(size_attrib).strip():
        avg.set(POINT, str(size_attrib).strip(), (hi - lo).astype(np.float32))
    if colored:
        avg.set(POINT, "Cd", pal[ids].astype(np.float32).reshape(-1, 3))
    if copy_attribs and ids:
        _copy_from_cluster(geo, avg, lab, ids, P, nm, int(max_samples), size_attrib)
    if output == "average_points":
        return avg, None, rep
    if output == "both":
        a, b = out.copy(), avg.copy()
        a.set_group(POINT, "clusterpoints", np.ones(a.npoints, bool))
        b.set_group(POINT, "averagepoints", np.ones(b.npoints, bool))
        return merge(a, b), None, rep
    boxes = []
    for j, c in enumerate(ids):
        bx = box(size=tuple(hi[j] - lo[j]), center=tuple(0.5 * (hi[j] + lo[j])))
        bx.set(PRIM, nm, np.full((bx.nprims, 1), c, np.int32))
        if colored:
            bx.set(PRIM, "Cd", np.tile(pal[c], (bx.nprims, 1)).astype(np.float32))
        boxes.append(bx)
    return merge(*boxes), None, rep


def _copy_from_cluster(geo, avg, lab, ids, P, nm, ns, size_attrib):
    """
    Copy Point Attributes from Cluster: a center point's attributes = the average of the Max Sample Count points of the cluster nearest to it
    (numeric attributes); string attributes take the nearest point. Already written ones like P, cluster, Cd / size are not overwritten.
    """
    skip = {"P", nm, str(size_attrib).strip()} | set(avg.attribs[POINT])
    ns = max(1, ns)
    near = []
    for j, c in enumerate(ids):
        idx = np.nonzero(lab == c)[0]
        d = np.linalg.norm(P[idx] - np.asarray(avg.get(POINT, "P"), np.float64)[j], axis=1)
        near.append(idx[np.argsort(d, kind="stable")[:ns]])
    for k, v in geo.attribs[POINT].items():
        if k in skip:
            continue
        v = np.asarray(v)
        if is_string(v):
            val = np.array([v[n[0]] for n in near])
        else:
            val = np.array([v[n].astype(np.float64).mean(0) for n in near]).astype(v.dtype)
        avg.set(POINT, k, val.reshape(len(ids), -1))
