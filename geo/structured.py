"""
Structured input -- a piece of **JSON text** becomes geometry. Item 2 on the list.

Up to the previous batch, the only things AI could give this plugin were **pixels** (control images, textures) and
**shapes** (Import Mesh). But what LLMs / VLMs are best at outputting is actually a third thing: **structure** --
layouts, bboxes, labels, classes, "this part should be roof". Not one of the 161 nodes had a JSON
entry point (Wrangle takes code, which does not count), so this kind of output could not get into the graph at all.

With this added the chain is:

    LLM / VLM (emits JSON) -> From JSON -> points / boxes / curves + attributes + groups
    -> Copy to Points / PolyExtrude / group by name / Switch routing

**AI plans, procedural executes.** It pairs with the previous batch's Attrib from Camera: that one carries
"where", this one carries "what, how many, what is it called".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Parsing must be **tolerant**, but when it tolerates something it must say so
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What models emit is almost never clean JSON: wrapped in ```json fences, preceded by a sentence like
"Here is the layout:", a trailing comma at the end. If a human had to strip these each time, nobody would use this node.

So parsing is a **four-step ladder**: parse directly -> strip ``` fences -> extract the **first balanced**
`[...]` / `{...}` from the text -> remove trailing commas and parse again.

But the fact that "it was fixed" must be **written into the info output**. Silent fixes are the hardest kind to track down: it runs today,
tomorrow the model changes its format, and you think your own graph broke. So info states which step of the ladder was used.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Keys -> attributes: the conventional names are **aligned automatically**, the rest are carried over as is
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`P` / `pos` / `position` / `translate` all land on `P`, `color` / `Cd` land on `Cd`
(and hex like `"#ff8800"` is recognized -- models love writing colors). This is not "convenience", it is
**necessary**: models use different key names every time, and without aligning them you would have to change the graph with every prompt.

Keys that do not match become attributes as is, typed by value: number -> float, fixed-length array -> vector, string ->
string attribute. **Arrays of uneven length are an error** rather than zero-padded: a "vector" attribute mixing 3 and 2
components means nothing downstream, and zero-padding only pushes the error further along. Missing keys are different -- they are
the norm, so they are zero-filled and the count is reported in info.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The reverse is done too: geometry -> JSON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"AI plans the layout" presupposes that it **can see the current layout**. `dumps()` exports the geometry's attributes as the same
JSON to feed back to the model. As a side effect this gives the whole thing its hardest criterion: **round-trip bit-identical**.
"""
from __future__ import annotations

import json
import re

import numpy as np

from .core import Geometry, POINT, PRIM, DETAIL, is_string
from . import ops as _ops
from . import build as _build

MODES = ("points", "boxes", "curves")
PLANES = ("xz", "xy", "yz")
# conventional key names -> attribute names in this package. **Case-insensitive**
ALIASES = {
    "p": "P", "pos": "P", "position": "P", "translate": "P", "t": "P",
    "xyz": "P", "loc": "P", "location": "P",
    "n": "N", "normal": "N", "nml": "N", "up": "N",
    "cd": "Cd", "color": "Cd", "colour": "Cd", "rgb": "Cd",
    "scale": "scale", "size": "scale", "s": "scale",
    "pscale": "pscale", "radius": "pscale", "r": "pscale",
    "rot": "rot", "rotate": "rot", "rotation": "rot", "euler": "rot",
    "orient": "orient", "quat": "orient", "quaternion": "orient",
    "v": "v", "vel": "v", "velocity": "v",
    "name": "name", "label": "name", "type": "name", "kind": "name",
    "tag": "name", "category": "name", "id": "id", "index": "id",
    "class": "class", "group": "class", "piece": "class",
}
# these keys are "the geometry itself" and are not written a second time as ordinary attributes
SHAPE_KEYS = {"bbox", "box", "bounds", "min", "max", "points", "pts",
              "path", "polyline", "closed", "verts", "vertices"}
_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


# ═══════════════════════════════════════════════════════ tolerant parsing
def strip_fences(text):
    """Strip ```json ... ``` fences. Returns (text, whether used)."""
    s = str(text or "")
    m = re.search(r"```[ \t]*(?:json|JSON|jsonc|json5)?[ \t]*\r?\n(.*?)```",
                  s, re.S)
    if m:
        return m.group(1), True
    return s, False


def _balanced(s):
    """
    Extract the **first balanced** [...] or {...} from the text.

    Scans character by character, and must skip brackets inside strings -- otherwise `{"note": "a ] b"}`
    closes early at that ], extracts half a segment, and the error reported is still "invalid JSON".
    """
    start = None
    for i, c in enumerate(s):
        if c in "[{":
            start = i
            break
    if start is None:
        return None
    open_c = s[start]
    close_c = "]" if open_c == "[" else "}"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _drop_trailing_commas(s):
    """`[1, 2, ]` -> `[1, 2 ]`. Only touches things **outside strings**."""
    out, in_str, esc = [], False, False
    for i, c in enumerate(s):
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            out.append(c)
            continue
        if c == ",":
            j = i + 1
            while j < len(s) and s[j] in " \t\r\n":
                j += 1
            if j < len(s) and s[j] in "]}":
                out.append(" ")          # use a space as placeholder so column numbers stay the same and errors are readable
                continue
        out.append(c)
    return "".join(out)


def loads(text):
    """
    Tolerant parsing -> (data, description of steps). See the module doc for the steps.

    The description string is carried all the way into the info output -- **whatever was fixed must be said**.
    """
    raw = str(text or "")
    if not raw.strip():
        raise ValueError("The input is empty -- connect a node that outputs JSON, or paste some in directly")
    steps = []
    s, fenced = strip_fences(raw)
    if fenced:
        steps.append("stripped ``` fences")
    try:
        return json.loads(s), "+".join(steps) if steps else "clean"
    except json.JSONDecodeError as e0:
        first = e0
    cut = _balanced(s)
    if cut is not None and cut != s.strip():
        steps.append("extracted a JSON segment from the text")
        s = cut
        try:
            return json.loads(s), "+".join(steps)
        except json.JSONDecodeError:
            pass
    fixed = _drop_trailing_commas(s)
    if fixed != s:
        steps.append("removed trailing commas")
        try:
            return json.loads(fixed), "+".join(steps)
        except json.JSONDecodeError:
            pass
    raise ValueError(
        f"This is not valid JSON. Line {first.lineno}, column {first.colno}: "
        f"{first.msg}\n  this line: {_line_of(s, first.lineno)}\n"
        f"  (already tried stripping fences / extracting a JSON segment / removing trailing commas)")


def _line_of(s, n):
    lines = str(s).splitlines()
    return lines[n - 1].strip()[:80] if 0 < n <= len(lines) else ""


def records(data, path="auto"):
    """
    -> (list of records, dict of top-level scalars).

    Models wrap JSON in all sorts of ways: a bare array, `{"items": [...]}`,
    `{"objects": [...], "seed": 3}`. `auto` mode picks **the first list consisting entirely of objects**;
    if none is found it errors and lists the top-level keys -- far more useful than "the result is empty".
    """
    detail = {}
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        p = str(path or "auto").strip()
        if p and p != "auto":
            cur = data
            for part in p.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    raise ValueError(
                        f"path '{p}': cannot find '{part}'. Top-level keys: "
                        f"{sorted(data.keys())}")
                cur = cur[part]
            items = cur
        else:
            items = None
            for k, v in data.items():
                if isinstance(v, list) and v and all(isinstance(x, dict)
                                                     for x in v):
                    items = v
                    break
            if items is None:
                # a single object also counts as one record -- that is what happens when the model generates only one thing
                if any(not isinstance(v, (list, dict)) for v in data.values()):
                    items = [data]
                else:
                    raise ValueError(
                        f"No list of records found in this JSON. Top-level keys: "
                        f"{sorted(data.keys())}. Use the path parameter to point at that list, "
                        f"e.g. path=items")
        for k, v in data.items():
            if not isinstance(v, (list, dict)):
                detail[k] = v
    else:
        raise ValueError(f"The top level must be an array or object, got {type(data).__name__}")
    if not isinstance(items, list):
        raise ValueError(f"path does not point to an array but to {type(items).__name__}")
    out = []
    for i, r in enumerate(items):
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, (list, tuple)) and all(
                isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in r):
            out.append({"P": list(r)})        # a bare coordinate table like [[x,y,z], ...]
        else:
            raise ValueError(
                f"Record {i} is neither an object nor a coordinate array but "
                f"{type(r).__name__}:{str(r)[:60]}")
    return out, detail


# ═════════════════════════════════════════════════════ keys -> attributes
def _flatten(rec, prefix=""):
    """Flatten nested objects into `a.b`. Models love wrapping things in a transform / properties layer."""
    out = {}
    for k, v in rec.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def canon(key):
    """Key name -> attribute name. Known ones are aligned, unknown ones kept as is (only invalid characters replaced with _)."""
    k = str(key).strip()
    a = ALIASES.get(k.lower())
    if a:
        return a
    out = re.sub(r"[^0-9A-Za-z_.]", "_", k)
    return out or "attr"


def _hex_rgb(s):
    m = _HEX.match(str(s).strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _vec(v, n, fill=0.0):
    v = list(v)[:n]
    return v + [fill] * (n - len(v))


def columns(recs, color_hex=True):
    """
    List of records -> {attribute name: (list of values, width, is string)} + stats.

    Arrays of uneven length are an **error**, missing keys are zero-filled -- see the module header for why.
    """
    flat = [_flatten(r) for r in recs]
    order, kind, width = [], {}, {}
    for f in flat:
        for k in f:
            name = canon(k)
            if k.split(".")[0].lower() in SHAPE_KEYS:
                continue
            if name not in kind:
                order.append(name)
                kind[name] = None
                width[name] = 1
    filled = 0
    cols = {}
    for name in order:
        vals, w, is_str = [], 1, False
        for f in flat:
            v = None
            for k in f:
                if canon(k) == name and k.split(".")[0].lower() \
                        not in SHAPE_KEYS:
                    v = f[k]
                    break
            vals.append(v)
        for v in vals:
            if v is None:
                continue
            if isinstance(v, str):
                if color_hex and name == "Cd" and _hex_rgb(v) is not None:
                    w = max(w, 3)
                    continue
                is_str = True
            elif isinstance(v, (list, tuple)):
                if not all(isinstance(x, (int, float))
                           and not isinstance(x, bool) for x in v):
                    is_str = True
                else:
                    w = max(w, len(v))
        if not is_str:
            lens = {len(v) for v in vals
                    if isinstance(v, (list, tuple))}
            if len(lens) > 1:
                raise ValueError(
                    f"Attribute '{name}' has arrays of different lengths ({sorted(lens)}) -- "
                    f"padding them makes no sense; write them with the same number of components, "
                    f"or use different key names")
        out = []
        for v in vals:
            if v is None:
                filled += 1
                out.append("" if is_str else [0.0] * w)
            elif is_str:
                out.append(v if isinstance(v, str) else json.dumps(
                    v, ensure_ascii=False))
            elif isinstance(v, str):
                out.append(_vec(_hex_rgb(v), w))
            elif isinstance(v, (list, tuple)):
                out.append(_vec([float(x) for x in v], w))
            elif isinstance(v, bool):
                out.append(_vec([1.0 if v else 0.0], w))
            else:
                out.append(_vec([float(v)], w))
        cols[name] = (out, w, is_str)
    return cols, {"filled": filled}


def _apply(geo, cls, cols, skip=("P",)):
    for name, (vals, w, is_str) in cols.items():
        if name in skip:
            continue
        if is_str:
            geo.set_string(cls, name, [str(v) for v in vals])
        else:
            geo.set(cls, name, np.asarray(vals, np.float64).reshape(-1, w),
                    dtype=np.float32, owned=True)
    return geo


def _groups(geo, cls, cols, group_by):
    """Create groups from the values of a string attribute. Classes assigned by the AI become usable groups directly."""
    name = canon(str(group_by).strip()) if str(group_by).strip() else ""
    if not name or name not in cols:
        return 0
    vals, _w, is_str = cols[name]
    keys = [str(v) if is_str else json.dumps(v) for v in vals]
    made = 0
    for u in dict.fromkeys(keys):
        safe = re.sub(r"[^0-9A-Za-z_]", "_", u) or "empty"
        geo.set_group(cls, safe, np.asarray([k == u for k in keys], bool))
        made += 1
    return made


# ══════════════════════════════════════════════════════ the three forms
def _plane_axes(plane):
    if plane not in PLANES:
        raise ValueError(f"plane must be one of {PLANES}")
    return {"xz": (0, 2, 1), "xy": (0, 1, 2), "yz": (1, 2, 0)}[plane]


def _place(u, v, plane, size, center, flip_v):
    """Normalized (u,v) -> world coordinates. size is the side length of the whole patch, center its center."""
    a, b, c = _plane_axes(plane)
    if flip_v:
        v = 1.0 - np.asarray(v, np.float64)
    P = np.zeros((len(np.atleast_1d(u)), 3), np.float64)
    P[:, a] = (np.asarray(u, np.float64) - 0.5) * size[0] + center[a]
    P[:, b] = (np.asarray(v, np.float64) - 0.5) * size[1] + center[b]
    P[:, c] = center[c]
    return P


def _to_world(A, plane, size, center, flip_v, normalized):
    """
    Record coordinates -> world coordinates. All three forms (points / boxes / curves) go through this one function,
    with a single set of rules (unified in pcg90; before, each of the three had its own, Center used by some and not others when not normalized,
    3D boxes scaled by size while 3D points and curves were not):

      2 components + normalized   0..1 maps onto a size-sized patch of the plane, centered at Center;
                              flip_v: v -> 1 − v (image space y points down)
      2 components, not normalized   world units on the plane, translated by Center;
                              flip_v:v → −v
      3 components               world coordinates, translated by Center (normalized only applies to 2D:
                              in 3D there is no "which plane does it land on")
    """
    A = np.asarray(A, np.float64)
    n, w = A.shape
    c = np.asarray(center, np.float64)
    if w == 2:
        if normalized:
            return _place(A[:, 0], A[:, 1], plane, size, center, flip_v)
        a, b, _ = _plane_axes(plane)
        P = np.zeros((n, 3))
        P[:, a] = A[:, 0]
        P[:, b] = -A[:, 1] if flip_v else A[:, 1]
        return P + c
    return np.pad(A, ((0, 0), (0, max(0, 3 - w))))[:, :3] + c


def _rec_get(rec, *names):
    flat = _flatten(rec)
    low = {k.lower(): v for k, v in flat.items()}
    for n in names:
        if n in low:
            return low[n]
    return None


def build_points(recs, cols, plane, size, center, flip_v, normalized):
    """One point per record. Uses P if present, otherwise lands at the center of the plane."""
    n = len(recs)
    g = Geometry(n)
    if "P" in cols:
        vals, w, is_str = cols["P"]
        if is_str:
            raise ValueError("The value of P is not a number")
        A = np.asarray(vals, np.float64).reshape(n, w)
        if w < 2:                                   # only one number: treat as 3D x
            A = np.pad(A, ((0, 0), (0, 3 - w)))
        P = _to_world(A[:, :3], plane, size, center, flip_v, normalized)
    else:
        P = np.repeat(np.asarray(center, np.float64)[None, :], n, 0)
    g.set(POINT, "P", P, dtype=np.float32, owned=True)
    _apply(g, POINT, cols)
    return g


def _bbox_of(rec):
    """-> (min, max) or None. Recognizes bbox / box / bounds / min+max spellings."""
    b = _rec_get(rec, "bbox", "box", "bounds", "rect", "aabb")
    if b is None:
        mn = _rec_get(rec, "min", "start", "lo")
        mx = _rec_get(rec, "max", "end", "hi")
        if mn is None or mx is None:
            return None
        b = list(mn) + list(mx)
    b = list(b)
    if isinstance(b[0], (list, tuple)):          # [[x0,y0],[x1,y1]]
        b = list(b[0]) + list(b[1])
    if len(b) not in (4, 6):
        raise ValueError(
            f"bbox needs 4 numbers (x0 y0 x1 y1) or 6 numbers (3D), got {len(b)}")
    k = len(b) // 2
    lo = [float(x) for x in b[:k]]
    hi = [float(x) for x in b[k:]]
    return [min(a, c) for a, c in zip(lo, hi)], \
           [max(a, c) for a, c in zip(lo, hi)]


def build_boxes(recs, cols, plane, size, center, flip_v, normalized,
                height=0.0):
    """
    One rectangle (4 numbers) or box (6 numbers) per record.

    This is the most direct landing form for VLM detection boxes and LLM room layouts: box -> face -> PolyExtrude
    gives walls. Attributes land on the **prim**, so each box carries its own label.
    """
    parts, keep = [], []
    for i, r in enumerate(recs):
        bb = _bbox_of(r)
        if bb is None:
            continue
        lo, hi = bb
        keep.append(i)
        if len(lo) == 2:
            u = np.array([lo[0], hi[0], hi[0], lo[0]])
            v = np.array([lo[1], lo[1], hi[1], hi[1]])
            P = _to_world(np.stack([u, v], 1), plane, size, center, flip_v, normalized)
            if height:
                a, b, c = _plane_axes(plane)
                P[:, c] += height
            g = Geometry.from_mesh(P.astype(np.float32), [[0, 1, 2, 3]])
        else:
            ctr = _to_world(np.array([[(lo[j] + hi[j]) * 0.5 for j in range(3)]]),
                            plane, size, center, flip_v, normalized)[0]
            ext = [max(hi[j] - lo[j], 1e-9) for j in range(3)]
            g = _build.box(size=ext, center=list(ctr))
        parts.append(g)
    if not parts:
        raise ValueError(
            "Not a single record has a bbox. boxes mode needs each record to have "
            "bbox / box / bounds, or min + max")
    out = _ops.merge(*parts) if len(parts) > 1 else parts[0]
    sub = {k: ([v[0][i] for i in keep], v[1], v[2]) for k, v in cols.items()}
    if out.nprims == len(keep):
        _apply(out, PRIM, sub, skip=())
    return out, sub


def build_curves(recs, cols, plane, size, center, flip_v, normalized):
    """One polyline per record. Paths, roads, outlines."""
    parts, keep = [], []
    for i, r in enumerate(recs):
        pts = _rec_get(r, "points", "pts", "path", "polyline", "verts",
                       "vertices")
        if not isinstance(pts, (list, tuple)) or len(pts) < 2:
            continue
        arr = []
        for p in pts:
            if not isinstance(p, (list, tuple)):
                raise ValueError(f"The points of record {i} contain a non-coordinate item: {p}")
            arr.append([float(x) for x in p])
        w = {len(p) for p in arr}
        if len(w) > 1:
            raise ValueError(f"The points of record {i} have inconsistent component counts: {sorted(w)}")
        A = np.asarray(arr, np.float64)
        if A.shape[1] < 2:
            raise ValueError(f"Each point in the points of record {i} needs at least 2 components")
        P = _to_world(A[:, :3], plane, size, center, flip_v, normalized)
        closed = bool(_rec_get(r, "closed", "close", "loop"))
        parts.append(Geometry.from_mesh(P.astype(np.float32),
                                        [list(range(len(P)))], closed=closed))
        keep.append(i)
    if not parts:
        raise ValueError(
            "Not a single record has points. curves mode needs each record to have "
            "points / path / polyline, with at least two points")
    out = _ops.merge(*parts) if len(parts) > 1 else parts[0]
    sub = {k: ([v[0][i] for i in keep], v[1], v[2]) for k, v in cols.items()}
    if out.nprims == len(keep):
        _apply(out, PRIM, sub, skip=())
    return out, sub


# ══════════════════════════════════════════════════════════ entry
def from_json(text, mode="points", path="auto", plane="xz", size=(10.0, 10.0),
              center=(0.0, 0.0, 0.0), flip_v=False, normalized=True,
              height=0.0, group_by="", color_hex=True):
    """JSON text -> (Geometry, info dict)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    data, how = loads(text)
    recs, detail = records(data, path)
    if not recs:
        raise ValueError("Parsing produced nothing -- not a single record")
    cols, stat = columns(recs, color_hex)
    center = list(np.asarray(center, np.float64).reshape(3))
    size = list(np.asarray(size, np.float64).reshape(2))
    if mode == "points":
        g = build_points(recs, cols, plane, size, center, flip_v, normalized)
        cls, used = POINT, cols
    elif mode == "boxes":
        g, used = build_boxes(recs, cols, plane, size, center, flip_v,
                              normalized, height)
        cls = PRIM
    else:
        g, used = build_curves(recs, cols, plane, size, center, flip_v,
                               normalized)
        cls = PRIM
    ngroups = _groups(g, cls, used, group_by)
    for k, v in detail.items():
        nm = canon(k)
        if isinstance(v, str):
            g.set_string(DETAIL, nm, [v])
        elif isinstance(v, bool):
            g.set(DETAIL, nm, [[1.0 if v else 0.0]], dtype=np.float32)
        elif isinstance(v, (int, float)):
            g.set(DETAIL, nm, [[float(v)]], dtype=np.float32)
    info = {"records": len(recs), "points": g.npoints, "prims": g.nprims,
            "attribs": [k for k in used if k != "P"], "parse": how,
            "filled": stat["filled"], "groups": ngroups,
            "detail": sorted(detail.keys())}
    return g, info


# ═══════════════════════════════════════════════════ reverse: geometry -> JSON
def dumps(geo, cls=POINT, attribs="", limit=0, precision=6, indent=0):
    """
    Geometry -> JSON in the same shape as the input. **For showing the model the current layout.**

    Only **attributes** are exported, not topology: this is meant for the model to read, and ten thousand vertex indices are no
    help to it, they would only eat up the context. For full geometry use Export Mesh / File Cache.

    `limit` truncates to the first N records and states the total at the end -- truncation must be said, otherwise the model will assume
    that is everything and give a layout that does not match up.
    """
    if cls not in (POINT, PRIM, DETAIL):
        raise ValueError("Can only export point / prim / detail")
    want = [a.strip() for a in str(attribs or "").replace(",", " ").split()
            if a.strip()]
    names = want or sorted(geo.attribs[cls].keys())
    missing = [a for a in names if a not in geo.attribs[cls]]
    if missing:
        raise KeyError(f"No {cls} attribute(s) {missing}. Existing: "
                       f"{sorted(geo.attribs[cls].keys())}")
    n = geo.count(cls)
    take = n if not limit else min(n, int(limit))
    rows = []
    for i in range(take):
        r = {}
        for a in names:
            v = geo.get(cls, a)
            if is_string(v):
                r[a] = str(v[i][0])
            else:
                arr = np.asarray(v[i], np.float64)
                vals = [round(float(x), int(precision)) for x in arr]
                r[a] = vals[0] if len(vals) == 1 else vals
        rows.append(r)
    out = rows
    if take < n:
        out = {"items": rows, "truncated": True, "total": int(n)}
    return json.dumps(out, ensure_ascii=False,
                      indent=(int(indent) or None))
