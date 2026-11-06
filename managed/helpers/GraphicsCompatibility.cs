using System;
using System.Runtime.CompilerServices;
using RoR2;
using UnityEngine;
using UnityEngine.Rendering;

namespace RoR2Arm64
{
    // Restores only the two original custom graphics-shader bindings. The
    // cached Addressables shader objects are byte-identical to the originals
    // in the shipped globalgamemanagers.assets; Shader.Find is not used.
    public sealed class GraphicsCompatibility : MonoBehaviour
    {
        private const string DisabledFlag = "--arm64-original-deferred-disabled";
        private const string ShadingName = "Hidden/Internal-DeferredShading";
        private const string ReflectionsName = "Hidden/Internal-DeferredReflections";
        private static bool installed;
        private bool subscribed;
        private bool finished;
        private bool earlyAttempted;

        public static void InstallIfRequested()
        {
            if (!ManagedSoloBootstrap.IsRequested() || installed) return;
            installed = true;
            foreach (string argument in Environment.GetCommandLineArgs())
                if (String.Equals(argument, DisabledFlag, StringComparison.Ordinal))
                {
                    Debug.Log("ARM64_ORIGINAL_DEFERRED_DISABLED: explicit comparison/rollback flag; graphics bindings unchanged.");
                    return;
                }
            var owner = new GameObject("RoR2 ARM64 Original Deferred Graphics");
            UnityEngine.Object.DontDestroyOnLoad(owner);
            owner.AddComponent<GraphicsCompatibility>();
            Debug.Log("ARM64_ORIGINAL_DEFERRED_INSTALLED: waiting for original shader preload; deferred shading/reflections only.");
        }

        // SubsystemRegistration is earlier than RoR2Application.Awake. Deferring
        // this reference until Start avoids forcing RoR2's static catalogs early.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private void Start()
        {
            RoR2Application.onLoad += ApplyAfterPreload;
            subscribed = true;
            if (RoR2Application.loadFinished) ApplyAfterPreload();
        }

        // macOS needs the game's deferred shaders while the intro can already
        // be visible. Keep the original onLoad fallback until both cached
        // shaders are available; ApplyAfterPreload validates and rolls back.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private void Update()
        {
            if (finished || earlyAttempted || Application.platform != RuntimePlatform.OSXPlayer) return;
            Shader shading, reflections;
            if (LegacyShaderAPI.TryToGetPreloadedShader(ShadingName, out shading) && shading && shading.isSupported &&
                LegacyShaderAPI.TryToGetPreloadedShader(ReflectionsName, out reflections) && reflections && reflections.isSupported)
            {
                earlyAttempted = true;
                ApplyCore(false);
            }
        }

        private static Shader RequireCached(string exactName)
        {
            Shader shader;
            if (!LegacyShaderAPI.TryToGetPreloadedShader(exactName, out shader) || !shader)
                throw new InvalidOperationException("Original shader preload cache is missing: " + exactName);
            if (!String.Equals(shader.name, exactName, StringComparison.Ordinal) || !shader.isSupported)
                throw new InvalidOperationException("Original cached shader has the wrong name or is unsupported: " + Describe(shader));
            return shader;
        }

        private static string Describe(Shader shader)
        {
            return shader ? shader.name + "#" + shader.GetInstanceID() + ":supported=" + shader.isSupported + ":passes=" + shader.passCount : "null";
        }

        private void ApplyAfterPreload() { ApplyCore(true); }

        private void ApplyCore(bool finalAttempt)
        {
            if (finished) return;
            bool succeeded = false;
            Shader oldShading = null;
            Shader oldReflections = null;
            BuiltinShaderMode oldShadingMode = BuiltinShaderMode.Disabled;
            BuiltinShaderMode oldReflectionsMode = BuiltinShaderMode.Disabled;
            bool captured = false;
            bool changing = false;
            try
            {
                // Validate both source objects before changing either binding.
                Shader shading = RequireCached(ShadingName);
                Shader reflections = RequireCached(ReflectionsName);
                oldShading = GraphicsSettings.GetCustomShader(BuiltinShaderType.DeferredShading);
                oldReflections = GraphicsSettings.GetCustomShader(BuiltinShaderType.DeferredReflections);
                oldShadingMode = GraphicsSettings.GetShaderMode(BuiltinShaderType.DeferredShading);
                oldReflectionsMode = GraphicsSettings.GetShaderMode(BuiltinShaderType.DeferredReflections);
                captured = true;
                bool identical = oldShading == shading && oldReflections == reflections &&
                    oldShadingMode == BuiltinShaderMode.UseCustom && oldReflectionsMode == BuiltinShaderMode.UseCustom;
                Debug.Log("ARM64_ORIGINAL_DEFERRED_BEFORE: shading=" + Describe(oldShading) + " mode=" + oldShadingMode +
                    " reflections=" + Describe(oldReflections) + " mode=" + oldReflectionsMode);
                if (!identical)
                {
                    changing = true;
                    GraphicsSettings.SetCustomShader(BuiltinShaderType.DeferredShading, shading);
                    GraphicsSettings.SetShaderMode(BuiltinShaderType.DeferredShading, BuiltinShaderMode.UseCustom);
                    GraphicsSettings.SetCustomShader(BuiltinShaderType.DeferredReflections, reflections);
                    GraphicsSettings.SetShaderMode(BuiltinShaderType.DeferredReflections, BuiltinShaderMode.UseCustom);
                }
                if (GraphicsSettings.GetCustomShader(BuiltinShaderType.DeferredShading) != shading ||
                    GraphicsSettings.GetCustomShader(BuiltinShaderType.DeferredReflections) != reflections ||
                    GraphicsSettings.GetShaderMode(BuiltinShaderType.DeferredShading) != BuiltinShaderMode.UseCustom ||
                    GraphicsSettings.GetShaderMode(BuiltinShaderType.DeferredReflections) != BuiltinShaderMode.UseCustom)
                    throw new InvalidOperationException("Original deferred shader bindings did not retain the cached objects/modes.");
                Debug.Log("ARM64_ORIGINAL_DEFERRED_APPLIED: shading=" + Describe(shading) + " mode=UseCustom reflections=" +
                    Describe(reflections) + " mode=UseCustom alreadyIdentical=" + identical +
                    " cachedOriginalObjects=True scope=deferred-shading-and-reflections-only");
                if (Application.platform == RuntimePlatform.OSXPlayer)
                    MetalDepthCompatibility.Install(System.IO.Path.Combine(Application.streamingAssetsPath, "RoR2Mac", "depth-copy.bundle"));
                succeeded = true;
            }
            catch (Exception error)
            {
                if (captured && changing)
                    try
                    {
                        GraphicsSettings.SetCustomShader(BuiltinShaderType.DeferredShading, oldShading);
                        GraphicsSettings.SetShaderMode(BuiltinShaderType.DeferredShading, oldShadingMode);
                        GraphicsSettings.SetCustomShader(BuiltinShaderType.DeferredReflections, oldReflections);
                        GraphicsSettings.SetShaderMode(BuiltinShaderType.DeferredReflections, oldReflectionsMode);
                    }
                    catch (Exception rollbackError) { Debug.LogError("ARM64_ORIGINAL_DEFERRED_ROLLBACK_FAILED: " + rollbackError); }
                Debug.LogError("ARM64_ORIGINAL_DEFERRED_FAILED: " + error);
            }
            finally
            {
                if (succeeded || finalAttempt)
                {
                    finished = true;
                    Unsubscribe();
                    enabled = false;
                    UnityEngine.Object.Destroy(gameObject);
                }
                else Debug.Log("ARM64_ORIGINAL_DEFERRED_EARLY_FALLBACK: will retry at onLoad.");
            }
        }

        private void Unsubscribe()
        {
            if (!subscribed) return;
            subscribed = false;
            RoR2Application.onLoad -= ApplyAfterPreload;
        }

        private void OnDestroy() { Unsubscribe(); }
    }
}
