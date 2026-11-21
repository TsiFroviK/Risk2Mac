using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

public static class BuildComputeDonor
{
    public static void Build()
    {
        string output = Environment.GetEnvironmentVariable("ROR2_MAC_COMPUTE_DONOR_OUTPUT");
        if (String.IsNullOrEmpty(output) || !Path.IsPathRooted(output) || Directory.Exists(output))
            throw new InvalidOperationException("ROR2_MAC_COMPUTE_DONOR_OUTPUT must be a fresh absolute directory.");
        var target = BuildTarget.StandaloneOSX;
        if (!BuildPipeline.IsBuildTargetSupported(BuildTargetGroup.Standalone,target)) throw new InvalidOperationException("Mac build support missing");
        if (!EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Standalone,target)) throw new InvalidOperationException("Mac target switch failed");
        PlayerSettings.SetUseDefaultGraphicsAPIs(target,false);
        PlayerSettings.SetGraphicsAPIs(target,new[]{GraphicsDeviceType.Metal});
        var assets=AssetDatabase.FindAssets("t:ComputeShader",new[]{"Assets/ComputeDonor"}).Select(AssetDatabase.GUIDToAssetPath).OrderBy(x=>x).ToArray();
        if (assets.Length!=12) throw new InvalidOperationException("Expected 12 original Unity PostProcessing compute shaders, got "+assets.Length);
        Directory.CreateDirectory(output);
        var builds=new[]{new AssetBundleBuild{assetBundleName="compute-donor.bundle",assetNames=assets}};
        var result=BuildPipeline.BuildAssetBundles(output,builds,BuildAssetBundleOptions.None,target);
        if (!result || !File.Exists(Path.Combine(output,"compute-donor.bundle"))) throw new InvalidOperationException("Compute donor build failed");
        Debug.Log("MAC_COMPUTE_DONOR_BUILD_OK: assets="+assets.Length+" path="+output);
    }
}
