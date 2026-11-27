// comfyui_pcg world import for Unity (Editor): Tools > PCG World > Import World.json...
//
// Put the exported world (ComfyUI's output/pcg/world) somewhere under Assets/ and pick its World.json. glb files need
// a glTF importer package (glTFast: com.unity.cloud.gltfast) so that Unity imports them as prefabs. From World.json:
//
//   terrain     one Terrain per tile from the full-map 16-bit heightmap (257 samples a tile, shared edges, the
//               manifest's height range), neighbours connected; the splat maps as alphamaps over terrain layers made
//               from the layer textures (World.json's splat_layers: names and tile sizes)
//   buildings   the towns' glb, each asset under an LODGroup built from its LOD manifest (Unity transition heights)
//   water       the water glb (flow in the vertex colour, see World.json's water)
//   instances   the instance tables, a child per instance under one object per tile and asset; an asset uses
//               Assets/.../Prefabs/<asset>.prefab; else, for a LOD chain in the asset library (its LOD manifest:
//               <asset>_LOD0, _LOD1 ... and collision nodes UCX_<asset>_NN), a prefab made and saved there: an
//               LODGroup over the levels (the manifest's transitions) and a convex MeshCollider from each UCX node;
//               else the node of the same name in the asset library glbs; else it is skipped (counted in the log).
//               With World.json's city key (the modular city), an instance's facade column swaps the wall material
//               (wall_material) for that variant's (facade_materials), found by name among the project's materials
//               or, when there is none, made from the material library's textures (facade_textures)
//   roads       a LineRenderer per road polyline, its width from the road class
//
// Coordinates: see PcgWorldCore.cs (x = x, y = y, z = -z). glTF importers already convert glb files from glTF's
// right-handed frame; GltfFlipsX says how (glTFast negates x): the meshes' root is then turned 180 degrees about Y,
// so they land where World.json says. Set it to false for an importer that negates z instead.
#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Pcg.World
{
    public static class PcgWorldImporter
    {
        public static bool GltfFlipsX = true;

        [MenuItem("Tools/PCG World/Import World.json...")]
        public static void ImportMenu()
        {
            string path = EditorUtility.OpenFilePanel("World.json", Application.dataPath, "json");
            if (!string.IsNullOrEmpty(path)) Import(path);
        }

        static string AssetPath(string full)
        {
            full = full.Replace('\\', '/');
            string data = Application.dataPath.Replace('\\', '/');
            return full.StartsWith(data) ? "Assets" + full.Substring(data.Length) : null;
        }

        static UnityEngine.Vector3 V(Vec3 v) { return new UnityEngine.Vector3((float)v.x, (float)v.y, (float)v.z); }

        static UnityEngine.Quaternion Q(Quat q)
        {
            return new UnityEngine.Quaternion((float)q.x, (float)q.y, (float)q.z, (float)q.w);
        }

        public static GameObject Import(string worldJson)
        {
            var w = World.Load(worldJson);
            string folder = Path.GetDirectoryName(AssetPath(worldJson) ?? "Assets/PCGWorld/World.json").Replace('\\', '/');
            string gen = folder + "/Generated";
            if (!AssetDatabase.IsValidFolder(gen)) AssetDatabase.CreateFolder(folder, "Generated");
            var root = new GameObject("PCGWorld");
            Terrains(w, root.transform, gen);
            Meshes(w, root.transform);
            int skipped = Instances(w, root.transform, folder);
            Roads(w, root.transform);
            AssetDatabase.SaveAssets();
            Debug.Log("PCG World: imported " + worldJson + (skipped > 0 ? " (" + skipped + " instances without a prefab)" : ""));
            return root;
        }

        static void Terrains(World w, Transform root, string gen)
        {
            string raw = w.HeightRawFile();
            if (raw == null) { Debug.LogWarning("PCG World: no .r16 heightmap in World.json"); return; }
            var ter = World.Obj(w.J, "terrain");
            var samples = World.Arr(ter, "samples");
            var full = World.ReadR16(raw, (int)(double)samples[0], (int)(double)samples[1]);
            var hr = w.HeightRange;
            var layers = TerrainLayers(w, gen);
            int nx = w.TilesX, ny = w.TilesY;
            var tiles = new Terrain[nx, ny];
            for (int i = 0; i < nx; i++)
                for (int j = 0; j < ny; j++)
                {
                    var td = new TerrainData();
                    td.heightmapResolution = w.TileSamples;
                    td.size = new UnityEngine.Vector3((float)w.TileSize, (float)(hr[1] - hr[0]), (float)w.TileSize);
                    td.SetHeights(0, 0, w.TileHeights(full, i, j));
                    if (layers.Count > 0)
                    {
                        td.terrainLayers = layers.ToArray();
                        var am = Alphamaps(w, i, j, layers.Count);
                        if (am != null)
                        {
                            td.alphamapResolution = am.GetLength(0);
                            td.SetAlphamaps(0, 0, am);
                        }
                    }
                    AssetDatabase.CreateAsset(td, gen + "/Terrain_x" + i + "_y" + j + ".asset");
                    var go = Terrain.CreateTerrainGameObject(td);
                    go.name = "Terrain_x" + i + "_y" + j;
                    go.transform.SetParent(root, false);
                    go.transform.position = V(w.TilePosition(i, j));
                    tiles[i, j] = go.GetComponent<Terrain>();
                }
            // neighbours: left, top (north = World.json's smaller j), right, bottom
            for (int i = 0; i < nx; i++)
                for (int j = 0; j < ny; j++)
                    tiles[i, j].SetNeighbors(i > 0 ? tiles[i - 1, j] : null, j > 0 ? tiles[i, j - 1] : null,
                                             i < nx - 1 ? tiles[i + 1, j] : null, j < ny - 1 ? tiles[i, j + 1] : null);
        }

        static List<TerrainLayer> TerrainLayers(World w, string gen)
        {
            var o = new List<TerrainLayer>();
            foreach (var e in World.Arr(w.J, "splat_layers"))
            {
                var d = e as Dictionary<string, object>;
                string name = d != null ? World.Str(d, "name") : e.ToString();
                double size = d != null ? World.Num(d, "size_m", 4) : 4;
                var tl = new TerrainLayer();
                tl.diffuseTexture = LoadTex(w, "texture/layers/T_Layer_" + name + "_Color");
                tl.normalMapTexture = LoadTex(w, "texture/layers/T_Layer_" + name + "_Normal_GL");
                tl.tileSize = new UnityEngine.Vector2((float)size, (float)size);
                AssetDatabase.CreateAsset(tl, gen + "/Layer_" + name + ".terrainlayer");
                o.Add(tl);
            }
            return o;
        }

        static Texture2D LoadTex(World w, string imageSet)
        {
            var img = World.Obj(World.Obj(w.J, "images"), imageSet);
            var fs = World.Arr(img, "files");
            if (fs.Count == 0) return null;
            string ap = AssetPath(w.Path_(World.Str((Dictionary<string, object>)fs[0], "file")));
            return ap != null ? AssetDatabase.LoadAssetAtPath<Texture2D>(ap) : null;
        }

        // the splat maps' tile (i, j): four layers per RGBA image, in splat_layers order; Texture2D rows start at the
        // image's bottom (World.json's southern edge), as Unity's alphamap rows do
        static float[,,] Alphamaps(World w, int i, int j, int nl)
        {
            float[,,] am = null;
            for (int k = 0; k * 4 < nl; k++)
            {
                var img = World.Obj(World.Obj(w.J, "images"), "texture/T_Terrain_Splat" + k);
                if (img == null) return null;
                string file = null;
                foreach (var f in World.Arr(img, "files"))
                {
                    var fd = (Dictionary<string, object>)f;
                    if ((int)World.Num(fd, "tx") == i && (int)World.Num(fd, "ty") == j) file = World.Str(fd, "file");
                }
                if (file == null) return null;
                var tex = new Texture2D(2, 2);
                tex.LoadImage(File.ReadAllBytes(w.Path_(file)));
                int n = tex.width;
                if (am == null) am = new float[n, n, nl];
                var px = tex.GetPixels();
                for (int y = 0; y < n; y++)
                    for (int x = 0; x < n; x++)
                    {
                        var c = px[y * n + x];
                        float[] ch = { c.r, c.g, c.b, c.a };
                        for (int q = 0; q < 4 && k * 4 + q < nl; q++) am[y, x, k * 4 + q] = ch[q];
                    }
            }
            if (am == null) return null;
            int s = am.GetLength(0);
            for (int y = 0; y < s; y++)
                for (int x = 0; x < s; x++)
                {
                    float t = 0;
                    for (int q = 0; q < nl; q++) t += am[y, x, q];
                    if (t > 1e-6f) for (int q = 0; q < nl; q++) am[y, x, q] /= t;
                    else am[y, x, 0] = 1;
                }
            return am;
        }

        static GameObject Place(World w, string rel, Transform parent)
        {
            string ap = AssetPath(w.Path_(rel));
            var prefab = ap != null ? AssetDatabase.LoadAssetAtPath<GameObject>(ap) : null;
            if (prefab == null) { Debug.LogWarning("PCG World: " + rel + " is not imported (a glTF importer package?)"); return null; }
            var go = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            go.transform.SetParent(parent, false);
            if (GltfFlipsX) go.transform.localRotation = UnityEngine.Quaternion.Euler(0, 180, 0);
            return go;
        }

        static Transform Find(Transform t, string name)
        {
            if (t.name == name) return t;
            foreach (Transform c in t)
            {
                var r = Find(c, name);
                if (r != null) return r;
            }
            return null;
        }

        static void Meshes(World w, Transform root)
        {
            foreach (var kv in World.Obj(w.J, "meshes"))
            {
                var m = (Dictionary<string, object>)kv.Value;
                string role = World.Str(m, "role");
                if (role == "assets") continue;
                var go = Place(w, World.Str(m, "file"), root);
                if (go == null) continue;
                foreach (var a in World.Arr(m, "assets"))
                {
                    var ad = (Dictionary<string, object>)a;
                    var lods = World.Arr(ad, "lods");
                    var group = new GameObject(World.Str(ad, "name"));
                    group.transform.SetParent(go.transform, false);
                    var arr = new LOD[lods.Count];
                    for (int k = 0; k < lods.Count; k++)
                    {
                        var ld = (Dictionary<string, object>)lods[k];
                        var node = Find(go.transform, World.Str(ld, "node"));
                        var rs = new Renderer[0];
                        if (node != null)
                        {
                            node.SetParent(group.transform, true);
                            rs = node.GetComponentsInChildren<Renderer>();
                        }
                        arr[k] = new LOD((float)World.Num(ld, "unity_transition"), rs);
                    }
                    group.AddComponent<LODGroup>().SetLODs(arr);
                }
            }
        }

        static GameObject Asset(World w, string folder, string asset, Dictionary<string, GameObject> cache)
        {
            GameObject g;
            if (cache.TryGetValue(asset, out g)) return g;
            g = AssetDatabase.LoadAssetAtPath<GameObject>(folder + "/Prefabs/" + asset + ".prefab");
            if (g == null) g = LodPrefab(w, folder, asset);
            if (g == null)
                foreach (var kv in World.Obj(w.J, "meshes"))
                {
                    var m = (Dictionary<string, object>)kv.Value;
                    if (World.Str(m, "role") != "assets") continue;
                    string ap = AssetPath(w.Path_(World.Str(m, "file")));
                    var lib = ap != null ? AssetDatabase.LoadAssetAtPath<GameObject>(ap) : null;
                    var t = lib != null ? Find(lib.transform, asset) : null;
                    if (t == null && lib != null) t = Find(lib.transform, asset + "_LOD0");   // a LOD chain's LOD0
                    if (t != null) { g = t.gameObject; break; }
                }
            cache[asset] = g;
            return g;
        }

        // a LOD chain of the asset library as one prefab: the levels under an LODGroup, the UCX nodes as convex
        // colliders; saved as Prefabs/<asset>.prefab (so a second import finds it), null when there is no chain
        static GameObject LodPrefab(World w, string folder, string asset)
        {
            foreach (var kv in World.Obj(w.J, "meshes"))
            {
                var m = (Dictionary<string, object>)kv.Value;
                if (World.Str(m, "role") != "assets") continue;
                foreach (var a in World.Arr(m, "assets"))
                {
                    var ad = (Dictionary<string, object>)a;
                    if (World.Str(ad, "name") != asset) continue;
                    var lods = World.Arr(ad, "lods");
                    string ap = AssetPath(w.Path_(World.Str(m, "file")));
                    var lib = ap != null ? AssetDatabase.LoadAssetAtPath<GameObject>(ap) : null;
                    if (lib == null || lods.Count == 0) return null;
                    var go = new GameObject(asset);
                    var arr = new LOD[lods.Count];
                    for (int k = 0; k < lods.Count; k++)
                    {
                        var ld = (Dictionary<string, object>)lods[k];
                        var t = Find(lib.transform, World.Str(ld, "node"));
                        var rs = new Renderer[0];
                        if (t != null)
                        {
                            var c = Object.Instantiate(t.gameObject, go.transform, false);
                            c.name = World.Str(ld, "node");
                            rs = c.GetComponentsInChildren<Renderer>();
                        }
                        arr[k] = new LOD((float)World.Num(ld, "unity_transition"), rs);
                    }
                    go.AddComponent<LODGroup>().SetLODs(arr);
                    foreach (var u in World.Arr(ad, "collision"))
                    {
                        var t = Find(lib.transform, u.ToString());
                        var mfs = t != null ? t.GetComponentsInChildren<MeshFilter>() : new MeshFilter[0];
                        if (mfs.Length == 0) continue;
                        var mc = go.AddComponent<MeshCollider>();
                        mc.sharedMesh = mfs[0].sharedMesh;
                        mc.convex = true;
                    }
                    string dir = folder + "/Prefabs";
                    if (!AssetDatabase.IsValidFolder(dir)) AssetDatabase.CreateFolder(folder, "Prefabs");
                    var pf = PrefabUtility.SaveAsPrefabAsset(go, dir + "/" + asset + ".prefab");
                    Object.DestroyImmediate(go);
                    return pf;
                }
            }
            return null;
        }

        // the modular city's facade variants: the variant's material in place of the wall's, on every renderer
        static Material FacadeMaterial(World w, int facade, Dictionary<string, Material> cache)
        {
            string name = w.FacadeMaterial(facade);
            if (name.Length == 0) return null;
            Material mat;
            if (cache.TryGetValue(name, out mat)) return mat;
            foreach (var guid in AssetDatabase.FindAssets("t:Material " + name))
            {
                string p = AssetDatabase.GUIDToAssetPath(guid);
                if (Path.GetFileNameWithoutExtension(p) == name) { mat = AssetDatabase.LoadAssetAtPath<Material>(p); break; }
            }
            if (mat == null) mat = MakeFacadeMaterial(w, name);
            if (mat == null) Debug.LogWarning("PCG World: no material " + name + " in the project (facade " + facade + ")");
            cache[name] = mat;
            return mat;
        }

        // a facade material the project lacks, made from the material library's textures (World.json's
        // facade_textures): copied under Assets/PCGWorld/Facades, the normal map imported as one (the files are
        // OpenGL, Unity's convention), the ORM's occlusion in green is not URP's packing, so only base colour and
        // normal are set, with a matt smoothness
        static Material MakeFacadeMaterial(World w, string name)
        {
            var tex = w.FacadeTextures(name);
            string bc;
            if (!tex.TryGetValue("basecolor", out bc)) return null;
            if (!AssetDatabase.IsValidFolder("Assets/PCGWorld")) AssetDatabase.CreateFolder("Assets", "PCGWorld");
            if (!AssetDatabase.IsValidFolder("Assets/PCGWorld/Facades")) AssetDatabase.CreateFolder("Assets/PCGWorld", "Facades");
            var loaded = new Dictionary<string, Texture2D>();
            foreach (var kv in tex)
            {
                if (kv.Key == "orm") continue;
                string dst = "Assets/PCGWorld/Facades/" + Path.GetFileName(kv.Value);
                string full = Path.Combine(Path.GetDirectoryName(Application.dataPath), dst);
                if (!File.Exists(full)) File.Copy(kv.Value, full);
                AssetDatabase.ImportAsset(dst);
                if (kv.Key == "normal")
                {
                    var ti = AssetImporter.GetAtPath(dst) as TextureImporter;
                    if (ti != null) { ti.textureType = TextureImporterType.NormalMap; ti.SaveAndReimport(); }
                }
                loaded[kv.Key] = AssetDatabase.LoadAssetAtPath<Texture2D>(dst);
            }
            var sh = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            if (sh == null) return null;
            var mat = new Material(sh);
            Texture2D t;
            if (loaded.TryGetValue("basecolor", out t) && t != null)
            {
                if (mat.HasProperty("_BaseMap")) mat.SetTexture("_BaseMap", t);
                if (mat.HasProperty("_MainTex")) mat.SetTexture("_MainTex", t);
            }
            if (loaded.TryGetValue("normal", out t) && t != null && mat.HasProperty("_BumpMap"))
            {
                mat.SetTexture("_BumpMap", t);
                mat.EnableKeyword("_NORMALMAP");
            }
            if (mat.HasProperty("_Smoothness")) mat.SetFloat("_Smoothness", 0.15f);
            if (mat.HasProperty("_Glossiness")) mat.SetFloat("_Glossiness", 0.15f);
            AssetDatabase.CreateAsset(mat, "Assets/PCGWorld/Facades/" + name + ".mat");
            Debug.Log("PCG World: facade material " + name + " made from its textures");
            return mat;
        }

        static void SwapWall(GameObject go, string wall, Material mat)
        {
            foreach (var r in go.GetComponentsInChildren<Renderer>())
            {
                var ms = r.sharedMaterials;
                bool hit = false;
                for (int k = 0; k < ms.Length; k++)
                    if (ms[k] != null && ms[k].name == wall) { ms[k] = mat; hit = true; }
                if (hit) r.sharedMaterials = ms;
            }
        }

        static int Instances(World w, Transform root, string folder)
        {
            int skipped = 0;
            var cache = new Dictionary<string, GameObject>();
            var mats = new Dictionary<string, Material>();
            string wall = w.WallMaterial();
            var top = new GameObject("Instances").transform;
            top.SetParent(root, false);
            for (int i = 0; i < w.TilesX; i++)
                for (int j = 0; j < w.TilesY; j++)
                {
                    var tile = w.Tile(i, j);
                    if (tile == null) continue;
                    var tt = new GameObject("Tile_x" + i + "_y" + j).transform;
                    tt.SetParent(top, false);
                    var groups = new Dictionary<string, Transform>();
                    foreach (var f in World.Arr(World.Obj(tile, "instances"), "files"))
                        foreach (var ins in w.ReadInstances(w.Path_(f.ToString())))
                        {
                            var src = Asset(w, folder, ins.asset, cache);
                            if (src == null) { skipped++; continue; }
                            Transform gr;
                            if (!groups.TryGetValue(ins.asset, out gr))
                            {
                                gr = new GameObject(ins.asset).transform;
                                gr.SetParent(tt, false);
                                groups[ins.asset] = gr;
                            }
                            var go = (GameObject)Object.Instantiate(src, gr);
                            go.transform.localPosition = V(ins.position);
                            go.transform.localRotation = Q(ins.rotation);
                            go.transform.localScale = V(ins.scale);
                            if (ins.facade != 0 && wall.Length > 0)
                            {
                                var fm = FacadeMaterial(w, ins.facade, mats);
                                if (fm != null) SwapWall(go, wall, fm);
                            }
                        }
                }
            return skipped;
        }

        static void Roads(World w, Transform root)
        {
            var top = new GameObject("Roads").transform;
            top.SetParent(root, false);
            var classes = World.Obj(w.J, "road_classes");
            if (classes == null) return;
            foreach (var kv in classes)
            {
                var c = (Dictionary<string, object>)kv.Value;
                var pl = World.Obj(World.Obj(w.J, "polylines"), World.Str(c, "polylines"));
                if (pl == null) continue;
                var ct = new GameObject(kv.Key).transform;
                ct.SetParent(top, false);
                int n = 0;
                foreach (var line in World.ReadObjLines(w.Path_(World.Str(pl, "file"))))
                {
                    var go = new GameObject(kv.Key + "_" + n++);
                    go.transform.SetParent(ct, false);
                    var lr = go.AddComponent<LineRenderer>();
                    lr.useWorldSpace = false;
                    lr.widthMultiplier = (float)World.Num(c, "width_m", 4);
                    lr.positionCount = line.Count;
                    for (int k = 0; k < line.Count; k++) lr.SetPosition(k, V(line[k]));
                }
            }
        }
    }
}
#endif
