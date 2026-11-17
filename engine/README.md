# Engine import examples

Two scripts that read a world exported by comfyui_pcg through the single file **World.json** (written by the
World Manifest node, as in the `pcg_prod_world_tiles` example workflow) and set it up in an engine: terrain,
instances, LODs, materials, roads and water.

They are examples to start from rather than finished importers. The parts that need no engine are covered by the
plugin's tests (`tests/test_engine_import.py`): reading the manifest, the coordinate conversions, the Landscape
height settings, the instance tables, the LOD plan, and the Unity C# core, compiled and run with Mono. The calls
into Unreal and Unity have not been run in the engines themselves.

## Coordinates

World.json uses metres with +Y up, x east and z south. The world spans 0..size from its north-west corner, and tile
(i, j) covers x from i × tile and z from j × tile.

| Engine | Position | Rotation (quaternion x, y, z, w) |
|---|---|---|
| Unreal | X = x, Y = z, Z = y, in centimetres | (−x, −z, −y, w) |
| Unity | x = x, y = y, z = −z | (−x, −y, z, w) |

Both mappings are reflections, because the engines are left-handed and glTF is right-handed. The map is not
mirrored in either engine.

## Unreal (`unreal/pcg_world_import.py`)

Requirements: the Python Editor Script Plugin, and a glTF importer (Interchange).

```python
import sys; sys.path.append(r"<plugin>/engine/unreal")
import pcg_world_import as W
W.run(r"D:/ComfyUI/output/pcg/world/World.json")
```

- **Terrain:** the script prints the Landscape import settings that reproduce the heights exactly: the `.r16`,
  the resolution, Scale X/Y/Z and the location. Use them in Landscape mode > Import from File. Unreal has no Python
  call that builds a Landscape from a file.
- **Textures:** the splat maps and layer textures are imported as textures.
- **Meshes:** the glbs are imported. Each town's LOD chain is set on its LOD0 mesh, using the screen sizes from
  the LOD manifest.
- **Instances:** Hierarchical Instanced Static Mesh components, one actor per tile and asset. An asset without a
  mesh of its own name falls back to the exported proxies.
- **Roads:** one spline actor per polyline. The road class, width and material are stored in the actor's tags.
- **If the towns land off the Landscape:** your glTF importer converts axes differently. Pass `mesh_yaw` to turn
  the placed meshes.

## Unity (`unity/Editor/PcgWorldCore.cs`, `unity/Editor/PcgWorldImporter.cs`)

Requirements: copy the `unity/Editor` folder into your project. Put the exported world somewhere under `Assets/`,
and install glTFast (`com.unity.cloud.gltfast`) so that the glbs import as prefabs.

To run it, use the menu **Tools > PCG World > Import World.json...**.

- **Terrain:** one Terrain per tile (257 samples, shared edges, the manifest's height range). Neighbouring tiles
  are connected.
- **Terrain layers:** built from the layer textures (`splat_layers`: names and tile sizes). The splat maps become
  the alphamaps.
- **Buildings:** each town gets an LODGroup with the Unity transition heights from the LOD manifest.
- **Water:** the water mesh is placed in the scene. Its flow is stored in the vertex colour.
- **Instances:** each instance uses `Prefabs/<asset>.prefab`, or else the node of the same name in the asset
  library glbs.
- **Roads:** one LineRenderer per polyline, as wide as its road class.
- **Axis setting:** `GltfFlipsX` tells the script how the glTF importer converts axes. glTFast negates x, which is
  the default.
