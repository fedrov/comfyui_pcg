// The few UnityEngine / UnityEditor members the world importer uses, with Unity's signatures: enough to compile
// engine/unity/Editor/PcgWorldImporter.cs with Mono in the tests (nothing here runs).
using System;
using System.Collections;
using System.Collections.Generic;

namespace UnityEngine
{
    public class Object
    {
        public string name;
        public static T Instantiate<T>(T original, Transform parent) where T : Object { return original; }
    }
    public struct Vector2 { public float x, y; public Vector2(float x, float y) { this.x = x; this.y = y; } }
    public struct Vector3 { public float x, y, z; public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; } }
    public struct Quaternion
    {
        public float x, y, z, w;
        public Quaternion(float x, float y, float z, float w) { this.x = x; this.y = y; this.z = z; this.w = w; }
        public static Quaternion Euler(float x, float y, float z) { return new Quaternion(0, 0, 0, 1); }
    }
    public struct Color { public float r, g, b, a; }
    public static class Debug
    {
        public static void Log(object m) { }
        public static void LogWarning(object m) { }
    }
    public static class Application { public static string dataPath = ""; }
    public class Component : Object
    {
        public Transform transform;
        public GameObject gameObject;
        public T[] GetComponentsInChildren<T>() { return new T[0]; }
    }
    public class Transform : Component, IEnumerable
    {
        public Vector3 position, localPosition, localScale;
        public Quaternion localRotation;
        public void SetParent(Transform p) { }
        public void SetParent(Transform p, bool worldPositionStays) { }
        public IEnumerator GetEnumerator() { return new List<Transform>().GetEnumerator(); }
    }
    public class GameObject : Object
    {
        public Transform transform;
        public GameObject() { }
        public GameObject(string name) { }
        public T AddComponent<T>() where T : Component, new() { return new T(); }
        public T GetComponent<T>() { return default(T); }
    }
    public class Renderer : Component { }
    public class Behaviour : Component { }
    public class LineRenderer : Renderer
    {
        public bool useWorldSpace;
        public float widthMultiplier;
        public int positionCount;
        public void SetPosition(int index, Vector3 position) { }
    }
    public struct LOD { public LOD(float screenRelativeTransitionHeight, Renderer[] renderers) { } }
    public class LODGroup : Component { public void SetLODs(LOD[] lods) { } }
    public class Texture : Object { public int width, height; }
    public class Texture2D : Texture
    {
        public Texture2D(int width, int height) { }
        public Color[] GetPixels() { return new Color[0]; }
    }
    public static class ImageConversion { public static bool LoadImage(this Texture2D tex, byte[] data) { return true; } }
    public class TerrainLayer : Object
    {
        public Texture2D diffuseTexture, normalMapTexture;
        public Vector2 tileSize;
    }
    public class TerrainData : Object
    {
        public int heightmapResolution, alphamapResolution;
        public Vector3 size;
        public TerrainLayer[] terrainLayers;
        public void SetHeights(int xBase, int yBase, float[,] heights) { }
        public void SetAlphamaps(int x, int y, float[,,] map) { }
    }
    public class Terrain : Behaviour
    {
        public static GameObject CreateTerrainGameObject(TerrainData assignTerrain) { return null; }
        public void SetNeighbors(Terrain left, Terrain top, Terrain right, Terrain bottom) { }
    }
}

namespace UnityEditor
{
    [AttributeUsage(AttributeTargets.Method)]
    public class MenuItem : Attribute { public MenuItem(string itemName) { } }
    public static class EditorUtility
    {
        public static string OpenFilePanel(string title, string directory, string extension) { return ""; }
    }
    public static class AssetDatabase
    {
        public static bool IsValidFolder(string path) { return true; }
        public static string CreateFolder(string parentFolder, string newFolderName) { return ""; }
        public static void CreateAsset(UnityEngine.Object asset, string path) { }
        public static T LoadAssetAtPath<T>(string assetPath) where T : UnityEngine.Object { return null; }
        public static void SaveAssets() { }
    }
    public static class PrefabUtility
    {
        public static UnityEngine.Object InstantiatePrefab(UnityEngine.Object assetComponentOrGameObject) { return null; }
    }
}
