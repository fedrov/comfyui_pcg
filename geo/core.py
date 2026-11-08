"""
Core geometry data structure -- modelled on Houdini's attribute-centric model.

Design points (these directly decide whether all the later nodes can be written at all):

1) Topology is stored as CSR, corresponding exactly to Houdini's three levels prim -> vertex -> point:
       vertex_point : (NV,) int32   which point each vertex references
       prim_offset  : (NP+1,) int32 vertex range of prim i is [offset[i], offset[i+1])
       prim_closed  : (NP,) bool    True=polygon face, False=open polyline
   That way ngons / polylines / mixed topology can all be stored, unlike (F,3) which can only hold triangles.

2) Attributes are always stored as (N, C) numpy arrays. C=1 is a scalar, C=3 is a vector.
   Always 2-D, which saves a pile of shape-branching checks.

3) **All arrays are writeable=False.**
   This is the most important rule in the ComfyUI environment: a node's output is cached and may be fed
   to several downstream nodes at once. If a downstream node modified an array in place, the upstream cache would be polluted and you would get the kind of
   ghost bug where "the second run gives a different result". Frozen arrays turn this class of error into an immediate exception.
   To modify, take a writable copy with get_w() (copy-on-write).
"""
from __future__ import annotations

import numpy as np

POINT, VERTEX, PRIM, DETAIL = "point", "vertex", "prim", "detail"
CLASSES = (POINT, VERTEX, PRIM, DETAIL)

# The prim **category**. prim_closed is a POLY-only flag (face or polyline); the two are orthogonal.
# Only POLY is used now; the rest is a gap left for the future: when packed instances, volumes, NURBS curves are added,
# the `prim_type == POLY` checks in traversal code are already in place, no need to go back over everything.
PRIM_POLY, PRIM_PACKED, PRIM_VOLUME, PRIM_CURVE = 0, 1, 2, 3
PRIM_NURBS_CURVE, PRIM_NURBS_SURF = 4, 5
PRIM_BEZIER_CURVE, PRIM_BEZIER_SURF = 6, 7
SPLINE_TYPES = (4, 5, 6, 7)
EDGE = "edge"          # edges are not a separate element class; they exist only as carriers of groups
PRIM_TYPE_NAMES = {0: "poly", 1: "packed", 2: "volume", 3: "curve",
                   4: "nurbs_curve", 5: "nurbs_surf",
                   6: "bezier_curve", 7: "bezier_surf"}


def is_string(a) -> bool:
    """String attribute check. numpy unicode dtype, kind == 'U'."""
    return getattr(a, "dtype", None) is not None and a.dtype.kind == "U"


def _as2d(value, dtype=None) -> np.ndarray:
    """Normalizes any input into an (N, C) 2-D array."""
    a = np.asarray(value) if dtype is None else np.asarray(value, dtype=dtype)
    if a.ndim == 0:
        a = a.reshape(1, 1)
    elif a.ndim == 1:
        a = a.reshape(-1, 1)
    elif a.ndim > 2:
        a = a.reshape(a.shape[0], -1)
    return a


def freeze(a: np.ndarray) -> np.ndarray:
    """Returns a non-writable contiguous array. If a writable array is passed it is copied first, to avoid freezing the caller's data."""
    a = np.ascontiguousarray(a)
    if a.flags.writeable:
        a = a.copy()
        a.setflags(write=False)
    return a


class Geometry:
    __slots__ = ("attribs", "groups", "edge_groups", "vertex_point",
                 "prim_offset", "prim_closed", "prim_type", "prim_data",
                 "_npoints", "_topo")

    # ------------------------------------------------------------------ construction
    def __init__(self, npoints: int = 0):
        self.attribs = {c: {} for c in CLASSES}
        self.groups = {c: {} for c in (POINT, VERTEX, PRIM)}
        self._npoints = int(npoints)
        self.vertex_point = freeze(np.zeros(0, np.int32))
        self.prim_offset = freeze(np.zeros(1, np.int32))
        self.prim_closed = freeze(np.zeros(0, bool))
        self.prim_type = freeze(np.zeros(0, np.uint8))
        self._topo = None          # adjacency structure cache, see topology.py
        # **Variable-length** per-prim data. Attribute tables are fixed-length (N,C) arrays and can't hold things like voxel grids
        # or non-uniform knot vectors whose length differs per prim, so a separate side channel is opened.
        # Keys are prim indices, values are {name: any object}. Same convention as attributes: arrays inside
        # are treated as immutable; to change one, replace it with a new one.
        self.prim_data = {}
        # Edge groups: name -> (E,2) int32 **point pairs**, with both endpoints sorted.
        #
        # Point pairs are stored instead of edge indices because edge indices are derived from topology -- after delete / merge /
        # fuse the whole numbering changes, and a group storing indices would silently point at other edges. Point pairs only depend on point numbers,
        # and those operators have to remap point numbers anyway, so it comes along for free.
        self.edge_groups = {}
        if npoints:
            self.set(POINT, "P", np.zeros((npoints, 3), np.float32))

    @staticmethod
    def from_mesh(points, faces, closed=True) -> "Geometry":
        """
        points : (N,3) point positions
        faces  : (F,K) fixed-length array, or list[list[int]] variable-length ngons
        """
        points = np.asarray(points, np.float32).reshape(-1, 3)
        g = Geometry(len(points))
        g.set(POINT, "P", points)

        if isinstance(faces, np.ndarray) and faces.ndim == 2:
            F, K = faces.shape
            vp = faces.reshape(-1).astype(np.int32)
            off = (np.arange(F + 1, dtype=np.int32) * K)
        else:
            faces = [np.asarray(f, np.int32) for f in faces]
            sizes = np.array([len(f) for f in faces], np.int32)
            vp = (np.concatenate(faces) if len(faces)
                  else np.zeros(0, np.int32)).astype(np.int32)
            off = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int32)

        g.set_topology(vp, off, np.full(len(off) - 1, bool(closed)))
        return g

    @staticmethod
    def from_points(points) -> "Geometry":
        """A point cloud with points only, no faces."""
        points = np.asarray(points, np.float32).reshape(-1, 3)
        g = Geometry(len(points))
        g.set(POINT, "P", points)
        return g

    # ------------------------------------------------------------------ counts
    @property
    def npoints(self) -> int:
        return self._npoints

    @property
    def nvertices(self) -> int:
        return len(self.vertex_point)

    @property
    def nprims(self) -> int:
        return len(self.prim_offset) - 1

    def count(self, cls: str) -> int:
        return {POINT: self.npoints, VERTEX: self.nvertices,
                PRIM: self.nprims, DETAIL: 1}[cls]

    # ------------------------------------------------------------- attribute access
    def has(self, cls, name) -> bool:
        return name in self.attribs[cls]

    def get(self, cls, name, default=None):
        """Read-only view. Modifying it raises ValueError -- this is intentional."""
        return self.attribs[cls].get(name, default)

    def get_w(self, cls, name, default=None) -> np.ndarray:
        """copy-on-write: get a writable copy. Go through here to modify attributes."""
        a = self.attribs[cls].get(name)
        if a is None:
            if default is None:
                raise KeyError(f"{cls} attribute '{name}' not found")
            return np.array(default)
        return np.array(a, copy=True)

    def set_string(self, cls, name, values):
        """
        String attribute. Stored with numpy's fixed-length unicode dtype, not Houdini's
        "index + string table" -- because slicing, concatenate and unique all work natively on <U,
        and operators like delete/merge/promote need no changes at all. The cost is a fixed width per row,
        which is irrelevant at the scale of @name / @path.
        """
        v = np.asarray(values)
        if v.dtype.kind != "U":
            v = np.array(["" if x is None else str(x) for x in v.reshape(-1)],
                         dtype=str).reshape(v.shape)       # width from the content, no truncation
        return self.set(cls, name, v)

    def set(self, cls, name, value, dtype=None, owned=False):
        """
        owned=True means value is a temporary array the caller just built and won't use again,
        so one copy can be skipped. Used on hot paths.
        """
        v = _as2d(value, dtype)
        if cls == DETAIL:
            v = v.reshape(1, -1)
        else:
            n = self.count(cls)
            if v.shape[0] != n:
                raise ValueError(
                    f"attribute {cls}.{name}: expected {n} rows, got {v.shape[0]} rows")
        if owned:
            v = np.ascontiguousarray(v)
            v.setflags(write=False)
        else:
            v = freeze(v)
        self.attribs[cls][name] = v
        return v

    def remove(self, cls, name):
        self.attribs[cls].pop(name, None)

    def names(self, cls):
        return list(self.attribs[cls].keys())

    # --------------------------------------------------------------- groups
    def set_group(self, cls, name, mask):
        mask = np.asarray(mask)
        if mask.dtype != bool:                      # index arrays are allowed
            m = np.zeros(self.count(cls), bool)
            m[mask] = True
            mask = m
        self.groups[cls][name] = freeze(mask.reshape(-1))

    def get_group(self, cls, name):
        return self.groups[cls].get(name)

    # ---------------------------------------------------------------- topology
    def set_topology(self, vertex_point, prim_offset, prim_closed=None,
                     prim_type=None):
        vp = np.asarray(vertex_point, np.int32).reshape(-1)
        off = np.asarray(prim_offset, np.int32).reshape(-1)
        np_ = len(off) - 1
        if prim_closed is None:
            prim_closed = np.ones(np_, bool)
        pc = np.asarray(prim_closed, bool).reshape(-1)
        assert len(pc) == np_, "prim_closed length must equal the prim count"
        self.vertex_point = freeze(vp)
        self.prim_offset = freeze(off)
        self.prim_closed = freeze(pc)
        self.prim_type = freeze(np.full(np_, PRIM_POLY, np.uint8)
                                if prim_type is None
                                else np.asarray(prim_type, np.uint8).reshape(-1))
        self._topo = None          # topology changed, adjacency cache invalidated

    def prim_sizes(self) -> np.ndarray:
        return np.diff(self.prim_offset)

    def prim_points(self, i) -> np.ndarray:
        """Point indices referenced by prim i."""
        return self.vertex_point[self.prim_offset[i]:self.prim_offset[i + 1]]

    def vertex_prim(self) -> np.ndarray:
        """(NV,) which prim each vertex belongs to -- the vertex<->prim reverse lookup table."""
        return np.repeat(np.arange(self.nprims, dtype=np.int32),
                         self.prim_sizes())

    def triangles(self, with_corners=False):
        """
        Fan triangulation. Returns (T,3) point indices by default; correct for convex ngons, concave ngons get artifacts;
        to really handle concave faces, replace this with the mapbox_earcut / triangle library.
        Only closed prims are triangulated; polylines are ignored.

        With with_corners=True also returns the (T,3) **vertex (corner) indices**.
        Needed for displaying vertex normals and hard-edge shading -- after triangulation the correspondence between corners and
        points can't be recovered, so it has to be computed here at the same time.
        """
        sizes = self.prim_sizes()
        keep = self.prim_closed & (sizes >= 3) & (self.prim_type == PRIM_POLY)
        if not keep.any():
            z = np.zeros((0, 3), np.int32)
            return (z, z.copy()) if with_corners else z
        tri, cor = [], []
        for k in np.unique(sizes[keep]):            # bucket by edge count, vectorized within a bucket
            sel = np.nonzero(keep & (sizes == k))[0]
            starts = self.prim_offset[sel]
            corner = starts[:, None] + np.arange(k)[None, :]   # (m,k) corner
            idx = self.vertex_point[corner]                    # (m,k) point
            for t in range(1, k - 1):
                tri.append(np.stack([idx[:, 0], idx[:, t], idx[:, t + 1]], 1))
                if with_corners:
                    cor.append(np.stack(
                        [corner[:, 0], corner[:, t], corner[:, t + 1]], 1))
        T = np.concatenate(tri).astype(np.int32)
        if not with_corners:
            return T
        return T, np.concatenate(cor).astype(np.int32)

    def next_corner(self) -> np.ndarray:
        """(NV,) the next corner of each corner within the same prim (closed prims wrap around to the start).
        Needed for Newell face normals and extracting polygon edges."""
        sizes = self.prim_sizes()
        starts = np.repeat(self.prim_offset[:-1], sizes)
        local = np.arange(self.nvertices, dtype=np.int32) - starts
        return starts + (local + 1) % np.repeat(sizes, sizes)

    # ---------------------------------------------------------------- misc
    def bbox(self):
        P = self.get(POINT, "P")
        if P is None or len(P) == 0:
            z = np.zeros(3, np.float32)
            return z, z
        return P.min(0), P.max(0)

    def copy(self) -> "Geometry":
        """
        Shallow copy: the dicts are new, the underlying arrays shared.
        Since all arrays are read-only, sharing is safe -- that is the payoff of the immutability convention:
        g = geo.copy() at the start of every node costs almost nothing.
        """
        g = Geometry.__new__(Geometry)
        g.attribs = {c: dict(d) for c, d in self.attribs.items()}
        g.groups = {c: dict(d) for c, d in self.groups.items()}
        g._npoints = self._npoints
        g.vertex_point = self.vertex_point
        g.prim_offset = self.prim_offset
        g.prim_closed = self.prim_closed
        g.prim_type = self.prim_type
        g.prim_data = {k: dict(v) for k, v in self.prim_data.items()}
        g.edge_groups = {k: v for k, v in self.edge_groups.items()}
        # Adjacency depends only on topology, and topology arrays are shared and read-only, so the cache can come along too.
        # transform / smooth change P, which doesn't affect connectivity.
        g._topo = self._topo
        return g

    def _resize_points(self, n):
        """Internal: when the point count changes, point attributes of mismatched length must be cleaned up at the same time."""
        self._npoints = int(n)

    def set_edge_group(self, name, pairs):
        """pairs may be an (E,2) array or an iterable of point pairs. Sorted and deduplicated on storage."""
        a = np.asarray(pairs, np.int32).reshape(-1, 2)
        if len(a):
            a = np.unique(np.sort(a, axis=1), axis=0)
        self.edge_groups[name] = freeze(a.astype(np.int32))

    def get_edge_group(self, name):
        return self.edge_groups.get(name)

    def remap_edge_groups(self, point_map, npoints):
        """
        Rebuilds edge groups after point numbers change. point_map[old] = new, -1 means the point is gone.
        Only edges with both endpoints still present are kept.
        """
        out = {}
        for k, v in self.edge_groups.items():
            if not len(v):
                out[k] = v
                continue
            m = point_map[v]
            keep = (m >= 0).all(1)
            out[k] = freeze(np.unique(np.sort(m[keep], axis=1), axis=0)
                            .astype(np.int32) if keep.any()
                            else np.zeros((0, 2), np.int32))
        return out

    def pdata(self, i, name, default=None):
        """Reads a prim's side-channel data."""
        return self.prim_data.get(int(i), {}).get(name, default)

    def set_pdata(self, i, name, value):
        self.prim_data.setdefault(int(i), {})[name] = value

    def remap_prim_data(self, src_index):
        """
        Rebuilds the side channel by src_index (new prim -> original prim index).
        Every operator that touches prims must call this; missing one silently loses data -- and what is lost
        is the kind of thing (voxels / knot vectors) that only blows up downstream, very hard to track down.
        """
        if not self.prim_data:
            return {}
        out = {}
        for new, old in enumerate(np.asarray(src_index).tolist()):
            d = self.prim_data.get(int(old))
            if d:
                out[new] = dict(d)
        return out

    def string_names(self, cls):
        return [k for k, v in self.attribs[cls].items() if is_string(v)]

    def info(self) -> str:
        """Summary modelled on Houdini's Geometry Spreadsheet, a debugging lifesaver."""
        lines = [f"Points: {self.npoints}   Vertices: {self.nvertices}   "
                 f"Prims: {self.nprims}"]
        for cls in CLASSES:
            d = self.attribs[cls]
            if d:
                desc = ", ".join(
                    f"{k}[{v.shape[1]}]{v.dtype.kind}" for k, v in d.items())
                lines.append(f"  {cls:<7}: {desc}")
        for cls in (POINT, VERTEX, PRIM):
            if self.groups[cls]:
                g = ", ".join(f"{k}({int(v.sum())})"
                              for k, v in self.groups[cls].items())
                lines.append(f"  {cls} groups: {g}")
        if self.nprims:
            kinds = np.unique(self.prim_type)
            if len(kinds) > 1 or (len(kinds) and kinds[0] != PRIM_POLY):
                lines.append("  prim types: " + ", ".join(
                    f"{PRIM_TYPE_NAMES.get(int(k), k)}"
                    f"({int((self.prim_type == k).sum())})" for k in kinds))
        mn, mx = self.bbox()
        lines.append(f"  bbox: {np.round(mn,4).tolist()} .. "
                     f"{np.round(mx,4).tolist()}")
        return "\n".join(lines)

    def __repr__(self):
        return f"<Geometry pts={self.npoints} prims={self.nprims}>"
