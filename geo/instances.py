"""
Export Instances (pcg84): points -> instance table (CSV / JSON), for an engine's instancing / scattering system to read.

Scattered trees, rocks and the pieces of modular buildings are, in production, not handed over merged into one big mesh, but
as one row per item: "which asset, where, how rotated, how big", and the engine instances from the table (HISM / GPU Instancer /
PCG graphs / in-house level tools). This node exports exactly the transform set Copy to Points would use:

  transform     read the same way as Copy to Points (xform.point_matrices): orient > N + up >
                rot / scale / pscale ... so "what Copy to Points previews in ComfyUI"
                is what the table says
  asset         Asset Attribute names a point attribute (string or integer), written into the asset column
  columns       px py pz (position), qx qy qz qw (quaternion), rx ry rz (Euler angles, degrees,
                XYZ order: X first, then Y, then Z, R = Rz*Ry*Rx), sx sy sz (scale), plus
                the point attributes listed in Extra Attributes (vectors split into name_0 name_1 ...)
  axes          Axis Map: three words saying which original axis the new x y z each take (may be negated),
                e.g. x y z (unchanged, Y-up right-handed) / x -z y (Z-up right-handed) / x z y (Z-up left-handed);
                rotations are converted together as A*R*A^T (A is that signed permutation; with determinant -1 handedness flips
                and the result is still a pure rotation). Unit Scale multiplies positions (metres -> centimetres: 100)
  tiling        With Tile Size > 0, tiles by the original x and z coordinates, one file per tile, with {tx} {ty} in the file name
                replaced by tile indices (open worlds stream by tile); an extra master table _index.json lists every tile
  packed        (pcg122) packed primitives are read directly: one row per packed primitive with its own
                transform (packedxform, position = where the piece's origin lands); the asset is the point or
                prim attribute, or piece0 / piece1 ... per distinct piece when there is none
"""
from __future__ import annotations

import csv
import io
import json
import os

import numpy as np

from .core import POINT, is_string

FORMATS = ("csv", "json")


def parse_axis_map(spec):
    toks = str(spec).split()
    if len(toks) != 3:
        raise ValueError(f"Axis Map needs three words (e.g. x -z y), got '{spec}'")
    A = np.zeros((3, 3))
    used = set()
    for i, t in enumerate(toks):
        sgn = -1.0 if t.startswith("-") else 1.0
        ax = t.lstrip("+-").lower()
        if ax not in ("x", "y", "z") or ax in used:
            raise ValueError(f"Each word of Axis Map is x / y / z (may be negated), with no repeats: '{spec}'")
        used.add(ax)
        A[i, "xyz".index(ax)] = sgn
    return A


def euler_xyz(R):
    """(n,3,3) -> (n,3) degrees, R = Rz*Ry*Rx."""
    sy = np.clip(-R[:, 2, 0], -1.0, 1.0)
    ry = np.arcsin(sy)
    gimbal = np.abs(sy) > 1 - 1e-9
    rx = np.where(gimbal, 0.0, np.arctan2(R[:, 2, 1], R[:, 2, 2]))
    rz = np.where(gimbal, np.arctan2(-R[:, 0, 1], R[:, 1, 1]),
                  np.arctan2(R[:, 1, 0], R[:, 0, 0]))
    # The same rotation has two solutions: (rx, ry, rz) and (rx +- 180, 180 - ry, rz +- 180).
    # Something rotated only 180 deg about Y (a wall facing backwards, a tree) would be written as (180, 0, 180) by the first,
    # which places identically in the engine but is a trap when people read / hand-edit the table -- switch to the other solution when both exceed 90 deg
    alt = (~gimbal) & (np.abs(rx) > np.pi / 2) & (np.abs(rz) > np.pi / 2)
    rx = np.where(alt, rx - np.sign(rx) * np.pi, rx)
    rz = np.where(alt, rz - np.sign(rz) * np.pi, rz)
    ry = np.where(alt, np.where(ry >= 0, np.pi - ry, -np.pi - ry), ry)
    return np.degrees(np.stack([rx, ry, rz], 1))


def table(pts, asset_attribute="name", extra="", axis_map="x y z",
          unit_scale=1.0, up=(0, 1, 0)):
    """Returns (column names, list of rows, original positions P (n,3))."""
    from .xform import point_matrices
    from .curveframe import mat_to_quat
    from .core import PRIM
    from .packed import is_packed, transforms
    packed = is_packed(pts)
    if packed:
        # packed primitives: one row per packed prim, transform = its packedxform, position = where the piece's
        # origin lands; asset = point attribute, else prim attribute, else piece0 / piece1 ... per distinct piece
        prims, pidx, M, P0, piece_ids = transforms(pts)
        n = len(prims)
    else:
        n = pts.npoints
        pidx = np.arange(n)
        M, T, piv = point_matrices(pts, up=up)
        P0 = np.asarray(T, np.float64)

    def lookup(nm):
        a = pts.get(POINT, nm)
        if a is not None:
            return np.asarray(a)[pidx] if not is_string(a) else np.asarray(a, dtype=object)[pidx]
        if packed:
            a = pts.get(PRIM, nm)
            if a is not None:
                return np.asarray(a)[prims] if not is_string(a) else np.asarray(a, dtype=object)[prims]
        return None
    # Split into rotation x scale (column norms are the scale; with a negative determinant negate one axis's scale so the rotation stays pure)
    S = np.linalg.norm(M, axis=1)
    R = M / np.where(S < 1e-12, 1.0, S)[:, None, :]
    neg = np.linalg.det(R) < 0
    if neg.any():
        R[neg, :, 0] *= -1
        S[neg, 0] *= -1
    A = parse_axis_map(axis_map)
    Pn = (P0 @ A.T) * float(unit_scale)
    Rn = np.einsum("ij,njk,lk->nil", A, R, A)
    Sn = S @ np.abs(A).T                  # A*diag(S)*A^T = diag(|A|*S): scale follows the axis swap
    q = mat_to_quat(Rn)
    e = euler_xyz(Rn)
    cols = ["asset", "px", "py", "pz", "qx", "qy", "qz", "qw", "rx", "ry", "rz",
            "sx", "sy", "sz"]
    name = str(asset_attribute).strip()
    if name:
        a = lookup(name)
        if a is None and packed:
            assets = [f"piece{int(k)}" for k in piece_ids]
        elif a is None:
            raise KeyError(f"Asset Attribute: no point attribute '{name}'")
        else:
            assets = [str(x) if isinstance(x, str) else
                      (str(int(x)) if float(x).is_integer() else str(x))
                      for x in a[:, 0]]
    elif packed:
        assets = [f"piece{int(k)}" for k in piece_ids]
    else:
        assets = [""] * n
    ex = []
    for nm in str(extra).split():
        a = lookup(nm)
        if a is None:
            raise KeyError(f"Extra Attributes: no point attribute '{nm}'")
        if a.shape[1] == 1:
            cols.append(nm)
        else:
            cols += [f"{nm}_{k}" for k in range(a.shape[1])]
        ex.append(a)
    rows = []
    for i in range(n):
        r = [assets[i], *Pn[i], *q[i], *e[i], *Sn[i]]
        for a in ex:
            r += [x if isinstance(x, str) else float(x) for x in a[i]]
        rows.append(r)
    return cols, rows, P0


def _fmt(v):
    if isinstance(v, (float, np.floating)):
        return f"{float(v):.7g}"
    return str(v)


def write(pts, outdir, filename="pcg/instances", fmt="csv", asset_attribute="name",
          extra="", axis_map="x y z", unit_scale=1.0, tile_size=0.0, index=0):
    """Writes the files, returns a report dict."""
    if fmt not in FORMATS:
        raise ValueError(f"Format must be one of {FORMATS}")
    cols, rows, P0 = table(pts, asset_attribute, extra, axis_map, unit_scale)
    groups = {}
    ts = float(tile_size)
    for i, r in enumerate(rows):
        key = ((int(np.floor(P0[i, 0] / ts)), int(np.floor(P0[i, 2] / ts)))
               if ts > 0 else (0, 0))
        groups.setdefault(key, []).append(r)
    if not rows:
        groups = {(0, 0): []}
    files = []
    meta = {"columns": cols, "axis_map": axis_map, "unit_scale": float(unit_scale),
            "euler": "XYZ degrees, R = Rz*Ry*Rx", "quaternion": "x y z w"}
    for (tx, ty), rr in sorted(groups.items()):
        name = str(filename).replace("{index}", str(int(index))) \
            .replace("{tx}", str(tx)).replace("{ty}", str(ty))
        rel = name + "." + fmt
        full = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(cols)
            for r in rr:
                w.writerow([_fmt(v) for v in r])
            with open(full, "w", encoding="utf-8", newline="") as f:
                f.write(buf.getvalue())
        else:
            doc = dict(meta, count=len(rr), tile=[tx, ty] if ts > 0 else None,
                       instances=[{c: (float(v) if isinstance(v, (float, np.floating))
                                       else v) for c, v in zip(cols, r)} for r in rr])
            with open(full, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        files.append({"file": rel.replace("\\", "/"), "tile": [tx, ty], "count": len(rr)})
    rep = dict(meta, count=len(rows), tile_size=ts, files=files)
    if ts > 0:
        from .cop.imagefile import strip_tile_tokens
        idx = strip_tile_tokens(filename).replace("{index}", str(int(index))) + "_index.json"
        with open(os.path.join(outdir, idx), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        rep["index_file"] = idx.replace("\\", "/")
    assets = sorted({r[0] for r in rows})
    rep["assets"] = assets
    return rep
