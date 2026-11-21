using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class BuildTextureStreams
{
    [Serializable]
    public sealed class ImportSettings
    {
        public string name;
        public bool sprite;
        public bool mipmaps;
        public bool cube;
        public bool linear;
        public int format;
    }

    [Serializable]
    public sealed class ImportPlan
    {
        public ImportSettings[] textures;
    }

    public static void Build()
    {
        var output = Environment.GetEnvironmentVariable("RISK2MAC_TEXTURE_STREAM_OUTPUT");
        var planPath = Environment.GetEnvironmentVariable("RISK2MAC_TEXTURE_STREAM_PLAN");
        if (String.IsNullOrEmpty(output) || !Path.IsPathRooted(output) || Directory.Exists(output))
            throw new InvalidOperationException("A fresh absolute texture output directory is required.");
        var plan = JsonUtility.FromJson<ImportPlan>(File.ReadAllText(planPath));
        var target = BuildTarget.StandaloneOSX;
        PlayerSettings.SetUseDefaultGraphicsAPIs(target, false);
        PlayerSettings.SetGraphicsAPIs(target, new[] { GraphicsDeviceType.Metal });
        PlayerSettings.colorSpace = ColorSpace.Linear;

        var assets = plan.textures.Select(ImportTexture).ToArray();
        Directory.CreateDirectory(output);
        var builds = new[] { new AssetBundleBuild { assetBundleName = "textures.bundle", assetNames = assets } };
        if (!BuildPipeline.BuildAssetBundles(output, builds, BuildAssetBundleOptions.None, target))
            throw new InvalidOperationException("Could not build the startup texture bundle.");
    }

    private static string ImportTexture(ImportSettings request)
    {
        var file = "Assets/Textures/" + request.name + ".png";
        var importer = (TextureImporter)AssetImporter.GetAtPath(file);
        importer.textureType = request.sprite ? TextureImporterType.Sprite : TextureImporterType.Default;
        if (request.sprite)
        {
            importer.spriteImportMode = SpriteImportMode.Single;
            var sprite = importer.GetPlatformTextureSettings("Standalone");
            sprite.overridden = true;
            sprite.format = request.format == 4 ? TextureImporterFormat.RGBA32 : TextureImporterFormat.BC7;
            sprite.textureCompression = TextureImporterCompression.CompressedHQ;
            sprite.compressionQuality = 50;
            importer.SetPlatformTextureSettings(sprite);
        }
        importer.sRGBTexture = !request.linear;
        importer.alphaSource = TextureImporterAlphaSource.FromInput;
        importer.alphaIsTransparency = true;
        importer.mipmapEnabled = request.mipmaps;
        importer.npotScale = request.cube ? TextureImporterNPOTScale.ToNearest : TextureImporterNPOTScale.None;
        if (request.cube)
        {
            importer.textureShape = TextureImporterShape.TextureCube;
            importer.generateCubemap = TextureImporterGenerateCubemap.AutoCubemap;
        }
        importer.textureCompression = TextureImporterCompression.CompressedHQ;
        importer.compressionQuality = 50;
        importer.SaveAndReimport();
        return file;
    }
}
