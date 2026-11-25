// comfyui_pcg world import for Unity: the engine-independent part (reading World.json, the coordinate conversion, the
// heightmap and instance tables). No UnityEngine here, so the plugin's tests compile and run it with Mono.
//
// World.json (World Manifest node): metres, +Y up, x east, z south, the world in 0..size from the north-west corner.
// Unity is left-handed with +Y up: x = x, y = y, z = -z (north stays up the screen, the map is not mirrored).
// The z flip is a reflection, so a rotation's axis turns as a pseudovector: quaternion (x, y, z, w) -> (-x, -y, z, w).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace Pcg.World
{
    public static class MiniJson
    {
        // object -> Dictionary<string, object>, array -> List<object>, number -> double, string, bool, null
        public static object Parse(string s)
        {
            int i = 0;
            object v = Value(s, ref i);
            Ws(s, ref i);
            if (i != s.Length) throw new FormatException("trailing characters at " + i);
            return v;
        }

        static void Ws(string s, ref int i) { while (i < s.Length && char.IsWhiteSpace(s[i])) i++; }

        static object Value(string s, ref int i)
        {
            Ws(s, ref i);
            if (i >= s.Length) throw new FormatException("unexpected end");
            char c = s[i];
            if (c == '{')
            {
                var d = new Dictionary<string, object>();
                i++; Ws(s, ref i);
                if (s[i] == '}') { i++; return d; }
                while (true)
                {
                    Ws(s, ref i);
                    string k = Str(s, ref i);
                    Ws(s, ref i);
                    if (s[i] != ':') throw new FormatException("':' expected at " + i);
                    i++;
                    d[k] = Value(s, ref i);
                    Ws(s, ref i);
                    if (s[i] == ',') { i++; continue; }
                    if (s[i] == '}') { i++; return d; }
                    throw new FormatException("',' or '}' expected at " + i);
                }
            }
            if (c == '[')
            {
                var l = new List<object>();
                i++; Ws(s, ref i);
                if (s[i] == ']') { i++; return l; }
                while (true)
                {
                    l.Add(Value(s, ref i));
                    Ws(s, ref i);
                    if (s[i] == ',') { i++; continue; }
                    if (s[i] == ']') { i++; return l; }
                    throw new FormatException("',' or ']' expected at " + i);
                }
            }
            if (c == '"') return Str(s, ref i);
            if (s.Substring(i).StartsWith("true")) { i += 4; return true; }
            if (s.Substring(i).StartsWith("false")) { i += 5; return false; }
            if (s.Substring(i).StartsWith("null")) { i += 4; return null; }
            int j = i;
            while (j < s.Length && "+-0123456789.eE".IndexOf(s[j]) >= 0) j++;
            if (j == i) throw new FormatException("value expected at " + i);
            double v = double.Parse(s.Substring(i, j - i), CultureInfo.InvariantCulture);
            i = j;
            return v;
        }

        static string Str(string s, ref int i)
        {
            if (s[i] != '"') throw new FormatException("string expected at " + i);
            var b = new StringBuilder();
            i++;
            while (s[i] != '"')
            {
                if (s[i] == '\\')
                {
                    i++;
                    char e = s[i];
                    if (e == 'n') b.Append('\n');
                    else if (e == 't') b.Append('\t');
                    else if (e == 'r') b.Append('\r');
                    else if (e == 'b') b.Append('\b');
                    else if (e == 'f') b.Append('\f');
                    else if (e == 'u') { b.Append((char)Convert.ToInt32(s.Substring(i + 1, 4), 16)); i += 4; }
                    else b.Append(e);
                    i++;
                }
                else b.Append(s[i++]);
            }
            i++;
            return b.ToString();
        }
    }

    public struct Vec3
    {
        public double x, y, z;
        public Vec3(double x, double y, double z) { this.x = x; this.y = y; this.z = z; }
    }

    public struct Quat
    {
        public double x, y, z, w;
        public Quat(double x, double y, double z, double w) { this.x = x; this.y = y; this.z = z; this.w = w; }
    }

    public struct Instance
    {
        public string asset;
        public Vec3 position;     // Unity
        public Quat rotation;     // Unity
        public Vec3 scale;        // Unity
        public int facade;        // the modular city's facade variant (the table's facade column; 0 without one)
    }

    public static class Convert3
    {
        public static Vec3 Position(double x, double y, double z) { return new Vec3(x, y, -z); }
        public static Quat Rotation(double x, double y, double z, double w) { return new Quat(-x, -y, z, w); }
        public static Vec3 Scale(double x, double y, double z) { return new Vec3(x, y, z); }
    }

    public class World
    {
        public Dictionary<string, object> J;
        public string Root;                 // the folder World.json's paths are relative to (ComfyUI's output folder)

        public static World Load(string path)
        {
            var w = new World();
            w.J = (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(path, Encoding.UTF8));
            if (Str(w.J, "format") != "pcg-world") throw new InvalidDataException(path + ": not a pcg-world manifest");
            string root = Path.GetDirectoryName(Path.GetFullPath(path));
            foreach (var part in Str(w.J, "folder").Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries))
                root = Path.GetDirectoryName(root);
            w.Root = root;
            return w;
        }

        public static string Str(Dictionary<string, object> d, string k)
        {
            object v;
            return d != null && d.TryGetValue(k, out v) && v != null ? v.ToString() : "";
        }

        public static double Num(Dictionary<string, object> d, string k, double dflt = 0)
        {
            object v;
            return d != null && d.TryGetValue(k, out v) && v is double ? (double)v : dflt;
        }

        public static Dictionary<string, object> Obj(Dictionary<string, object> d, string k)
        {
            object v;
            return d != null && d.TryGetValue(k, out v) ? v as Dictionary<string, object> : null;
        }

        public static List<object> Arr(Dictionary<string, object> d, string k)
        {
            object v;
            return d != null && d.TryGetValue(k, out v) && v is List<object> ? (List<object>)v : new List<object>();
        }

        public string Path_(string rel) { return Path.Combine(Root, rel.Replace('/', Path.DirectorySeparatorChar)); }

        public double TileSize { get { return Num(Obj(J, "coordinates"), "tile_size", 1024); } }
        public int TilesX { get { return (int)(double)Arr(Obj(J, "coordinates"), "tiles")[0]; } }
        public int TilesY { get { return (int)(double)Arr(Obj(J, "coordinates"), "tiles")[1]; } }

        public double[] HeightRange
        {
            get
            {
                var r = Arr(Obj(J, "terrain"), "range_metres");
                return new[] { (double)r[0], (double)r[1] };
            }
        }

        public int TileSamples { get { return (int)Num(Obj(J, "terrain"), "tile_samples", 257); } }

        // the full-map 16-bit raw heightmap (the height image set with one .r16 file)
        public string HeightRawFile()
        {
            foreach (var kv in Obj(J, "images"))
            {
                var img = (Dictionary<string, object>)kv.Value;
                var fs = Arr(img, "files");
                if (Str(img, "role") == "height" && fs.Count == 1)
                {
                    string f = Str((Dictionary<string, object>)fs[0], "file");
                    if (f.EndsWith(".r16")) return Path_(f);
                }
            }
            return null;
        }

        public static ushort[,] ReadR16(string path, int w, int h)
        {
            var b = File.ReadAllBytes(path);
            if (b.Length != w * h * 2) throw new InvalidDataException(path + ": expected " + (w * h * 2) + " bytes");
            var a = new ushort[h, w];
            for (int r = 0, k = 0; r < h; r++)
                for (int c = 0; c < w; c++, k += 2) a[r, c] = (ushort)(b[k] | (b[k + 1] << 8));
            return a;
        }

        // Unity TerrainData heights (0..1 of the range) for tile (i, j): [row, col] with rows along Unity +z (north),
        // so row 0 is the tile's southern edge (World.json's largest z)
        public float[,] TileHeights(ushort[,] full, int i, int j)
        {
            int n = TileSamples, step = n - 1;
            var h = new float[n, n];
            for (int r = 0; r < n; r++)
            {
                int src = j * step + (step - r);
                for (int c = 0; c < n; c++) h[r, c] = full[src, i * step + c] / 65535f;
            }
            return h;
        }

        // the Unity position of tile (i, j)'s terrain (its south-west corner, at the range's bottom)
        public Vec3 TilePosition(int i, int j)
        {
            double t = TileSize;
            return new Vec3(i * t, HeightRange[0], -(j + 1) * t);
        }

        public List<Instance> ReadInstances(string csvPath)
        {
            var o = new List<Instance>();
            var lines = File.ReadAllLines(csvPath, Encoding.UTF8);
            if (lines.Length == 0) return o;
            var head = new List<string>(lines[0].Split(','));
            int ia = head.IndexOf("asset");
            int ifa = head.IndexOf(FacadeColumn());
            Func<string[], string, double> g = (p, k) => double.Parse(p[head.IndexOf(k)], CultureInfo.InvariantCulture);
            for (int k = 1; k < lines.Length; k++)
            {
                if (lines[k].Length == 0) continue;
                var p = lines[k].Split(',');
                o.Add(new Instance
                {
                    asset = p[ia],
                    position = Convert3.Position(g(p, "px"), g(p, "py"), g(p, "pz")),
                    rotation = Convert3.Rotation(g(p, "qx"), g(p, "qy"), g(p, "qz"), g(p, "qw")),
                    scale = Convert3.Scale(g(p, "sx"), g(p, "sy"), g(p, "sz")),
                    facade = ifa >= 0 && p[ifa].Length > 0 ? (int)double.Parse(p[ifa], CultureInfo.InvariantCulture) : 0,
                });
            }
            return o;
        }

        // the modular city (World.json's city key): which column holds the facade variant, the wall slot it
        // replaces, and the material of each variant ("" = keep the wall)
        public string FacadeColumn()
        {
            var c = Obj(J, "city");
            string s = c != null ? Str(c, "instances_facade_column") : null;
            return string.IsNullOrEmpty(s) ? "facade" : s;
        }

        public string WallMaterial() { var c = Obj(J, "city"); return c != null ? Str(c, "wall_material") ?? "" : ""; }

        public string FacadeMaterial(int facade)
        {
            var c = Obj(J, "city");
            var m = c != null ? Obj(c, "facade_materials") : null;
            if (m == null) return "";
            object v;
            string s = m.TryGetValue(facade.ToString(CultureInfo.InvariantCulture), out v) && v != null ? v.ToString() : "";
            return s == WallMaterial() ? "" : s;
        }

        public Dictionary<string, object> Tile(int i, int j)
        {
            foreach (var t in Arr(J, "tiles"))
            {
                var d = (Dictionary<string, object>)t;
                var ij = Arr(d, "tile");
                if ((int)(double)ij[0] == i && (int)(double)ij[1] == j)
                    return (Dictionary<string, object>)MiniJson.Parse(File.ReadAllText(Path_(Str(d, "file")), Encoding.UTF8));
            }
            return null;
        }

        // OBJ polylines -> Unity points
        public static List<List<Vec3>> ReadObjLines(string path)
        {
            var vs = new List<Vec3>();
            var lines = new List<List<Vec3>>();
            foreach (var ln in File.ReadAllLines(path))
            {
                if (ln.StartsWith("v "))
                {
                    var p = ln.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                    vs.Add(Convert3.Position(double.Parse(p[1], CultureInfo.InvariantCulture),
                                             double.Parse(p[2], CultureInfo.InvariantCulture),
                                             double.Parse(p[3], CultureInfo.InvariantCulture)));
                }
                else if (ln.StartsWith("l "))
                {
                    var pl = new List<Vec3>();
                    foreach (var t in ln.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries))
                    {
                        if (t == "l") continue;
                        int k = int.Parse(t.Split('/')[0]);
                        pl.Add(vs[k > 0 ? k - 1 : vs.Count + k]);
                    }
                    lines.Add(pl);
                }
            }
            return lines;
        }
    }
}
