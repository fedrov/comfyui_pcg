# Houdini node index

Which comfyui_pcg node to use for a given Houdini SOP or Copernicus COP. *Equivalent* means the node does the same job, though individual options can still differ; *partial* means part of the Houdini node is missing. The node's reference entry (*Compared with Houdini*) lists known differences. Houdini nodes that are not listed have no equivalent yet, are out of scope (KineFX, crowds, solvers, VDB, ...), or are covered by ComfyUI itself (switches, nulls, subnetworks).

## Geometry (SOP)

| Houdini node | comfyui_pcg node | Status |
|---|---|---|
| Adaptive Prune | [Adaptive Prune (PCG)](scatter.md#pcg-adaptiveprune) | equivalent |
| Add | [Add (PCG)](generate.md#pcg-add) | equivalent |
| Assemble | [Assemble (PCG)](scatter.md#pcg-assemble) | equivalent |
| Attribute Adjust Color | [Attribute Adjust Color (PCG)](attribute.md#pcg-attribadjustcolor) | equivalent |
| Attribute Adjust Float | [Attribute Adjust Float (PCG)](attribute.md#pcg-attribadjustfloat) | equivalent |
| Attribute Adjust Integer | [Attribute Adjust Integer (PCG)](attribute.md#pcg-attribadjustinteger) | equivalent |
| Attribute Adjust Vector | [Attribute Adjust Vector (PCG)](attribute.md#pcg-attribadjustvector) | equivalent |
| Attribute Blur | [Attribute Blur (PCG)](attribute.md#pcg-attribblur) | equivalent |
| Attribute Cast | [Attribute Cast (PCG)](attribute.md#pcg-attribcast) | equivalent |
| Attribute Combine | [Wrangle (PCG)](attribute.md#pcg-wrangle) | equivalent |
| Attribute Composite | [Attribute Composite (PCG)](attribute.md#pcg-attribcomposite) | equivalent |
| Attribute Copy | [Attribute Copy (PCG)](attribute.md#pcg-attribcopy) | equivalent |
| Attribute Create | [Attribute Create (PCG)](attribute.md#pcg-attribcreate) | equivalent |
| Attribute Delete | [Attribute Delete (PCG)](attribute.md#pcg-attribdelete) | equivalent |
| Attribute Expression | [Wrangle (PCG)](attribute.md#pcg-wrangle) | equivalent |
| Attribute Fade | [Attribute Fade · Time (PCG)](attribute.md#pcg-attribfadetime) | equivalent |
| Attribute Fill | [Attribute Fill (PCG)](attribute.md#pcg-attribfill) | equivalent |
| Attribute from Map | [Attribute from Map (PCG)](attribute.md#pcg-attribfrommap) | equivalent |
| Attribute From Pieces | [Attribute from Pieces (PCG)](attribute.md#pcg-attribfrompieces) | equivalent |
| Attribute from Volume | [Attribute from Volume (PCG)](attribute.md#pcg-attribfromvolume) | equivalent |
| Attribute Interpolate | [Attribute Interpolate (PCG)](attribute.md#pcg-attribinterpolate) | equivalent |
| Attribute Mirror | [Attribute Mirror (PCG)](attribute.md#pcg-attribmirror) | equivalent |
| Attribute Noise | [Attribute Noise (PCG)](attribute.md#pcg-attribnoise) | equivalent |
| Attribute Promote | [Attribute Promote (PCG)](attribute.md#pcg-attribpromote) | equivalent |
| Attribute Randomize | [Attribute Randomize (PCG)](attribute.md#pcg-attribrandomize) | equivalent |
| Attribute Remap | [Attribute Adjust (PCG)](attribute.md#pcg-attribadjust) | equivalent |
| Attribute Rename | [Attribute Rename (PCG)](attribute.md#pcg-attribrename) | equivalent |
| Attribute Reorient | [Attribute Reorient (PCG)](attribute.md#pcg-attribreorient) | equivalent |
| Attribute String Edit | [Attribute String Edit (PCG)](attribute.md#pcg-attribstringedit) | equivalent |
| Attribute Swap | [Wrangle (PCG)](attribute.md#pcg-wrangle) | equivalent |
| Attribute Transfer | [Attribute Transfer (PCG)](attribute.md#pcg-attribtransfer) | equivalent |
| Attribute Transfer by UV | [Attribute Transfer by UV (PCG)](attribute.md#pcg-attribtransferbyuv) | equivalent |
| Attribute Transform Extract | [Attribute Transform Extract · Houdini (PCG)](attribute.md#pcg-attribtransformextracthou) | equivalent |
| Attribute Wrangle | [Wrangle (PCG)](attribute.md#pcg-wrangle) | equivalent |
| Bake Pre-Process | [COP Bake Textures (PCG)](cop-geometry.md#pcg-copbaketextures) | equivalent |
| Ballistic Path | [Ballistic Path (PCG)](generate.md#pcg-ballisticpath) | equivalent |
| Bend | [Twist / Bend / Taper (PCG)](deform.md#pcg-deform) | equivalent |
| Blast | [Blast (PCG)](modify.md#pcg-blast) | equivalent |
| Blast by Attribute | [Blast by Attribute (PCG)](modify.md#pcg-blastbyattribute) | equivalent |
| Blend Shapes | [Blend Shapes (PCG)](deform.md#pcg-blendshapes) | equivalent |
| Boolean | [Boolean (PCG)](modify.md#pcg-boolean) | equivalent |
| Boolean Fracture | [Boolean Fracture (PCG)](modify.md#pcg-booleanfracture) | equivalent |
| Bound | [Bound (PCG)](modify.md#pcg-bound) | equivalent |
| Box | [Box (PCG)](generate.md#pcg-box) | equivalent |
| Bulge | [Bulge (PCG)](deform.md#pcg-bulge) | equivalent |
| Camera | [Camera (PCG)](render.md#pcg-camera) | equivalent |
| Camera from Points | [Camera from Points (PCG)](render.md#pcg-camerafrompoints) | equivalent |
| Camera To Points | [Camera To Points (PCG)](render.md#pcg-cameratopoints) | equivalent |
| Carve | [Carve (PCG)](modify.md#pcg-carve) | equivalent |
| Chain | [Chain (PCG)](scatter.md#pcg-chain) | equivalent |
| Circle | [Circle (PCG)](generate.md#pcg-circle) | equivalent |
| Circle from Edges | [Circle from Edges (PCG)](modify.md#pcg-circlefromedges) | equivalent |
| Circle Spline | [Circle Spline (PCG)](modify.md#pcg-circlespline) | equivalent |
| Clean | [Clean (PCG)](modify.md#pcg-clean) | equivalent |
| Clip | [Clip (PCG)](modify.md#pcg-clip) | equivalent |
| Cluster | [Cluster Points (PCG)](attribute.md#pcg-clusterpoints) | equivalent |
| Cluster Points | [Cluster Points (PCG)](attribute.md#pcg-clusterpoints) | equivalent |
| Color | [Color (PCG)](attribute.md#pcg-color) | equivalent |
| Connect Adjacent Pieces | [Connect Adjacent Pieces (PCG)](topology.md#pcg-connectadjacentpieces) | equivalent |
| Connectivity | [Connectivity (PCG)](topology.md#pcg-connectivity) | equivalent |
| Convert | [Convert (PCG)](modify.md#pcg-convert) | equivalent |
| Convert Line | [Convert Line (PCG)](convert.md#pcg-convertline) | equivalent |
| Convert VDB | [Convert VDB (PCG)](volume.md#pcg-convertvdb) | equivalent |
| Convert Volume | [Convert (PCG)](modify.md#pcg-convert) | equivalent |
| Convex Decomposition | [Convex Decompose (PCG)](modify.md#pcg-convexdecompose) | equivalent |
| Copy and Transform | [Copy and Transform (PCG)](scatter.md#pcg-copyandtransform) | equivalent |
| Copy to Curves | [Copy to Curves (PCG)](scatter.md#pcg-copytocurves) | equivalent |
| Copy to Points | [Copy to Points (PCG)](scatter.md#pcg-copytopoints) | equivalent |
| Crease | [Crease (PCG)](modify.md#pcg-crease) | equivalent |
| Cross Section Surface | [Cross Section Surface · Houdini (PCG)](generate.md#pcg-crosssectionsurfacehou) | equivalent |
| Curve | [Curve (PCG)](generate.md#pcg-curve) | equivalent |
| Curve Intersect | [Curve Intersect (PCG)](modify.md#pcg-curveintersect) | equivalent |
| Delete | [Delete (PCG)](modify.md#pcg-delete) | equivalent |
| DeltaMush | [DeltaMush (PCG)](deform.md#pcg-deltamush) | equivalent |
| Dissolve | [Dissolve (PCG)](modify.md#pcg-dissolve) | equivalent |
| Distance along Geometry | [Distance along Geometry (PCG)](attribute.md#pcg-distancealonggeometry) | equivalent |
| Distance from Geometry | [Distance from Geometry (PCG)](attribute.md#pcg-distancefromgeometry) | equivalent |
| Divide | [Divide (PCG)](modify.md#pcg-divide) | equivalent |
| Edge Collapse | [Edge Collapse (PCG)](modify.md#pcg-edgecollapse) | equivalent |
| Edge Cusp | [Edge Cusp (PCG)](topology.md#pcg-edgecusp) | equivalent |
| Edge Divide | [Edge Divide (PCG)](modify.md#pcg-edgedivide) | equivalent |
| Edge Equalize | [Edge Equalize (PCG)](modify.md#pcg-edgeequalize) | equivalent |
| Edge Flip | [Edge Flip (PCG)](topology.md#pcg-edgeflip) | equivalent |
| Edge Straighten | [Edge Straighten (PCG)](modify.md#pcg-edgestraighten) | equivalent |
| Edge Transport | [Edge Transport (PCG)](attribute.md#pcg-edgetransport) | equivalent |
| Ends | [Ends (PCG)](modify.md#pcg-ends) | equivalent |
| Enumerate | [Enumerate (PCG)](attribute.md#pcg-enumerate) | equivalent |
| Exploded View | [Exploded View (PCG)](modify.md#pcg-explodedview) | equivalent |
| Extract Centroid | [Extract Centroid (PCG)](attribute.md#pcg-extractcentroid) | equivalent |
| Extract Silhouette | [Extract Silhouette (PCG)](generate.md#pcg-extractsilhouette) | equivalent |
| Extract Transform | [Extract Transform (PCG)](modify.md#pcg-extracttransform) | equivalent |
| Facet | [Facet (PCG)](modify.md#pcg-facet) | equivalent |
| File | [Import Mesh (PCG)](convert.md#pcg-importmesh) | equivalent |
| File Cache | [File Cache (PCG)](output.md#pcg-filecache) | equivalent |
| File Merge | [File Merge (PCG)](convert.md#pcg-filemerge) | equivalent |
| Find Shortest Path | [Find Shortest Path (PCG)](topology.md#pcg-findshortestpath) | equivalent |
| Font | [Font (PCG)](generate.md#pcg-font) | equivalent |
| Fractal | [Fractal (PCG)](deform.md#pcg-fractal) | equivalent |
| Fuse | [Fuse (PCG)](modify.md#pcg-fuse) | equivalent |
| Grid | [Grid (PCG)](generate.md#pcg-grid) | equivalent |
| Group | [Group Create (PCG)](group.md#pcg-groupcreate) | equivalent |
| Group Combine | [Group Combine (PCG)](group.md#pcg-groupcombine) | equivalent |
| Group Copy | [Attribute Copy (PCG)](attribute.md#pcg-attribcopy) | equivalent |
| Group Delete | [Group Delete (PCG)](group.md#pcg-groupdelete) | equivalent |
| Group Expand | [Group Expand (PCG)](group.md#pcg-groupexpand) | equivalent |
| Group Expression | [Group Create (PCG)](group.md#pcg-groupcreate) | equivalent |
| Group Find Path | [Group Find Path (PCG)](group.md#pcg-groupfindpath) | equivalent |
| Group from Attribute Boundary | [Group from Attribute Boundary (PCG)](group.md#pcg-groupfromattribboundary) | equivalent |
| Group Promote | [Group Promote (PCG)](group.md#pcg-grouppromote) | equivalent |
| Group Range | [Group Create (PCG)](group.md#pcg-groupcreate) | equivalent |
| Group Rename | [Attribute Rename (PCG)](attribute.md#pcg-attribrename) | equivalent |
| Group Transfer | [Attribute Transfer (PCG)](attribute.md#pcg-attribtransfer) | equivalent |
| HeightField Scatter | [Scatter from Map (PCG)](scatter.md#pcg-scatterfrommap) | equivalent |
| HeightField Tile Splice | [COP HeightField Tile Splice (PCG)](cop-utility.md#pcg-coptilesplice) | equivalent |
| HeightField Tile Split | [COP HeightField Tile Split (PCG)](cop-utility.md#pcg-coptilesplit) | equivalent |
| Intersection Analysis | [Intersection Analysis (PCG)](modify.md#pcg-intersectionanalysis) | equivalent |
| Intersection Stitch | [Boolean (PCG)](modify.md#pcg-boolean) | partial |
| IsoOffset | [IsoOffset (PCG)](generate.md#pcg-isooffset) | equivalent |
| IsoSurface | [IsoSurface (PCG)](generate.md#pcg-isosurface) | equivalent |
| Join | [Join (PCG)](modify.md#pcg-join) | equivalent |
| Knife | [Clip (PCG)](modify.md#pcg-clip) | equivalent |
| L-System | [L-System (PCG)](generate.md#pcg-lsystem) | equivalent |
| Lattice | [Lattice (PCG)](deform.md#pcg-lattice) | equivalent |
| Lidar Import | [Import Mesh (PCG)](convert.md#pcg-importmesh) | partial |
| Line | [Line (PCG)](generate.md#pcg-line) | equivalent |
| Magnet | [Magnet (PCG)](deform.md#pcg-magnet) | equivalent |
| Match Axis | [Match Axis (PCG)](modify.md#pcg-matchaxis) | equivalent |
| Match Size | [Match Size (PCG)](modify.md#pcg-matchsize) | equivalent |
| Match Topology | [Match Topology (PCG)](topology.md#pcg-matchtopology) | equivalent |
| Measure | [Measure (PCG)](attribute.md#pcg-measure) | equivalent |
| Merge | [Merge (PCG)](modify.md#pcg-merge) | equivalent |
| Mirror | [Mirror (PCG)](modify.md#pcg-mirror) | equivalent |
| Mountain | [Attribute Noise (PCG)](attribute.md#pcg-attribnoise) | equivalent |
| Name | [Name (PCG)](attribute.md#pcg-name) | equivalent |
| Normal | [Normal (PCG)](attribute.md#pcg-normal) | equivalent |
| Orient Along Curve | [Orient Along Curve (PCG)](attribute.md#pcg-orientalongcurve) | equivalent |
| Pack | [Pack (PCG)](scatter.md#pcg-pack) | equivalent |
| Partition | [Partition (PCG)](group.md#pcg-partition) | equivalent |
| Path Deform | [Path Deform (PCG)](deform.md#pcg-pathdeform) | equivalent |
| Peak | [Peak (PCG)](modify.md#pcg-peak) | equivalent |
| Platonic Solids | [Platonic Solids (PCG)](generate.md#pcg-platonicsolids) | equivalent |
| Point Deform | [Point Deform (PCG)](deform.md#pcg-pointdeform) | equivalent |
| Point Generate | [Add (PCG)](generate.md#pcg-add) | equivalent |
| Point Jitter | [Point Jitter (PCG)](modify.md#pcg-pointjitter) | equivalent |
| Point Relax | [Point Relax (PCG)](scatter.md#pcg-pointrelax) | equivalent |
| Point Replicate | [Point Replicate (PCG)](scatter.md#pcg-pointreplicate) | equivalent |
| Point Split | [Point Split (PCG)](modify.md#pcg-pointsplit) | equivalent |
| Point Velocity | [Point Velocity (PCG)](attribute.md#pcg-pointvelocity) | equivalent |
| Points from Volume | [Scatter in Volume (PCG)](scatter.md#pcg-scattervolume) | equivalent |
| Poly Bridge | [Poly Bridge (PCG)](modify.md#pcg-polybridge) | equivalent |
| PolyBevel | [PolyBevel (PCG)](modify.md#pcg-polybevel) | equivalent |
| PolyCut | [PolyCut (PCG)](topology.md#pcg-polycut) | equivalent |
| PolyDoctor | [PolyDoctor (PCG)](modify.md#pcg-polydoctor) | partial |
| PolyExpand2D | [PolyExpand2D (PCG)](modify.md#pcg-polyexpand2d) | equivalent |
| PolyExtrude | [PolyExtrude (PCG)](modify.md#pcg-polyextrude) | equivalent |
| PolyFill | [PolyFill (PCG)](modify.md#pcg-polyfill) | equivalent |
| PolyFrame | [PolyFrame (PCG)](attribute.md#pcg-polyframe) | equivalent |
| PolyLoft | [PolyLoft (PCG)](generate.md#pcg-polyloft) | equivalent |
| PolyPath | [PolyPath (PCG)](modify.md#pcg-polypath) | equivalent |
| PolyReduce | [PolyReduce (PCG)](modify.md#pcg-polyreduce) | equivalent |
| PolySpline | [PolySpline (PCG)](modify.md#pcg-polyspline) | equivalent |
| PolySplit | [PolySplit (PCG)](topology.md#pcg-polysplit) | equivalent |
| PolyStitch | [PolyStitch (PCG)](topology.md#pcg-polystitch) | equivalent |
| PolyWire | [PolyWire (PCG)](generate.md#pcg-polywire) | equivalent |
| Primitive | [Primitive (PCG)](modify.md#pcg-primitive) | equivalent |
| Primitive Split | [Primitive Split (PCG)](modify.md#pcg-primitivesplit) | equivalent |
| Ray | [Ray (PCG)](modify.md#pcg-ray) | equivalent |
| Refine | [Refine (PCG)](modify.md#pcg-refine) | equivalent |
| Remesh | [Remesh (PCG)](modify.md#pcg-remesh) | equivalent |
| Remesh to Grid | [Remesh to Grid (PCG)](modify.md#pcg-remeshtogrid) | equivalent |
| Resample | [Resample (PCG)](modify.md#pcg-resample) | equivalent |
| Rest Position | [Wrangle (PCG)](attribute.md#pcg-wrangle) | equivalent |
| Reverse | [Reverse (PCG)](modify.md#pcg-reverse) | equivalent |
| Revolve | [Revolve (PCG)](generate.md#pcg-revolve) | equivalent |
| Rewire Vertices | [Rewire Vertices (PCG)](topology.md#pcg-rewirevertices) | equivalent |
| Scatter | [Scatter (PCG)](scatter.md#pcg-scatter) | equivalent |
| Scatter and Align | [Scatter and Align (PCG)](scatter.md#pcg-scatteralign) | equivalent |
| Sequence Blend | [Time Blend (PCG)](loop.md#pcg-timeblend) | equivalent |
| Shrinkwrap | [Shrinkwrap (PCG)](modify.md#pcg-shrinkwrap) | equivalent |
| Skin | [Skin (PCG)](generate.md#pcg-skin) | equivalent |
| Smooth | [Smooth (PCG)](modify.md#pcg-smooth) | equivalent |
| Soft Peak | [Soft Peak (PCG)](deform.md#pcg-softpeak) | equivalent |
| Soft Transform | [Soft Transform (PCG)](deform.md#pcg-softtransform) | equivalent |
| Sort | [Sort (PCG)](modify.md#pcg-sort) | equivalent |
| Sphere | [Sphere (PCG)](generate.md#pcg-sphere) | equivalent |
| Split | [Split (PCG)](modify.md#pcg-split) | equivalent |
| Split Points | [Point Split (PCG)](modify.md#pcg-pointsplit) | equivalent |
| Stash | [File Cache (PCG)](output.md#pcg-filecache) | equivalent |
| Subdivide | [Subdivide (PCG)](modify.md#pcg-subdivide) | equivalent |
| Sweep | [Sweep (PCG)](generate.md#pcg-sweep) | equivalent |
| Switch | [Switch (PCG)](modify.md#pcg-switch) | equivalent |
| Switch-If | [Switch-If (PCG)](modify.md#pcg-switchif) | equivalent |
| Tangent Field | [Tangent Field (PCG)](attribute.md#pcg-tangentfield) | equivalent |
| Time Shift | [Retime (PCG)](loop.md#pcg-retime) | equivalent |
| Topo Transfer | [Topo Transfer (PCG)](deform.md#pcg-topotransfer) | equivalent |
| Torus | [Torus (PCG)](generate.md#pcg-torus) | equivalent |
| Trace | [Trace (PCG)](convert.md#pcg-trace) | equivalent |
| Trail | [Trail (PCG)](loop.md#pcg-trail) | equivalent |
| Transform | [Transform (PCG)](modify.md#pcg-transform) | equivalent |
| Transform by Attribute | [Transform by Attribute (PCG)](modify.md#pcg-transformbyattrib) | equivalent |
| Transform Pieces | [Transform Pieces (PCG)](deform.md#pcg-transformpieces) | equivalent |
| Tri Divide | [Tri Divide (PCG)](topology.md#pcg-tridivide) | equivalent |
| Triangulate 2D | [Triangulate 2D (PCG)](modify.md#pcg-triangulate2d) | equivalent |
| Tube | [Tube (PCG)](generate.md#pcg-tube) | equivalent |
| Twist | [Twist / Bend / Taper (PCG)](deform.md#pcg-deform) | equivalent |
| Unpack | [Unpack (PCG)](scatter.md#pcg-unpack) | equivalent |
| Unsubdivide | [Unsubdivide (PCG)](topology.md#pcg-unsubdivide) | equivalent |
| UV Autoseam | [UV Auto Seams (PCG)](uv.md#pcg-uvautoseams) | equivalent |
| UV Flatten | [UV Flatten (PCG)](uv.md#pcg-uvflatten) | equivalent |
| UV Fuse | [UV Fuse (PCG)](uv.md#pcg-uvfuse) | equivalent |
| UV Layout | [UV Layout (PCG)](uv.md#pcg-uvlayout) | equivalent |
| UV Pelt | [UV Pelt (PCG)](uv.md#pcg-uvpelt) | equivalent |
| UV Project | [UV Project (PCG)](uv.md#pcg-uvproject) | equivalent |
| UV Quick Shade | [Texture Render (PCG)](render.md#pcg-texturerender) | equivalent |
| UV Smooth | [UV Smooth (PCG)](uv.md#pcg-uvsmooth) | equivalent |
| UV Texture | [UV Project (PCG)](uv.md#pcg-uvproject) | equivalent |
| UV Transform | [UV Transform (PCG)](uv.md#pcg-uvtransform) | equivalent |
| UV Unwrap | [UV Unwrap (PCG)](uv.md#pcg-uvunwrap) | equivalent |
| UV Visualize | [Geo Metrics (PCG)](output.md#pcg-geometrics) | equivalent |
| VDB | [VDB (PCG)](volume.md#pcg-vdb) | equivalent |
| VDB Activate | [VDB Activate (PCG)](volume.md#pcg-vdbactivate) | equivalent |
| VDB Activate SDF | [VDB Activate SDF (PCG)](volume.md#pcg-vdbactivatesdf) | equivalent |
| VDB Advect | [VDB Advect (PCG)](volume.md#pcg-vdbadvect) | equivalent |
| VDB Advect Points | [VDB Advect Points (PCG)](volume.md#pcg-vdbadvectpoints) | equivalent |
| VDB Analysis | [VDB Analysis (PCG)](volume.md#pcg-vdbanalysis) | equivalent |
| VDB Clip | [VDB Clip (PCG)](volume.md#pcg-vdbclip) | partial |
| VDB Combine | [VDB Combine (PCG)](volume.md#pcg-vdbcombine) | equivalent |
| VDB Densify | [VDB Densify (PCG)](volume.md#pcg-vdbdensify) | equivalent |
| VDB Diagnostics | [VDB Diagnostics (PCG)](volume.md#pcg-vdbdiagnostics) | equivalent |
| VDB Extrapolate | [VDB Extrapolate (PCG)](volume.md#pcg-vdbextrapolate) | equivalent |
| VDB Fill | [VDB Fill (PCG)](volume.md#pcg-vdbfill) | equivalent |
| VDB Fracture | [VDB Fracture (PCG)](volume.md#pcg-vdbfracture) | equivalent |
| VDB from Particle Fluid | [VDB from Particle Fluid (PCG)](volume.md#pcg-vdbfromparticlefluid) | equivalent |
| VDB from Particles | [VDB from Particles (PCG)](volume.md#pcg-vdbfromparticles) | equivalent |
| VDB from Polygons | [VDB from Polygons (PCG)](volume.md#pcg-vdbfrompolygons) | equivalent |
| VDB LOD | [VDB LOD (PCG)](volume.md#pcg-vdblod) | equivalent |
| VDB Merge | [VDB Merge (PCG)](volume.md#pcg-vdbmerge) | equivalent |
| VDB Metadata | [VDB Metadata (PCG)](volume.md#pcg-vdbmetadata) | equivalent |
| VDB Morph SDF | [VDB Morph SDF (PCG)](volume.md#pcg-vdbmorphsdf) | equivalent |
| VDB Noise | [VDB Noise (PCG)](volume.md#pcg-vdbnoise) | equivalent |
| VDB Occlusion Mask | [VDB Occlusion Mask (PCG)](volume.md#pcg-vdbocclusionmask) | partial |
| VDB Platonic | [VDB Platonic (PCG)](volume.md#pcg-vdbplatonic) | equivalent |
| VDB Points Group | [VDB Points Group (PCG)](volume.md#pcg-vdbpointsgroup) | equivalent |
| VDB Potential Flow | [VDB Potential Flow (PCG)](volume.md#pcg-vdbpotentialflow) | equivalent |
| VDB Project Non-Divergent | [VDB Project Non-Divergent (PCG)](volume.md#pcg-vdbprojectnondivergent) | equivalent |
| VDB Prune | [VDB Prune (PCG)](volume.md#pcg-vdbprune) | equivalent |
| VDB Rasterize Points | [Volume Rasterize Points (PCG)](volume.md#pcg-volumerasterizepoints) | equivalent |
| VDB Ray | [VDB Ray (PCG)](volume.md#pcg-vdbray) | equivalent |
| VDB Rebuild SDF | [VDB Rebuild SDF (PCG)](volume.md#pcg-vdbrebuildsdf) | equivalent |
| VDB Remap | [VDB Remap (PCG)](volume.md#pcg-vdbremap) | equivalent |
| VDB Renormalize SDF | [VDB Renormalize SDF (PCG)](volume.md#pcg-vdbrenormalizesdf) | equivalent |
| VDB Resample | [VDB Resample (PCG)](volume.md#pcg-vdbresample) | equivalent |
| VDB Reshape SDF | [Volume Reshape SDF (PCG)](modify.md#pcg-volumereshapesdf) | equivalent |
| VDB Sample Points | [Attribute from Volume (PCG)](attribute.md#pcg-attribfromvolume) | equivalent |
| VDB Scatter | [VDB Scatter (PCG)](volume.md#pcg-vdbscatter) | equivalent |
| VDB Segment by Connectivity | [VDB Segment by Connectivity (PCG)](volume.md#pcg-vdbsegment) | equivalent |
| VDB Smooth | [VDB Smooth (PCG)](volume.md#pcg-vdbsmooth) | equivalent |
| VDB Smooth SDF | [Volume Smooth SDF (PCG)](modify.md#pcg-volumesmoothsdf) | equivalent |
| VDB to Spheres | [VDB to Spheres (PCG)](volume.md#pcg-vdbtospheres) | equivalent |
| VDB Topology to SDF | [VDB Topology to SDF (PCG)](volume.md#pcg-vdbtopologytosdf) | equivalent |
| VDB Transform | [VDB Transform (PCG)](volume.md#pcg-vdbtransform) | equivalent |
| VDB Vector Merge | [VDB Vector Merge (PCG)](volume.md#pcg-vdbvectormerge) | equivalent |
| VDB Vector Split | [VDB Vector Split (PCG)](volume.md#pcg-vdbvectorsplit) | equivalent |
| VDB Visualize Tree | [VDB Visualize Tree (PCG)](volume.md#pcg-vdbvisualizetree) | equivalent |
| Volume | [Volume (PCG)](generate.md#pcg-volume) | equivalent |
| Volume Adjust Fog | [Volume Adjust Fog (PCG)](volume.md#pcg-volumeadjustfog) | equivalent |
| Volume Analysis | [VDB Analysis (PCG)](volume.md#pcg-vdbanalysis) | equivalent |
| Volume Blur | [Volume Blur (PCG)](modify.md#pcg-volumeblur) | equivalent |
| Volume Bound | [Volume Bound (PCG)](volume.md#pcg-volumebound) | equivalent |
| Volume Break | [Volume Break (PCG)](volume.md#pcg-volumebreak) | equivalent |
| Volume Compress | [Volume Compress (PCG)](volume.md#pcg-volumecompress) | equivalent |
| Volume Convolve 3×3×3 | [Volume Convolve 3×3×3 (PCG)](volume.md#pcg-volumeconvolve) | equivalent |
| Volume Feather | [Volume Feather (PCG)](volume.md#pcg-volumefeather) | equivalent |
| Volume FFT | [Volume FFT (PCG)](volume.md#pcg-volumefft) | equivalent |
| Volume from Attrib | [Volume from Attrib (PCG)](volume.md#pcg-volumefromattrib) | equivalent |
| Volume Merge | [Volume Merge (PCG)](volume.md#pcg-volumemerge) | equivalent |
| Volume Mix | [Volume Mix (PCG)](modify.md#pcg-volumemix) | equivalent |
| Volume Optical Flow | [Volume Optical Flow (PCG)](volume.md#pcg-volumeopticalflow) | equivalent |
| Volume Patch | [Volume Patch (PCG)](volume.md#pcg-volumepatch) | equivalent |
| Volume Ramp | [Volume Ramp (PCG)](volume.md#pcg-volumeramp) | equivalent |
| Volume Rasterize | [Volume Rasterize Points (PCG)](volume.md#pcg-volumerasterizepoints) | equivalent |
| Volume Rasterize Attributes | [Volume Rasterize Attributes (PCG)](convert.md#pcg-volumerasterizeattribs) | equivalent |
| Volume Rasterize Curve | [Volume Rasterize Curve (PCG)](volume.md#pcg-volumerasterizecurve) | equivalent |
| Volume Rasterize Hair | [Volume Rasterize Curve (PCG)](volume.md#pcg-volumerasterizecurve) | equivalent |
| Volume Rasterize Particles | [Volume Rasterize Particles (PCG)](volume.md#pcg-volumerasterizeparticles) | equivalent |
| Volume Rasterize Points | [Volume Rasterize Points (PCG)](volume.md#pcg-volumerasterizepoints) | equivalent |
| Volume Reduce | [Volume Reduce (PCG)](volume.md#pcg-volumereduce) | equivalent |
| Volume Resample | [Volume Resample (PCG)](modify.md#pcg-volumeresample) | equivalent |
| Volume Resize | [Volume Resize (PCG)](volume.md#pcg-volumeresize) | equivalent |
| Volume Sample | [Attribute from Volume (PCG)](attribute.md#pcg-attribfromvolume) | equivalent |
| Volume SDF | [Volume SDF (PCG)](volume.md#pcg-volumesdf) | equivalent |
| Volume Slice | [Volume Slice (PCG)](volume.md#pcg-volumeslice) | equivalent |
| Volume Splice | [Volume Splice (PCG)](volume.md#pcg-volumesplice) | equivalent |
| Volume Stamp | [Volume Stamp (PCG)](volume.md#pcg-volumestamp) | equivalent |
| Volume Trail | [Volume Trail (PCG)](volume.md#pcg-volumetrail) | equivalent |
| Volume Vector Join | [VDB Vector Merge (PCG)](volume.md#pcg-vdbvectormerge) | equivalent |
| Volume Vector Split | [VDB Vector Split (PCG)](volume.md#pcg-vdbvectorsplit) | equivalent |
| Volume Velocity | [Volume Velocity (PCG)](volume.md#pcg-volumevelocity) | partial |
| Volume Velocity from Curves | [Volume Velocity from Curves (PCG)](volume.md#pcg-volumevelocityfromcurves) | equivalent |
| Volume Velocity from Surface | [Volume Velocity from Surface (PCG)](volume.md#pcg-volumevelocityfromsurface) | equivalent |
| Volume Visualization | [Volume Visualization (PCG)](volume.md#pcg-volumevisualization) | equivalent |
| Volume Wrangle | [Volume Wrangle (PCG)](modify.md#pcg-volumewrangle) | equivalent |
| Voronoi Fracture | [Voronoi Fracture (PCG)](modify.md#pcg-voronoifracture) | equivalent |
| Voronoi Split | [Voronoi Split (PCG)](modify.md#pcg-voronoisplit) | equivalent |
| Wireframe | [PolyWire (PCG)](generate.md#pcg-polywire) | equivalent |

## Copernicus (COP)

| Houdini node | comfyui_pcg node | Status |
|---|---|---|
| Align | [COP Align Window (PCG)](cop-transform.md#pcg-copalignwindow) | equivalent |
| Align Pixels | [COP Align Pixels (PCG)](cop-transform.md#pcg-copalignpixels) | equivalent |
| Attribute from Layer | [Attribute from Map (PCG)](attribute.md#pcg-attribfrommap) | equivalent |
| Auto Stereogram | [COP Stereogram (PCG)](cop-generate.md#pcg-copstereogram) | equivalent |
| Bake Geometry Textures | [COP Bake Textures (PCG)](cop-geometry.md#pcg-copbaketextures) | equivalent |
| Bake Geometry Textures 2.0 | [COP Bake Textures (PCG)](cop-geometry.md#pcg-copbaketextures) | equivalent |
| Bake Pre-Process | [COP Bake Textures (PCG)](cop-geometry.md#pcg-copbaketextures) | equivalent |
| Bend | [COP Bend (PCG)](cop-transform.md#pcg-copbend) | equivalent |
| Blend | [COP Composite (PCG)](cop-composite.md#pcg-copcomposite) | equivalent |
| Blur | [COP Blur (PCG)](cop-filter.md#pcg-copblur) | equivalent |
| Bokeh | [COP Defocus (PCG)](cop-filter.md#pcg-copdefocus) | equivalent |
| Bounding Rectangle | [COP Bounding Rect (PCG)](cop-utility.md#pcg-copboundingrect) | equivalent |
| Bright | [COP Color Correct (PCG)](cop-color.md#pcg-copcolorcorrect) | equivalent |
| Bubble Noise | [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | equivalent |
| Cell Pattern | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Cellular Noise | [COP Cellular Noise (PCG)](cop-generate.md#pcg-copcellularnoise) | equivalent |
| Cellular Noise 3D | [COP Cellular Noise (PCG)](cop-generate.md#pcg-copcellularnoise) | equivalent |
| Channel Extract | [COP Swizzle (PCG)](cop-layers.md#pcg-copswizzle) | equivalent |
| Channel Join | [COP Channel Join (PCG)](cop-layers.md#pcg-copchanneljoin) | equivalent |
| Channel Split | [COP Channel Split (PCG)](cop-layers.md#pcg-copchannelsplit) | equivalent |
| Channel Swap | [COP Swizzle (PCG)](cop-layers.md#pcg-copswizzle) | equivalent |
| Checkerboard | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Chladni Cymatic Patterns | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Chroma Key | [COP Chroma Key (PCG)](cop-color.md#pcg-copchromakey) | equivalent |
| Chromatic Aberration | [COP Chromatic Aberration (PCG)](cop-transform.md#pcg-copchromaticaberration) | equivalent |
| Clamp | [COP Clamp (PCG)](cop-color.md#pcg-copclamp) | equivalent |
| Cloud Noise 3D | [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | equivalent |
| Color Correct | [COP Color Correct (PCG)](cop-color.md#pcg-copcolorcorrect) | equivalent |
| Combine Normals | [COP Combine Normals (PCG)](cop-composite.md#pcg-copcombinenormals) | equivalent |
| Compare | [COP Compare Mask (PCG)](cop-composite.md#pcg-copcomparemask) | equivalent |
| Compare and Blend | [COP Select (PCG)](cop-composite.md#pcg-copselect) | equivalent |
| Configure Stamps | [COP Configure Stamps (PCG)](cop-geometry.md#pcg-copconfigurestamps) | equivalent |
| Constant | [COP Constant (PCG)](cop-generate.md#pcg-copconstant) | equivalent |
| Contact Sheet | [COP Contact Sheet (PCG)](cop-utility.md#pcg-copcontactsheet) | equivalent |
| Contrast | [COP Color Correct (PCG)](cop-color.md#pcg-copcolorcorrect) | equivalent |
| Convert Depth | [COP Convert Depth (PCG)](cop-layers.md#pcg-copconvertdepth) | equivalent |
| Convert Normal | [COP Convert Normal (PCG)](cop-layers.md#pcg-copconvertnormal) | equivalent |
| Convolve 3x3 | [COP Convolve (PCG)](cop-filter.md#pcg-copconvolve) | equivalent |
| Convolve Filter | [COP Convolve (PCG)](cop-filter.md#pcg-copconvolve) | equivalent |
| Copy and Transform | [COP Copy Transform (PCG)](cop-transform.md#pcg-copcopytransform) | equivalent |
| Corner Detect | [COP Corner Detect (PCG)](cop-filter.md#pcg-copcornerdetect) | equivalent |
| Corner Pin | [COP Corner Pin (PCG)](cop-transform.md#pcg-copcornerpin) | equivalent |
| Crop | [COP Crop / Pad (PCG)](cop-transform.md#pcg-copcrop) | equivalent |
| Cross Product | [COP Vector Math (PCG)](cop-utility.md#pcg-copvectormath) | equivalent |
| Crystal Noise | [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | equivalent |
| Crystal Noise 3D | [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | equivalent |
| Curl | [COP Derivative (PCG)](cop-filter.md#pcg-copderivative) | equivalent |
| Curl Noise | [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | equivalent |
| Curl Noise 3D | [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | equivalent |
| Curvature | [COP Curvature (PCG)](cop-terrain.md#pcg-copcurvature) | equivalent |
| Defocus | [COP Defocus (PCG)](cop-filter.md#pcg-copdefocus) | equivalent |
| Denoise TVD | [COP Denoise TV (PCG)](cop-filter.md#pcg-copdenoisetv) | equivalent |
| Derivative | [COP Derivative (PCG)](cop-filter.md#pcg-copderivative) | equivalent |
| Despill | [COP Despill (PCG)](cop-color.md#pcg-copdespill) | equivalent |
| Dilate Erode | [COP Erode / Dilate (PCG)](cop-filter.md#pcg-copmorph) | equivalent |
| Distort | [COP Distort (PCG)](cop-transform.md#pcg-copdistort) | equivalent |
| Dot Product | [COP Vector Math (PCG)](cop-utility.md#pcg-copvectormath) | equivalent |
| Drop Shadow | [COP Drop Shadow (PCG)](cop-composite.md#pcg-copdropshadow) | equivalent |
| Edge Detect | [COP Edge Detect (PCG)](cop-filter.md#pcg-copedge) | equivalent |
| Edge Detect by Contour | [COP Edge Detect Probe (PCG)](cop-filter.md#pcg-copedgedetectprobe) | equivalent |
| Edge Detect by Depth | [COP Edge Detect Probe (PCG)](cop-filter.md#pcg-copedgedetectprobe) | equivalent |
| Edge Detect by Normal | [COP Edge Detect Probe (PCG)](cop-filter.md#pcg-copedgedetectprobe) | equivalent |
| Eikonal | [COP Eikonal (PCG)](cop-sim.md#pcg-copeikonal) | equivalent |
| Equalize | [COP Equalize (PCG)](cop-color.md#pcg-copequalize) | equivalent |
| Error | [COP Compare (PCG)](cop-utility.md#pcg-copcompare) | equivalent |
| Extrapolate Boundaries | [COP Extrapolate Boundaries (PCG)](cop-filter.md#pcg-copextrapolateboundaries) | equivalent |
| Fast Fourier Transform | [COP FFT (PCG)](cop-filter.md#pcg-copfft) | equivalent |
| Feather | [COP Feather Slope (PCG)](cop-filter.md#pcg-copfeatherslope) | equivalent |
| Fill | [COP Fill (PCG)](cop-generate.md#pcg-copfill) | equivalent |
| Fill Connected | [COP Flood Fill (PCG)](cop-utility.md#pcg-copfloodfill) | equivalent |
| Filter Frequencies | [COP FFT (PCG)](cop-filter.md#pcg-copfft) | equivalent |
| Flip | [COP Flip (PCG)](cop-transform.md#pcg-copflip) | equivalent |
| Flow Block Begin | [COP Flow Solve (PCG)](cop-sim.md#pcg-copflowsolve) | equivalent |
| Flow Block End | [COP Flow Solve (PCG)](cop-sim.md#pcg-copflowsolve) | equivalent |
| Flow Project Non-Divergent Multigrid | [COP Flow Solve (PCG)](cop-sim.md#pcg-copflowsolve) | equivalent |
| Font | [COP Text (PCG)](cop-generate.md#pcg-coptext) | equivalent |
| Fractal Noise | [COP Noise (PCG)](cop-generate.md#pcg-copnoise) | equivalent |
| Fractal Noise 3D | [COP Noise (PCG)](cop-generate.md#pcg-copnoise) | equivalent |
| Fractal Sample | [COP Fractal Sample (PCG)](cop-generate.md#pcg-copfractalsample) | equivalent |
| Function | [COP Function (PCG)](cop-color.md#pcg-copfunction) | equivalent |
| Gamma | [COP Color Correct (PCG)](cop-color.md#pcg-copcolorcorrect) | equivalent |
| Geometry Attribute from Layer | [Attribute from Map (PCG)](attribute.md#pcg-attribfrommap) | equivalent |
| Geometry to Layer | [COP Geometry to Layer (PCG)](cop-geometry.md#pcg-copgeotolayer) | equivalent |
| Glow | [COP Glow (PCG)](cop-filter.md#pcg-copglow) | equivalent |
| Heat Distort | [COP Heat Distort (PCG)](cop-transform.md#pcg-copheatdistort) | equivalent |
| Heat Distort by Layer | [COP Heat Distort by Layer (PCG)](cop-transform.md#pcg-copheatdistortbylayer) | equivalent |
| Height to Ambient Occlusion | [COP Height to AO (PCG)](cop-terrain.md#pcg-copheighttoao) | equivalent |
| Height to Caustics | [COP Height to Caustics (PCG)](cop-terrain.md#pcg-copheighttocaustics) | equivalent |
| Height to Normal | [COP Height to Normal (PCG)](cop-terrain.md#pcg-copheighttonormal) | equivalent |
| Height to Shadow | [COP Height to Shadow (PCG)](cop-terrain.md#pcg-copheighttoshadow) | equivalent |
| HeightField Clip | [COP HeightField Clip (PCG)](cop-terrain.md#pcg-cophfclip) | equivalent |
| HeightField Erode | [COP HeightField Hydraulic Erosion (PCG)](cop-terrain.md#pcg-cophydraulicerosion) | equivalent |
| HeightField Mask by Feature | [COP HeightField Mask by Feature (PCG)](cop-terrain.md#pcg-copmaskbyfeature) | equivalent |
| HeightField Project | [COP HeightField Project (PCG)](cop-terrain.md#pcg-cophfproject) | equivalent |
| HeightField Slump | [COP HeightField Thermal Erosion (PCG)](cop-terrain.md#pcg-copthermalerosion) | equivalent |
| HeightField Strata | [COP Strata (PCG)](cop-terrain.md#pcg-copstrata) | equivalent |
| HeightField Terrace | [COP HeightField Terrace (PCG)](cop-terrain.md#pcg-copterrace) | equivalent |
| HeightField to Mono | [COP Luminance (PCG)](cop-layers.md#pcg-copluminance) | equivalent |
| HeightField Transform 2D | [COP Transform (PCG)](cop-transform.md#pcg-coptransform) | equivalent |
| HeightField Transform 3D | [COP HeightField Project (PCG)](cop-terrain.md#pcg-cophfproject) | equivalent |
| HeightField Visualize | [COP Visualize (PCG)](cop-utility.md#pcg-copvisualize) | equivalent |
| Hex Tile | [COP Hex Tile (PCG)](cop-transform.md#pcg-cophextile) | equivalent |
| Histogram | [COP Histogram Plot (PCG)](cop-utility.md#pcg-cophistogramplot) | equivalent |
| HSV Adjust | [COP Color Correct (PCG)](cop-color.md#pcg-copcolorcorrect) | equivalent |
| ID to Mask | [COP ID Convert (PCG)](cop-layers.md#pcg-copidconvert) | equivalent |
| ID to Mono | [COP ID Convert (PCG)](cop-layers.md#pcg-copidconvert) | equivalent |
| ID to RGB | [Control Image (PCG)](cop-layers.md#pcg-controlimage) | equivalent |
| ID to SDF | [COP ID Convert (PCG)](cop-layers.md#pcg-copidconvert) | equivalent |
| Illegal Pixel | [COP Illegal Pixel (PCG)](cop-utility.md#pcg-copillegalpixel) | equivalent |
| Integrate Volume | [COP Integrate Volume (PCG)](cop-geometry.md#pcg-copintegratevolume) | equivalent |
| Invert | [COP Invert (PCG)](cop-color.md#pcg-copinvert) | equivalent |
| Julia Fractal | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Knit | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Kuwahara Filter | [COP Kuwahara (PCG)](cop-filter.md#pcg-copkuwahara) | equivalent |
| Labs UV Grid Texture | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Laplacian | [COP Derivative (PCG)](cop-filter.md#pcg-copderivative) | equivalent |
| Lattice Deform | [COP Lattice Deform (PCG)](cop-transform.md#pcg-coplatticedeform) | equivalent |
| Layer | [COP Constant (PCG)](cop-generate.md#pcg-copconstant) | equivalent |
| Layer from Attribute | [COP Layer from Attribute (PCG)](cop-geometry.md#pcg-coplayerfromattrib) | equivalent |
| Layer from Curves | [COP Rasterize Curves (PCG)](cop-geometry.md#pcg-coprasterizecurves) | equivalent |
| Layer Merge | [COP Layer Combine (PCG)](cop-composite.md#pcg-coplayercombine) | equivalent |
| Layer to Geometry | [COP HeightField to Mesh (PCG)](cop-geometry.md#pcg-copheightfieldtomesh) | equivalent |
| Layer to Points | [COP Layer To Points (PCG)](cop-geometry.md#pcg-coplayertopoints) | equivalent |
| Lens Distort | [COP Lens Distort (PCG)](cop-transform.md#pcg-coplensdistort) | equivalent |
| Light | [COP Light (PCG)](cop-utility.md#pcg-coplight) | equivalent |
| Logic | [COP Logic (PCG)](cop-composite.md#pcg-coplogic) | equivalent |
| Mask Combine | [COP Mask Combine (PCG)](cop-composite.md#pcg-copmaskcombine) | equivalent |
| Mask from Curves | [COP Rasterize Curves (PCG)](cop-geometry.md#pcg-coprasterizecurves) | equivalent |
| Median | [COP Median (PCG)](cop-filter.md#pcg-copmedian) | equivalent |
| Mirror | [COP Mirror (PCG)](cop-transform.md#pcg-copmirror) | equivalent |
| Mono | [COP Luminance (PCG)](cop-layers.md#pcg-copluminance) | equivalent |
| Mono to HeightField | [COP Mono to HeightField (PCG)](cop-terrain.md#pcg-copmonotoheightfield) | equivalent |
| Mono to ID | [COP Segment By Value (PCG)](cop-utility.md#pcg-copsegmentbyvalue) | equivalent |
| Mono to RGB | [COP Mono to RGB (PCG)](cop-color.md#pcg-copmonotorgb) | equivalent |
| Mono to RGBA | [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | equivalent |
| Mono to SDF | [COP SDF from Mask (PCG)](cop-filter.md#pcg-copsdffrommask) | equivalent |
| Normal to Height | [COP Normal to Height (PCG)](cop-terrain.md#pcg-copnormaltoheight) | equivalent |
| Ocean Evaluate | [COP Ocean (PCG)](cop-sim.md#pcg-copocean) | equivalent |
| Ocean Spectrum | [COP Ocean (PCG)](cop-sim.md#pcg-copocean) | equivalent |
| Phasor Noise | [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | equivalent |
| Pixelate | [COP Pixelate (PCG)](cop-filter.md#pcg-coppixelate) | equivalent |
| Planar Inflate | [COP Planar Inflate (PCG)](cop-geometry.md#pcg-copplanarinflate) | equivalent |
| Point Delete | [Delete (PCG)](modify.md#pcg-delete) | equivalent |
| Point Generate | [COP Point Generate (PCG)](cop-geometry.md#pcg-coppointgenerate) | equivalent |
| Point Merge | [Merge (PCG)](modify.md#pcg-merge) | equivalent |
| Points from Blobs | [COP Points From Blobs (PCG)](cop-geometry.md#pcg-coppointsfromblobs) | equivalent |
| Polar to UV | [COP Polar Coords (PCG)](cop-transform.md#pcg-coppolarcoords) | equivalent |
| Position Map | [COP Position Map (PCG)](cop-generate.md#pcg-coppositionmap) | equivalent |
| Position Sample | [Attribute from Camera (PCG)](attribute.md#pcg-attribfromcamera) | equivalent |
| Prefix Sum | [COP Prefix Sum (PCG)](cop-utility.md#pcg-copprefixsum) | equivalent |
| Premultiply | [COP Premultiply (PCG)](cop-composite.md#pcg-coppremultiply) | equivalent |
| Python Snippet | [COP Wrangle (PCG)](cop-utility.md#pcg-copwrangle) | equivalent |
| Quantize | [COP Quantize (PCG)](cop-color.md#pcg-copquantize) | equivalent |
| Ramp | [COP Gradient (PCG)](cop-generate.md#pcg-copgradient) | equivalent |
| Random Mono | [COP Random (PCG)](cop-generate.md#pcg-coprandom) | equivalent |
| Random RGB | [COP Random (PCG)](cop-generate.md#pcg-coprandom) | equivalent |
| Rasterize Curves | [COP Rasterize Curves (PCG)](cop-geometry.md#pcg-coprasterizecurves) | equivalent |
| Rasterize Geometry | [Render Pass (PCG)](cop-geometry.md#pcg-renderpass) | equivalent |
| Rasterize GSplats | [COP Rasterize Splats (PCG)](cop-geometry.md#pcg-coprasterizesplats) | equivalent |
| Reaction-Diffusion Block Begin | [COP Reaction Diffusion (PCG)](cop-sim.md#pcg-copreactiondiffusion) | equivalent |
| Reaction-Diffusion Block End | [COP Reaction Diffusion (PCG)](cop-sim.md#pcg-copreactiondiffusion) | equivalent |
| Refract from Height | [COP Refract from Height (PCG)](cop-transform.md#pcg-coprefractfromheight) | equivalent |
| Remap | [COP Remap (PCG)](cop-color.md#pcg-copremap) | equivalent |
| Rename | [COP Layer Edit (PCG)](cop-layers.md#pcg-coplayeredit) | equivalent |
| Resample | [COP Resize (PCG)](cop-transform.md#pcg-copresize) | equivalent |
| Resize | [COP Resize (PCG)](cop-transform.md#pcg-copresize) | equivalent |
| Retile | [COP Retile (PCG)](cop-transform.md#pcg-copretile) | equivalent |
| Reverse | [COP Sequence Ops (PCG)](cop-utility.md#pcg-copsequenceops) | equivalent |
| RGB to RGBA | [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | equivalent |
| RGB to UV | [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | equivalent |
| RGBA to RGB | [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | equivalent |
| RGBA to UV | [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | equivalent |
| Ripple Block Begin | [COP Ripple (PCG)](cop-sim.md#pcg-copripple) | equivalent |
| Ripple Block End | [COP Ripple (PCG)](cop-sim.md#pcg-copripple) | equivalent |
| ROP Image Output | [COP Write File (PCG)](cop-utility.md#pcg-copwritefile) | equivalent |
| Scatter on Curves | [COP Scatter Shapes (PCG)](cop-geometry.md#pcg-copscattershapes) | equivalent |
| Scatter Shapes | [COP Scatter Shapes (PCG)](cop-geometry.md#pcg-copscattershapes) | equivalent |
| SDF Blend | [COP SDF Ops (PCG)](cop-filter.md#pcg-copsdfops) | equivalent |
| SDF Shape | [COP Shape (PCG)](cop-generate.md#pcg-copshape) | equivalent |
| SDF to Mono | [COP SDF Ops (PCG)](cop-filter.md#pcg-copsdfops) | equivalent |
| Segment by Connectivity | [COP Segment by Connectivity (PCG)](cop-utility.md#pcg-copsegment) | equivalent |
| Segment by Value | [COP Segment By Value (PCG)](cop-utility.md#pcg-copsegmentbyvalue) | equivalent |
| Sequence | [COP Sequence Clips (PCG)](cop-utility.md#pcg-copsequenceclips) | equivalent |
| Sequence Blend | [COP Sequence Ops (PCG)](cop-utility.md#pcg-copsequenceops) | equivalent |
| Sharpen | [COP Sharpen (PCG)](cop-filter.md#pcg-copsharpen) | equivalent |
| Slope Direction | [COP Slope & Aspect (PCG)](cop-terrain.md#pcg-copslope) | equivalent |
| Smooth Fill | [COP Smooth Fill (PCG)](cop-filter.md#pcg-copsmoothfill) | equivalent |
| Solve Poisson | [COP Solve Poisson (PCG)](cop-sim.md#pcg-copsolvepoisson) | equivalent |
| Space Transform | [COP Space Transform (PCG)](cop-transform.md#pcg-copspacetransform) | equivalent |
| Sphere Sample | [COP Sphere Sample (PCG)](cop-transform.md#pcg-copspheresample) | equivalent |
| Stamp Points | [COP Scatter Shapes (PCG)](cop-geometry.md#pcg-copscattershapes) | equivalent |
| Star Glow | [COP Glow (PCG)](cop-filter.md#pcg-copglow) | equivalent |
| Statistics | [COP Statistics (PCG)](cop-utility.md#pcg-copstatistics) | equivalent |
| Streak Blur | [COP Directional Blur (PCG)](cop-filter.md#pcg-copdirectionalblur) | equivalent |
| Surface Dither | [COP Surface Dither (PCG)](cop-filter.md#pcg-copsurfacedither) | equivalent |
| Swirl | [COP Swirl (PCG)](cop-transform.md#pcg-copswirl) | equivalent |
| Tile Pattern | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Time Blend | [COP Sequence Ops (PCG)](cop-utility.md#pcg-copsequenceops) | equivalent |
| Time Loop | [COP Sequence Ops (PCG)](cop-utility.md#pcg-copsequenceops) | equivalent |
| Time Pack | [COP Time Pack (PCG)](cop-utility.md#pcg-coptimepack) | equivalent |
| Time Shift | [COP Sequence Ops (PCG)](cop-utility.md#pcg-copsequenceops) | equivalent |
| Tone Map | [COP Tone Map (PCG)](cop-color.md#pcg-coptonemap) | equivalent |
| Transform 2D | [COP Transform (PCG)](cop-transform.md#pcg-coptransform) | equivalent |
| Transform 3D | [COP Transform 3D (PCG)](cop-transform.md#pcg-coptransform3d) | equivalent |
| Triplanar | [COP Triplanar (PCG)](cop-geometry.md#pcg-coptriplanar) | equivalent |
| Triplanar Hex Tile | [COP Triplanar (PCG)](cop-geometry.md#pcg-coptriplanar) | equivalent |
| Triplanar UV | [COP Triplanar (PCG)](cop-geometry.md#pcg-coptriplanar) | equivalent |
| Turing Patterns | [COP Turing Patterns (PCG)](cop-sim.md#pcg-copturingpatterns) | equivalent |
| UV Inverse | [COP UV Inverse (PCG)](cop-transform.md#pcg-copuvinverse) | equivalent |
| UV Map | [COP UV Map (PCG)](cop-transform.md#pcg-copuvmap) | equivalent |
| UV Map by ID | [COP UV Map (PCG)](cop-transform.md#pcg-copuvmap) | equivalent |
| UV Sample | [COP UV Sample (PCG)](cop-transform.md#pcg-copuvsample) | equivalent |
| UV Shape | [COP UV Shape (PCG)](cop-geometry.md#pcg-copuvshape) | equivalent |
| UV to Polar | [COP Polar Coords (PCG)](cop-transform.md#pcg-coppolarcoords) | equivalent |
| UV to RGB | [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | equivalent |
| UV to RGBA | [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | equivalent |
| UV Transform | [COP UV Transform (PCG)](cop-transform.md#pcg-copuvtransform) | equivalent |
| Vector Transform | [COP Vector Transform (PCG)](cop-utility.md#pcg-copvectortransform) | equivalent |
| Vector Transform 2D | [COP Vector Transform (PCG)](cop-utility.md#pcg-copvectortransform) | equivalent |
| Vignette | [COP Vignette (PCG)](cop-color.md#pcg-copvignette) | equivalent |
| Visualize Velocity | [COP Visualize (PCG)](cop-utility.md#pcg-copvisualize) | equivalent |
| Weave | [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | equivalent |
| Wipe | [COP Wipe (PCG)](cop-composite.md#pcg-copwipe) | equivalent |
| Worley Noise | [COP Worley Noise (PCG)](cop-generate.md#pcg-copworleynoise) | equivalent |
| Worley Noise 3D | [COP Worley Noise (PCG)](cop-generate.md#pcg-copworleynoise) | equivalent |
| Wrangle | [COP Wrangle (PCG)](cop-utility.md#pcg-copwrangle) | equivalent |
