# Modular city

Modular buildings: first a kit of facade pieces (each 4 m wide, one storey = 3.5 m), then rules that place the kit onto the facades of twelve buildings along two crossing streets. The deliverable is **the kit meshes plus an instance table**, not one merged building mesh.

## Load it

Drag `example_workflows/pcg_prod_modular_city.json` onto the ComfyUI canvas and press **Queue**. Only comfyui_pcg nodes plus ComfyUI's Preview Image are used. Run the [material library](pcg_prod_material_library.md) first if you want the kit to open with textures (see below).

Output, in `output/pcg/assets/kit/`:

| File | Content |
|---|---|
| `SM_Kit_<piece>.glb` | One glb per kit piece. |
| `Block_Instances.csv` | One row per placed piece. The `asset` column is the kit glb's file name without extension; the extra columns `bld` (building) and `floor` are included. |

## The kit (left four columns)

Pieces: `Wall_Plain`, `Wall_Window`, `Wall_Door`, `Wall_Shopfront`, `Wall_Balcony`, `Corner_Pillar`, `Roof_Cornice`, `Roof_Flat`.

Conventions:

- The pivot is at the centre of the bottom edge; the outer facade faces +Z and the wall thickness goes towards -Z.
- Every face carries a `material` attribute (`M_Wall`, `M_Trim`, `M_Glass`, `M_Door`, `M_Metal`, `M_Roof`, `M_Sign`), exported as glTF material slots.
- UVs are a world-scale box projection (1 UV = 1 m), the same density as the material library (one texture = 1 m).
- All seven slots point by relative path to the material library's textures, so after running the material library the kit opens textured.

How the pieces are built: **[Box (PCG)](../reference/generate.md#pcg-box)** parts, openings cut with **[Boolean (PCG)](../reference/modify.md#pcg-boolean)** (subtract). The facade face is z = 0; glass and door leaves sit back at z = -0.2, so every opening has a 20 cm reveal. The window has a stone surround, a lintel with a keystone, a sill and a painted frame with a mullion and a transom; the door has a casing, four raised panels, a handle and a canopy on two diagonal brackets; the balcony door a metal frame, and the balcony a slab, rails, corner posts and 12 cm balusters on three sides (one baluster box copied onto a row of points with **[Copy to Points (PCG)](../reference/scatter.md#pcg-copytopoints)**), 1 m high; the shopfront a stall riser, a metal frame in three bays with a transom, a sloping awning and a sign; the corner pillar a plinth and a capital; the cornice a fascia, a bed moulding, a row of dentils and a crown rounded with **[PolyBevel (PCG)](../reference/modify.md#pcg-polybevel)**. each part tagged with a `material` by a **[Wrangle (PCG)](../reference/attribute.md#pcg-wrangle)**, and each piece merged with **[Merge (PCG)](../reference/modify.md#pcg-merge)** and named (`s@name = "Wall_Window"` and so on). The library is merged, UV-projected with **[UV Project (PCG)](../reference/uv.md#pcg-uvproject)** (box, 1 UV = 1 m), coloured per material for previews, and exported by **[Export Mesh (PCG)](../reference/output.md#pcg-exportmesh)** with *Split by Attribute* `name`, so each piece becomes its own glb.

## Assembly (right columns)

1. **Footprints.** **[Grid (PCG)](../reference/generate.md#pcg-grid)** with 4 m cells; a Wrangle over primitives assigns cells to twelve buildings by rules (L shapes, slabs, a 14-storey tower, small houses, from a table in the generator) and gives each a floor count from 3 to 14. The streets run along x = 0 and z = 0 (16 m between the facades, 10 m of road). **[Blast (PCG)](../reference/modify.md#pcg-blast)** keeps the occupied cells and **[Divide (PCG)](../reference/modify.md#pcg-divide)** (remove shared edges) merges them into outlines.
2. **Slots.** **[PolyExtrude (PCG)](../reference/modify.md#pcg-polyextrude)** extrudes the outlines to the maximum height in 14 storey-high divisions; faces above each building's floor count are removed. Every side face is now a 4 m x 3.5 m slot. **[Normal (PCG)](../reference/attribute.md#pcg-normal)** (on primitives) gives the outward normal, and **[Extract Centroid (PCG)](../reference/attribute.md#pcg-extractcentroid)** puts one point at the centre of each slot, carrying `N`, `floors` and `bld`.
3. **Rules.** A Wrangle decides per slot point: ground floors facing one of the two streets (the point 2 m in front of the facade lies within 8 m of a street axis) are shopfronts, other ground floors are occasionally doors; upper floors use a random number per facade column (so pieces line up vertically), with random balconies on even floors of the street facade and a few plain walls. The top-floor slots are copied up one storey as `Roof_Cornice`. Corner pillars go on the points of sharp edges of the extruded mass (**[Group Create (PCG)](../reference/group.md#pcg-groupcreate)** by edge angle, one per storey, without the top ring). Roof points are the centres of the footprint cells lifted to the roof height (`Roof_Flat`).
4. **Delivery.** All instance points are merged, `asset` is set to `SM_Kit_<name>`, and **[Export Instances (PCG)](../reference/output.md#pcg-exportinstances)** writes the CSV.
5. **Preview.** **[Copy to Points (PCG)](../reference/scatter.md#pcg-copytopoints)** with *Piece Attribute* `name` places the kit back onto the points. The streets are a cobbled road (`Ground_Cobble`) 15 cm below the four paved quarters (`Ground_Cobble`), with 3 m concrete sidewalks (`M_Trim`) along the curbs in front of the facades, and street lamps and trees alternate every 6 m along the curbs (made in the workflow, not part of the kit). The 3D viewport and a 1600 x 1066 render show the result. A second preview lines up all eight kit pieces in two rows. Both use **[Geometry Preview (PCG)](../reference/output.md#pcg-previewimage)** in the *Studio* look with the material library's textures (`basecolor = pcg/materials/T_{material}_BaseColor.png`, `normal = pcg/materials/T_{material}_Normal_GL.png`, `orm = pcg/materials/T_{material}_ORM.png` for PBR shading, looked up by each face's `material`); a material whose files are missing keeps its colour.

![The assembled block in the studio preview, textured with the material library](images/pcg_prod_modular_city.png)

## Worth tweaking

| Node | Parameter | Effect |
|---|---|---|
| Footprint rule Wrangle | `code` | Building shapes and floor counts. |
| Slot rule Wrangle | `code` | Which piece goes where: shopfront and door rules, balcony probability (`h > 0.55`), share of plain walls. |
| Kit boxes | `size_*`, `c*` | Proportions of windows, doors and trims (keep the 4 m x 3.5 m module). |
| Export Mesh (kit) | `textures`, `texture_materials` | Which slots get texture paths, and the paths themselves. |

## See also

- [Material library](pcg_prod_material_library.md): the textures the kit points to.
- [City block](pcg_sop_city_block.md): buildings modelled in place instead of assembled.
- [Viewing and export](../concepts/viewing-and-export.md): glb and instance export.
- [Example index](README.md).
