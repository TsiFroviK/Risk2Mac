using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

public static class BuildRisk2MacStartup
{
    public static void Build()
    {
        var output = Environment.GetEnvironmentVariable("RISK2MAC_STARTUP_OUTPUT");
        if (string.IsNullOrEmpty(output) || !Path.IsPathRooted(output) ||
            Directory.Exists(output) || File.Exists(output))
            throw new InvalidOperationException("Expected a fresh absolute startup build path.");

        const BuildTarget target = BuildTarget.StandaloneOSX;
        const BuildTargetGroup group = BuildTargetGroup.Standalone;
        if (!BuildPipeline.IsBuildTargetSupported(group, target))
            throw new InvalidOperationException("Install macOS Build Support for Unity 2023.1.0f1.");

        // Both Mac player architectures use the same startup data layout.
        PlayerSettings.SetArchitecture(group, 1);
        PlayerSettings.SetScriptingBackend(group, ScriptingImplementation.Mono2x);
        PlayerSettings.SetApiCompatibilityLevel(group, ApiCompatibilityLevel.NET_4_6);
        PlayerSettings.SetManagedStrippingLevel(group, ManagedStrippingLevel.Disabled);
        PlayerSettings.stripEngineCode = false;
        PlayerSettings.SplashScreen.show = true;
        PlayerSettings.SetDefaultShaderChunkSizeInMB(16);
        PlayerSettings.SetUseDefaultGraphicsAPIs(target, false);
        PlayerSettings.SetGraphicsAPIs(target, new[] { GraphicsDeviceType.Metal });

        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = new[] { "Assets/RoR2/Base/Scenes/loadingbasic/loadingbasic.unity" },
            locationPathName = output,
            target = target,
            options = BuildOptions.None
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException("Could not build the startup scene: " + report.summary.result);
    }
}
