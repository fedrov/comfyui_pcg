# Node reference

All 504 nodes of comfyui_pcg, generated from the code by `docs/build_docs.py` (parameter names, types, defaults and menu options are always current).

In the parameter tables, the first column is the label shown in the node's panel followed by the input's internal name (the name used in saved workflows, relative references and `ch()` expressions). *Hidden when* / *Disabled when* repeat the panel's own rules.

## [Generate](generate.md)

Primitives, curves, terrain and other nodes that create geometry from nothing.

[Add (PCG)](generate.md#pcg-add), [Ballistic Path (PCG)](generate.md#pcg-ballisticpath), [Box (PCG)](generate.md#pcg-box), [Circle (PCG)](generate.md#pcg-circle), [Cross Section Surface (PCG)](generate.md#pcg-crosssectionsurface), [Cross Section Surface · Houdini (PCG)](generate.md#pcg-crosssectionsurfacehou), [Curve (PCG)](generate.md#pcg-curve), [Extract Silhouette (PCG)](generate.md#pcg-extractsilhouette), [Font (PCG)](generate.md#pcg-font), [Grid (PCG)](generate.md#pcg-grid), [IsoOffset (PCG)](generate.md#pcg-isooffset), [IsoSurface (PCG)](generate.md#pcg-isosurface), [L-System (PCG)](generate.md#pcg-lsystem), [Line (PCG)](generate.md#pcg-line), [Platonic Solids (PCG)](generate.md#pcg-platonicsolids), [PolyLoft (PCG)](generate.md#pcg-polyloft), [PolyWire (PCG)](generate.md#pcg-polywire), [Revolve (PCG)](generate.md#pcg-revolve), [Skin (PCG)](generate.md#pcg-skin), [Sphere (PCG)](generate.md#pcg-sphere), [Sweep (PCG)](generate.md#pcg-sweep), [Torus (PCG)](generate.md#pcg-torus), [Tube (PCG)](generate.md#pcg-tube), [Volume (PCG)](generate.md#pcg-volume)

## [Modify](modify.md)

Modeling operations: extrude, bevel, boolean, clip, fuse, remesh, subdivide and friends.

[Blast (PCG)](modify.md#pcg-blast), [Blast by Attribute (PCG)](modify.md#pcg-blastbyattribute), [Boolean (PCG)](modify.md#pcg-boolean), [Boolean Fracture (PCG)](modify.md#pcg-booleanfracture), [Bound (PCG)](modify.md#pcg-bound), [Carve (PCG)](modify.md#pcg-carve), [Circle from Edges (PCG)](modify.md#pcg-circlefromedges), [Circle Spline (PCG)](modify.md#pcg-circlespline), [Clean (PCG)](modify.md#pcg-clean), [Clip (PCG)](modify.md#pcg-clip), [Convert (PCG)](modify.md#pcg-convert), [Convex Decompose (PCG)](modify.md#pcg-convexdecompose), [Convex Hull (PCG)](modify.md#pcg-convexhull), [Crease (PCG)](modify.md#pcg-crease), [Curve Fillet (PCG)](modify.md#pcg-curvefillet), [Curve Intersect (PCG)](modify.md#pcg-curveintersect), [Delete (PCG)](modify.md#pcg-delete), [Dissolve (PCG)](modify.md#pcg-dissolve), [Divide (PCG)](modify.md#pcg-divide), [Edge Collapse (PCG)](modify.md#pcg-edgecollapse), [Edge Divide (PCG)](modify.md#pcg-edgedivide), [Edge Equalize (PCG)](modify.md#pcg-edgeequalize), [Edge Straighten (PCG)](modify.md#pcg-edgestraighten), [Ends (PCG)](modify.md#pcg-ends), [Exploded View (PCG)](modify.md#pcg-explodedview), [Extract Transform (PCG)](modify.md#pcg-extracttransform), [Facet (PCG)](modify.md#pcg-facet), [Fracture Detail (PCG)](modify.md#pcg-fracturedetail), [Fuse (PCG)](modify.md#pcg-fuse), [Intersection Analysis (PCG)](modify.md#pcg-intersectionanalysis), [Join (PCG)](modify.md#pcg-join), [Loop Cut (PCG)](modify.md#pcg-loopcut), [Match Axis (PCG)](modify.md#pcg-matchaxis), [Match Size (PCG)](modify.md#pcg-matchsize), [Merge (PCG)](modify.md#pcg-merge), [Mirror (PCG)](modify.md#pcg-mirror), [Peak (PCG)](modify.md#pcg-peak), [Point Jitter (PCG)](modify.md#pcg-pointjitter), [Point Split (PCG)](modify.md#pcg-pointsplit), [Poly Bridge (PCG)](modify.md#pcg-polybridge), [PolyBevel (PCG)](modify.md#pcg-polybevel), [PolyDoctor (PCG)](modify.md#pcg-polydoctor), [PolyExpand2D (PCG)](modify.md#pcg-polyexpand2d), [PolyExtrude (PCG)](modify.md#pcg-polyextrude), [PolyFill (PCG)](modify.md#pcg-polyfill), [PolyPath (PCG)](modify.md#pcg-polypath), [PolyReduce (PCG)](modify.md#pcg-polyreduce), [PolySpline (PCG)](modify.md#pcg-polyspline), [Primitive (PCG)](modify.md#pcg-primitive), [Primitive Split (PCG)](modify.md#pcg-primitivesplit), [Ray (PCG)](modify.md#pcg-ray), [Refine (PCG)](modify.md#pcg-refine), [Remesh (PCG)](modify.md#pcg-remesh), [Remesh to Grid (PCG)](modify.md#pcg-remeshtogrid), [Resample (PCG)](modify.md#pcg-resample), [Reverse (PCG)](modify.md#pcg-reverse), [Shrinkwrap (PCG)](modify.md#pcg-shrinkwrap), [Smooth (PCG)](modify.md#pcg-smooth), [Sort (PCG)](modify.md#pcg-sort), [Split (PCG)](modify.md#pcg-split), [Subdivide (PCG)](modify.md#pcg-subdivide), [Switch (PCG)](modify.md#pcg-switch), [Switch-If (PCG)](modify.md#pcg-switchif), [Thicken (PCG)](modify.md#pcg-thicken), [Transform (PCG)](modify.md#pcg-transform), [Transform by Attribute (PCG)](modify.md#pcg-transformbyattrib), [Triangulate 2D (PCG)](modify.md#pcg-triangulate2d), [Volume Blur (PCG)](modify.md#pcg-volumeblur), [Volume Mix (PCG)](modify.md#pcg-volumemix), [Volume Resample (PCG)](modify.md#pcg-volumeresample), [Volume Reshape SDF (PCG)](modify.md#pcg-volumereshapesdf), [Volume Smooth SDF (PCG)](modify.md#pcg-volumesmoothsdf), [Volume Wrangle (PCG)](modify.md#pcg-volumewrangle), [Voronoi Cluster (PCG)](modify.md#pcg-voronoicluster), [Voronoi Fracture (PCG)](modify.md#pcg-voronoifracture), [Voronoi Split (PCG)](modify.md#pcg-voronoisplit)

## [Deform](deform.md)

Nodes that move points without changing topology.

[Blend Shapes (PCG)](deform.md#pcg-blendshapes), [Bulge (PCG)](deform.md#pcg-bulge), [DeltaMush (PCG)](deform.md#pcg-deltamush), [Displace from Map (PCG)](deform.md#pcg-displacefrommap), [Fractal (PCG)](deform.md#pcg-fractal), [Lattice (PCG)](deform.md#pcg-lattice), [Lattice From Bound (PCG)](deform.md#pcg-latticefrombound), [Magnet (PCG)](deform.md#pcg-magnet), [Path Deform (PCG)](deform.md#pcg-pathdeform), [Point Deform (PCG)](deform.md#pcg-pointdeform), [Soft Peak (PCG)](deform.md#pcg-softpeak), [Soft Transform (PCG)](deform.md#pcg-softtransform), [Spherify (PCG)](deform.md#pcg-spherify), [Topo Transfer (PCG)](deform.md#pcg-topotransfer), [Transform Pieces (PCG)](deform.md#pcg-transformpieces), [Twist / Bend / Taper (PCG)](deform.md#pcg-deform)

## [Topology](topology.md)

Connectivity, edges, paths and other structural queries and edits.

[Connect Adjacent Pieces (PCG)](topology.md#pcg-connectadjacentpieces), [Connectivity (PCG)](topology.md#pcg-connectivity), [Edge Cusp (PCG)](topology.md#pcg-edgecusp), [Edge Flip (PCG)](topology.md#pcg-edgeflip), [Find Shortest Path (PCG)](topology.md#pcg-findshortestpath), [Match Topology (PCG)](topology.md#pcg-matchtopology), [PolyCut (PCG)](topology.md#pcg-polycut), [PolySplit (PCG)](topology.md#pcg-polysplit), [PolyStitch (PCG)](topology.md#pcg-polystitch), [Rewire Vertices (PCG)](topology.md#pcg-rewirevertices), [Tri Divide (PCG)](topology.md#pcg-tridivide), [Unsubdivide (PCG)](topology.md#pcg-unsubdivide)

## [Attributes](attribute.md)

Create, edit, transfer and randomize attributes.

[Attribute Adjust (PCG)](attribute.md#pcg-attribadjust), [Attribute Adjust Color (PCG)](attribute.md#pcg-attribadjustcolor), [Attribute Adjust Float (PCG)](attribute.md#pcg-attribadjustfloat), [Attribute Adjust Integer (PCG)](attribute.md#pcg-attribadjustinteger), [Attribute Adjust Vector (PCG)](attribute.md#pcg-attribadjustvector), [Attribute Blur (PCG)](attribute.md#pcg-attribblur), [Attribute Cast (PCG)](attribute.md#pcg-attribcast), [Attribute Composite (PCG)](attribute.md#pcg-attribcomposite), [Attribute Copy (PCG)](attribute.md#pcg-attribcopy), [Attribute Create (PCG)](attribute.md#pcg-attribcreate), [Attribute Delete (PCG)](attribute.md#pcg-attribdelete), [Attribute Fade (PCG)](attribute.md#pcg-attribfade), [Attribute Fade · Time (PCG)](attribute.md#pcg-attribfadetime), [Attribute Fill (PCG)](attribute.md#pcg-attribfill), [Attribute from Camera (PCG)](attribute.md#pcg-attribfromcamera), [Attribute from Map (PCG)](attribute.md#pcg-attribfrommap), [Attribute from Pieces (PCG)](attribute.md#pcg-attribfrompieces), [Attribute from Volume (PCG)](attribute.md#pcg-attribfromvolume), [Attribute Interpolate (PCG)](attribute.md#pcg-attribinterpolate), [Attribute Mirror (PCG)](attribute.md#pcg-attribmirror), [Attribute Noise (PCG)](attribute.md#pcg-attribnoise), [Attribute Promote (PCG)](attribute.md#pcg-attribpromote), [Attribute Randomize (PCG)](attribute.md#pcg-attribrandomize), [Attribute Rename (PCG)](attribute.md#pcg-attribrename), [Attribute Reorient (PCG)](attribute.md#pcg-attribreorient), [Attribute String Edit (PCG)](attribute.md#pcg-attribstringedit), [Attribute Transfer (PCG)](attribute.md#pcg-attribtransfer), [Attribute Transfer by UV (PCG)](attribute.md#pcg-attribtransferbyuv), [Attribute Transform Extract (PCG)](attribute.md#pcg-attribtransformextract), [Attribute Transform Extract · Houdini (PCG)](attribute.md#pcg-attribtransformextracthou), [Cluster Points (PCG)](attribute.md#pcg-clusterpoints), [Color (PCG)](attribute.md#pcg-color), [Distance along Geometry (PCG)](attribute.md#pcg-distancealonggeometry), [Distance from Geometry (PCG)](attribute.md#pcg-distancefromgeometry), [Edge Transport (PCG)](attribute.md#pcg-edgetransport), [Enumerate (PCG)](attribute.md#pcg-enumerate), [Extract Centroid (PCG)](attribute.md#pcg-extractcentroid), [Measure (PCG)](attribute.md#pcg-measure), [Name (PCG)](attribute.md#pcg-name), [Normal (PCG)](attribute.md#pcg-normal), [Orient Along Curve (PCG)](attribute.md#pcg-orientalongcurve), [Point Velocity (PCG)](attribute.md#pcg-pointvelocity), [PolyFrame (PCG)](attribute.md#pcg-polyframe), [Tangent Field (PCG)](attribute.md#pcg-tangentfield), [Wrangle (PCG)](attribute.md#pcg-wrangle)

## [Groups](group.md)

Create, combine and convert groups.

[Edge Group Promote (PCG)](group.md#pcg-edgegrouppromote), [Group Combine (PCG)](group.md#pcg-groupcombine), [Group Create (PCG)](group.md#pcg-groupcreate), [Group Delete (PCG)](group.md#pcg-groupdelete), [Group Edges (PCG)](group.md#pcg-groupedges), [Group Expand (PCG)](group.md#pcg-groupexpand), [Group Find Path (PCG)](group.md#pcg-groupfindpath), [Group from Attribute Boundary (PCG)](group.md#pcg-groupfromattribboundary), [Group Inside (PCG)](group.md#pcg-groupinside), [Group Promote (PCG)](group.md#pcg-grouppromote), [Partition (PCG)](group.md#pcg-partition)

## [Scatter & Copy](scatter.md)

Scatter points and copy geometry onto them.

[Adaptive Prune (PCG)](scatter.md#pcg-adaptiveprune), [Assemble (PCG)](scatter.md#pcg-assemble), [Chain (PCG)](scatter.md#pcg-chain), [Copy and Transform (PCG)](scatter.md#pcg-copyandtransform), [Copy to Curves (PCG)](scatter.md#pcg-copytocurves), [Copy to Points (PCG)](scatter.md#pcg-copytopoints), [Pack (PCG)](scatter.md#pcg-pack), [Point Relax (PCG)](scatter.md#pcg-pointrelax), [Point Replicate (PCG)](scatter.md#pcg-pointreplicate), [Scatter (PCG)](scatter.md#pcg-scatter), [Scatter and Align (PCG)](scatter.md#pcg-scatteralign), [Scatter from Map (PCG)](scatter.md#pcg-scatterfrommap), [Scatter in Volume (PCG)](scatter.md#pcg-scattervolume), [Unpack (PCG)](scatter.md#pcg-unpack), [Voronoi 2D (PCG)](scatter.md#pcg-voronoi2d)

## [UV](uv.md)

UV projection, unwrapping, layout and seams.

[UV Auto Seams (PCG)](uv.md#pcg-uvautoseams), [UV Flatten (PCG)](uv.md#pcg-uvflatten), [UV Fuse (PCG)](uv.md#pcg-uvfuse), [UV Layout (PCG)](uv.md#pcg-uvlayout), [UV Pelt (PCG)](uv.md#pcg-uvpelt), [UV Project (PCG)](uv.md#pcg-uvproject), [UV Smooth (PCG)](uv.md#pcg-uvsmooth), [UV Transform (PCG)](uv.md#pcg-uvtransform), [UV Unwrap (PCG)](uv.md#pcg-uvunwrap)

## [Convert](convert.md)

Conversions between primitive types, volumes and other representations.

[Convert Line (PCG)](convert.md#pcg-convertline), [File Merge (PCG)](convert.md#pcg-filemerge), [From JSON (PCG)](convert.md#pcg-fromjson), [Geo to JSON (PCG)](convert.md#pcg-geotojson), [Import Mesh (PCG)](convert.md#pcg-importmesh), [Trace (PCG)](convert.md#pcg-trace), [Volume Rasterize Attributes (PCG)](convert.md#pcg-volumerasterizeattribs)

## [Volumes & VDB](volume.md)

VDB creation, active regions, level sets, fields and the rest of the Volume SOPs (pcg106).

[Convert VDB (PCG)](volume.md#pcg-convertvdb), [VDB (PCG)](volume.md#pcg-vdb), [VDB Activate (PCG)](volume.md#pcg-vdbactivate), [VDB Activate SDF (PCG)](volume.md#pcg-vdbactivatesdf), [VDB Advect (PCG)](volume.md#pcg-vdbadvect), [VDB Advect Points (PCG)](volume.md#pcg-vdbadvectpoints), [VDB Analysis (PCG)](volume.md#pcg-vdbanalysis), [VDB Clip (PCG)](volume.md#pcg-vdbclip), [VDB Combine (PCG)](volume.md#pcg-vdbcombine), [VDB Densify (PCG)](volume.md#pcg-vdbdensify), [VDB Diagnostics (PCG)](volume.md#pcg-vdbdiagnostics), [VDB Extrapolate (PCG)](volume.md#pcg-vdbextrapolate), [VDB Fill (PCG)](volume.md#pcg-vdbfill), [VDB Fracture (PCG)](volume.md#pcg-vdbfracture), [VDB from Particle Fluid (PCG)](volume.md#pcg-vdbfromparticlefluid), [VDB from Particles (PCG)](volume.md#pcg-vdbfromparticles), [VDB from Polygons (PCG)](volume.md#pcg-vdbfrompolygons), [VDB LOD (PCG)](volume.md#pcg-vdblod), [VDB Merge (PCG)](volume.md#pcg-vdbmerge), [VDB Metadata (PCG)](volume.md#pcg-vdbmetadata), [VDB Morph SDF (PCG)](volume.md#pcg-vdbmorphsdf), [VDB Noise (PCG)](volume.md#pcg-vdbnoise), [VDB Occlusion Mask (PCG)](volume.md#pcg-vdbocclusionmask), [VDB Platonic (PCG)](volume.md#pcg-vdbplatonic), [VDB Points Group (PCG)](volume.md#pcg-vdbpointsgroup), [VDB Potential Flow (PCG)](volume.md#pcg-vdbpotentialflow), [VDB Project Non-Divergent (PCG)](volume.md#pcg-vdbprojectnondivergent), [VDB Prune (PCG)](volume.md#pcg-vdbprune), [VDB Ray (PCG)](volume.md#pcg-vdbray), [VDB Rebuild SDF (PCG)](volume.md#pcg-vdbrebuildsdf), [VDB Remap (PCG)](volume.md#pcg-vdbremap), [VDB Renormalize SDF (PCG)](volume.md#pcg-vdbrenormalizesdf), [VDB Resample (PCG)](volume.md#pcg-vdbresample), [VDB Scatter (PCG)](volume.md#pcg-vdbscatter), [VDB Segment by Connectivity (PCG)](volume.md#pcg-vdbsegment), [VDB Smooth (PCG)](volume.md#pcg-vdbsmooth), [VDB to Spheres (PCG)](volume.md#pcg-vdbtospheres), [VDB Topology to SDF (PCG)](volume.md#pcg-vdbtopologytosdf), [VDB Transform (PCG)](volume.md#pcg-vdbtransform), [VDB Vector Merge (PCG)](volume.md#pcg-vdbvectormerge), [VDB Vector Split (PCG)](volume.md#pcg-vdbvectorsplit), [VDB Visualize Tree (PCG)](volume.md#pcg-vdbvisualizetree), [Volume Adjust Fog (PCG)](volume.md#pcg-volumeadjustfog), [Volume Bound (PCG)](volume.md#pcg-volumebound), [Volume Break (PCG)](volume.md#pcg-volumebreak), [Volume Compress (PCG)](volume.md#pcg-volumecompress), [Volume Convolve 3×3×3 (PCG)](volume.md#pcg-volumeconvolve), [Volume Feather (PCG)](volume.md#pcg-volumefeather), [Volume FFT (PCG)](volume.md#pcg-volumefft), [Volume from Attrib (PCG)](volume.md#pcg-volumefromattrib), [Volume Merge (PCG)](volume.md#pcg-volumemerge), [Volume Optical Flow (PCG)](volume.md#pcg-volumeopticalflow), [Volume Patch (PCG)](volume.md#pcg-volumepatch), [Volume Ramp (PCG)](volume.md#pcg-volumeramp), [Volume Rasterize Curve (PCG)](volume.md#pcg-volumerasterizecurve), [Volume Rasterize Particles (PCG)](volume.md#pcg-volumerasterizeparticles), [Volume Rasterize Points (PCG)](volume.md#pcg-volumerasterizepoints), [Volume Reduce (PCG)](volume.md#pcg-volumereduce), [Volume Resize (PCG)](volume.md#pcg-volumeresize), [Volume SDF (PCG)](volume.md#pcg-volumesdf), [Volume Slice (PCG)](volume.md#pcg-volumeslice), [Volume Splice (PCG)](volume.md#pcg-volumesplice), [Volume Stamp (PCG)](volume.md#pcg-volumestamp), [Volume Trail (PCG)](volume.md#pcg-volumetrail), [Volume Velocity (PCG)](volume.md#pcg-volumevelocity), [Volume Velocity from Curves (PCG)](volume.md#pcg-volumevelocityfromcurves), [Volume Velocity from Surface (PCG)](volume.md#pcg-volumevelocityfromsurface), [Volume Visualization (PCG)](volume.md#pcg-volumevisualization)

## [Render & View](render.md)

Preview images, 3D viewport, cameras and render passes.

[Camera (PCG)](render.md#pcg-camera), [Camera from Points (PCG)](render.md#pcg-camerafrompoints), [Camera Path (PCG)](render.md#pcg-camerapath), [Camera Pick (PCG)](render.md#pcg-camerapick), [Camera To Points (PCG)](render.md#pcg-cameratopoints), [Motion Vectors (PCG)](render.md#pcg-motionvectors), [Render Sequence (PCG)](render.md#pcg-rendersequence), [Sequence Motion (PCG)](render.md#pcg-sequencemotion), [Texture Render (PCG)](render.md#pcg-texturerender), [UV Backproject (PCG)](render.md#pcg-uvbackproject), [UV Resolve (PCG)](render.md#pcg-uvresolve)

## [Output & Export](output.md)

Writing files and exporting to other applications.

[Display (PCG)](output.md#pcg-display), [Export Instances (PCG)](output.md#pcg-exportinstances), [Export Mesh (PCG)](output.md#pcg-exportmesh), [File Cache (PCG)](output.md#pcg-filecache), [Geo Metrics (PCG)](output.md#pcg-geometrics), [Geometry Preview (PCG)](output.md#pcg-previewimage), [Geometry Spreadsheet (PCG)](output.md#pcg-geospreadsheet), [Viewport (PCG)](output.md#pcg-viewport)

## [Loops](loop.md)

For-each loops and frame loops.

[For-Each Begin (PCG)](loop.md#pcg-foreachbegin), [For-Each End (PCG)](loop.md#pcg-foreachend), [For-Each Frame Begin (PCG)](loop.md#pcg-foreachframebegin), [For-Each Frame End (PCG)](loop.md#pcg-foreachframeend), [Geo Sequence Pick (PCG)](loop.md#pcg-geosequencepick), [Retime (PCG)](loop.md#pcg-retime), [Select Best (PCG)](loop.md#pcg-selectbest), [Time Blend (PCG)](loop.md#pcg-timeblend), [Trail (PCG)](loop.md#pcg-trail)

## [Parameters & Expressions](param.md)

Controller nodes, values, expressions and parameter plumbing.

[Channel (PCG)](param.md#pcg-channel), [Channel XYZ (PCG)](param.md#pcg-channel3), [Expression (PCG)](param.md#pcg-expr), [Expression XYZ (PCG)](param.md#pcg-expr3), [Frame (PCG)](param.md#pcg-frame), [Param Pick (PCG)](param.md#pcg-parampick), [Parameters (PCG)](param.md#pcg-parameters), [Params from JSON (PCG)](param.md#pcg-paramsfromjson), [Value (PCG)](param.md#pcg-value)

## [Image](image.md)

Bridges between ComfyUI images and the plugin.

[Heightfield from Image (PCG)](image.md#pcg-heightfieldfromimage)

## [Image: Generators](cop-generate.md)

Noise, patterns, shapes, ramps and other image sources.

[COP Cellular Noise (PCG)](cop-generate.md#pcg-copcellularnoise), [COP Constant (PCG)](cop-generate.md#pcg-copconstant), [COP Fill (PCG)](cop-generate.md#pcg-copfill), [COP Fractal Sample (PCG)](cop-generate.md#pcg-copfractalsample), [COP Gradient (PCG)](cop-generate.md#pcg-copgradient), [COP Noise (PCG)](cop-generate.md#pcg-copnoise), [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra), [COP Pattern (PCG)](cop-generate.md#pcg-coppattern), [COP Position Map (PCG)](cop-generate.md#pcg-coppositionmap), [COP Random (PCG)](cop-generate.md#pcg-coprandom), [COP Shape (PCG)](cop-generate.md#pcg-copshape), [COP Stereogram (PCG)](cop-generate.md#pcg-copstereogram), [COP Text (PCG)](cop-generate.md#pcg-coptext), [COP Worley Noise (PCG)](cop-generate.md#pcg-copworleynoise)

## [Image: Color & Levels](cop-color.md)

Color correction, levels, remapping, keying.

[COP Chroma Key (PCG)](cop-color.md#pcg-copchromakey), [COP Clamp (PCG)](cop-color.md#pcg-copclamp), [COP Color Correct (PCG)](cop-color.md#pcg-copcolorcorrect), [COP Despill (PCG)](cop-color.md#pcg-copdespill), [COP Equalize (PCG)](cop-color.md#pcg-copequalize), [COP Fit (PCG)](cop-color.md#pcg-copfit), [COP Function (PCG)](cop-color.md#pcg-copfunction), [COP Histogram (PCG)](cop-color.md#pcg-cophistogram), [COP Invert (PCG)](cop-color.md#pcg-copinvert), [COP Levels (PCG)](cop-color.md#pcg-coplevels), [COP Mono to RGB (PCG)](cop-color.md#pcg-copmonotorgb), [COP Quantize (PCG)](cop-color.md#pcg-copquantize), [COP Remap (PCG)](cop-color.md#pcg-copremap), [COP Tone Map (PCG)](cop-color.md#pcg-coptonemap), [COP Vignette (PCG)](cop-color.md#pcg-copvignette)

## [Image: Filters](cop-filter.md)

Blur, sharpen, edge detection, convolution, morphology.

[COP Blur (PCG)](cop-filter.md#pcg-copblur), [COP Contour (PCG)](cop-filter.md#pcg-copcontour), [COP Convolve (PCG)](cop-filter.md#pcg-copconvolve), [COP Corner Detect (PCG)](cop-filter.md#pcg-copcornerdetect), [COP Defocus (PCG)](cop-filter.md#pcg-copdefocus), [COP Denoise TV (PCG)](cop-filter.md#pcg-copdenoisetv), [COP Derivative (PCG)](cop-filter.md#pcg-copderivative), [COP Directional Blur (PCG)](cop-filter.md#pcg-copdirectionalblur), [COP Dither (PCG)](cop-filter.md#pcg-copdither), [COP Edge Detect (PCG)](cop-filter.md#pcg-copedge), [COP Edge Detect Probe (PCG)](cop-filter.md#pcg-copedgedetectprobe), [COP Erode / Dilate (PCG)](cop-filter.md#pcg-copmorph), [COP Extrapolate Boundaries (PCG)](cop-filter.md#pcg-copextrapolateboundaries), [COP Feather (PCG)](cop-filter.md#pcg-copfeather), [COP Feather Slope (PCG)](cop-filter.md#pcg-copfeatherslope), [COP FFT (PCG)](cop-filter.md#pcg-copfft), [COP Glow (PCG)](cop-filter.md#pcg-copglow), [COP Kuwahara (PCG)](cop-filter.md#pcg-copkuwahara), [COP Median (PCG)](cop-filter.md#pcg-copmedian), [COP Pixelate (PCG)](cop-filter.md#pcg-coppixelate), [COP SDF from Mask (PCG)](cop-filter.md#pcg-copsdffrommask), [COP SDF Ops (PCG)](cop-filter.md#pcg-copsdfops), [COP Sharpen (PCG)](cop-filter.md#pcg-copsharpen), [COP Smooth Fill (PCG)](cop-filter.md#pcg-copsmoothfill), [COP Surface Dither (PCG)](cop-filter.md#pcg-copsurfacedither)

## [Image: Compositing & Masks](cop-composite.md)

Blending images and building masks.

[COP Combine Normals (PCG)](cop-composite.md#pcg-copcombinenormals), [COP Compare Mask (PCG)](cop-composite.md#pcg-copcomparemask), [COP Composite (PCG)](cop-composite.md#pcg-copcomposite), [COP Drop Shadow (PCG)](cop-composite.md#pcg-copdropshadow), [COP Layer Combine (PCG)](cop-composite.md#pcg-coplayercombine), [COP Logic (PCG)](cop-composite.md#pcg-coplogic), [COP Mask Combine (PCG)](cop-composite.md#pcg-copmaskcombine), [COP Premultiply (PCG)](cop-composite.md#pcg-coppremultiply), [COP Select (PCG)](cop-composite.md#pcg-copselect), [COP Wipe (PCG)](cop-composite.md#pcg-copwipe)

## [Image: Transform & Warp](cop-transform.md)

Transforms, distortion, UV mapping and sampling.

[COP Align (PCG)](cop-transform.md#pcg-copalign), [COP Align Pixels (PCG)](cop-transform.md#pcg-copalignpixels), [COP Align Window (PCG)](cop-transform.md#pcg-copalignwindow), [COP Bend (PCG)](cop-transform.md#pcg-copbend), [COP Chromatic Aberration (PCG)](cop-transform.md#pcg-copchromaticaberration), [COP Copy Transform (PCG)](cop-transform.md#pcg-copcopytransform), [COP Corner Pin (PCG)](cop-transform.md#pcg-copcornerpin), [COP Crop / Pad (PCG)](cop-transform.md#pcg-copcrop), [COP Distort (PCG)](cop-transform.md#pcg-copdistort), [COP Flip (PCG)](cop-transform.md#pcg-copflip), [COP Heat Distort (PCG)](cop-transform.md#pcg-copheatdistort), [COP Heat Distort by Layer (PCG)](cop-transform.md#pcg-copheatdistortbylayer), [COP Hex Tile (PCG)](cop-transform.md#pcg-cophextile), [COP Lattice Deform (PCG)](cop-transform.md#pcg-coplatticedeform), [COP Lens Distort (PCG)](cop-transform.md#pcg-coplensdistort), [COP Mirror (PCG)](cop-transform.md#pcg-copmirror), [COP Polar (PCG)](cop-transform.md#pcg-coppolar), [COP Polar Coords (PCG)](cop-transform.md#pcg-coppolarcoords), [COP Refract from Height (PCG)](cop-transform.md#pcg-coprefractfromheight), [COP Resize (PCG)](cop-transform.md#pcg-copresize), [COP Retile (PCG)](cop-transform.md#pcg-copretile), [COP Space Transform (PCG)](cop-transform.md#pcg-copspacetransform), [COP Sphere Sample (PCG)](cop-transform.md#pcg-copspheresample), [COP Swirl (PCG)](cop-transform.md#pcg-copswirl), [COP Tile (PCG)](cop-transform.md#pcg-coptile), [COP Transform (PCG)](cop-transform.md#pcg-coptransform), [COP Transform 3D (PCG)](cop-transform.md#pcg-coptransform3d), [COP UV Inverse (PCG)](cop-transform.md#pcg-copuvinverse), [COP UV Map (PCG)](cop-transform.md#pcg-copuvmap), [COP UV Sample (PCG)](cop-transform.md#pcg-copuvsample), [COP UV Transform (PCG)](cop-transform.md#pcg-copuvtransform), [COP Warp (PCG)](cop-transform.md#pcg-copwarp)

## [Image: Channels & Layers](cop-layers.md)

Channels, layers, conversions between data types.

[Control Image (PCG)](cop-layers.md#pcg-controlimage), [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert), [COP Channel Join (PCG)](cop-layers.md#pcg-copchanneljoin), [COP Channel Split (PCG)](cop-layers.md#pcg-copchannelsplit), [COP Convert Depth (PCG)](cop-layers.md#pcg-copconvertdepth), [COP Convert Normal (PCG)](cop-layers.md#pcg-copconvertnormal), [COP ID Convert (PCG)](cop-layers.md#pcg-copidconvert), [COP Layer Edit (PCG)](cop-layers.md#pcg-coplayeredit), [COP Layer Merge (PCG)](cop-layers.md#pcg-coplayermerge), [COP Luminance (PCG)](cop-layers.md#pcg-copluminance), [COP Swizzle (PCG)](cop-layers.md#pcg-copswizzle), [ID Masks (PCG)](cop-layers.md#pcg-idmasks), [Regional Prompt from COP (PCG)](cop-layers.md#pcg-regionalprompt)

## [Image: Height Fields & Terrain](cop-terrain.md)

Height field generation, erosion, masks and terrain tools.

[COP Curvature (PCG)](cop-terrain.md#pcg-copcurvature), [COP Erosion Filter (PCG)](cop-terrain.md#pcg-coperosion), [COP Flow Accumulation (PCG)](cop-terrain.md#pcg-copflowaccumulation), [COP Height to AO (PCG)](cop-terrain.md#pcg-copheighttoao), [COP Height to Caustics (PCG)](cop-terrain.md#pcg-copheighttocaustics), [COP Height to Normal (PCG)](cop-terrain.md#pcg-copheighttonormal), [COP Height to Shadow (PCG)](cop-terrain.md#pcg-copheighttoshadow), [COP HeightField Clip (PCG)](cop-terrain.md#pcg-cophfclip), [COP HeightField Cutout by Object (PCG)](cop-terrain.md#pcg-cophfcutoutbyobject), [COP HeightField Erode (PCG)](cop-terrain.md#pcg-copheightfielderode), [COP HeightField from Depth (PCG)](cop-terrain.md#pcg-copheightfieldfromdepth), [COP HeightField Hydraulic Erosion (PCG)](cop-terrain.md#pcg-cophydraulicerosion), [COP HeightField Mask by Feature (PCG)](cop-terrain.md#pcg-copmaskbyfeature), [COP HeightField Mask by Object (PCG)](cop-terrain.md#pcg-cophfmaskbyobject), [COP HeightField Project (PCG)](cop-terrain.md#pcg-cophfproject), [COP HeightField Splat Map (PCG)](cop-terrain.md#pcg-copsplatmap), [COP HeightField Stream Power Erosion (PCG)](cop-terrain.md#pcg-copstreampower), [COP HeightField Terrace (PCG)](cop-terrain.md#pcg-copterrace), [COP HeightField Thermal Erosion (PCG)](cop-terrain.md#pcg-copthermalerosion), [COP Mono to HeightField (PCG)](cop-terrain.md#pcg-copmonotoheightfield), [COP Normal to Height (PCG)](cop-terrain.md#pcg-copnormaltoheight), [COP Slope & Aspect (PCG)](cop-terrain.md#pcg-copslope), [COP Strata (PCG)](cop-terrain.md#pcg-copstrata)

## [Image: Geometry and Images](cop-geometry.md)

Rasterizing and baking geometry; turning images back into geometry.

[COP Bake Textures (PCG)](cop-geometry.md#pcg-copbaketextures), [COP Configure Stamps (PCG)](cop-geometry.md#pcg-copconfigurestamps), [COP Geometry to Layer (PCG)](cop-geometry.md#pcg-copgeotolayer), [COP HeightField to Mesh (PCG)](cop-geometry.md#pcg-copheightfieldtomesh), [COP Integrate Volume (PCG)](cop-geometry.md#pcg-copintegratevolume), [COP Layer from Attribute (PCG)](cop-geometry.md#pcg-coplayerfromattrib), [COP Layer To Points (PCG)](cop-geometry.md#pcg-coplayertopoints), [COP Planar Inflate (PCG)](cop-geometry.md#pcg-copplanarinflate), [COP Point Generate (PCG)](cop-geometry.md#pcg-coppointgenerate), [COP Points From Blobs (PCG)](cop-geometry.md#pcg-coppointsfromblobs), [COP Rasterize Curves (PCG)](cop-geometry.md#pcg-coprasterizecurves), [COP Rasterize Splats (PCG)](cop-geometry.md#pcg-coprasterizesplats), [COP Scatter Shapes (PCG)](cop-geometry.md#pcg-copscattershapes), [COP Triplanar (PCG)](cop-geometry.md#pcg-coptriplanar), [COP UV Shape (PCG)](cop-geometry.md#pcg-copuvshape), [Render Pass (PCG)](cop-geometry.md#pcg-renderpass)

## [Image: Simulation](cop-sim.md)

Reaction-diffusion, fluids, solvers and other iterative image processes.

[COP Eikonal (PCG)](cop-sim.md#pcg-copeikonal), [COP Flow Solve (PCG)](cop-sim.md#pcg-copflowsolve), [COP Ocean (PCG)](cop-sim.md#pcg-copocean), [COP Reaction Diffusion (PCG)](cop-sim.md#pcg-copreactiondiffusion), [COP Ripple (PCG)](cop-sim.md#pcg-copripple), [COP Solve Poisson (PCG)](cop-sim.md#pcg-copsolvepoisson), [COP Turing Patterns (PCG)](cop-sim.md#pcg-copturingpatterns)

## [Image: Analysis, I/O & Utility](cop-utility.md)

Statistics, import / export, sequences, devices and wrangles.

[COP Bounding Rect (PCG)](cop-utility.md#pcg-copboundingrect), [COP Compare (PCG)](cop-utility.md#pcg-copcompare), [COP Contact Sheet (PCG)](cop-utility.md#pcg-copcontactsheet), [COP Export (PCG)](cop-utility.md#pcg-copexport), [COP Flood Fill (PCG)](cop-utility.md#pcg-copfloodfill), [COP HeightField Tile Splice (PCG)](cop-utility.md#pcg-coptilesplice), [COP HeightField Tile Split (PCG)](cop-utility.md#pcg-coptilesplit), [COP Histogram Plot (PCG)](cop-utility.md#pcg-cophistogramplot), [COP Illegal Pixel (PCG)](cop-utility.md#pcg-copillegalpixel), [COP Import (PCG)](cop-utility.md#pcg-copimport), [COP Info (PCG)](cop-utility.md#pcg-copinfo), [COP Light (PCG)](cop-utility.md#pcg-coplight), [COP Prefix Sum (PCG)](cop-utility.md#pcg-copprefixsum), [COP Segment by Connectivity (PCG)](cop-utility.md#pcg-copsegment), [COP Segment By Value (PCG)](cop-utility.md#pcg-copsegmentbyvalue), [COP Sequence Clips (PCG)](cop-utility.md#pcg-copsequenceclips), [COP Sequence Ops (PCG)](cop-utility.md#pcg-copsequenceops), [COP Statistics (PCG)](cop-utility.md#pcg-copstatistics), [COP Time Pack (PCG)](cop-utility.md#pcg-coptimepack), [COP To Device (PCG)](cop-utility.md#pcg-coptodevice), [COP Vector Math (PCG)](cop-utility.md#pcg-copvectormath), [COP Vector Transform (PCG)](cop-utility.md#pcg-copvectortransform), [COP Visualize (PCG)](cop-utility.md#pcg-copvisualize), [COP Wrangle (PCG)](cop-utility.md#pcg-copwrangle), [COP Write File (PCG)](cop-utility.md#pcg-copwritefile), [Sequence Export (PCG)](cop-utility.md#pcg-sequenceexport), [Sequence Import (PCG)](cop-utility.md#pcg-sequenceimport), [Sequence Pick (PCG)](cop-utility.md#pcg-sequencepick)

## Alphabetical index

| Node | ID | Page |
|---|---|---|
| [Adaptive Prune (PCG)](scatter.md#pcg-adaptiveprune) | `PCG_AdaptivePrune` | Scatter & Copy |
| [Add (PCG)](generate.md#pcg-add) | `PCG_Add` | Generate |
| [Assemble (PCG)](scatter.md#pcg-assemble) | `PCG_Assemble` | Scatter & Copy |
| [Attribute Adjust (PCG)](attribute.md#pcg-attribadjust) | `PCG_AttribAdjust` | Attributes |
| [Attribute Adjust Color (PCG)](attribute.md#pcg-attribadjustcolor) | `PCG_AttribAdjustColor` | Attributes |
| [Attribute Adjust Float (PCG)](attribute.md#pcg-attribadjustfloat) | `PCG_AttribAdjustFloat` | Attributes |
| [Attribute Adjust Integer (PCG)](attribute.md#pcg-attribadjustinteger) | `PCG_AttribAdjustInteger` | Attributes |
| [Attribute Adjust Vector (PCG)](attribute.md#pcg-attribadjustvector) | `PCG_AttribAdjustVector` | Attributes |
| [Attribute Blur (PCG)](attribute.md#pcg-attribblur) | `PCG_AttribBlur` | Attributes |
| [Attribute Cast (PCG)](attribute.md#pcg-attribcast) | `PCG_AttribCast` | Attributes |
| [Attribute Composite (PCG)](attribute.md#pcg-attribcomposite) | `PCG_AttribComposite` | Attributes |
| [Attribute Copy (PCG)](attribute.md#pcg-attribcopy) | `PCG_AttribCopy` | Attributes |
| [Attribute Create (PCG)](attribute.md#pcg-attribcreate) | `PCG_AttribCreate` | Attributes |
| [Attribute Delete (PCG)](attribute.md#pcg-attribdelete) | `PCG_AttribDelete` | Attributes |
| [Attribute Fade (PCG)](attribute.md#pcg-attribfade) | `PCG_AttribFade` | Attributes |
| [Attribute Fade · Time (PCG)](attribute.md#pcg-attribfadetime) | `PCG_AttribFadeTime` | Attributes |
| [Attribute Fill (PCG)](attribute.md#pcg-attribfill) | `PCG_AttribFill` | Attributes |
| [Attribute from Camera (PCG)](attribute.md#pcg-attribfromcamera) | `PCG_AttribFromCamera` | Attributes |
| [Attribute from Map (PCG)](attribute.md#pcg-attribfrommap) | `PCG_AttribFromMap` | Attributes |
| [Attribute from Pieces (PCG)](attribute.md#pcg-attribfrompieces) | `PCG_AttribFromPieces` | Attributes |
| [Attribute from Volume (PCG)](attribute.md#pcg-attribfromvolume) | `PCG_AttribFromVolume` | Attributes |
| [Attribute Interpolate (PCG)](attribute.md#pcg-attribinterpolate) | `PCG_AttribInterpolate` | Attributes |
| [Attribute Mirror (PCG)](attribute.md#pcg-attribmirror) | `PCG_AttribMirror` | Attributes |
| [Attribute Noise (PCG)](attribute.md#pcg-attribnoise) | `PCG_AttribNoise` | Attributes |
| [Attribute Promote (PCG)](attribute.md#pcg-attribpromote) | `PCG_AttribPromote` | Attributes |
| [Attribute Randomize (PCG)](attribute.md#pcg-attribrandomize) | `PCG_AttribRandomize` | Attributes |
| [Attribute Rename (PCG)](attribute.md#pcg-attribrename) | `PCG_AttribRename` | Attributes |
| [Attribute Reorient (PCG)](attribute.md#pcg-attribreorient) | `PCG_AttribReorient` | Attributes |
| [Attribute String Edit (PCG)](attribute.md#pcg-attribstringedit) | `PCG_AttribStringEdit` | Attributes |
| [Attribute Transfer (PCG)](attribute.md#pcg-attribtransfer) | `PCG_AttribTransfer` | Attributes |
| [Attribute Transfer by UV (PCG)](attribute.md#pcg-attribtransferbyuv) | `PCG_AttribTransferByUV` | Attributes |
| [Attribute Transform Extract (PCG)](attribute.md#pcg-attribtransformextract) | `PCG_AttribTransformExtract` | Attributes |
| [Attribute Transform Extract · Houdini (PCG)](attribute.md#pcg-attribtransformextracthou) | `PCG_AttribTransformExtractHou` | Attributes |
| [Ballistic Path (PCG)](generate.md#pcg-ballisticpath) | `PCG_BallisticPath` | Generate |
| [Blast (PCG)](modify.md#pcg-blast) | `PCG_Blast` | Modify |
| [Blast by Attribute (PCG)](modify.md#pcg-blastbyattribute) | `PCG_BlastByAttribute` | Modify |
| [Blend Shapes (PCG)](deform.md#pcg-blendshapes) | `PCG_BlendShapes` | Deform |
| [Boolean (PCG)](modify.md#pcg-boolean) | `PCG_Boolean` | Modify |
| [Boolean Fracture (PCG)](modify.md#pcg-booleanfracture) | `PCG_BooleanFracture` | Modify |
| [Bound (PCG)](modify.md#pcg-bound) | `PCG_Bound` | Modify |
| [Box (PCG)](generate.md#pcg-box) | `PCG_Box` | Generate |
| [Bulge (PCG)](deform.md#pcg-bulge) | `PCG_Bulge` | Deform |
| [Camera (PCG)](render.md#pcg-camera) | `PCG_Camera` | Render & View |
| [Camera from Points (PCG)](render.md#pcg-camerafrompoints) | `PCG_CameraFromPoints` | Render & View |
| [Camera Path (PCG)](render.md#pcg-camerapath) | `PCG_CameraPath` | Render & View |
| [Camera Pick (PCG)](render.md#pcg-camerapick) | `PCG_CameraPick` | Render & View |
| [Camera To Points (PCG)](render.md#pcg-cameratopoints) | `PCG_CameraToPoints` | Render & View |
| [Carve (PCG)](modify.md#pcg-carve) | `PCG_Carve` | Modify |
| [Chain (PCG)](scatter.md#pcg-chain) | `PCG_Chain` | Scatter & Copy |
| [Channel (PCG)](param.md#pcg-channel) | `PCG_Channel` | Parameters & Expressions |
| [Channel XYZ (PCG)](param.md#pcg-channel3) | `PCG_Channel3` | Parameters & Expressions |
| [Circle (PCG)](generate.md#pcg-circle) | `PCG_Circle` | Generate |
| [Circle from Edges (PCG)](modify.md#pcg-circlefromedges) | `PCG_CircleFromEdges` | Modify |
| [Circle Spline (PCG)](modify.md#pcg-circlespline) | `PCG_CircleSpline` | Modify |
| [Clean (PCG)](modify.md#pcg-clean) | `PCG_Clean` | Modify |
| [Clip (PCG)](modify.md#pcg-clip) | `PCG_Clip` | Modify |
| [Cluster Points (PCG)](attribute.md#pcg-clusterpoints) | `PCG_ClusterPoints` | Attributes |
| [Color (PCG)](attribute.md#pcg-color) | `PCG_Color` | Attributes |
| [Connect Adjacent Pieces (PCG)](topology.md#pcg-connectadjacentpieces) | `PCG_ConnectAdjacentPieces` | Topology |
| [Connectivity (PCG)](topology.md#pcg-connectivity) | `PCG_Connectivity` | Topology |
| [Control Image (PCG)](cop-layers.md#pcg-controlimage) | `PCG_ControlImage` | Image: Channels & Layers |
| [Convert (PCG)](modify.md#pcg-convert) | `PCG_Convert` | Modify |
| [Convert Line (PCG)](convert.md#pcg-convertline) | `PCG_ConvertLine` | Convert |
| [Convert VDB (PCG)](volume.md#pcg-convertvdb) | `PCG_ConvertVDB` | Volumes & VDB |
| [Convex Decompose (PCG)](modify.md#pcg-convexdecompose) | `PCG_ConvexDecompose` | Modify |
| [Convex Hull (PCG)](modify.md#pcg-convexhull) | `PCG_ConvexHull` | Modify |
| [COP Align (PCG)](cop-transform.md#pcg-copalign) | `PCG_COPAlign` | Image: Transform & Warp |
| [COP Align Pixels (PCG)](cop-transform.md#pcg-copalignpixels) | `PCG_COPAlignPixels` | Image: Transform & Warp |
| [COP Align Window (PCG)](cop-transform.md#pcg-copalignwindow) | `PCG_COPAlignWindow` | Image: Transform & Warp |
| [COP Bake Textures (PCG)](cop-geometry.md#pcg-copbaketextures) | `PCG_COPBakeTextures` | Image: Geometry and Images |
| [COP Bend (PCG)](cop-transform.md#pcg-copbend) | `PCG_COPBend` | Image: Transform & Warp |
| [COP Blur (PCG)](cop-filter.md#pcg-copblur) | `PCG_COPBlur` | Image: Filters |
| [COP Bounding Rect (PCG)](cop-utility.md#pcg-copboundingrect) | `PCG_COPBoundingRect` | Image: Analysis, I/O & Utility |
| [COP Cellular Noise (PCG)](cop-generate.md#pcg-copcellularnoise) | `PCG_COPCellularNoise` | Image: Generators |
| [COP Channel Convert (PCG)](cop-layers.md#pcg-copchannelconvert) | `PCG_COPChannelConvert` | Image: Channels & Layers |
| [COP Channel Join (PCG)](cop-layers.md#pcg-copchanneljoin) | `PCG_COPChannelJoin` | Image: Channels & Layers |
| [COP Channel Split (PCG)](cop-layers.md#pcg-copchannelsplit) | `PCG_COPChannelSplit` | Image: Channels & Layers |
| [COP Chroma Key (PCG)](cop-color.md#pcg-copchromakey) | `PCG_COPChromaKey` | Image: Color & Levels |
| [COP Chromatic Aberration (PCG)](cop-transform.md#pcg-copchromaticaberration) | `PCG_COPChromaticAberration` | Image: Transform & Warp |
| [COP Clamp (PCG)](cop-color.md#pcg-copclamp) | `PCG_COPClamp` | Image: Color & Levels |
| [COP Color Correct (PCG)](cop-color.md#pcg-copcolorcorrect) | `PCG_COPColorCorrect` | Image: Color & Levels |
| [COP Combine Normals (PCG)](cop-composite.md#pcg-copcombinenormals) | `PCG_COPCombineNormals` | Image: Compositing & Masks |
| [COP Compare (PCG)](cop-utility.md#pcg-copcompare) | `PCG_COPCompare` | Image: Analysis, I/O & Utility |
| [COP Compare Mask (PCG)](cop-composite.md#pcg-copcomparemask) | `PCG_COPCompareMask` | Image: Compositing & Masks |
| [COP Composite (PCG)](cop-composite.md#pcg-copcomposite) | `PCG_COPComposite` | Image: Compositing & Masks |
| [COP Configure Stamps (PCG)](cop-geometry.md#pcg-copconfigurestamps) | `PCG_COPConfigureStamps` | Image: Geometry and Images |
| [COP Constant (PCG)](cop-generate.md#pcg-copconstant) | `PCG_COPConstant` | Image: Generators |
| [COP Contact Sheet (PCG)](cop-utility.md#pcg-copcontactsheet) | `PCG_COPContactSheet` | Image: Analysis, I/O & Utility |
| [COP Contour (PCG)](cop-filter.md#pcg-copcontour) | `PCG_COPContour` | Image: Filters |
| [COP Convert Depth (PCG)](cop-layers.md#pcg-copconvertdepth) | `PCG_COPConvertDepth` | Image: Channels & Layers |
| [COP Convert Normal (PCG)](cop-layers.md#pcg-copconvertnormal) | `PCG_COPConvertNormal` | Image: Channels & Layers |
| [COP Convolve (PCG)](cop-filter.md#pcg-copconvolve) | `PCG_COPConvolve` | Image: Filters |
| [COP Copy Transform (PCG)](cop-transform.md#pcg-copcopytransform) | `PCG_COPCopyTransform` | Image: Transform & Warp |
| [COP Corner Detect (PCG)](cop-filter.md#pcg-copcornerdetect) | `PCG_COPCornerDetect` | Image: Filters |
| [COP Corner Pin (PCG)](cop-transform.md#pcg-copcornerpin) | `PCG_COPCornerPin` | Image: Transform & Warp |
| [COP Crop / Pad (PCG)](cop-transform.md#pcg-copcrop) | `PCG_COPCrop` | Image: Transform & Warp |
| [COP Curvature (PCG)](cop-terrain.md#pcg-copcurvature) | `PCG_COPCurvature` | Image: Height Fields & Terrain |
| [COP Defocus (PCG)](cop-filter.md#pcg-copdefocus) | `PCG_COPDefocus` | Image: Filters |
| [COP Denoise TV (PCG)](cop-filter.md#pcg-copdenoisetv) | `PCG_COPDenoiseTV` | Image: Filters |
| [COP Derivative (PCG)](cop-filter.md#pcg-copderivative) | `PCG_COPDerivative` | Image: Filters |
| [COP Despill (PCG)](cop-color.md#pcg-copdespill) | `PCG_COPDespill` | Image: Color & Levels |
| [COP Directional Blur (PCG)](cop-filter.md#pcg-copdirectionalblur) | `PCG_COPDirectionalBlur` | Image: Filters |
| [COP Distort (PCG)](cop-transform.md#pcg-copdistort) | `PCG_COPDistort` | Image: Transform & Warp |
| [COP Dither (PCG)](cop-filter.md#pcg-copdither) | `PCG_COPDither` | Image: Filters |
| [COP Drop Shadow (PCG)](cop-composite.md#pcg-copdropshadow) | `PCG_COPDropShadow` | Image: Compositing & Masks |
| [COP Edge Detect (PCG)](cop-filter.md#pcg-copedge) | `PCG_COPEdge` | Image: Filters |
| [COP Edge Detect Probe (PCG)](cop-filter.md#pcg-copedgedetectprobe) | `PCG_COPEdgeDetectProbe` | Image: Filters |
| [COP Eikonal (PCG)](cop-sim.md#pcg-copeikonal) | `PCG_COPEikonal` | Image: Simulation |
| [COP Equalize (PCG)](cop-color.md#pcg-copequalize) | `PCG_COPEqualize` | Image: Color & Levels |
| [COP Erode / Dilate (PCG)](cop-filter.md#pcg-copmorph) | `PCG_COPMorph` | Image: Filters |
| [COP Erosion Filter (PCG)](cop-terrain.md#pcg-coperosion) | `PCG_COPErosion` | Image: Height Fields & Terrain |
| [COP Export (PCG)](cop-utility.md#pcg-copexport) | `PCG_COPExport` | Image: Analysis, I/O & Utility |
| [COP Extrapolate Boundaries (PCG)](cop-filter.md#pcg-copextrapolateboundaries) | `PCG_COPExtrapolateBoundaries` | Image: Filters |
| [COP Feather (PCG)](cop-filter.md#pcg-copfeather) | `PCG_COPFeather` | Image: Filters |
| [COP Feather Slope (PCG)](cop-filter.md#pcg-copfeatherslope) | `PCG_COPFeatherSlope` | Image: Filters |
| [COP FFT (PCG)](cop-filter.md#pcg-copfft) | `PCG_COPFFT` | Image: Filters |
| [COP Fill (PCG)](cop-generate.md#pcg-copfill) | `PCG_COPFill` | Image: Generators |
| [COP Fit (PCG)](cop-color.md#pcg-copfit) | `PCG_COPFit` | Image: Color & Levels |
| [COP Flip (PCG)](cop-transform.md#pcg-copflip) | `PCG_COPFlip` | Image: Transform & Warp |
| [COP Flood Fill (PCG)](cop-utility.md#pcg-copfloodfill) | `PCG_COPFloodFill` | Image: Analysis, I/O & Utility |
| [COP Flow Accumulation (PCG)](cop-terrain.md#pcg-copflowaccumulation) | `PCG_COPFlowAccumulation` | Image: Height Fields & Terrain |
| [COP Flow Solve (PCG)](cop-sim.md#pcg-copflowsolve) | `PCG_COPFlowSolve` | Image: Simulation |
| [COP Fractal Sample (PCG)](cop-generate.md#pcg-copfractalsample) | `PCG_COPFractalSample` | Image: Generators |
| [COP Function (PCG)](cop-color.md#pcg-copfunction) | `PCG_COPFunction` | Image: Color & Levels |
| [COP Geometry to Layer (PCG)](cop-geometry.md#pcg-copgeotolayer) | `PCG_COPGeoToLayer` | Image: Geometry and Images |
| [COP Glow (PCG)](cop-filter.md#pcg-copglow) | `PCG_COPGlow` | Image: Filters |
| [COP Gradient (PCG)](cop-generate.md#pcg-copgradient) | `PCG_COPGradient` | Image: Generators |
| [COP Heat Distort (PCG)](cop-transform.md#pcg-copheatdistort) | `PCG_COPHeatDistort` | Image: Transform & Warp |
| [COP Heat Distort by Layer (PCG)](cop-transform.md#pcg-copheatdistortbylayer) | `PCG_COPHeatDistortByLayer` | Image: Transform & Warp |
| [COP Height to AO (PCG)](cop-terrain.md#pcg-copheighttoao) | `PCG_COPHeightToAO` | Image: Height Fields & Terrain |
| [COP Height to Caustics (PCG)](cop-terrain.md#pcg-copheighttocaustics) | `PCG_COPHeightToCaustics` | Image: Height Fields & Terrain |
| [COP Height to Normal (PCG)](cop-terrain.md#pcg-copheighttonormal) | `PCG_COPHeightToNormal` | Image: Height Fields & Terrain |
| [COP Height to Shadow (PCG)](cop-terrain.md#pcg-copheighttoshadow) | `PCG_COPHeightToShadow` | Image: Height Fields & Terrain |
| [COP HeightField Clip (PCG)](cop-terrain.md#pcg-cophfclip) | `PCG_COPHFClip` | Image: Height Fields & Terrain |
| [COP HeightField Cutout by Object (PCG)](cop-terrain.md#pcg-cophfcutoutbyobject) | `PCG_COPHFCutoutByObject` | Image: Height Fields & Terrain |
| [COP HeightField Erode (PCG)](cop-terrain.md#pcg-copheightfielderode) | `PCG_COPHeightfieldErode` | Image: Height Fields & Terrain |
| [COP HeightField from Depth (PCG)](cop-terrain.md#pcg-copheightfieldfromdepth) | `PCG_COPHeightfieldFromDepth` | Image: Height Fields & Terrain |
| [COP HeightField Hydraulic Erosion (PCG)](cop-terrain.md#pcg-cophydraulicerosion) | `PCG_COPHydraulicErosion` | Image: Height Fields & Terrain |
| [COP HeightField Mask by Feature (PCG)](cop-terrain.md#pcg-copmaskbyfeature) | `PCG_COPMaskByFeature` | Image: Height Fields & Terrain |
| [COP HeightField Mask by Object (PCG)](cop-terrain.md#pcg-cophfmaskbyobject) | `PCG_COPHFMaskByObject` | Image: Height Fields & Terrain |
| [COP HeightField Project (PCG)](cop-terrain.md#pcg-cophfproject) | `PCG_COPHFProject` | Image: Height Fields & Terrain |
| [COP HeightField Splat Map (PCG)](cop-terrain.md#pcg-copsplatmap) | `PCG_COPSplatMap` | Image: Height Fields & Terrain |
| [COP HeightField Stream Power Erosion (PCG)](cop-terrain.md#pcg-copstreampower) | `PCG_COPStreamPower` | Image: Height Fields & Terrain |
| [COP HeightField Terrace (PCG)](cop-terrain.md#pcg-copterrace) | `PCG_COPTerrace` | Image: Height Fields & Terrain |
| [COP HeightField Thermal Erosion (PCG)](cop-terrain.md#pcg-copthermalerosion) | `PCG_COPThermalErosion` | Image: Height Fields & Terrain |
| [COP HeightField Tile Splice (PCG)](cop-utility.md#pcg-coptilesplice) | `PCG_COPTileSplice` | Image: Analysis, I/O & Utility |
| [COP HeightField Tile Split (PCG)](cop-utility.md#pcg-coptilesplit) | `PCG_COPTileSplit` | Image: Analysis, I/O & Utility |
| [COP HeightField to Mesh (PCG)](cop-geometry.md#pcg-copheightfieldtomesh) | `PCG_COPHeightfieldToMesh` | Image: Geometry and Images |
| [COP Hex Tile (PCG)](cop-transform.md#pcg-cophextile) | `PCG_COPHexTile` | Image: Transform & Warp |
| [COP Histogram (PCG)](cop-color.md#pcg-cophistogram) | `PCG_COPHistogram` | Image: Color & Levels |
| [COP Histogram Plot (PCG)](cop-utility.md#pcg-cophistogramplot) | `PCG_COPHistogramPlot` | Image: Analysis, I/O & Utility |
| [COP ID Convert (PCG)](cop-layers.md#pcg-copidconvert) | `PCG_COPIDConvert` | Image: Channels & Layers |
| [COP Illegal Pixel (PCG)](cop-utility.md#pcg-copillegalpixel) | `PCG_COPIllegalPixel` | Image: Analysis, I/O & Utility |
| [COP Import (PCG)](cop-utility.md#pcg-copimport) | `PCG_COPImport` | Image: Analysis, I/O & Utility |
| [COP Info (PCG)](cop-utility.md#pcg-copinfo) | `PCG_COPInfo` | Image: Analysis, I/O & Utility |
| [COP Integrate Volume (PCG)](cop-geometry.md#pcg-copintegratevolume) | `PCG_COPIntegrateVolume` | Image: Geometry and Images |
| [COP Invert (PCG)](cop-color.md#pcg-copinvert) | `PCG_COPInvert` | Image: Color & Levels |
| [COP Kuwahara (PCG)](cop-filter.md#pcg-copkuwahara) | `PCG_COPKuwahara` | Image: Filters |
| [COP Lattice Deform (PCG)](cop-transform.md#pcg-coplatticedeform) | `PCG_COPLatticeDeform` | Image: Transform & Warp |
| [COP Layer Combine (PCG)](cop-composite.md#pcg-coplayercombine) | `PCG_COPLayerCombine` | Image: Compositing & Masks |
| [COP Layer Edit (PCG)](cop-layers.md#pcg-coplayeredit) | `PCG_COPLayerEdit` | Image: Channels & Layers |
| [COP Layer from Attribute (PCG)](cop-geometry.md#pcg-coplayerfromattrib) | `PCG_COPLayerFromAttrib` | Image: Geometry and Images |
| [COP Layer Merge (PCG)](cop-layers.md#pcg-coplayermerge) | `PCG_COPLayerMerge` | Image: Channels & Layers |
| [COP Layer To Points (PCG)](cop-geometry.md#pcg-coplayertopoints) | `PCG_COPLayerToPoints` | Image: Geometry and Images |
| [COP Lens Distort (PCG)](cop-transform.md#pcg-coplensdistort) | `PCG_COPLensDistort` | Image: Transform & Warp |
| [COP Levels (PCG)](cop-color.md#pcg-coplevels) | `PCG_COPLevels` | Image: Color & Levels |
| [COP Light (PCG)](cop-utility.md#pcg-coplight) | `PCG_COPLight` | Image: Analysis, I/O & Utility |
| [COP Logic (PCG)](cop-composite.md#pcg-coplogic) | `PCG_COPLogic` | Image: Compositing & Masks |
| [COP Luminance (PCG)](cop-layers.md#pcg-copluminance) | `PCG_COPLuminance` | Image: Channels & Layers |
| [COP Mask Combine (PCG)](cop-composite.md#pcg-copmaskcombine) | `PCG_COPMaskCombine` | Image: Compositing & Masks |
| [COP Median (PCG)](cop-filter.md#pcg-copmedian) | `PCG_COPMedian` | Image: Filters |
| [COP Mirror (PCG)](cop-transform.md#pcg-copmirror) | `PCG_COPMirror` | Image: Transform & Warp |
| [COP Mono to HeightField (PCG)](cop-terrain.md#pcg-copmonotoheightfield) | `PCG_COPMonoToHeightField` | Image: Height Fields & Terrain |
| [COP Mono to RGB (PCG)](cop-color.md#pcg-copmonotorgb) | `PCG_COPMonoToRGB` | Image: Color & Levels |
| [COP Noise (PCG)](cop-generate.md#pcg-copnoise) | `PCG_COPNoise` | Image: Generators |
| [COP Noise Extra (PCG)](cop-generate.md#pcg-copnoiseextra) | `PCG_COPNoiseExtra` | Image: Generators |
| [COP Normal to Height (PCG)](cop-terrain.md#pcg-copnormaltoheight) | `PCG_COPNormalToHeight` | Image: Height Fields & Terrain |
| [COP Ocean (PCG)](cop-sim.md#pcg-copocean) | `PCG_COPOcean` | Image: Simulation |
| [COP Pattern (PCG)](cop-generate.md#pcg-coppattern) | `PCG_COPPattern` | Image: Generators |
| [COP Pixelate (PCG)](cop-filter.md#pcg-coppixelate) | `PCG_COPPixelate` | Image: Filters |
| [COP Planar Inflate (PCG)](cop-geometry.md#pcg-copplanarinflate) | `PCG_COPPlanarInflate` | Image: Geometry and Images |
| [COP Point Generate (PCG)](cop-geometry.md#pcg-coppointgenerate) | `PCG_COPPointGenerate` | Image: Geometry and Images |
| [COP Points From Blobs (PCG)](cop-geometry.md#pcg-coppointsfromblobs) | `PCG_COPPointsFromBlobs` | Image: Geometry and Images |
| [COP Polar (PCG)](cop-transform.md#pcg-coppolar) | `PCG_COPPolar` | Image: Transform & Warp |
| [COP Polar Coords (PCG)](cop-transform.md#pcg-coppolarcoords) | `PCG_COPPolarCoords` | Image: Transform & Warp |
| [COP Position Map (PCG)](cop-generate.md#pcg-coppositionmap) | `PCG_COPPositionMap` | Image: Generators |
| [COP Prefix Sum (PCG)](cop-utility.md#pcg-copprefixsum) | `PCG_COPPrefixSum` | Image: Analysis, I/O & Utility |
| [COP Premultiply (PCG)](cop-composite.md#pcg-coppremultiply) | `PCG_COPPremultiply` | Image: Compositing & Masks |
| [COP Quantize (PCG)](cop-color.md#pcg-copquantize) | `PCG_COPQuantize` | Image: Color & Levels |
| [COP Random (PCG)](cop-generate.md#pcg-coprandom) | `PCG_COPRandom` | Image: Generators |
| [COP Rasterize Curves (PCG)](cop-geometry.md#pcg-coprasterizecurves) | `PCG_COPRasterizeCurves` | Image: Geometry and Images |
| [COP Rasterize Splats (PCG)](cop-geometry.md#pcg-coprasterizesplats) | `PCG_COPRasterizeSplats` | Image: Geometry and Images |
| [COP Reaction Diffusion (PCG)](cop-sim.md#pcg-copreactiondiffusion) | `PCG_COPReactionDiffusion` | Image: Simulation |
| [COP Refract from Height (PCG)](cop-transform.md#pcg-coprefractfromheight) | `PCG_COPRefractFromHeight` | Image: Transform & Warp |
| [COP Remap (PCG)](cop-color.md#pcg-copremap) | `PCG_COPRemap` | Image: Color & Levels |
| [COP Resize (PCG)](cop-transform.md#pcg-copresize) | `PCG_COPResize` | Image: Transform & Warp |
| [COP Retile (PCG)](cop-transform.md#pcg-copretile) | `PCG_COPRetile` | Image: Transform & Warp |
| [COP Ripple (PCG)](cop-sim.md#pcg-copripple) | `PCG_COPRipple` | Image: Simulation |
| [COP Scatter Shapes (PCG)](cop-geometry.md#pcg-copscattershapes) | `PCG_COPScatterShapes` | Image: Geometry and Images |
| [COP SDF from Mask (PCG)](cop-filter.md#pcg-copsdffrommask) | `PCG_COPSDFFromMask` | Image: Filters |
| [COP SDF Ops (PCG)](cop-filter.md#pcg-copsdfops) | `PCG_COPSDFOps` | Image: Filters |
| [COP Segment by Connectivity (PCG)](cop-utility.md#pcg-copsegment) | `PCG_COPSegment` | Image: Analysis, I/O & Utility |
| [COP Segment By Value (PCG)](cop-utility.md#pcg-copsegmentbyvalue) | `PCG_COPSegmentByValue` | Image: Analysis, I/O & Utility |
| [COP Select (PCG)](cop-composite.md#pcg-copselect) | `PCG_COPSelect` | Image: Compositing & Masks |
| [COP Sequence Clips (PCG)](cop-utility.md#pcg-copsequenceclips) | `PCG_COPSequenceClips` | Image: Analysis, I/O & Utility |
| [COP Sequence Ops (PCG)](cop-utility.md#pcg-copsequenceops) | `PCG_COPSequenceOps` | Image: Analysis, I/O & Utility |
| [COP Shape (PCG)](cop-generate.md#pcg-copshape) | `PCG_COPShape` | Image: Generators |
| [COP Sharpen (PCG)](cop-filter.md#pcg-copsharpen) | `PCG_COPSharpen` | Image: Filters |
| [COP Slope & Aspect (PCG)](cop-terrain.md#pcg-copslope) | `PCG_COPSlope` | Image: Height Fields & Terrain |
| [COP Smooth Fill (PCG)](cop-filter.md#pcg-copsmoothfill) | `PCG_COPSmoothFill` | Image: Filters |
| [COP Solve Poisson (PCG)](cop-sim.md#pcg-copsolvepoisson) | `PCG_COPSolvePoisson` | Image: Simulation |
| [COP Space Transform (PCG)](cop-transform.md#pcg-copspacetransform) | `PCG_COPSpaceTransform` | Image: Transform & Warp |
| [COP Sphere Sample (PCG)](cop-transform.md#pcg-copspheresample) | `PCG_COPSphereSample` | Image: Transform & Warp |
| [COP Statistics (PCG)](cop-utility.md#pcg-copstatistics) | `PCG_COPStatistics` | Image: Analysis, I/O & Utility |
| [COP Stereogram (PCG)](cop-generate.md#pcg-copstereogram) | `PCG_COPStereogram` | Image: Generators |
| [COP Strata (PCG)](cop-terrain.md#pcg-copstrata) | `PCG_COPStrata` | Image: Height Fields & Terrain |
| [COP Surface Dither (PCG)](cop-filter.md#pcg-copsurfacedither) | `PCG_COPSurfaceDither` | Image: Filters |
| [COP Swirl (PCG)](cop-transform.md#pcg-copswirl) | `PCG_COPSwirl` | Image: Transform & Warp |
| [COP Swizzle (PCG)](cop-layers.md#pcg-copswizzle) | `PCG_COPSwizzle` | Image: Channels & Layers |
| [COP Text (PCG)](cop-generate.md#pcg-coptext) | `PCG_COPText` | Image: Generators |
| [COP Tile (PCG)](cop-transform.md#pcg-coptile) | `PCG_COPTile` | Image: Transform & Warp |
| [COP Time Pack (PCG)](cop-utility.md#pcg-coptimepack) | `PCG_COPTimePack` | Image: Analysis, I/O & Utility |
| [COP To Device (PCG)](cop-utility.md#pcg-coptodevice) | `PCG_COPToDevice` | Image: Analysis, I/O & Utility |
| [COP Tone Map (PCG)](cop-color.md#pcg-coptonemap) | `PCG_COPToneMap` | Image: Color & Levels |
| [COP Transform (PCG)](cop-transform.md#pcg-coptransform) | `PCG_COPTransform` | Image: Transform & Warp |
| [COP Transform 3D (PCG)](cop-transform.md#pcg-coptransform3d) | `PCG_COPTransform3D` | Image: Transform & Warp |
| [COP Triplanar (PCG)](cop-geometry.md#pcg-coptriplanar) | `PCG_COPTriplanar` | Image: Geometry and Images |
| [COP Turing Patterns (PCG)](cop-sim.md#pcg-copturingpatterns) | `PCG_COPTuringPatterns` | Image: Simulation |
| [COP UV Inverse (PCG)](cop-transform.md#pcg-copuvinverse) | `PCG_COPUVInverse` | Image: Transform & Warp |
| [COP UV Map (PCG)](cop-transform.md#pcg-copuvmap) | `PCG_COPUVMap` | Image: Transform & Warp |
| [COP UV Sample (PCG)](cop-transform.md#pcg-copuvsample) | `PCG_COPUVSample` | Image: Transform & Warp |
| [COP UV Shape (PCG)](cop-geometry.md#pcg-copuvshape) | `PCG_COPUVShape` | Image: Geometry and Images |
| [COP UV Transform (PCG)](cop-transform.md#pcg-copuvtransform) | `PCG_COPUVTransform` | Image: Transform & Warp |
| [COP Vector Math (PCG)](cop-utility.md#pcg-copvectormath) | `PCG_COPVectorMath` | Image: Analysis, I/O & Utility |
| [COP Vector Transform (PCG)](cop-utility.md#pcg-copvectortransform) | `PCG_COPVectorTransform` | Image: Analysis, I/O & Utility |
| [COP Vignette (PCG)](cop-color.md#pcg-copvignette) | `PCG_COPVignette` | Image: Color & Levels |
| [COP Visualize (PCG)](cop-utility.md#pcg-copvisualize) | `PCG_COPVisualize` | Image: Analysis, I/O & Utility |
| [COP Warp (PCG)](cop-transform.md#pcg-copwarp) | `PCG_COPWarp` | Image: Transform & Warp |
| [COP Wipe (PCG)](cop-composite.md#pcg-copwipe) | `PCG_COPWipe` | Image: Compositing & Masks |
| [COP Worley Noise (PCG)](cop-generate.md#pcg-copworleynoise) | `PCG_COPWorleyNoise` | Image: Generators |
| [COP Wrangle (PCG)](cop-utility.md#pcg-copwrangle) | `PCG_COPWrangle` | Image: Analysis, I/O & Utility |
| [COP Write File (PCG)](cop-utility.md#pcg-copwritefile) | `PCG_COPWriteFile` | Image: Analysis, I/O & Utility |
| [Copy and Transform (PCG)](scatter.md#pcg-copyandtransform) | `PCG_CopyAndTransform` | Scatter & Copy |
| [Copy to Curves (PCG)](scatter.md#pcg-copytocurves) | `PCG_CopyToCurves` | Scatter & Copy |
| [Copy to Points (PCG)](scatter.md#pcg-copytopoints) | `PCG_CopyToPoints` | Scatter & Copy |
| [Crease (PCG)](modify.md#pcg-crease) | `PCG_Crease` | Modify |
| [Cross Section Surface (PCG)](generate.md#pcg-crosssectionsurface) | `PCG_CrossSectionSurface` | Generate |
| [Cross Section Surface · Houdini (PCG)](generate.md#pcg-crosssectionsurfacehou) | `PCG_CrossSectionSurfaceHou` | Generate |
| [Curve (PCG)](generate.md#pcg-curve) | `PCG_Curve` | Generate |
| [Curve Fillet (PCG)](modify.md#pcg-curvefillet) | `PCG_CurveFillet` | Modify |
| [Curve Intersect (PCG)](modify.md#pcg-curveintersect) | `PCG_CurveIntersect` | Modify |
| [Delete (PCG)](modify.md#pcg-delete) | `PCG_Delete` | Modify |
| [DeltaMush (PCG)](deform.md#pcg-deltamush) | `PCG_DeltaMush` | Deform |
| [Displace from Map (PCG)](deform.md#pcg-displacefrommap) | `PCG_DisplaceFromMap` | Deform |
| [Display (PCG)](output.md#pcg-display) | `PCG_Display` | Output & Export |
| [Dissolve (PCG)](modify.md#pcg-dissolve) | `PCG_Dissolve` | Modify |
| [Distance along Geometry (PCG)](attribute.md#pcg-distancealonggeometry) | `PCG_DistanceAlongGeometry` | Attributes |
| [Distance from Geometry (PCG)](attribute.md#pcg-distancefromgeometry) | `PCG_DistanceFromGeometry` | Attributes |
| [Divide (PCG)](modify.md#pcg-divide) | `PCG_Divide` | Modify |
| [Edge Collapse (PCG)](modify.md#pcg-edgecollapse) | `PCG_EdgeCollapse` | Modify |
| [Edge Cusp (PCG)](topology.md#pcg-edgecusp) | `PCG_EdgeCusp` | Topology |
| [Edge Divide (PCG)](modify.md#pcg-edgedivide) | `PCG_EdgeDivide` | Modify |
| [Edge Equalize (PCG)](modify.md#pcg-edgeequalize) | `PCG_EdgeEqualize` | Modify |
| [Edge Flip (PCG)](topology.md#pcg-edgeflip) | `PCG_EdgeFlip` | Topology |
| [Edge Group Promote (PCG)](group.md#pcg-edgegrouppromote) | `PCG_EdgeGroupPromote` | Groups |
| [Edge Straighten (PCG)](modify.md#pcg-edgestraighten) | `PCG_EdgeStraighten` | Modify |
| [Edge Transport (PCG)](attribute.md#pcg-edgetransport) | `PCG_EdgeTransport` | Attributes |
| [Ends (PCG)](modify.md#pcg-ends) | `PCG_Ends` | Modify |
| [Enumerate (PCG)](attribute.md#pcg-enumerate) | `PCG_Enumerate` | Attributes |
| [Exploded View (PCG)](modify.md#pcg-explodedview) | `PCG_ExplodedView` | Modify |
| [Export Instances (PCG)](output.md#pcg-exportinstances) | `PCG_ExportInstances` | Output & Export |
| [Export Mesh (PCG)](output.md#pcg-exportmesh) | `PCG_ExportMesh` | Output & Export |
| [Expression (PCG)](param.md#pcg-expr) | `PCG_Expr` | Parameters & Expressions |
| [Expression XYZ (PCG)](param.md#pcg-expr3) | `PCG_Expr3` | Parameters & Expressions |
| [Extract Centroid (PCG)](attribute.md#pcg-extractcentroid) | `PCG_ExtractCentroid` | Attributes |
| [Extract Silhouette (PCG)](generate.md#pcg-extractsilhouette) | `PCG_ExtractSilhouette` | Generate |
| [Extract Transform (PCG)](modify.md#pcg-extracttransform) | `PCG_ExtractTransform` | Modify |
| [Facet (PCG)](modify.md#pcg-facet) | `PCG_Facet` | Modify |
| [File Cache (PCG)](output.md#pcg-filecache) | `PCG_FileCache` | Output & Export |
| [File Merge (PCG)](convert.md#pcg-filemerge) | `PCG_FileMerge` | Convert |
| [Find Shortest Path (PCG)](topology.md#pcg-findshortestpath) | `PCG_FindShortestPath` | Topology |
| [Font (PCG)](generate.md#pcg-font) | `PCG_Font` | Generate |
| [For-Each Begin (PCG)](loop.md#pcg-foreachbegin) | `PCG_ForEachBegin` | Loops |
| [For-Each End (PCG)](loop.md#pcg-foreachend) | `PCG_ForEachEnd` | Loops |
| [For-Each Frame Begin (PCG)](loop.md#pcg-foreachframebegin) | `PCG_ForEachFrameBegin` | Loops |
| [For-Each Frame End (PCG)](loop.md#pcg-foreachframeend) | `PCG_ForEachFrameEnd` | Loops |
| [Fractal (PCG)](deform.md#pcg-fractal) | `PCG_Fractal` | Deform |
| [Fracture Detail (PCG)](modify.md#pcg-fracturedetail) | `PCG_FractureDetail` | Modify |
| [Frame (PCG)](param.md#pcg-frame) | `PCG_Frame` | Parameters & Expressions |
| [From JSON (PCG)](convert.md#pcg-fromjson) | `PCG_FromJSON` | Convert |
| [Fuse (PCG)](modify.md#pcg-fuse) | `PCG_Fuse` | Modify |
| [Geo Metrics (PCG)](output.md#pcg-geometrics) | `PCG_GeoMetrics` | Output & Export |
| [Geo Sequence Pick (PCG)](loop.md#pcg-geosequencepick) | `PCG_GeoSequencePick` | Loops |
| [Geo to JSON (PCG)](convert.md#pcg-geotojson) | `PCG_GeoToJSON` | Convert |
| [Geometry Preview (PCG)](output.md#pcg-previewimage) | `PCG_PreviewImage` | Output & Export |
| [Geometry Spreadsheet (PCG)](output.md#pcg-geospreadsheet) | `PCG_GeoSpreadsheet` | Output & Export |
| [Grid (PCG)](generate.md#pcg-grid) | `PCG_Grid` | Generate |
| [Group Combine (PCG)](group.md#pcg-groupcombine) | `PCG_GroupCombine` | Groups |
| [Group Create (PCG)](group.md#pcg-groupcreate) | `PCG_GroupCreate` | Groups |
| [Group Delete (PCG)](group.md#pcg-groupdelete) | `PCG_GroupDelete` | Groups |
| [Group Edges (PCG)](group.md#pcg-groupedges) | `PCG_GroupEdges` | Groups |
| [Group Expand (PCG)](group.md#pcg-groupexpand) | `PCG_GroupExpand` | Groups |
| [Group Find Path (PCG)](group.md#pcg-groupfindpath) | `PCG_GroupFindPath` | Groups |
| [Group from Attribute Boundary (PCG)](group.md#pcg-groupfromattribboundary) | `PCG_GroupFromAttribBoundary` | Groups |
| [Group Inside (PCG)](group.md#pcg-groupinside) | `PCG_GroupInside` | Groups |
| [Group Promote (PCG)](group.md#pcg-grouppromote) | `PCG_GroupPromote` | Groups |
| [Heightfield from Image (PCG)](image.md#pcg-heightfieldfromimage) | `PCG_HeightfieldFromImage` | Image |
| [ID Masks (PCG)](cop-layers.md#pcg-idmasks) | `PCG_IDMasks` | Image: Channels & Layers |
| [Import Mesh (PCG)](convert.md#pcg-importmesh) | `PCG_ImportMesh` | Convert |
| [Intersection Analysis (PCG)](modify.md#pcg-intersectionanalysis) | `PCG_IntersectionAnalysis` | Modify |
| [IsoOffset (PCG)](generate.md#pcg-isooffset) | `PCG_IsoOffset` | Generate |
| [IsoSurface (PCG)](generate.md#pcg-isosurface) | `PCG_IsoSurface` | Generate |
| [Join (PCG)](modify.md#pcg-join) | `PCG_Join` | Modify |
| [L-System (PCG)](generate.md#pcg-lsystem) | `PCG_LSystem` | Generate |
| [Lattice (PCG)](deform.md#pcg-lattice) | `PCG_Lattice` | Deform |
| [Lattice From Bound (PCG)](deform.md#pcg-latticefrombound) | `PCG_LatticeFromBound` | Deform |
| [Line (PCG)](generate.md#pcg-line) | `PCG_Line` | Generate |
| [Loop Cut (PCG)](modify.md#pcg-loopcut) | `PCG_LoopCut` | Modify |
| [Magnet (PCG)](deform.md#pcg-magnet) | `PCG_Magnet` | Deform |
| [Match Axis (PCG)](modify.md#pcg-matchaxis) | `PCG_MatchAxis` | Modify |
| [Match Size (PCG)](modify.md#pcg-matchsize) | `PCG_MatchSize` | Modify |
| [Match Topology (PCG)](topology.md#pcg-matchtopology) | `PCG_MatchTopology` | Topology |
| [Measure (PCG)](attribute.md#pcg-measure) | `PCG_Measure` | Attributes |
| [Merge (PCG)](modify.md#pcg-merge) | `PCG_Merge` | Modify |
| [Mirror (PCG)](modify.md#pcg-mirror) | `PCG_Mirror` | Modify |
| [Motion Vectors (PCG)](render.md#pcg-motionvectors) | `PCG_MotionVectors` | Render & View |
| [Name (PCG)](attribute.md#pcg-name) | `PCG_Name` | Attributes |
| [Normal (PCG)](attribute.md#pcg-normal) | `PCG_Normal` | Attributes |
| [Orient Along Curve (PCG)](attribute.md#pcg-orientalongcurve) | `PCG_OrientAlongCurve` | Attributes |
| [Pack (PCG)](scatter.md#pcg-pack) | `PCG_Pack` | Scatter & Copy |
| [Param Pick (PCG)](param.md#pcg-parampick) | `PCG_ParamPick` | Parameters & Expressions |
| [Parameters (PCG)](param.md#pcg-parameters) | `PCG_Parameters` | Parameters & Expressions |
| [Params from JSON (PCG)](param.md#pcg-paramsfromjson) | `PCG_ParamsFromJSON` | Parameters & Expressions |
| [Partition (PCG)](group.md#pcg-partition) | `PCG_Partition` | Groups |
| [Path Deform (PCG)](deform.md#pcg-pathdeform) | `PCG_PathDeform` | Deform |
| [Peak (PCG)](modify.md#pcg-peak) | `PCG_Peak` | Modify |
| [Platonic Solids (PCG)](generate.md#pcg-platonicsolids) | `PCG_PlatonicSolids` | Generate |
| [Point Deform (PCG)](deform.md#pcg-pointdeform) | `PCG_PointDeform` | Deform |
| [Point Jitter (PCG)](modify.md#pcg-pointjitter) | `PCG_PointJitter` | Modify |
| [Point Relax (PCG)](scatter.md#pcg-pointrelax) | `PCG_PointRelax` | Scatter & Copy |
| [Point Replicate (PCG)](scatter.md#pcg-pointreplicate) | `PCG_PointReplicate` | Scatter & Copy |
| [Point Split (PCG)](modify.md#pcg-pointsplit) | `PCG_PointSplit` | Modify |
| [Point Velocity (PCG)](attribute.md#pcg-pointvelocity) | `PCG_PointVelocity` | Attributes |
| [Poly Bridge (PCG)](modify.md#pcg-polybridge) | `PCG_PolyBridge` | Modify |
| [PolyBevel (PCG)](modify.md#pcg-polybevel) | `PCG_PolyBevel` | Modify |
| [PolyCut (PCG)](topology.md#pcg-polycut) | `PCG_PolyCut` | Topology |
| [PolyDoctor (PCG)](modify.md#pcg-polydoctor) | `PCG_PolyDoctor` | Modify |
| [PolyExpand2D (PCG)](modify.md#pcg-polyexpand2d) | `PCG_PolyExpand2D` | Modify |
| [PolyExtrude (PCG)](modify.md#pcg-polyextrude) | `PCG_PolyExtrude` | Modify |
| [PolyFill (PCG)](modify.md#pcg-polyfill) | `PCG_PolyFill` | Modify |
| [PolyFrame (PCG)](attribute.md#pcg-polyframe) | `PCG_PolyFrame` | Attributes |
| [PolyLoft (PCG)](generate.md#pcg-polyloft) | `PCG_PolyLoft` | Generate |
| [PolyPath (PCG)](modify.md#pcg-polypath) | `PCG_PolyPath` | Modify |
| [PolyReduce (PCG)](modify.md#pcg-polyreduce) | `PCG_PolyReduce` | Modify |
| [PolySpline (PCG)](modify.md#pcg-polyspline) | `PCG_PolySpline` | Modify |
| [PolySplit (PCG)](topology.md#pcg-polysplit) | `PCG_PolySplit` | Topology |
| [PolyStitch (PCG)](topology.md#pcg-polystitch) | `PCG_PolyStitch` | Topology |
| [PolyWire (PCG)](generate.md#pcg-polywire) | `PCG_PolyWire` | Generate |
| [Primitive (PCG)](modify.md#pcg-primitive) | `PCG_Primitive` | Modify |
| [Primitive Split (PCG)](modify.md#pcg-primitivesplit) | `PCG_PrimitiveSplit` | Modify |
| [Ray (PCG)](modify.md#pcg-ray) | `PCG_Ray` | Modify |
| [Refine (PCG)](modify.md#pcg-refine) | `PCG_Refine` | Modify |
| [Regional Prompt from COP (PCG)](cop-layers.md#pcg-regionalprompt) | `PCG_RegionalPrompt` | Image: Channels & Layers |
| [Remesh (PCG)](modify.md#pcg-remesh) | `PCG_Remesh` | Modify |
| [Remesh to Grid (PCG)](modify.md#pcg-remeshtogrid) | `PCG_RemeshToGrid` | Modify |
| [Render Pass (PCG)](cop-geometry.md#pcg-renderpass) | `PCG_RenderPass` | Image: Geometry and Images |
| [Render Sequence (PCG)](render.md#pcg-rendersequence) | `PCG_RenderSequence` | Render & View |
| [Resample (PCG)](modify.md#pcg-resample) | `PCG_Resample` | Modify |
| [Retime (PCG)](loop.md#pcg-retime) | `PCG_Retime` | Loops |
| [Reverse (PCG)](modify.md#pcg-reverse) | `PCG_Reverse` | Modify |
| [Revolve (PCG)](generate.md#pcg-revolve) | `PCG_Revolve` | Generate |
| [Rewire Vertices (PCG)](topology.md#pcg-rewirevertices) | `PCG_RewireVertices` | Topology |
| [Scatter (PCG)](scatter.md#pcg-scatter) | `PCG_Scatter` | Scatter & Copy |
| [Scatter and Align (PCG)](scatter.md#pcg-scatteralign) | `PCG_ScatterAlign` | Scatter & Copy |
| [Scatter from Map (PCG)](scatter.md#pcg-scatterfrommap) | `PCG_ScatterFromMap` | Scatter & Copy |
| [Scatter in Volume (PCG)](scatter.md#pcg-scattervolume) | `PCG_ScatterVolume` | Scatter & Copy |
| [Select Best (PCG)](loop.md#pcg-selectbest) | `PCG_SelectBest` | Loops |
| [Sequence Export (PCG)](cop-utility.md#pcg-sequenceexport) | `PCG_SequenceExport` | Image: Analysis, I/O & Utility |
| [Sequence Import (PCG)](cop-utility.md#pcg-sequenceimport) | `PCG_SequenceImport` | Image: Analysis, I/O & Utility |
| [Sequence Motion (PCG)](render.md#pcg-sequencemotion) | `PCG_SequenceMotion` | Render & View |
| [Sequence Pick (PCG)](cop-utility.md#pcg-sequencepick) | `PCG_SequencePick` | Image: Analysis, I/O & Utility |
| [Shrinkwrap (PCG)](modify.md#pcg-shrinkwrap) | `PCG_Shrinkwrap` | Modify |
| [Skin (PCG)](generate.md#pcg-skin) | `PCG_Skin` | Generate |
| [Smooth (PCG)](modify.md#pcg-smooth) | `PCG_Smooth` | Modify |
| [Soft Peak (PCG)](deform.md#pcg-softpeak) | `PCG_SoftPeak` | Deform |
| [Soft Transform (PCG)](deform.md#pcg-softtransform) | `PCG_SoftTransform` | Deform |
| [Sort (PCG)](modify.md#pcg-sort) | `PCG_Sort` | Modify |
| [Sphere (PCG)](generate.md#pcg-sphere) | `PCG_Sphere` | Generate |
| [Spherify (PCG)](deform.md#pcg-spherify) | `PCG_Spherify` | Deform |
| [Split (PCG)](modify.md#pcg-split) | `PCG_Split` | Modify |
| [Subdivide (PCG)](modify.md#pcg-subdivide) | `PCG_Subdivide` | Modify |
| [Sweep (PCG)](generate.md#pcg-sweep) | `PCG_Sweep` | Generate |
| [Switch (PCG)](modify.md#pcg-switch) | `PCG_Switch` | Modify |
| [Switch-If (PCG)](modify.md#pcg-switchif) | `PCG_SwitchIf` | Modify |
| [Tangent Field (PCG)](attribute.md#pcg-tangentfield) | `PCG_TangentField` | Attributes |
| [Texture Render (PCG)](render.md#pcg-texturerender) | `PCG_TextureRender` | Render & View |
| [Thicken (PCG)](modify.md#pcg-thicken) | `PCG_Thicken` | Modify |
| [Time Blend (PCG)](loop.md#pcg-timeblend) | `PCG_TimeBlend` | Loops |
| [Topo Transfer (PCG)](deform.md#pcg-topotransfer) | `PCG_TopoTransfer` | Deform |
| [Torus (PCG)](generate.md#pcg-torus) | `PCG_Torus` | Generate |
| [Trace (PCG)](convert.md#pcg-trace) | `PCG_Trace` | Convert |
| [Trail (PCG)](loop.md#pcg-trail) | `PCG_Trail` | Loops |
| [Transform (PCG)](modify.md#pcg-transform) | `PCG_Transform` | Modify |
| [Transform by Attribute (PCG)](modify.md#pcg-transformbyattrib) | `PCG_TransformByAttrib` | Modify |
| [Transform Pieces (PCG)](deform.md#pcg-transformpieces) | `PCG_TransformPieces` | Deform |
| [Tri Divide (PCG)](topology.md#pcg-tridivide) | `PCG_TriDivide` | Topology |
| [Triangulate 2D (PCG)](modify.md#pcg-triangulate2d) | `PCG_Triangulate2D` | Modify |
| [Tube (PCG)](generate.md#pcg-tube) | `PCG_Tube` | Generate |
| [Twist / Bend / Taper (PCG)](deform.md#pcg-deform) | `PCG_Deform` | Deform |
| [Unpack (PCG)](scatter.md#pcg-unpack) | `PCG_Unpack` | Scatter & Copy |
| [Unsubdivide (PCG)](topology.md#pcg-unsubdivide) | `PCG_Unsubdivide` | Topology |
| [UV Auto Seams (PCG)](uv.md#pcg-uvautoseams) | `PCG_UVAutoSeams` | UV |
| [UV Backproject (PCG)](render.md#pcg-uvbackproject) | `PCG_UVBackproject` | Render & View |
| [UV Flatten (PCG)](uv.md#pcg-uvflatten) | `PCG_UVFlatten` | UV |
| [UV Fuse (PCG)](uv.md#pcg-uvfuse) | `PCG_UVFuse` | UV |
| [UV Layout (PCG)](uv.md#pcg-uvlayout) | `PCG_UVLayout` | UV |
| [UV Pelt (PCG)](uv.md#pcg-uvpelt) | `PCG_UVPelt` | UV |
| [UV Project (PCG)](uv.md#pcg-uvproject) | `PCG_UVProject` | UV |
| [UV Resolve (PCG)](render.md#pcg-uvresolve) | `PCG_UVResolve` | Render & View |
| [UV Smooth (PCG)](uv.md#pcg-uvsmooth) | `PCG_UVSmooth` | UV |
| [UV Transform (PCG)](uv.md#pcg-uvtransform) | `PCG_UVTransform` | UV |
| [UV Unwrap (PCG)](uv.md#pcg-uvunwrap) | `PCG_UVUnwrap` | UV |
| [Value (PCG)](param.md#pcg-value) | `PCG_Value` | Parameters & Expressions |
| [VDB (PCG)](volume.md#pcg-vdb) | `PCG_VDB` | Volumes & VDB |
| [VDB Activate (PCG)](volume.md#pcg-vdbactivate) | `PCG_VDBActivate` | Volumes & VDB |
| [VDB Activate SDF (PCG)](volume.md#pcg-vdbactivatesdf) | `PCG_VDBActivateSDF` | Volumes & VDB |
| [VDB Advect (PCG)](volume.md#pcg-vdbadvect) | `PCG_VDBAdvect` | Volumes & VDB |
| [VDB Advect Points (PCG)](volume.md#pcg-vdbadvectpoints) | `PCG_VDBAdvectPoints` | Volumes & VDB |
| [VDB Analysis (PCG)](volume.md#pcg-vdbanalysis) | `PCG_VDBAnalysis` | Volumes & VDB |
| [VDB Clip (PCG)](volume.md#pcg-vdbclip) | `PCG_VDBClip` | Volumes & VDB |
| [VDB Combine (PCG)](volume.md#pcg-vdbcombine) | `PCG_VDBCombine` | Volumes & VDB |
| [VDB Densify (PCG)](volume.md#pcg-vdbdensify) | `PCG_VDBDensify` | Volumes & VDB |
| [VDB Diagnostics (PCG)](volume.md#pcg-vdbdiagnostics) | `PCG_VDBDiagnostics` | Volumes & VDB |
| [VDB Extrapolate (PCG)](volume.md#pcg-vdbextrapolate) | `PCG_VDBExtrapolate` | Volumes & VDB |
| [VDB Fill (PCG)](volume.md#pcg-vdbfill) | `PCG_VDBFill` | Volumes & VDB |
| [VDB Fracture (PCG)](volume.md#pcg-vdbfracture) | `PCG_VDBFracture` | Volumes & VDB |
| [VDB from Particle Fluid (PCG)](volume.md#pcg-vdbfromparticlefluid) | `PCG_VDBFromParticleFluid` | Volumes & VDB |
| [VDB from Particles (PCG)](volume.md#pcg-vdbfromparticles) | `PCG_VDBFromParticles` | Volumes & VDB |
| [VDB from Polygons (PCG)](volume.md#pcg-vdbfrompolygons) | `PCG_VDBFromPolygons` | Volumes & VDB |
| [VDB LOD (PCG)](volume.md#pcg-vdblod) | `PCG_VDBLOD` | Volumes & VDB |
| [VDB Merge (PCG)](volume.md#pcg-vdbmerge) | `PCG_VDBMerge` | Volumes & VDB |
| [VDB Metadata (PCG)](volume.md#pcg-vdbmetadata) | `PCG_VDBMetadata` | Volumes & VDB |
| [VDB Morph SDF (PCG)](volume.md#pcg-vdbmorphsdf) | `PCG_VDBMorphSDF` | Volumes & VDB |
| [VDB Noise (PCG)](volume.md#pcg-vdbnoise) | `PCG_VDBNoise` | Volumes & VDB |
| [VDB Occlusion Mask (PCG)](volume.md#pcg-vdbocclusionmask) | `PCG_VDBOcclusionMask` | Volumes & VDB |
| [VDB Platonic (PCG)](volume.md#pcg-vdbplatonic) | `PCG_VDBPlatonic` | Volumes & VDB |
| [VDB Points Group (PCG)](volume.md#pcg-vdbpointsgroup) | `PCG_VDBPointsGroup` | Volumes & VDB |
| [VDB Potential Flow (PCG)](volume.md#pcg-vdbpotentialflow) | `PCG_VDBPotentialFlow` | Volumes & VDB |
| [VDB Project Non-Divergent (PCG)](volume.md#pcg-vdbprojectnondivergent) | `PCG_VDBProjectNonDivergent` | Volumes & VDB |
| [VDB Prune (PCG)](volume.md#pcg-vdbprune) | `PCG_VDBPrune` | Volumes & VDB |
| [VDB Ray (PCG)](volume.md#pcg-vdbray) | `PCG_VDBRay` | Volumes & VDB |
| [VDB Rebuild SDF (PCG)](volume.md#pcg-vdbrebuildsdf) | `PCG_VDBRebuildSDF` | Volumes & VDB |
| [VDB Remap (PCG)](volume.md#pcg-vdbremap) | `PCG_VDBRemap` | Volumes & VDB |
| [VDB Renormalize SDF (PCG)](volume.md#pcg-vdbrenormalizesdf) | `PCG_VDBRenormalizeSDF` | Volumes & VDB |
| [VDB Resample (PCG)](volume.md#pcg-vdbresample) | `PCG_VDBResample` | Volumes & VDB |
| [VDB Scatter (PCG)](volume.md#pcg-vdbscatter) | `PCG_VDBScatter` | Volumes & VDB |
| [VDB Segment by Connectivity (PCG)](volume.md#pcg-vdbsegment) | `PCG_VDBSegment` | Volumes & VDB |
| [VDB Smooth (PCG)](volume.md#pcg-vdbsmooth) | `PCG_VDBSmooth` | Volumes & VDB |
| [VDB to Spheres (PCG)](volume.md#pcg-vdbtospheres) | `PCG_VDBToSpheres` | Volumes & VDB |
| [VDB Topology to SDF (PCG)](volume.md#pcg-vdbtopologytosdf) | `PCG_VDBTopologyToSDF` | Volumes & VDB |
| [VDB Transform (PCG)](volume.md#pcg-vdbtransform) | `PCG_VDBTransform` | Volumes & VDB |
| [VDB Vector Merge (PCG)](volume.md#pcg-vdbvectormerge) | `PCG_VDBVectorMerge` | Volumes & VDB |
| [VDB Vector Split (PCG)](volume.md#pcg-vdbvectorsplit) | `PCG_VDBVectorSplit` | Volumes & VDB |
| [VDB Visualize Tree (PCG)](volume.md#pcg-vdbvisualizetree) | `PCG_VDBVisualizeTree` | Volumes & VDB |
| [Viewport (PCG)](output.md#pcg-viewport) | `PCG_Viewport` | Output & Export |
| [Volume (PCG)](generate.md#pcg-volume) | `PCG_Volume` | Generate |
| [Volume Adjust Fog (PCG)](volume.md#pcg-volumeadjustfog) | `PCG_VolumeAdjustFog` | Volumes & VDB |
| [Volume Blur (PCG)](modify.md#pcg-volumeblur) | `PCG_VolumeBlur` | Modify |
| [Volume Bound (PCG)](volume.md#pcg-volumebound) | `PCG_VolumeBound` | Volumes & VDB |
| [Volume Break (PCG)](volume.md#pcg-volumebreak) | `PCG_VolumeBreak` | Volumes & VDB |
| [Volume Compress (PCG)](volume.md#pcg-volumecompress) | `PCG_VolumeCompress` | Volumes & VDB |
| [Volume Convolve 3×3×3 (PCG)](volume.md#pcg-volumeconvolve) | `PCG_VolumeConvolve` | Volumes & VDB |
| [Volume Feather (PCG)](volume.md#pcg-volumefeather) | `PCG_VolumeFeather` | Volumes & VDB |
| [Volume FFT (PCG)](volume.md#pcg-volumefft) | `PCG_VolumeFFT` | Volumes & VDB |
| [Volume from Attrib (PCG)](volume.md#pcg-volumefromattrib) | `PCG_VolumeFromAttrib` | Volumes & VDB |
| [Volume Merge (PCG)](volume.md#pcg-volumemerge) | `PCG_VolumeMerge` | Volumes & VDB |
| [Volume Mix (PCG)](modify.md#pcg-volumemix) | `PCG_VolumeMix` | Modify |
| [Volume Optical Flow (PCG)](volume.md#pcg-volumeopticalflow) | `PCG_VolumeOpticalFlow` | Volumes & VDB |
| [Volume Patch (PCG)](volume.md#pcg-volumepatch) | `PCG_VolumePatch` | Volumes & VDB |
| [Volume Ramp (PCG)](volume.md#pcg-volumeramp) | `PCG_VolumeRamp` | Volumes & VDB |
| [Volume Rasterize Attributes (PCG)](convert.md#pcg-volumerasterizeattribs) | `PCG_VolumeRasterizeAttribs` | Convert |
| [Volume Rasterize Curve (PCG)](volume.md#pcg-volumerasterizecurve) | `PCG_VolumeRasterizeCurve` | Volumes & VDB |
| [Volume Rasterize Particles (PCG)](volume.md#pcg-volumerasterizeparticles) | `PCG_VolumeRasterizeParticles` | Volumes & VDB |
| [Volume Rasterize Points (PCG)](volume.md#pcg-volumerasterizepoints) | `PCG_VolumeRasterizePoints` | Volumes & VDB |
| [Volume Reduce (PCG)](volume.md#pcg-volumereduce) | `PCG_VolumeReduce` | Volumes & VDB |
| [Volume Resample (PCG)](modify.md#pcg-volumeresample) | `PCG_VolumeResample` | Modify |
| [Volume Reshape SDF (PCG)](modify.md#pcg-volumereshapesdf) | `PCG_VolumeReshapeSDF` | Modify |
| [Volume Resize (PCG)](volume.md#pcg-volumeresize) | `PCG_VolumeResize` | Volumes & VDB |
| [Volume SDF (PCG)](volume.md#pcg-volumesdf) | `PCG_VolumeSDF` | Volumes & VDB |
| [Volume Slice (PCG)](volume.md#pcg-volumeslice) | `PCG_VolumeSlice` | Volumes & VDB |
| [Volume Smooth SDF (PCG)](modify.md#pcg-volumesmoothsdf) | `PCG_VolumeSmoothSDF` | Modify |
| [Volume Splice (PCG)](volume.md#pcg-volumesplice) | `PCG_VolumeSplice` | Volumes & VDB |
| [Volume Stamp (PCG)](volume.md#pcg-volumestamp) | `PCG_VolumeStamp` | Volumes & VDB |
| [Volume Trail (PCG)](volume.md#pcg-volumetrail) | `PCG_VolumeTrail` | Volumes & VDB |
| [Volume Velocity (PCG)](volume.md#pcg-volumevelocity) | `PCG_VolumeVelocity` | Volumes & VDB |
| [Volume Velocity from Curves (PCG)](volume.md#pcg-volumevelocityfromcurves) | `PCG_VolumeVelocityFromCurves` | Volumes & VDB |
| [Volume Velocity from Surface (PCG)](volume.md#pcg-volumevelocityfromsurface) | `PCG_VolumeVelocityFromSurface` | Volumes & VDB |
| [Volume Visualization (PCG)](volume.md#pcg-volumevisualization) | `PCG_VolumeVisualization` | Volumes & VDB |
| [Volume Wrangle (PCG)](modify.md#pcg-volumewrangle) | `PCG_VolumeWrangle` | Modify |
| [Voronoi 2D (PCG)](scatter.md#pcg-voronoi2d) | `PCG_Voronoi2D` | Scatter & Copy |
| [Voronoi Cluster (PCG)](modify.md#pcg-voronoicluster) | `PCG_VoronoiCluster` | Modify |
| [Voronoi Fracture (PCG)](modify.md#pcg-voronoifracture) | `PCG_VoronoiFracture` | Modify |
| [Voronoi Split (PCG)](modify.md#pcg-voronoisplit) | `PCG_VoronoiSplit` | Modify |
| [Wrangle (PCG)](attribute.md#pcg-wrangle) | `PCG_Wrangle` | Attributes |

See also: [Houdini node index](houdini-index.md) — find the node that replaces a Houdini SOP or COP.
