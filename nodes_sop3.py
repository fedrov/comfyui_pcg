"""
The third SOP node file (pcg121): nodes added after the code review.

  Distances     Distance from Geometry, Distance along Geometry (edge Dijkstra / heat-method geodesics)
  Curves        Path Deform, PolyWire, Curve Fillet
  Modelling     Thicken
  Packed        Pack, Unpack, Assemble (+ Copy to Points' Pack and Instance, viewport instancing; see geo/packed.py)
  Scene         Lot Subdivision, Building Generator, LOD Create, Impostor Textures (after SideFX Labs)

The end of nodes.py merges the mappings here into the main table; the Houdini mapping is in tests/sop_map.py.
"""
from __future__ import annotations

from .nodes_common import GEO, CAT, _f, _i, _group, _names, _sec  # noqa: F401
from .geo import distgeo as _dg, pathdeform as _pd, polywire as _pw, thicken as _th, curvefillet as _cf
from .geo import packed as _pk
from .geo import lotsubdiv as _ls, building as _bg, lodcreate as _lc, impostor as _imp
from .nodes_common import COP
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



# ═══════════════════════════════════════════════════════ Scene generation (after SideFX Labs)
@_node("generate")
class PCG_LotSubdivision:
    """
    Maps to: Labs Lot Subdivision. Cuts polygons (city blocks) into lots: every polygon is cut in two by a straight
    line, each half again, Iterations times; lots under Minimum Lot Size are left. Alignment: across the bounding
    box's longer side (cuts parallel to the axes) or perpendicular to the longest edge (cuts follow the block).
    Cluster Lots joins neighbouring lots until Number of Clusters remain per block. Writes prim attributes
    lot / block / area; lots share points along common edges.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "group": _group("Polygons to cut; the rest pass through"),
            "alignment": (list(_ls.ALIGNMENTS),),
            "min_lot_size": _f(0.0, 0.0, 1e9, 1.0),
            "iterations": _i(3, 0, 16),
            "rand_seed": _i(0, 0, 2 ** 31 - 1),
            "irregularity": _sec("Shape Settings", _f(0.0, 0.0, 1.0, 0.01)),
            "cluster_lots": _sec("Shape Settings", _b(False)),
            "clusters": _sec("Shape Settings", _i(4, 1, 1 << 20)),
            "cluster_seed": _sec("Shape Settings", _i(0, 0, 2 ** 31 - 1)),
        }}

    def run(self, geo, group, alignment, min_lot_size, iterations, rand_seed, irregularity, cluster_lots,
            clusters, cluster_seed):
        g, r = _ls.lot_subdivision(geo, group, alignment, min_lot_size, iterations, rand_seed, irregularity,
                                   cluster_lots, clusters, cluster_seed)
        return (g, _rep(r))


@_node("generate")
class PCG_BuildingGenerator:
    """
    Maps to: Labs Building Generator. Every footprint polygon (seen from above; up is +Y) becomes a building: walls
    split into floors (Full Floor Height) and bays (Module Width), each bay holding a module named by the Facade
    Module Pattern -- built in (wall, window, door, shopfront) or from a module library (second input: prims with a
    string attribute name, x = width, y = height, z = 0 the wall plane). Corners, top and bottom ledges, a flat or
    parapet roof, per-floor overrides. Writes prim attributes building / floor / part / material / module, a prim
    group per part, and vertex uv in metres.
    """
    @classmethod
    def INPUT_TYPES(cls):
        I = lambda w: _sec("Initialize", w)                # noqa: E731,E741
        Pw = lambda w: _sec("Wall Face", w)                # noqa: E731
        L = lambda w: _sec("Ledges", w)                    # noqa: E731
        Rf = lambda w: _sec("Roof", w)                     # noqa: E731
        return {"required": {
            "geo": (GEO,),
            "group": _group("Footprint polygons"),
            "color_floors": _b(False),
            "floor_height": I(_f(3.0, 0.1, 100.0, 0.05)),
            "floors_min": I(_i(2, 1, 500)),
            "floors_max": I(_i(6, 1, 500)),
            "floors_attribute": I(_s("floors")),
            "height_attribute": I(_s("height")),
            "rand_seed": I(_i(0, 0, 2 ** 31 - 1)),
            "facade_pattern": Pw(_s("window")),
            "module_width": Pw(_f(3.0, 0.1, 100.0, 0.05)),
            "window_width": Pw(_f(0.5, 0.05, 0.98, 0.01)),
            "window_height": Pw(_f(0.5, 0.05, 0.95, 0.01)),
            "window_sill": Pw(_f(0.3, 0.0, 0.9, 0.01)),
            "inset": Pw(_f(0.15, 0.0, 5.0, 0.01)),
            "corners": Pw(_b(True)),
            "corner_width": Pw(_f(0.4, 0.0, 50.0, 0.05)),
            "convex_corner_module": Pw(_s("")),
            "concave_corner_module": Pw(_s("")),
            "top_ledge": L(_b(True)),
            "top_ledge_height": L(_f(0.25, 0.0, 10.0, 0.01)),
            "bottom_ledge": L(_b(False)),
            "bottom_ledge_height": L(_f(0.4, 0.0, 10.0, 0.01)),
            "ledge_depth": L(_f(0.15, 0.0, 10.0, 0.01)),
            "roof": Rf((list(_bg.ROOFS),)),
            "parapet_height": Rf(_f(0.8, 0.0, 20.0, 0.05)),
            "parapet_thickness": Rf(_f(0.3, 0.0, 10.0, 0.05)),
            "floor_overrides": _sec("Customization", ("STRING", {"default": "", "multiline": True})),
            "footprint_inset": I(_f(0.0, 0.0, 100.0, 0.1)),
            "foundation_depth": I(_f(0.0, 0.0, 100.0, 0.1)),
            "front_attribute": Pw(_s("front")),
            "front_pattern": Pw(_s("")),
            "roof_pitch": Rf(_f(35.0, 5.0, 75.0, 1.0)),
            "roof_overhang": Rf(_f(0.3, 0.0, 5.0, 0.05)),
            "roof_attribute": Rf(_s("")),
            "front_pattern_attribute": Pw(_s("")),
            "chimney_chance": Rf(_f(0.0, 0.0, 1.0, 0.01)),
            "yard_wall_height": I(_f(0.0, 0.0, 20.0, 0.05)),
            "yard_wall_thickness": I(_f(0.25, 0.01, 5.0, 0.01)),
            "notch_attribute": I(_s("")),
        }, "optional": {"modules": (GEO,)}}

    def run(self, geo, group, color_floors, floor_height, floors_min, floors_max, floors_attribute,
            height_attribute, rand_seed, facade_pattern, module_width, window_width, window_height, window_sill,
            inset, corners, corner_width, convex_corner_module, concave_corner_module, top_ledge, top_ledge_height,
            bottom_ledge, bottom_ledge_height, ledge_depth, roof, parapet_height, parapet_thickness,
            floor_overrides, footprint_inset=0.0, foundation_depth=0.0, front_attribute="front", front_pattern="",
            roof_pitch=35.0, roof_overhang=0.3, roof_attribute="", front_pattern_attribute="", chimney_chance=0.0,
            yard_wall_height=0.0, yard_wall_thickness=0.25, notch_attribute="", modules=None):
        g, r = _bg.building_generator(
            geo, modules, group, floor_height, floors_min, floors_max, floors_attribute, height_attribute,
            rand_seed, facade_pattern, module_width, window_width, window_height, window_sill, inset, corners,
            corner_width, convex_corner_module, concave_corner_module, top_ledge, top_ledge_height, bottom_ledge,
            bottom_ledge_height, ledge_depth, roof, parapet_height, parapet_thickness, floor_overrides,
            color_floors, footprint_inset, foundation_depth, front_attribute, front_pattern, roof_pitch,
            roof_overhang, roof_attribute, front_pattern_attribute, chimney_chance, yard_wall_height,
            yard_wall_thickness, notch_attribute)
        return (g, _rep(r))


@_node("modify")
class PCG_LODCreate:
    """
    Maps to: Labs LOD Create. Builds a chain of levels of detail: Percent Triangles per level (100 = the mesh as it
    is, the others reduced from it by quadric edge collapse), Threshold Distance per level. Preserve UVs keeps the
    seams so all levels share LOD0's textures; Last LOD is Impostor replaces the last level by two crossed cards.
    A string prim attribute name splits the input into assets, each with its own chain. Writes lod / part / name /
    lod_distance / impostor and prim groups LOD0...; View shows all levels, one, or all side by side.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "percents": _sec("LOD Settings", _s("100 50 25 10")),
            "distances": _sec("LOD Settings", _s("")),
            "first_distance": _sec("LOD Settings", _f(20.0, 0.0, 1e6, 1.0)),
            "last_lod_impostor": _sec("Decimation Settings", _b(False)),
            "preserve_uvs": _sec("Decimation Settings", _b(True)),
            "boundary_weight": _sec("Decimation Settings", _f(4.0, 0.0, 1e6, 0.1)),
            "recalculate_normals": _sec("Decimation Settings", _b(True)),
            "cusp_angle": _sec("Decimation Settings", _f(60.0, 0.0, 180.0, 1.0)),
            "name_prefix": _sec("Export Settings", _s("LOD")),
            "view": _sec("Visualize", (list(_lc.VIEWS),)),
            "level": _sec("Visualize", _i(0, 0, 32)),
            "spacing": _sec("Visualize", _f(1.2, 0.0, 100.0, 0.05)),
        }, "optional": {"custom": (GEO,)}}

    def run(self, geo, percents, distances, first_distance, last_lod_impostor, preserve_uvs, boundary_weight,
            recalculate_normals, cusp_angle, name_prefix, view, level, spacing, custom=None):
        g, r = _lc.lod_create(geo, percents, distances, first_distance, preserve_uvs, boundary_weight,
                              recalculate_normals, cusp_angle, last_lod_impostor, name_prefix, view, level,
                              spacing, custom)
        return (g, _rep(r))


@_node("render", returns=((COP, "cop"), (GEO, "card"), ("STRING", "report")))
class PCG_ImpostorTextures:
    """
    Maps to: Labs Impostor Texture / Impostor Baker. Renders the geometry from a grid of directions into one atlas
    (orthographic, framed on the bounding sphere): octahedron (the whole sphere), hemi_octahedron (the upper half),
    fixed_axis (round the up axis at one Elevation) or 3d (azimuth x elevation). Layers: C (base colour from Cd,
    unlit), alpha, N (world or view space), depth (0..1 across the bounding sphere), beauty (lit). The second
    output is the card (a quad, uv 0..1) with the impostor's settings as detail attributes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "geo": (GEO,),
            "impostor_type": (list(_imp.TYPES),),
            "sprite_resolution": _i(128, 4, 2048),
            "frames_x": _i(8, 1, 64),
            "frames_y": _i(8, 1, 64),
            "elevation": _f(0.0, -89.0, 89.0, 1.0),
            "zoom": _f(1.0, 0.1, 10.0, 0.01),
            "normal_space": (list(_imp.NORMAL_SPACES),),
            "sun_direction": _s("0.4 0.8 0.45"),
        }}

    def run(self, geo, impostor_type, sprite_resolution, frames_x, frames_y, elevation, zoom, normal_space,
            sun_direction):
        img, card, r = _imp.impostor_textures(geo, impostor_type, sprite_resolution, frames_x, frames_y,
                                              elevation, zoom, normal_space, sun_direction)
        return (img, card, _rep(r))


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
    "PCG_LotSubdivision": "Lot Subdivision (PCG)",
    "PCG_BuildingGenerator": "Building Generator (PCG)",
    "PCG_LODCreate": "LOD Create (PCG)",
    "PCG_ImpostorTextures": "Impostor Textures (PCG)",
}

NODE_CLASS_MAPPINGS = {k: globals()[k] for k in _NAMES}
NODE_DISPLAY_NAME_MAPPINGS = dict(_NAMES)

