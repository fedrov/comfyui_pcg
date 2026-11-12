"""
Houdini geometry (SOP) nodes × comfyui_pcg, node-by-node mapping table: the gap inventory on the SOP side (pcg66).

━━ Where this table comes from, and what it is **not**
SideFX's SOP index page (Houdini 22.0, nodes/sop/index.html) has more than nine hundred entries,
and the fetch tool could only read its first part: A through "Detangle" was copied **entry by entry against the H22 index**;
E through R was checked against a mirror of an older index (about H17/18); the rest was compiled from the
Houdini 20.5–22 nodes. Therefore:

  · The core modeling / attribute / group / curve / UV / heightfield / fracture families are listed **one by one**;
    these are what the gap inventory cares about
  · Large families unrelated to this plugin's direction (KineFX / APEX / Agent / Crowd / Vellum / hair /
    muscle / cloud / fluid / Pyro / RBD solving / DOP / sparse VDB ...) are **merged into one row per family**,
    with roughly how many nodes and why they are not done. Together they make up more than half of the index
  · This is not a verbatim copy of the H22 index: a few new nodes may be missing, and a few names may be old-version names.
    The criterion is "nodes a Houdini user would look for when building procedural geometry in ComfyUI", not
    "every row of the index"

━━ Status
  done      has an equivalent node (named; several Houdini nodes are often merged into different modes of the **same**
            node, e.g. Twist / Bend / Taper are all modes of Deform (PCG))
  new       added after the inventory (from pcg67 on, nodes in nodes_sop2.py; pcg67 batches A/B, pcg68 batches C/D)
  partial   a node can do it, but a key piece of functionality is missing (says what)
  todo      should be added, not done yet. With priority:
              P1  backbone of procedural modeling; many chains cannot be built without it
              P2  common; there is a workaround but it is awkward
              P3  niche / nice to have
  platform  the ComfyUI graph itself is this feature (Null, Output, Object Merge, Switch-If ...)
  bridge    not reimplemented; connects to ComfyUI / other data types of this plugin (e.g. heightfields go through COP)
  oos       not done, with the reason

Value shapes:
  ("done", "PCG_X")                    ("done", "PCG_X", "note")
  ("partial", "PCG_X", "what is missing")
  ("todo", "P1", "planned node name: one sentence")
  ("platform" / "bridge" / "oos", "reason")
Keys in FAMILY are rows merged per family (values as above, plus a rough node count).
"""

# ─────────────────────────────────────────────────────────── Common reasons
OOS_CHAR = "Character / rigging / animation (KineFX, APEX, skeleton skinning): this plugin does procedural geometry and AI control images, not character pipelines"
OOS_SIM = "Solvers (need cross-frame state and a full set of force fields / constraints); the plugin's simulation only covers 2D fields on the COP side"
OOS_PACKED = "No packed semantics: Copy to Points outputs real geometry directly; chunking uses the piece attribute + For-Each"
OOS_VDB = "Sparse-VDB specific (active regions, tree structure, VDB points); volumes here are dense numpy grids (geo/volume.py)"
OOS_VIEWPORT = "Viewport interaction (brush / paint / manual drag); ComfyUI has no editing interaction in a geometry viewport"
OOS_IO = "Houdini proprietary formats / ROP output; geometry goes in and out via Import Mesh / Export Mesh / File Cache"
OOS_NURBS = "NURBS surface modeling (projection, surface-surface intersection, profile curves); NURBS here only goes as far as Convert / Carve / Resample"
OOS_ARRAY = "Array / dictionary attributes: the attribute table is a fixed-size (N, C) array and cannot store variable-length values"
OOS_META = "Houdini-specific prim types such as Metaball / tetrahedron / polygon soup"
OOS_TEST = "Test models"
OOS_RENDER = "Rendering / materials / shading (the exit here is Render Pass → ControlNet)"
PLATFORM = "The ComfyUI graph itself (wires, subgraphs, caching, outputs, switches)"
WRANGLE = "A one-line Wrangle does it"

M = {
 # ─────────────────────────────────────────────── A
 "Adapt to Terrain": ("oos", OOS_CHAR),
 "Adaptive Prune": ("new", "PCG_AdaptivePrune"),
 "Add": ("done", "PCG_Add"),
 "Alembic": ("oos", OOS_IO), "Alembic Group": ("oos", OOS_IO),
 "Alembic Primitive": ("oos", OOS_IO),
 "Armature Capture": ("oos", OOS_CHAR), "Armature Deform": ("oos", OOS_CHAR),
 "Assemble": ("new", "PCG_Assemble", "pcg122: connected pieces named prefix0..; Create Packed Geometry packs them"),
 "Association Select": ("oos", OOS_CHAR),
 "Attach Joint Geometry": ("oos", OOS_CHAR),
 "Attribute Adjust Array": ("oos", OOS_ARRAY),
 # pcg100 s6: the Houdini semantics are in PCG_AttribAdjustColor; PCG_Color is still the Color SOP
 "Attribute Adjust Color": ("new", "PCG_AttribAdjustColor"),
 "Attribute Adjust Dictionary": ("oos", OOS_ARRAY),
 # pcg100 s6: the Houdini semantics (Operation × Pattern Type) are in PCG_AttribAdjustFloat / Integer;
 # the merged PCG_AttribAdjust (four-stage pipeline + text operation stack) is kept; Attribute Remap still points to it
 "Attribute Adjust Float": ("new", "PCG_AttribAdjustFloat"),
 "Attribute Adjust Integer": ("new", "PCG_AttribAdjustInteger"),
 "Attribute Adjust Vector": ("new", "PCG_AttribAdjustVector"),
 "Attribute Blur": ("done", "PCG_AttribBlur"),
 "Attribute Cast": ("done", "PCG_AttribCast"),
 "Attribute Combine": ("done", "PCG_Wrangle", WRANGLE),
 "Attribute Composite": ("new", "PCG_AttribComposite"),
 "Attribute Copy": ("done", "PCG_AttribCopy"),
 "Attribute Create": ("done", "PCG_AttribCreate"),
 "Attribute Delete": ("done", "PCG_AttribDelete"),
 "Attribute Expression": ("done", "PCG_Wrangle", WRANGLE),
 # pcg100 s7: Houdini's Attribute Fade fades in/out over time; PCG_AttribFade (spatial falloff) is a different thing and is kept
 "Attribute Fade": ("new", "PCG_AttribFadeTime"),
 "Attribute Fill": ("new", "PCG_AttribFill"),
 "Attribute From Pieces": ("new", "PCG_AttribFromPieces"),
 "Attribute Interpolate": ("done", "PCG_AttribInterpolate"),
 "Attribute Mirror": ("new", "PCG_AttribMirror"),
 "Attribute Noise": ("done", "PCG_AttribNoise"),
 "Attribute Paint": ("oos", OOS_VIEWPORT),
 "Attribute Promote": ("done", "PCG_AttribPromote"),
 "Attribute Randomize": ("done", "PCG_AttribRandomize"),
 "Attribute Remap": ("done", "PCG_AttribAdjust", "The Use Remap section"),
 "Attribute Rename": ("done", "PCG_AttribRename"),
 "Attribute Reorient": ("new", "PCG_AttribReorient"),
 "Attribute Sort": ("oos", OOS_ARRAY),
 "Attribute String Edit": ("new", "PCG_AttribStringEdit"),
 "Attribute Swap": ("done", "PCG_Wrangle", WRANGLE),
 "Attribute Transfer": ("done", "PCG_AttribTransfer"),
 "Attribute Transfer by UV": ("new", "PCG_AttribTransferByUV"),
 "Attribute Transform Compute": ("oos", OOS_CHAR),
 # pcg100 s7: Houdini's one "splits a matrix attribute into components + Euler filter"; PCG_AttribTransformExtract (per-piece rigid transform) moved to EXTRA
 "Attribute Transform Extract": ("new", "PCG_AttribTransformExtractHou"),
 "Attribute VOP": ("platform", "A VOP network = the node graph itself; per-element computation uses Wrangle"),
 "Attribute Wrangle": ("done", "PCG_Wrangle"),
 "Attribute from Map": ("done", "PCG_AttribFromMap"),
 "Attribute from Parameters": ("platform", "Parameters / Param Pick nodes + wires"),
 "Attribute from Volume": ("new", "PCG_AttribFromVolume", "trilinear / nearest / gradient"),
 # ─────────────────────────────────────────────── B
 "Bake GSplats": ("oos", OOS_RENDER),
 "Bake ODE": ("oos", OOS_SIM),
 "Bake Pre-Process": ("done", "PCG_COPBakeTextures", "Bake pre-processing is merged into the bake node"),
 "Bake Volume": ("oos", OOS_RENDER),
 "Ballistic Path": ("new", "PCG_BallisticPath"),
 "Bend": ("done", "PCG_Deform", "bend mode"),
 "Blast": ("done", "PCG_Blast"),
 "Blast by Attribute": ("new", "PCG_BlastByAttribute"),
 "Blend Shapes": ("new", "PCG_BlendShapes", "additive / sequential; matched by point number or id"),
 "Block Begin": ("platform", "PCG_ForEachBegin"),
 "Block Begin Compile": ("platform", PLATFORM),
 "Block End": ("platform", "PCG_ForEachEnd"),
 "Block End Compile": ("platform", PLATFORM),
 "Boolean": ("done", "PCG_Boolean"),
 # pcg100 s9: the Houdini semantics (piece naming, inside/outside groups, normals) are in PCG_BooleanFracture
 "Boolean Fracture": ("new", "PCG_BooleanFracture", "Cutting surfaces used as Surface must pass through the whole object; point / vertex attributes are not carried"),
 "Bound": ("done", "PCG_Bound"),
 "Box": ("done", "PCG_Box"),
 "Bulge": ("new", "PCG_Bulge"),
 # ─────────────────────────────────────────────── C
 "COP Network": ("bridge", "The COP nodes (PCG/cop) are this network; Heightfield to Mesh / Rasterize connect both ends"),
 "COP Preview Material": ("oos", OOS_RENDER),
 "Cache": ("platform", PLATFORM), "Cache If": ("platform", PLATFORM),
 "Camera": ("done", "PCG_Camera"),
 "Camera Edit": ("oos", OOS_VIEWPORT), "Camera Import": ("oos", OOS_IO),
 "Camera To Points": ("new", "PCG_CameraToPoints"),
 "Camera from Points": ("new", "PCG_CameraFromPoints"),
 "Carve": ("done", "PCG_Carve"),
 "Chain": ("new", "PCG_Chain"),
 "Channel": ("oos", "CHOP channels; for animation channels use Channel (PCG)"),
 "Circle": ("done", "PCG_Circle"),
 "Circle Spline": ("new", "PCG_CircleSpline"),
 "Circle from Edges": ("new", "PCG_CircleFromEdges"),
 "Clean": ("new", "PCG_Clean"),
 "Clip": ("done", "PCG_Clip"),
 "Cluster": ("new", "PCG_ClusterPoints", "k-means point clustering"),
 "Cluster Points": ("new", "PCG_ClusterPoints"),
 "Color": ("new", "PCG_Color"),
 "Connect Adjacent Pieces": ("new", "PCG_ConnectAdjacentPieces"),
 "Connectivity": ("done", "PCG_Connectivity"),
 "Control": ("oos", OOS_VIEWPORT),
 "Convert": ("done", "PCG_Convert"),
 "Convert HeightField": ("bridge", "PCG_COPHeightfieldToMesh", "Heightfields live on the COP side"),
 "Convert Line": ("done", "PCG_ConvertLine"),
 "Convert Meta": ("oos", OOS_META), "Convert Tets": ("oos", OOS_META),
 "Convert VDB": ("new", "PCG_ConvertVDB", "pcg106: VDB ↔ volume, fog ↔ SDF, closed polygons"),
 "Convert VDB Points": ("bridge", "VDB Points are ordinary points here (pcg106): no conversion needed; the VDB Points nodes work on points"),
 "Convert Volume": ("done", "PCG_Convert", "volume -> polygons"),
 "Convex Decomposition": ("done", "PCG_ConvexDecompose"),
 "Copy and Transform": ("new", "PCG_CopyAndTransform"),
 "Copy to Curves": ("new", "PCG_CopyToCurves"),
 "Copy to Points": ("done", "PCG_CopyToPoints"),
 "Crease": ("new", "PCG_Crease"),
 # pcg100: the Houdini semantics are in PCG_CrossSectionSurfaceHou; PCG_CrossSectionSurface is a Gordon surface (two curve families) and is kept
 "Cross Section Surface": ("new", "PCG_CrossSectionSurfaceHou"),
 "Curve": ("done", "PCG_Curve", "Draw in the viewport: points, drag, insert, delete, close; Polygon / NURBS / Bezier"),
 "Curve Intersect": ("new", "PCG_CurveIntersect"),
 # ─────────────────────────────────────────────── D
 "Deflate": ("oos", OOS_SIM),
 "Deformation Wrangle": ("oos", OOS_CHAR),
 "Delete": ("done", "PCG_Delete"),
 "DeltaMush": ("new", "PCG_DeltaMush"),
 "Detangle": ("oos", OOS_SIM),
 "Dissolve": ("done", "PCG_Dissolve"),
 "Divide": ("done", "PCG_Divide"),
 # ─────────────────────────────────────────────── E
 "Edge Collapse": ("new", "PCG_EdgeCollapse"),
 "Edge Cusp": ("new", "PCG_EdgeCusp"),
 "Edge Divide": ("done", "PCG_EdgeDivide"),
 "Edge Equalize": ("new", "PCG_EdgeEqualize"),
 "Edge Flip": ("new", "PCG_EdgeFlip"),
 "Edge Straighten": ("new", "PCG_EdgeStraighten"),
 "Edge Transport": ("new", "PCG_EdgeTransport"),
 "Edit": ("oos", OOS_VIEWPORT),
 "Ends": ("done", "PCG_Ends"),
 "Enumerate": ("new", "PCG_Enumerate"),
 "Error": ("platform", "ComfyUI's node errors"),
 "Exploded View": ("done", "PCG_ExplodedView"),
 "Extract Centroid": ("done", "PCG_ExtractCentroid"),
 "Extract Silhouette": ("new", "PCG_ExtractSilhouette"),
 "Extract Transform": ("new", "PCG_ExtractTransform", "rigid / similarity / affine"),
 # ─────────────────────────────────────────────── F
 "Facet": ("done", "PCG_Facet"),
 "File": ("done", "PCG_ImportMesh"),
 "File Cache": ("done", "PCG_FileCache"),
 # pcg100 s9: $SLICE sequence merging is in PCG_FileMerge; Import Mesh unchanged
 "File Merge": ("new", "PCG_FileMerge", "No Load (Info / Info Bounding Box) and no Cache Length"),
 "Fillet": ("oos", OOS_NURBS),
 "Find Shortest Path": ("new", "PCG_FindShortestPath"),
 "Fit": ("oos", OOS_NURBS),
 "Font": ("new", "PCG_Font", "fontTools reads vector outlines; outline / faces / extrude; GPOS kerning not done"),
 "Fractal": ("new", "PCG_Fractal"),
 "Fuse": ("done", "PCG_Fuse"),
 # ─────────────────────────────────────────────── G
 "Grid": ("done", "PCG_Grid"),
 "Group": ("done", "PCG_GroupCreate"),
 "Group Combine": ("new", "PCG_GroupCombine"),
 "Group Copy": ("done", "PCG_AttribCopy", "groups parameter"),
 "Group Delete": ("done", "PCG_GroupDelete"),
 "Group Expand": ("done", "PCG_GroupExpand"),
 "Group Expression": ("done", "PCG_GroupCreate", "write an @expression in base"),
 "Group Find Path": ("new", "PCG_GroupFindPath"),
 "Group from Attribute Boundary": ("new", "PCG_GroupFromAttribBoundary"),
 "Group Paint": ("oos", OOS_VIEWPORT),
 "Group Promote": ("done", "PCG_GroupPromote", "for edge groups see also Edge Group Promote"),
 "Group Range": ("done", "PCG_GroupCreate", "write 0-99:2 in base"),
 "Group Rename": ("done", "PCG_AttribRename", "Rename Groups toggle"),
 "Group Transfer": ("done", "PCG_AttribTransfer", "point_groups / prim_groups"),
 # ─────────────────────────────────────────────── H (heightfields are all on the COP side)
 "HeightField": ("bridge", "PCG_COPConstant"),
 "HeightField Blur": ("bridge", "PCG_COPBlur"),
 "HeightField Clip": ("bridge", "PCG_COPHFClip"),
 "HeightField Copy Layer": ("bridge", "PCG_COPLayerEdit"),
 "HeightField Crop": ("bridge", "PCG_COPCrop"),
 "HeightField Cutout by Object": ("bridge", "PCG_COPHFCutoutByObject"),
 "HeightField Distort by Layer": ("bridge", "PCG_COPWarp"),
 "HeightField Distort by Noise": ("bridge", "PCG_COPDistort"),
 "HeightField Draw Mask": ("oos", OOS_VIEWPORT),
 "HeightField Erode": ("bridge", "PCG_COPHeightfieldErode", "Grid solver like Houdini; also Hydraulic Erosion (droplets), Erosion (filter), Stream Power"),
 "HeightField Erode Hydro": ("bridge", "PCG_COPHeightfieldErode"),
 "HeightField Erode Precipitation": ("bridge", "PCG_COPFlowAccumulation"),
 "HeightField Erode Thermal": ("bridge", "PCG_COPThermalErosion"),
 "HeightField File": ("bridge", "PCG_COPImport"),
 "HeightField Flow Field": ("bridge", "PCG_COPFlowAccumulation"),
 "HeightField Isolate Layer": ("bridge", "PCG_COPLayerEdit"),
 "HeightField Layer": ("bridge", "PCG_COPComposite"),
 "HeightField Layer Clear": ("bridge", "PCG_COPFill"),
 "HeightField Layer Property": ("oos", "Layers have no metadata attributes (boundary mode and projection are node parameters)"),
 "HeightField Mask by Feature": ("bridge", "PCG_COPMaskByFeature"),
 "HeightField Mask by Object": ("bridge", "PCG_COPHFMaskByObject"),
 "HeightField Mask by Occlusion": ("bridge", "PCG_COPHeightToAO"),
 "HeightField Mask Clear": ("bridge", "PCG_COPFill"),
 "HeightField Mask Expand": ("bridge", "PCG_COPMorph"),
 "HeightField Mask Noise": ("bridge", "PCG_COPNoise"),
 "HeightField Noise": ("bridge", "PCG_COPNoise"),
 "HeightField Output": ("bridge", "PCG_COPExport"),
 "HeightField Paint": ("oos", OOS_VIEWPORT),
 "HeightField Patch": ("bridge", "PCG_COPComposite"),
 "HeightField Pattern": ("bridge", "PCG_COPPattern"),
 "HeightField Project": ("bridge", "PCG_COPHFProject"),
 "HeightField Quick Shade": ("bridge", "PCG_COPLight"),
 "HeightField Remap": ("bridge", "PCG_COPRemap"),
 "HeightField Resample": ("bridge", "PCG_COPResize"),
 "HeightField Scatter": ("done", "PCG_ScatterFromMap"),
 "HeightField Slump": ("bridge", "PCG_COPThermalErosion"),
 "HeightField Smooth Lowlands": ("bridge", "PCG_COPMaskByFeature", "Make a mask by height, then Blur"),
 "HeightField Terrace": ("bridge", "PCG_COPTerrace"),
 "HeightField Tile Splice": ("new", "PCG_COPTileSplice"),
 "HeightField Tile Split": ("new", "PCG_COPTileSplit"),
 "HeightField Transform": ("bridge", "PCG_COPTransform"),
 "HeightField Visualize": ("bridge", "PCG_COPVisualize"),
 "HeightField Wrangle": ("bridge", "PCG_COPWrangle"),
 "Hole": ("oos", "A prim has only one vertex loop and cannot store faces with holes (which is also why Divide's Remove Shared Edges does not merge pieces with holes)"),
 # ─────────────────────────────────────────────── I – L
 "Instance": ("oos", OOS_PACKED),
 # pcg100 s9: intersection points + source attributes are in PCG_IntersectionAnalysis; Boolean's seam mode unchanged
 "Intersection Analysis": ("new", "PCG_IntersectionAnalysis", "Only outputs intersection points; no Point Num"),
 "Intersection Stitch": ("partial", "PCG_Boolean", "seam mode"),
 "Invoke Compiled Block": ("platform", PLATFORM),
 # pcg100 s9: the Houdini semantics (Mode / sampling / Offset / bounding box) are in PCG_IsoOffset; Convert's volume modes unchanged
 "IsoOffset": ("new", "PCG_IsoOffset", "Ray Intersect determines sign with pseudo-normals; no Tetra / Cubes / Meta Balls / Volume Sample"),
 "IsoSurface": ("new", "PCG_IsoSurface"),
 "Join": ("done", "PCG_Join"),
 "Knife": ("done", "PCG_Clip", "keep = both is a knife cut"),
 "L-System": ("new", "PCG_LSystem", "Stochastic rules, tropism; parametric and context-sensitive rules not done"),
 "Lattice": ("new", "PCG_Lattice", "Pairs with PCG_LatticeFromBound; trilinear / Bernstein"),
 "Lidar Import": ("partial", "PCG_ImportMesh", "Reads PLY point clouds; does not read LAS/LAZ"),
 "Line": ("done", "PCG_Line"),
 # ─────────────────────────────────────────────── M – O
 "MDD": ("oos", OOS_IO),
 "Magnet": ("new", "PCG_Magnet"),
 "Match Axis": ("new", "PCG_MatchAxis"),
 "Match Size": ("done", "PCG_MatchSize"),
 "Match Topology": ("new", "PCG_MatchTopology"),
 "Material": ("oos", OOS_RENDER),
 "Measure": ("done", "PCG_Measure"),
 "Merge": ("done", "PCG_Merge"),
 "Merge Packed": ("oos", OOS_PACKED),
 "Metaball": ("oos", OOS_META), "MetaGroups": ("oos", OOS_META),
 "Mirror": ("done", "PCG_Mirror"),
 "Mountain": ("done", "PCG_AttribNoise", "Add noise to P along the normal"),
 # pcg100 s7: Name is "write names for groups / name by group / rename"; the Format numbering mode is Enumerate (the row above)
 "Name": ("new", "PCG_Name"),
 "Normal": ("done", "PCG_Normal"),
 "Null": ("platform", PLATFORM),
 "Object Merge": ("platform", "A wire is Object Merge"),
 "Ocean Evaluate": ("bridge", "PCG_COPOcean"),
 "Ocean Spectrum": ("bridge", "PCG_COPOcean"),
 "OpenCL": ("oos", "OpenCL kernels; GPU compute goes through torch (COP's Compute / Device)"),
 "Orient Along Curve": ("new", "PCG_OrientAlongCurve"),
 "Output": ("platform", PLATFORM),
 # ─────────────────────────────────────────────── P
 "Pack": ("new", "PCG_Pack", "pcg121: packed primitives (one point per piece); Copy to Points' Pack and Instance; GPU instancing in the viewport"),
 "Unpack": ("new", "PCG_Unpack"),
 "Path Deform": ("new", "PCG_PathDeform"),
 "Distance from Geometry": ("new", "PCG_DistanceFromGeometry"),
 "Distance along Geometry": ("new", "PCG_DistanceAlongGeometry", "Geodesic = heat method; Edges = Dijkstra along edges"),
 "Unpack Points": ("oos", OOS_PACKED),
 "Paint Color Volume": ("oos", OOS_VIEWPORT),
 "Partition": ("new", "PCG_Partition"),
 "Peak": ("done", "PCG_Peak"),
 "Platonic Solids": ("new", "PCG_PlatonicSolids", "Utah teapot not done"),
 "Point Deform": ("new", "PCG_PointDeform", "rigid (local Kabsch) / translate"),
 "Point Generate": ("done", "PCG_Add"),
 "Point Jitter": ("done", "PCG_PointJitter"),
 "Point Relax": ("new", "PCG_PointRelax"),
 "Point Replicate": ("new", "PCG_PointReplicate"),
 "Point Split": ("new", "PCG_PointSplit"),
 "Point Velocity": ("new", "PCG_PointVelocity"),
 "Points from Volume": ("done", "PCG_ScatterVolume"),
 "Poly Bridge": ("new", "PCG_PolyBridge", "faces / curves / hole boundaries; linear / hermite"),
 "PolyBevel": ("done", "PCG_PolyBevel"),
 "PolyCut": ("new", "PCG_PolyCut"),
 # pcg100 s7: the per-item Ignore / Mark / Repair is in PCG_PolyDoctor; the Clean SOP is still PCG_Clean
 "PolyDoctor": ("partial", "PCG_PolyDoctor", "Not done: Self-intersecting, Globally Small Areas, Visualize, and the manifold patch items"),
 "PolyExpand2D": ("done", "PCG_PolyExpand2D"),
 "PolyExtrude": ("done", "PCG_PolyExtrude"),
 "PolyFill": ("done", "PCG_PolyFill"),
 "PolyFrame": ("new", "PCG_PolyFrame"),
 "PolyLoft": ("new", "PCG_PolyLoft"),
 "PolyPatch": ("oos", OOS_NURBS),
 "PolyPath": ("done", "PCG_PolyPath"),
 "PolyReduce": ("done", "PCG_PolyReduce"),
 "PolySoup": ("oos", OOS_META),
 "PolySpline": ("new", "PCG_PolySpline"),
 "PolySplit": ("new", "PCG_PolySplit"),
 "PolyStitch": ("new", "PCG_PolyStitch"),
 "PolyWire": ("new", "PCG_PolyWire", "pcg121: edge networks with joints (before: Sweep's round tube, one curve at a time)"),
 "Primitive": ("new", "PCG_Primitive"),
 "Primitive Split": ("new", "PCG_PrimitiveSplit"),
 "Profile": ("oos", OOS_NURBS), "Project": ("oos", OOS_NURBS),
 "Python": ("oos", "Python SOP; the scripting layer here is Wrangle expressions (arbitrary Python is not exposed, for safety)"),
 # ─────────────────────────────────────────────── R
 "Rails": ("oos", OOS_NURBS),
 "Ray": ("done", "PCG_Ray"),
 "Refine": ("done", "PCG_Refine"),
 "Remesh": ("new", "PCG_Remesh"),
 "Remesh to Grid": ("new", "PCG_RemeshToGrid"),
 "Resample": ("done", "PCG_Resample"),
 "Rest Position": ("done", "PCG_Wrangle", "v@rest = @P"),
 "Reverse": ("done", "PCG_Reverse"),
 "Revolve": ("new", "PCG_Revolve"),
 "Rewire Vertices": ("new", "PCG_RewireVertices"),
 # ─────────────────────────────────────────────── S
 "Scatter": ("done", "PCG_Scatter"),
 "Scatter and Align": ("new", "PCG_ScatterAlign"),
 "Script": ("oos", "HScript"),
 "Sequence Blend": ("done", "PCG_TimeBlend"),
 "Shrinkwrap": ("new", "PCG_Shrinkwrap"),
 "Skin": ("done", "PCG_Skin"),
 "Smooth": ("done", "PCG_Smooth"),
 "Soft Peak": ("new", "PCG_SoftPeak"),
 "Soft Transform": ("done", "PCG_SoftTransform"),
 "Solidify": ("oos", OOS_SIM),
 "Sort": ("done", "PCG_Sort"),
 "Sphere": ("done", "PCG_Sphere"),
 "Split": ("done", "PCG_Split"),
 "Split Points": ("new", "PCG_PointSplit"),
 "Spray Paint": ("oos", OOS_VIEWPORT),
 "Stash": ("done", "PCG_FileCache"),
 "Subdivide": ("done", "PCG_Subdivide"),
 "Surfsect": ("oos", OOS_NURBS),
 "Sweep": ("done", "PCG_Sweep"),
 "Switch": ("done", "PCG_Switch"),
 "Switch-If": ("new", "PCG_SwitchIf"),
 # ─────────────────────────────────────────────── T
 "Tangent Field": ("new", "PCG_TangentField"),
 "Time Shift": ("done", "PCG_Retime"),
 "TopoBuild": ("oos", OOS_VIEWPORT),
 "Topo Transfer": ("new", "PCG_TopoTransfer", "Projection + smoothed displacement field, not a full non-rigid ICP"),
 "Torus": ("done", "PCG_Torus"),
 "Trace": ("done", "PCG_Trace"),
 "Trail": ("done", "PCG_Trail"),
 "Transform": ("done", "PCG_Transform"),
 "Transform by Attribute": ("new", "PCG_TransformByAttrib"),
 "Transform Pieces": ("new", "PCG_TransformPieces"),
 "Tri Divide": ("new", "PCG_TriDivide"),
 "Triangulate 2D": ("done", "PCG_Triangulate2D"),
 "Tube": ("done", "PCG_Tube"),
 "Twist": ("done", "PCG_Deform", "twist / taper / squash / shear modes"),
 # ─────────────────────────────────────────────── U
 "Unsubdivide": ("new", "PCG_Unsubdivide"),
 "UV Autoseam": ("done", "PCG_UVAutoSeams"),
 "UV Edit": ("oos", OOS_VIEWPORT),
 "UV Flatten": ("done", "PCG_UVFlatten"),
 "UV Fuse": ("new", "PCG_UVFuse"),
 "UV Layout": ("done", "PCG_UVLayout"),
 "UV Pelt": ("new", "PCG_UVPelt"),
 "UV Project": ("done", "PCG_UVProject"),
 "UV Quick Shade": ("done", "PCG_TextureRender", "Render a checkerboard texture"),
 "UV Smooth": ("new", "PCG_UVSmooth"),
 "UV Texture": ("done", "PCG_UVProject"),
 "UV Transform": ("done", "PCG_UVTransform"),
 "UV Unwrap": ("new", "PCG_UVUnwrap"),
 "UV Visualize": ("done", "PCG_GeoMetrics", "uv utilization / overlap; to look at it use Texture Render"),
 # ─────────────────────────────────────────────── V – Z
 "Visibility": ("platform", "For the display flag use Display (PCG)"),
 "Volume": ("new", "PCG_Volume"),
 "Volume Blur": ("new", "PCG_VolumeBlur"),
 "Volume Mix": ("new", "PCG_VolumeMix"),
 "Volume Rasterize Attributes": ("new", "PCG_VolumeRasterizeAttribs"),
 "Volume Resample": ("new", "PCG_VolumeResample"),
 "Volume Sample": ("new", "PCG_AttribFromVolume"),
 "Volume Wrangle": ("new", "PCG_VolumeWrangle"),
 "VDB from Polygons": ("new", "PCG_VDBFromPolygons", "pcg106: narrow band, fill interior, unsigned, fog, surface attributes"),
 # pcg100 s9: Houdini's four Operations are in PCG_VolumeSmoothSDF; Volume Blur is still the Volume Blur SOP
 # ── pcg106: the VDB family (dense grid + active mask + background, geo/vdb.py) and the rest of the Volume SOPs
 "VDB": ("new", "PCG_VDB"),
 "VDB Activate": ("new", "PCG_VDBActivate"),
 "VDB Activate SDF": ("new", "PCG_VDBActivateSDF"),
 "VDB Advect": ("new", "PCG_VDBAdvect"),
 "VDB Advect Points": ("new", "PCG_VDBAdvectPoints"),
 "VDB Analysis": ("new", "PCG_VDBAnalysis"),
 "VDB Clip": ("partial", "PCG_VDBClip", "Geometry bounds and mask VDB; no camera frustum clipping"),
 "VDB Densify": ("new", "PCG_VDBDensify"),
 "VDB Diagnostics": ("new", "PCG_VDBDiagnostics"),
 "VDB Extrapolate": ("new", "PCG_VDBExtrapolate"),
 "VDB Fill": ("new", "PCG_VDBFill"),
 "VDB Fracture": ("new", "PCG_VDBFracture"),
 "VDB from Particles": ("new", "PCG_VDBFromParticles"),
 "VDB from Particle Fluid": ("new", "PCG_VDBFromParticleFluid"),
 "VDB LOD": ("new", "PCG_VDBLOD"),
 "VDB Merge": ("new", "PCG_VDBMerge"),
 "VDB Metadata": ("new", "PCG_VDBMetadata"),
 "VDB Morph SDF": ("new", "PCG_VDBMorphSDF"),
 "VDB Noise": ("new", "PCG_VDBNoise"),
 "VDB Occlusion Mask": ("partial", "PCG_VDBOcclusionMask", "The mask lives on the input grid, not in a camera frustum grid"),
 "VDB Platonic": ("new", "PCG_VDBPlatonic"),
 "VDB Points Delete": ("bridge", "VDB Points are ordinary points here: Blast / Delete by group"),
 "VDB Points Group": ("new", "PCG_VDBPointsGroup"),
 "VDB Points Merge": ("bridge", "VDB Points are ordinary points here: Merge"),
 "VDB Potential Flow": ("new", "PCG_VDBPotentialFlow"),
 "VDB Project Non-Divergent": ("new", "PCG_VDBProjectNonDivergent"),
 "VDB Prune": ("new", "PCG_VDBPrune"),
 "VDB Rasterize Frustum": ("oos", "Frustum (camera) transforms are not modelled: grids here are axis-aligned boxes"),
 "VDB Rasterize Points": ("new", "PCG_VolumeRasterizePoints"),
 "VDB Ray": ("new", "PCG_VDBRay"),
 "VDB Rebuild SDF": ("new", "PCG_VDBRebuildSDF"),
 "VDB Remap": ("new", "PCG_VDBRemap"),
 "VDB Renormalize SDF": ("new", "PCG_VDBRenormalizeSDF"),
 "VDB Resample": ("new", "PCG_VDBResample"),
 "VDB Sample Points": ("new", "PCG_AttribFromVolume"),
 "VDB Scatter": ("new", "PCG_VDBScatter"),
 "VDB Segment by Connectivity": ("new", "PCG_VDBSegment"),
 "VDB Sort Points": ("bridge", "VDB Points are ordinary points here: Sort"),
 "VDB to Spheres": ("new", "PCG_VDBToSpheres", "Spheres are points with pscale (no sphere prim type)"),
 "VDB Topology to SDF": ("new", "PCG_VDBTopologyToSDF"),
 "VDB Transform": ("new", "PCG_VDBTransform", "Rotation resamples (grids are axis aligned)"),
 "VDB Vector Merge": ("new", "PCG_VDBVectorMerge"),
 "VDB Vector Split": ("new", "PCG_VDBVectorSplit"),
 "VDB Visualize Tree": ("new", "PCG_VDBVisualizeTree"),
 "VDB AX": ("platform", "Volume Wrangle (Python-vectorised VEX-like syntax) covers VDB AX"),
 "Volume Adjust Fog": ("new", "PCG_VolumeAdjustFog"),
 "Volume Analysis": ("new", "PCG_VDBAnalysis"),
 "Volume Bound": ("new", "PCG_VolumeBound"),
 "Volume Break": ("new", "PCG_VolumeBreak", "Holes are not closed"),
 "Volume Compress": ("new", "PCG_VolumeCompress"),
 "Volume Convolve 3×3×3": ("new", "PCG_VolumeConvolve"),
 "Volume Feather": ("new", "PCG_VolumeFeather"),
 "Volume FFT": ("new", "PCG_VolumeFFT"),
 "Volume from Attrib": ("new", "PCG_VolumeFromAttrib"),
 "Volume Merge": ("new", "PCG_VolumeMerge"),
 "Volume Optical Flow": ("new", "PCG_VolumeOpticalFlow"),
 "Volume Patch": ("new", "PCG_VolumePatch"),
 "Volume Ramp": ("new", "PCG_VolumeRamp"),
 "Volume Rasterize": ("new", "PCG_VolumeRasterizePoints", "Points as spheres; no per-primitive VEX"),
 "Volume Rasterize Curve": ("new", "PCG_VolumeRasterizeCurve"),
 "Volume Rasterize Hair": ("new", "PCG_VolumeRasterizeCurve"),
 "Volume Rasterize Particles": ("new", "PCG_VolumeRasterizeParticles"),
 "Volume Rasterize Points": ("new", "PCG_VolumeRasterizePoints"),
 "Volume Reduce": ("new", "PCG_VolumeReduce"),
 "Volume Resize": ("new", "PCG_VolumeResize"),
 "Volume SDF": ("new", "PCG_VolumeSDF"),
 "Volume Slice": ("new", "PCG_VolumeSlice"),
 "Volume Splice": ("new", "PCG_VolumeSplice"),
 "Volume Stamp": ("new", "PCG_VolumeStamp"),
 "Volume Trail": ("new", "PCG_VolumeTrail"),
 "Volume Vector Join": ("new", "PCG_VDBVectorMerge"),
 "Volume Vector Split": ("new", "PCG_VDBVectorSplit"),
 "Volume Velocity": ("partial", "PCG_VolumeVelocity", "No From Object (object-level motion) term"),
 "Volume Velocity from Curves": ("new", "PCG_VolumeVelocityFromCurves"),
 "Volume Velocity from Surface": ("new", "PCG_VolumeVelocityFromSurface"),
 "Volume Visualization": ("new", "PCG_VolumeVisualization"),
 "Volume VOP": ("platform", "Volume Wrangle"),
 "VDB Smooth": ("new", "PCG_VDBSmooth"),
 "VDB Smooth SDF": ("new", "PCG_VolumeSmoothSDF", "Does not recompute distance in the narrow band; for a distance field connect Reshape SDF redistance"),
 "VDB Reshape SDF": ("new", "PCG_VolumeReshapeSDF"),
 "VDB Combine": ("new", "PCG_VDBCombine", "pcg106: all 18 operations, activity ops, collation (Volume Mix stays the Volume Mix SOP)"),
 "Voronoi Fracture": ("done", "PCG_VoronoiFracture"),
 "Voronoi Split": ("new", "PCG_VoronoiSplit"),
 "Wireframe": ("done", "PCG_PolyWire", "Same as PolyWire"),
}

# ─────────────────────────────────────────────── Rows merged per family (value, roughly how many nodes)
FAMILY = {
 "Agent * (crowd agents)": (("oos", OOS_CHAR), 27),
 "APEX * (rig graphs)": (("oos", OOS_CHAR), 31),
 "KineFX:Bone / Capture / Joint / Rig / Skeleton / Motion Clip / Biped / Character *": (("oos", OOS_CHAR), 70),
 "Crowd *": (("oos", OOS_CHAR), 12),
 "Muscle / Tissue / Solid *": (("oos", OOS_SIM), 20),
 "Vellum *": (("oos", OOS_SIM), 12),
 "Hair / Groom / Guide / Fur *": (("oos", OOS_SIM), 35),
 "Cloud * (cloud volumes)": (("oos", OOS_VDB), 12),
 "Pyro / Fluid / FLIP / Whitewater / Particle *": (("oos", OOS_SIM), 30),
 "RBD * (constraints, solving, material fracture)": (("partial", "PCG_VoronoiFracture", "Fracture + detail + exploded view + clustering exist (RBD Interior Detail = Fracture Detail, RBD Exploded View = Exploded View); constraints and solving not done"), 30),
 "DOP Import / DOP Network / Collision / Debris Source …": (("oos", OOS_SIM), 12),
 "Terrain (the new H21+ Terrain family)": (("bridge", "The terrain chain on the COP side (erosion, masks, terraces, strata, Splat Map)"), 15),
 "Ocean Foam / Ocean Source / Ocean Waves": (("oos", OOS_SIM), 3),
 "Test Geometry: *(Crag / Pig Head / Rubber Toy / Squab / Tommy / Shader Ball …)": (("oos", OOS_TEST), 10),
 "ROP / output drivers (Alembic ROP, FBX ROP, Geometry ROP ...)": (("oos", OOS_IO), 8),
 "Labs (SideFX Labs, not core SOPs, counted separately)": (("oos", "Not in the core index; ones like Road Generator, WFC and Tree will be evaluated separately later"), 0),
}

# ─────────────────────────────────────────────── Conversely: the plugin's own geometry-side nodes
# that have no one-to-one counterpart among Houdini SOPs (or correspond to one mode of some SOP). The tests require
# every non-COP node to be either referenced by the table above or listed here; if a new SOP node is added later without
# updating this table, the test goes red
EXTRA = {
 "PCG_AttribTransformExtract": "Per-piece rigid transforms from two same-topology geometries (rest / animated), outputs the template / rest points used by Transform Pieces (mapped to Attribute Transform Extract before pcg100 s7; that Houdini node splits matrix attributes and is in PCG_AttribTransformExtractHou)",
 "PCG_AttribFade": "Spatial falloff: writes a 0..1 soft-selection attribute by edge steps / distance from a group (mapped to Attribute Fade before pcg100 s7; Houdini's Attribute Fade fades in/out over time and is in PCG_AttribFadeTime)",
 "PCG_CrossSectionSurface": "Gordon surface: weaves a net from two curve families (cross sections + guides), resampled and interpolated (pcg75; Houdini's Cross Section Surface is in PCG_CrossSectionSurfaceHou)",
 "PCG_ConvexHull": "Exact convex hull (QuickHull, coplanar merging): the limit of Shrinkwrap as Radius → ∞; a separate node because it is exact and needs no voxels",
 "PCG_LoopCut": "Cuts a loop along an edge ring (in Houdini this is PolySplit's Edge Loop mode / the viewport Loop tool)",
 "PCG_LatticeFromBound": "Lattice's control cage (Houdini builds it inside the Lattice SOP from Bound + Divisions; split out here so any node can move the cage points)",
 "PCG_AttribFromCamera": "Projects an image through a camera onto geometry (the AI -> procedural hub; Houdini needs two steps: Attribute from Map + camera-projected UVs)",
 "PCG_UVBackproject": "Screen image -> uv texture (closed-loop back-projection)",
 "PCG_UVResolve": "Back-projection accumulator -> texture (divide by weight, dilate, fill holes)",
 "PCG_DisplaceFromMap": "Displacement sampled by uv (Attribute from Map + Peak combined)",
 "PCG_HeightfieldFromImage": "ComfyUI IMAGE -> displaced grid",
 "PCG_ExportMesh": "Writes glTF (.glb) / OBJ: UV, normals, tangents, vertex colors, material slots, texture references (corresponds to ROP Geometry Output / ROP FBX)",
 "PCG_ExportInstances": "Points -> instance table CSV / JSON (for an engine's instancing system; transforms are read the same way as Copy to Points)",
 "PCG_GeoToJSON": "Geometry -> JSON (for an LLM to read the layout)",
 "PCG_GeoSpreadsheet": "Geometry table (corresponds to Houdini's Geometry Spreadsheet pane)",
 "PCG_Viewport": "In-node three.js viewport",
 "PCG_Display": "Display flag",
 "PCG_PreviewImage": "Software rasterizer preview -> IMAGE",
 "PCG_EdgeGroupPromote": "Edge group <-> point group / primitive group (the edge half of Group Promote)",
 "PCG_GroupEdges": "Group Create's Edges section, outputs a real edge group",
 "PCG_GroupInside": "Group Create's Bounding Object section",
 "PCG_Thicken": "Gives open surfaces a thickness (SideFX Labs Thicken; in core Houdini PolyExtrude with Output Back and point normals)",
 "PCG_CurveFillet": "Rounds polyline corners with arcs (in Houdini PolyBevel's point mode on curves; PCG_PolyBevel works on polygons only)",
 "PCG_Spherify": "Pushes points onto a sphere (in Houdini this is Labs / Wrangle)",
 "PCG_FractureDetail": "= RBD Interior Detail (noise on fracture surfaces)",
 "PCG_VoronoiCluster": "= RBD Cluster / Voronoi Fracture's Cluster (glues pieces into larger chunks)",
 "PCG_Voronoi2D": "Planar Voronoi partition (Houdini has no dedicated SOP; usually Voronoi Fracture on a plane)",
 "PCG_SelectBest": "Picks the best of a variant sequence by expression (closed-loop automatic selection)",
 "PCG_ForEachFrameBegin": "Per-frame loop (in Houdini this is the timeline itself)",
 "PCG_ForEachFrameEnd": "Per-frame loop, collected into a geometry sequence",
 "PCG_GeoSequencePick": "Takes one frame from a geometry sequence",
 "PCG_Frame": "The single source of truth for the timeline (playbar)",
 "PCG_Channel": "Keyframe channel", "PCG_Channel3": "Triple keyframe channel",
 "PCG_Expr": "Expression parameter", "PCG_Expr3": "Triple expression parameter", "PCG_Value": "Global value",
 "PCG_Parameters": "Control panel (spare parameters)",
 "PCG_FromJSON": "JSON point list / polylines -> geometry (for LLM-generated geometry; mapped to Curve before pcg103, Curve is now PCG_Curve)",
 "PCG_ParamPick": "Takes one value from JSON", "PCG_ParamsFromJSON": "Lets the model fill in the parameter panel",
 "PCG_CameraPath": "Camera path -> camera sequence", "PCG_CameraPick": "Takes one camera from a camera sequence",
 "PCG_MotionVectors": "Exact screen-space displacement between two frames",
 "PCG_RenderSequence": "Camera sequence -> COP sequence (video)",
 "PCG_SequenceMotion": "Geometry sequence -> motion vector sequence",
}

STATUSES = ("done", "new", "partial", "todo", "platform", "bridge", "oos")


def by_status():
    out = {s: [] for s in STATUSES}
    for k, v in M.items():
        out[v[0]].append(k)
    return out


def todo_by_priority():
    out = {"P1": [], "P2": [], "P3": []}
    for k, v in M.items():
        if v[0] == "todo":
            out[v[1]].append((k, v[2]))
    return out


if __name__ == "__main__":
    b = by_status()
    print({s: len(b[s]) for s in STATUSES}, "listed individually:", len(M), "entries;",
          "merged per family:", len(FAMILY), "rows (about", sum(n for _, n in FAMILY.values()),
          "nodes)")
    for p, rows in todo_by_priority().items():
        print(f"\n{p}({len(rows)})")
        for k, note in rows:
            print(f"  {k:28s} {note}")
