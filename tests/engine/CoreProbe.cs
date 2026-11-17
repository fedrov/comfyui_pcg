// Prints what PcgWorldCore.cs reads from a World.json, as JSON, for tests/test_engine_import.py to check.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using Pcg.World;

public static class CoreProbe
{
    static string F(double v) { return v.ToString("R", CultureInfo.InvariantCulture); }

    public static int Main(string[] args)
    {
        var w = World.Load(args[0]);
        var sb = new StringBuilder("{");
        var hr = w.HeightRange;
        sb.Append("\"range\":[" + F(hr[0]) + "," + F(hr[1]) + "],");
        sb.Append("\"tile_samples\":" + w.TileSamples + ",\"tile_size\":" + F(w.TileSize) + ",");
        sb.Append("\"tiles\":[" + w.TilesX + "," + w.TilesY + "],");
        var ter = World.Obj(w.J, "terrain");
        var smp = World.Arr(ter, "samples");
        var full = World.ReadR16(w.HeightRawFile(), (int)(double)smp[0], (int)(double)smp[1]);
        // every tile: its position and the Unity world position of a few samples
        sb.Append("\"samples\":[");
        bool first = true;
        int n = w.TileSamples;
        double sp = w.TileSize / (n - 1);
        for (int i = 0; i < w.TilesX; i++)
            for (int j = 0; j < w.TilesY; j++)
            {
                var h = w.TileHeights(full, i, j);
                var p = w.TilePosition(i, j);
                foreach (var rc in new[] { new[] { 0, 0 }, new[] { 3, 7 }, new[] { n - 1, 2 }, new[] { n / 2, n - 1 } })
                {
                    int r = rc[0], c = rc[1];
                    double ux = p.x + c * sp, uz = p.z + r * sp, uy = p.y + h[r, c] * (hr[1] - hr[0]);
                    if (!first) sb.Append(",");
                    first = false;
                    sb.Append("[" + i + "," + j + "," + F(ux) + "," + F(uy) + "," + F(uz) + "]");
                }
            }
        sb.Append("],\"instances\":[");
        first = true;
        foreach (var f in World.Arr(World.Obj(w.J, "instances"), "files"))
            foreach (var ins in w.ReadInstances(w.Path_(f.ToString())))
            {
                if (!first) sb.Append(",");
                first = false;
                sb.Append("[\"" + ins.asset + "\"," + F(ins.position.x) + "," + F(ins.position.y) + "," + F(ins.position.z) + ","
                          + F(ins.rotation.x) + "," + F(ins.rotation.y) + "," + F(ins.rotation.z) + "," + F(ins.rotation.w) + "]");
            }
        sb.Append("],\"lines\":[");
        first = true;
        foreach (var kv in World.Obj(w.J, "polylines"))
            foreach (var ln in World.ReadObjLines(w.Path_(World.Str((Dictionary<string, object>)kv.Value, "file"))))
            {
                if (!first) sb.Append(",");
                first = false;
                sb.Append("[" + ln.Count + "," + F(ln[0].x) + "," + F(ln[0].y) + "," + F(ln[0].z) + "]");
            }
        sb.Append("]}");
        Console.WriteLine(sb.ToString());
        return 0;
    }
}
