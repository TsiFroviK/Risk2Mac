using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

public static class BuildUnityBuiltinFixture
{
    public static void Build()
    {
        var output = Environment.GetEnvironmentVariable("RISK2MAC_BUILTIN_FIXTURE_OUTPUT");
        if (String.IsNullOrEmpty(output) || !Path.IsPathRooted(output) || Directory.Exists(output))
            throw new InvalidOperationException("A fresh absolute Unity fixture output directory is required.");

        const BuildTarget target = BuildTarget.StandaloneOSX;
        const BuildTargetGroup group = BuildTargetGroup.Standalone;
        if (!BuildPipeline.IsBuildTargetSupported(group, target))
            throw new InvalidOperationException("Install Mac Build Support for Unity 2023.1.0f1.");
        PlayerSettings.SetScriptingBackend(group, ScriptingImplementation.Mono2x);
        PlayerSettings.SetArchitecture(group, 1);
        PlayerSettings.SetDefaultShaderChunkSizeInMB(16);
        PlayerSettings.SetManagedStrippingLevel(group, ManagedStrippingLevel.Disabled);
        PlayerSettings.stripEngineCode = false;
        PlayerSettings.SetUseDefaultGraphicsAPIs(target, false);
        PlayerSettings.SetGraphicsAPIs(target, new[] { GraphicsDeviceType.Metal });
        PlayerSettings.colorSpace = ColorSpace.Linear;

        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        const string scenePath = "Assets/Empty.unity";
        if (!EditorSceneManager.SaveScene(scene, scenePath))
            throw new InvalidOperationException("Could not save the empty Unity shader fixture.");
        Directory.CreateDirectory(output);
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions {
            scenes = new[] { scenePath },
            target = target,
            locationPathName = Path.Combine(output, "Fixture.app"),
            options = BuildOptions.None
        });
        if (report.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException("Could not generate the Unity built-in shader resource.");
    }
}
