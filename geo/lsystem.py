"""
L-System SOP -- string rewriting + 3D turtle graphics, producing branching curves.

━━ Rewriting
Premise (the axiom) is the starting string. Each generation replaces every character of the string by its rules, all at once:

    F=F[+F]F[-F]F          deterministic rule
    F=(0.6)F[+F]F          stochastic rule: the number in parentheses is a weight; several rules for one character are drawn by weight
    F=(0.4)F[-F]F

Characters without rules are kept unchanged. Random draws are keyed by Seed and "which generation, which position in the string",
so the same parameters always give the same result. Every character remembers **which generation produced it** (generation attribute):
those in the axiom are 0, those produced in generation k are k -- colouring by generation and controlling thickness by generation both rely on it.

The string grows exponentially (F->F[+F]F[-F]F is x5 per generation; 8 generations are 390k F's). Exceeding Max Symbols raises an error
stating the actual length, instead of silently truncating (a truncated tree is missing half of itself and looks like a bug).

━━ Turtle
The turtle has a position and three axes H (heading), L (left), U (up); it starts with H = +Y (plants grow upwards),
U = +Z, L = -X. Symbols (the part consistent with Houdini / ABOP):

    F  move Step and draw      f  move without drawing (break)
    +  turn left about U by Angle   -  turn right about U
    &  pitch down about L      ^  pitch up about L
    \\  roll left about H       /  roll right about H
    |  turn around (180 deg about U)
    [  push (branch start)     ]  pop (back to the branch point)
    !  width * Width Scale     "  step * Step Scale
    J K L M  place a "leaf point" at the current position (point group leaves, name attribute = that letter),
             for downstream Copy to Points to attach leaves / flowers. Points carry N = H, up = U, orient

Gravity (ABOP tropism) twists the heading slightly towards -Y on every step (twist angle proportional to |H x down|):
branches droop, and stop twisting once vertical. Angle Variance adds a uniform random deviation to every turn.

━━ Output
Each unbroken stroke is one open polyline. Branches start from the branch point and **share** that point (topologically connected,
so tubes from Sweep join at forks). Point attributes: width, generation (generation of the F that drew this step),
depth (bracket nesting depth, trunk 0).

Not implemented: parametric L-Systems (parameterized symbols like F(l,w) and conditional rules), context-sensitive rules
(A<B>C). Houdini has both; not in this version.
"""
from __future__ import annotations

import math
import zlib

import numpy as np

from .core import Geometry, POINT

LEAF_SYMBOLS = "JKLM"


def parse_rules(text):
    """'F=F[+F]F' one rule per line (semicolons work too) -> {character: [(weight, replacement), ...]}."""
    rules = {}
    for raw in str(text).replace(";", "\n").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Rule '{line}' has no '=' (format: F=F[+F]F)")
        lhs, rhs = line.split("=", 1)
        lhs, rhs = lhs.strip(), rhs.strip()
        if len(lhs) != 1:
            raise ValueError(f"The left side of rule '{line}' must be exactly one character (got '{lhs}')")
        w = 1.0
        if rhs.startswith("("):
            k = rhs.find(")")
            if k < 0:
                raise ValueError(f"The weight parenthesis of rule '{line}' is not closed")
            try:
                w = float(rhs[1:k])
            except ValueError:
                raise ValueError(f"Rule '{line}': weight '{rhs[1:k]}' is not a number")
            if w < 0:
                raise ValueError(f"Rule '{line}': weight cannot be negative")
            rhs = rhs[k + 1:].strip()
        rules.setdefault(lhs, []).append((w, rhs))
    return rules


def _u01(seed, gen, i):
    return (zlib.crc32(f"{seed}:{gen}:{i}".encode()) & 0xFFFFFFFF) / 2 ** 32


def rewrite(premise, rules, generations, seed=0, max_symbols=2_000_000):
    """Returns (string, list of the generation of each character)."""
    s = str(premise)
    gens = [0] * len(s)
    for g in range(1, int(generations) + 1):
        out, og = [], []
        for i, (c, cg) in enumerate(zip(s, gens)):
            rs = rules.get(c)
            if not rs:
                out.append(c)
                og.append(cg)
                continue
            if len(rs) == 1:
                rep = rs[0][1]
            else:
                tot = sum(w for w, _ in rs)
                u = _u01(seed, g, i) * tot
                rep = rs[-1][1]
                for w, r in rs:
                    if u < w:
                        rep = r
                        break
                    u -= w
            out.append(rep)
            og.extend([g] * len(rep))
        s = "".join(out)
        gens = og
        if len(s) > int(max_symbols):
            raise ValueError(
                f"The string of generation {g} has {len(s)} characters, exceeding Max Symbols = "
                f"{int(max_symbols)}. Reduce Generations, or if really needed raise Max "
                f"Symbols (the string grows each generation by the rules' length factor)")
    return s, gens


def _rot(axis, ang):
    """Rotation matrix of ang radians about unit axis axis (Rodrigues)."""
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def turtle(s, gens, angle=25.0, step=1.0, width=0.1, step_scale=0.9,
           width_scale=0.7, gravity=0.0, angle_variance=0.0, seed=0):
    """
    Turtle interpretation of the string. Returns (points (n,3), point attribute dict, polylines list[list[int]], leaf point list).
    """
    P = [np.zeros(3)]
    W = [float(width)]
    G = [0]
    D = [0]
    polys = []
    cur = [0]                              # current stroke (point numbers); the first point is the start
    pos = np.zeros(3)
    H = np.array([0.0, 1.0, 0.0])
    L = np.array([-1.0, 0.0, 0.0])
    U = np.array([0.0, 0.0, 1.0])
    st = float(step)
    wd = float(width)
    depth = 0
    here = 0                               # point number at the current position (-1 = none yet)
    stack = []
    leaves = []
    base = math.radians(float(angle))
    var = math.radians(float(angle_variance))
    down = np.array([0.0, -1.0, 0.0])

    def turn(axis, sgn, i):
        nonlocal H, L, U
        a = sgn * base
        if var:
            a += (2 * _u01(seed, -1, i) - 1) * var
        R = _rot(axis, a)
        H, L, U = R @ H, R @ L, R @ U

    for i, c in enumerate(s):
        if c == "F" or c == "f":
            if gravity:
                ax = np.cross(H, down)
                n = np.linalg.norm(ax)
                if n > 1e-12:
                    R = _rot(ax / n, float(gravity) * n)
                    H, L, U = R @ H, R @ L, R @ U
            pos = pos + H * st
            if c == "F":
                if here < 0:
                    P.append(pos - H * st)
                    W.append(wd)
                    G.append(gens[i])
                    D.append(depth)
                    here = len(P) - 1
                    cur = [here]
                P.append(pos.copy())
                W.append(wd)
                G.append(gens[i])
                D.append(depth)
                here = len(P) - 1
                cur.append(here)
            else:
                if len(cur) > 1:
                    polys.append(cur)
                cur = []
                here = -1
        elif c == "+":
            turn(U, 1, i)
        elif c == "-":
            turn(U, -1, i)
        elif c == "&":
            turn(L, 1, i)
        elif c == "^":
            turn(L, -1, i)
        elif c == "\\":
            turn(H, 1, i)
        elif c == "/":
            turn(H, -1, i)
        elif c == "|":
            R = _rot(U, math.pi)
            H, L, U = R @ H, R @ L, R @ U
        elif c == "[":
            stack.append((pos.copy(), H.copy(), L.copy(), U.copy(), st, wd,
                          here, cur, depth))
            depth += 1
            cur = [here] if here >= 0 else []
        elif c == "]":
            if not stack:
                raise ValueError(f"Character #{i} ']' has no matching '['")
            if len(cur) > 1:
                polys.append(cur)
            pos, H, L, U, st, wd, here, cur, depth = stack.pop()
        elif c == "!":
            wd *= float(width_scale)
        elif c == '"':
            st *= float(step_scale)
        elif c in LEAF_SYMBOLS:
            leaves.append((pos.copy(), H.copy(), U.copy(), c, depth, gens[i]))
    if len(cur) > 1:
        polys.append(cur)
    attrs = {"width": np.array(W), "generation": np.array(G, np.int32),
             "depth": np.array(D, np.int32)}
    return np.array(P), attrs, polys, leaves


def lsystem(premise="F", rules="F=F[+F]F[-F]F", generations=4, angle=25.0,
            step=1.0, width=0.1, step_scale=0.9, width_scale=0.7, gravity=0.0,
            angle_variance=0.0, seed=0, max_symbols=2_000_000):
    """Rewriting + turtle -> Geometry. Returns (geo, report)."""
    from .curveframe import mat_to_quat
    R = parse_rules(rules)
    s, gens = rewrite(premise, R, generations, seed, max_symbols)
    P, attrs, polys, leaves = turtle(s, gens, angle, step, width, step_scale,
                                     width_scale, gravity, angle_variance, seed)
    used = np.zeros(len(P), bool)
    for p in polys:
        used[p] = True
    keep = np.nonzero(used)[0]
    remap = np.full(len(P), -1, np.int64)
    remap[keep] = np.arange(len(keep))
    nl = len(leaves)
    Pall = np.vstack([P[keep]] + ([np.array([lf[0] for lf in leaves])]
                                  if nl else []))
    g = Geometry.from_mesh(Pall, [remap[p] for p in polys], closed=False)
    for k, v in attrs.items():
        extra = {"width": np.full(nl, float(width)),
                 "generation": np.array([lf[5] for lf in leaves], np.int32),
                 "depth": np.array([lf[4] for lf in leaves], np.int32)}[k]
        g.set(POINT, k, np.concatenate([v[keep], extra.astype(v.dtype)])[:, None],
              owned=True)
    leaf = np.zeros(len(Pall), bool)
    leaf[len(keep):] = True
    g.set_group(POINT, "leaves", leaf)
    if nl:
        N = np.zeros((len(Pall), 3))
        up = np.zeros((len(Pall), 3))
        N[len(keep):] = [lf[1] for lf in leaves]
        up[len(keep):] = [lf[2] for lf in leaves]
        g.set(POINT, "N", N.astype(np.float32), owned=True)
        g.set(POINT, "up", up.astype(np.float32), owned=True)
        # Columns = [up x N, up, N]: copies align +Z with N and +Y with up (same as Copy to Points)
        X = np.cross(up, N)
        M = np.stack([X, up, N], axis=2)
        M[: len(keep)] = np.eye(3)
        g.set(POINT, "orient", mat_to_quat(M).astype(np.float32), owned=True)
        names = np.array([""] * len(keep) + [lf[3] for lf in leaves])
        g.set_string(POINT, "name", names)
    rep = {"symbols": len(s), "segments": int(sum(len(p) - 1 for p in polys)),
           "curves": len(polys), "leaves": nl, "generations": int(generations)}
    return g, rep
