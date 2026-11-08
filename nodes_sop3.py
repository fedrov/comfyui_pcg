"""
The third SOP node file (pcg121): nodes added after the code review.

  Distances     Distance from Geometry, Distance along Geometry (edge Dijkstra / heat-method geodesics)
  Curves        Path Deform, PolyWire, Curve Fillet
  Modelling     Thicken
  Packed        Pack, Unpack, Assemble (+ Copy to Points' Pack and Instance, viewport instancing; see geo/packed.py)

The end of nodes.py merges the mappings here into the main table; the Houdini mapping is in tests/sop_map.py.
"""
from __future__ import annotations

from .nodes_common import GEO, CAT, _f, _i, _group, _names, _sec  # noqa: F401
from .geo import distgeo as _dg, pathdeform as _pd, polywire as _pw, thicken as _th, curvefillet as _cf
from .geo import packed as _pk
from .geo.ramp import MODES as _RAMP_MODES

_WITH_REPORT = ((GEO, "geo"), ("STRING", "report"))


def _s(default=""):
    return ("STRING", {"default": default})


def _b(default=False):
    return ("BOOLEAN", {"default": default})


def _rep(r):
    import json
    return json.dumps(r, ensure_ascii=False, default=str)


def _node(cat, returns=_WITH_REPORT):
    def deco(cls):
        cls.FUNCTION = "run"
        cls.CATEGORY = CAT + "/" + cat
        cls.RETURN_TYPES = tuple(t for t, _ in returns)
        cls.RETURN_NAMES = tuple(n for _, n in returns)
        return cls
    return deco


def _mask_inputs():
    return {
        "output_mask": _sec("Mask", _b(False), gate=True),
        "mask_attribute": _sec("Mask", _names("attrib", "point", "mask", "Point attribute for the 0..1 mask")),
        "mask_radius": _sec("Mask", _f(1.0, 0.0, 1e6, 0.01)),
        "mask_ramp": _sec("Mask", _s("0:1  1:0")),
        "ramp_mode": _sec("Mask", (list(_RAMP_MODES), {"default": "linear"})),
    }


@_node("attribute")
class PCG_DistanceFromGeometry:
    """
    Maps to: Distance from Geometry. Writes each point's distance to a reference geometry (second input) to a point
    attribute: closest point on its surface, on its edges / curves, or nearest reference point. Max Distance clamps
    (and speeds the search up); the optional mask turns distance into 0..1 through a ramp over Mask Radius.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "reference": (GEO,),
            "group": _group("Only these points get a distance"),
            "reference_group": _group("Primitives (Surface / Edges) or points (Points) of the reference to measure to"),
            "metric": (list(_dg.METRICS),),
            "distance_attribute": _names("attrib", "point", "dist", "Point attribute for the distance"),
            "use_max_distance": _b(False),
            "max_distance": _f(1.0, 0.0, 1e6, 0.01),
            **_mask_inputs(),
        }}

    def run(self, geo, reference, group, reference_group, metric, distance_attribute, use_max_distance,
            max_distance, output_mask, mask_attribute, mask_radius, mask_ramp, ramp_mode):
        g, r = _dg.distance_from_geometry(geo, reference, group, reference_group, metric, distance_attribute,
                                          use_max_distance, max_distance, output_mask, mask_attribute, mask_radius,
                                          mask_ramp, ramp_mode)
        return (g, _rep(r))


@_node("attribute")
class PCG_DistanceAlongGeometry:
    """
    Maps to: Distance along Geometry. Distance from the start points measured on the surface: Geodesic (heat
    method, smooth, follows the surface) or Edges (shortest path along edges, exact along edges but staircased
    across faces). Unreachable points get -1. Optional 0..1 mask through a ramp over Mask Radius.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "start_points": ("STRING", {"default": "0", "is_group": True,
                                        "tooltip": "Point group / numbers the distance is measured from"}),
            "method": (list(_dg.ALONG_METHODS),),
            "distance_attribute": _names("attrib", "point", "dist", "Point attribute for the distance"),
            "use_max_distance": _b(False),
            "max_distance": _f(1.0, 0.0, 1e6, 0.01),
            "heat_time": _f(1.0, 0.01, 100.0, 0.1),
            **_mask_inputs(),
        }}

    def run(self, geo, start_points, method, distance_attribute, use_max_distance, max_distance, heat_time,
            output_mask, mask_attribute, mask_radius, mask_ramp, ramp_mode):
        g, r = _dg.distance_along_geometry(geo, start_points, method, distance_attribute, use_max_distance,
                                           max_distance, output_mask, mask_attribute, mask_radius, mask_ramp,
                                           ramp_mode, heat_time)
        return (g, _rep(r))


@_node("deform")
class PCG_PathDeform:
    """
    Maps to: Path Deform. Bends the input along a curve (second input): the deform axis becomes arc length, the
    other two axes offsets in the curve's rotation-minimising frame. Stretch to Curve fits the input's length to the
    curve; Offset slides it; Roll / Twist rotate it about the curve; past the ends it continues straight.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,), "curve": (GEO,),
            "group": _group("Only deform these points"),
            "curve_group": _group("Which curve primitive to follow (the first one)"),
            "deform_axis": (list(_pd.AXES),),
            "stretch_to_curve": _b(True),
            "offset": _f(0.0, -1e6, 1e6, 0.01),
            "offset_as_fraction": _b(False),
            "scale": _f(1.0, -1e4, 1e4, 0.01),
            "cross_scale": _f(1.0, -1e4, 1e4, 0.01),
            "roll": _f(0.0, -36000.0, 36000.0, 1.0),
            "twist": _f(0.0, -36000.0, 36000.0, 1.0),
            "up_mode": (list(_pd.UP_MODES),),
            "up_x": _f(0.0), "up_y": _f(1.0), "up_z": _f(0.0),
        }}

    def run(self, geo, curve, group, curve_group, deform_axis, stretch_to_curve, offset, offset_as_fraction, scale,
            cross_scale, roll, twist, up_mode, up_x, up_y, up_z):
        g, r = _pd.path_deform(geo, curve, group, curve_group, deform_axis, stretch_to_curve, offset,
                               offset_as_fraction, scale, roll, twist, up_mode, (up_x, up_y, up_z), cross_scale)
        return (g, _rep(r))


@_node("generate")
class PCG_PolyWire:
    """
    Maps to: PolyWire. Tubes along every edge of a curve network (polylines and polygon edges, branches allowed):
    chains between junctions get rotation-minimising tubes, junctions and sharp bends get spheres so branches close,
    open ends get round or flat caps. Radius is constant or per point (width = diameter, pscale = radius).
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Primitives whose edges get wires"),
            "radius": _f(0.05, 0.0, 1e6, 0.005),
            "radius_from": (list(_pw.RADIUS_FROM),),
            "divisions": _i(8, 3, 256),
            "end_caps": (list(_pw.END_CAPS),),
            "joints": _b(True),
            "joint_angle": _f(45.0, 0.0, 180.0, 1.0),
            "carry_attributes": _b(True),
        }}

    def run(self, geo, group, radius, radius_from, divisions, end_caps, joints, joint_angle, carry_attributes):
        g, r = _pw.polywire(geo, group, radius, radius_from, divisions, end_caps, joints, joint_angle,
                            carry_attributes)
        return (g, _rep(r))


@_node("modify")
class PCG_Thicken:
    """
    Maps to: (Labs Thicken). Gives open surfaces a thickness: a second skin along the point normals plus side walls
    on the borders. Side: outward / inward / both (the input becomes the mid-surface). Groups thickenFront / Back /
    Side. Closed meshes become hollow shells.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Primitives to thicken"),
            "thickness": _f(0.1, -1e6, 1e6, 0.005),
            "side": (list(_th.MODES),),
            "divisions": _i(1, 1, 1000),
            "front_group": _s("thickenFront"),
            "back_group": _s("thickenBack"),
            "side_group": _s("thickenSide"),
        }}

    def run(self, geo, group, thickness, side, divisions, front_group, back_group, side_group):
        g, r = _th.thicken(geo, group, thickness, side, divisions, front_group, back_group, side_group)
        return (g, _rep(r))


@_node("modify")
class PCG_CurveFillet:
    """
    Maps to: PolyBevel (points on curves). Rounds polyline corners with circular arcs of Radius, tangent to both
    segments; Limit Radius shrinks the arc where the neighbouring segments are too short. Closed polylines /
    polygons round every corner; open curves keep their ends.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Curves (primitives) to fillet"),
            "points": ("STRING", {"default": "", "is_group": True,
                                  "tooltip": "Corner points to round; empty = all corners"}),
            "radius": _f(0.1, 0.0, 1e6, 0.005),
            "divisions": _i(6, 1, 512),
            "limit_radius": _b(True),
            "include_closed": _b(True),
        }}

    def run(self, geo, group, points, radius, divisions, limit_radius, include_closed):
        g, r = _cf.curve_fillet(geo, group, points, radius, divisions, limit_radius, include_closed)
        return (g, _rep(r))


@_node("scatter")
class PCG_Pack:
    """
    Maps to: Pack. Turns each piece (by piece attribute, connectivity, or everything) into one packed primitive:
    a single point carrying the whole piece. Packed geometry is cheap to copy, transform and merge, and the viewport
    draws it as GPU instances. Nodes that need real polygons unpack it automatically.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Primitives to pack"),
            "pack_by": (list(_pk.PACK_BY),),
            "piece_attribute": _names("attrib", "prim", "name", "Pieces are the primitives sharing a value"),
            "pivot": (list(_pk.PIVOTS),),
        }}

    def run(self, geo, group, pack_by, piece_attribute, pivot):
        g, r = _pk.pack(geo, group, pack_by, piece_attribute, pivot)
        return (g, _rep(r))


@_node("scatter")
class PCG_Unpack:
    """
    Maps to: Unpack. Expands packed primitives back into real geometry (other primitives pass through). Copies made
    by Copy to Points' Pack and Instance unpack to exactly what the unpacked copy gives. Transfer Attributes hands
    attributes of the packed points / primitives on to the unpacked pieces.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Packed primitives to unpack"),
            "transfer_attributes": _names("attrib", "point", "",
                                          "Attributes of the packed points / primitives copied to the pieces"),
        }}

    def run(self, geo, group, transfer_attributes):
        g, r = _pk.unpack(geo, group, transfer_attributes)
        return (g, _rep(r))


@_node("scatter")
class PCG_Assemble:
    """
    Maps to: Assemble. Finds the connected pieces of the group's primitives (shared points) and names them
    Name Prefix + number in a string prim attribute -- the usual step after a fracture or a Boolean that leaves loose
    parts. Create Packed Geometry turns every piece into a packed primitive (pivot as in Pack), ready for instancing,
    Transform per piece or export. Primitives outside the group pass through unchanged.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Primitives to assemble; the rest pass through"),
            "name_attribute": _s("name"),
            "name_prefix": _s("piece"),
            "create_packed": _b(False),
            "pivot": (list(_pk.PIVOTS),),
        }}

    def run(self, geo, group, name_attribute, name_prefix, create_packed, pivot):
        g, r = _pk.assemble(geo, group, name_attribute, name_prefix, create_packed, pivot)
        return (g, _rep(r))


_NAMES = {
    "PCG_DistanceFromGeometry": "Distance from Geometry (PCG)",
    "PCG_DistanceAlongGeometry": "Distance along Geometry (PCG)",
    "PCG_PathDeform": "Path Deform (PCG)",
    "PCG_PolyWire": "PolyWire (PCG)",
    "PCG_Thicken": "Thicken (PCG)",
    "PCG_CurveFillet": "Curve Fillet (PCG)",
    "PCG_Pack": "Pack (PCG)",
    "PCG_Unpack": "Unpack (PCG)",
    "PCG_Assemble": "Assemble (PCG)",
}

NODE_CLASS_MAPPINGS = {k: globals()[k] for k in _NAMES}
NODE_DISPLAY_NAME_MAPPINGS = dict(_NAMES)

