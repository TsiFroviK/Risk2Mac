using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

namespace RoR2Arm64
{
    // Candidate, not yet installed in the working port. Requires the matched
    // Cloud shader with the explicit state guard and original-depth fallback.
    public sealed class MetalDepthCompatibility : MonoBehaviour
    {
        static readonly int SafeDepth = Shader.PropertyToID("_RoR2SafeDepth");
        static readonly int SafeState = Shader.PropertyToID("_RoR2SafeDepthState");
        static MetalDepthCompatibility instance;
        sealed class CameraCommands
        {
            public int width, height;
            public CommandBuffer begin, end;
        }
        readonly Dictionary<Camera, CameraCommands> cameras = new Dictionary<Camera, CameraCommands>();
        readonly List<Camera> removed = new List<Camera>();
        AssetBundle bundle;
        Material copyMaterial;
        bool subscribed;

        public static bool Install(string shaderBundlePath)
        {
            if (instance) return true;
            if (Application.platform != RuntimePlatform.OSXPlayer || SystemInfo.graphicsDeviceType != GraphicsDeviceType.Metal) return false;
            if (!SystemInfo.SupportsRenderTextureFormat(RenderTextureFormat.RFloat)) return false;
            GameObject owner = null;
            try
            {
                if (String.IsNullOrEmpty(shaderBundlePath) || !File.Exists(shaderBundlePath)) throw new FileNotFoundException("Depth copy shader bundle missing", shaderBundlePath);
                owner = new GameObject("RoR2 Metal depth compatibility");
                DontDestroyOnLoad(owner);
                var candidate = owner.AddComponent<MetalDepthCompatibility>();
                candidate.bundle = AssetBundle.LoadFromFile(shaderBundlePath);
                if (!candidate.bundle) throw new InvalidOperationException("Depth copy shader bundle could not be loaded");
                Shader shader = candidate.bundle.LoadAsset<Shader>("SafeDepthCopy");
                if (!shader || !shader.isSupported) throw new InvalidOperationException("Depth copy shader is unavailable");
                candidate.copyMaterial = new Material(shader) { hideFlags = HideFlags.HideAndDontSave };
                Shader.SetGlobalVector(SafeState, Vector4.zero);
                Shader.SetGlobalTexture(SafeDepth, Texture2D.blackTexture);
                Camera.onPreCull += candidate.BeforeCamera;
                candidate.subscribed = true;
                instance = candidate;
                Debug.Log("ARM64_METAL_DEPTH_INSTALLED: independent opaque snapshot with original shader fallback");
                return true;
            }
            catch (Exception error)
            {
                Debug.LogError("ARM64_METAL_DEPTH_DISABLED: " + error);
                Shader.SetGlobalVector(SafeState, Vector4.zero);
                Shader.SetGlobalTexture(SafeDepth, Texture2D.blackTexture);
                if (owner) Destroy(owner);
                return false;
            }
        }

        static bool Supported(Camera camera)
        {
            // Unverified target textures, offsets, actual resolution scaling, stereo
            // and forward cameras use the unchanged original shader path.
            if (!camera || !camera.isActiveAndEnabled || camera.cameraType != CameraType.Game || camera.stereoEnabled || camera.targetTexture) return false;
            if (camera.allowDynamicResolution && (ScalableBufferManager.widthScaleFactor != 1f || ScalableBufferManager.heightScaleFactor != 1f)) return false;
            if (camera.scaledPixelWidth != camera.pixelWidth || camera.scaledPixelHeight != camera.pixelHeight) return false;
            if (camera.actualRenderingPath != RenderingPath.DeferredShading || (camera.depthTextureMode & DepthTextureMode.Depth) == 0) return false;
            Rect rect = camera.pixelRect;
            return rect.x == 0 && rect.y == 0 && camera.pixelWidth == Screen.width && camera.pixelHeight == Screen.height && camera.pixelWidth > 0 && camera.pixelHeight > 0;
        }

        void BeforeCamera(Camera camera)
        {
            // The guard must be off for every other camera, including cameras
            // that have never acquired our command buffers.
            Shader.SetGlobalVector(SafeState, Vector4.zero);
            if (!copyMaterial || !Supported(camera)) { Remove(camera); return; }
            CameraCommands existing;
            if (cameras.TryGetValue(camera, out existing))
            {
                if (existing.width == camera.pixelWidth && existing.height == camera.pixelHeight) return;
                Remove(camera);
            }
            var entry = new CameraCommands { width = camera.pixelWidth, height = camera.pixelHeight };
            bool addedBegin = false, addedEnd = false;
            try
            {
                entry.begin = new CommandBuffer { name = "RoR2 independent opaque depth" };
                entry.end = new CommandBuffer { name = "RoR2 opaque depth release" };
                entry.begin.SetGlobalVector(SafeState, Vector4.zero);
                entry.begin.GetTemporaryRT(SafeDepth, entry.width, entry.height, 0, FilterMode.Point, RenderTextureFormat.RFloat, RenderTextureReadWrite.Linear, 1);
                entry.begin.Blit(BuiltinRenderTextureType.None, new RenderTargetIdentifier(SafeDepth), copyMaterial, 0);
                entry.begin.SetGlobalTexture(SafeDepth, new RenderTargetIdentifier(SafeDepth));
                entry.begin.SetGlobalVector(SafeState, new Vector4(1, entry.width, entry.height, SystemInfo.usesReversedZBuffer ? 1 : -1));
                entry.end.SetGlobalVector(SafeState, Vector4.zero);
                entry.end.SetGlobalTexture(SafeDepth, Texture2D.blackTexture);
                entry.end.ReleaseTemporaryRT(SafeDepth);
                camera.AddCommandBuffer(CameraEvent.BeforeForwardAlpha, entry.begin); addedBegin = true;
                camera.AddCommandBuffer(CameraEvent.AfterForwardAlpha, entry.end); addedEnd = true;
                cameras.Add(camera, entry);
                Debug.Log("ARM64_METAL_DEPTH_CAMERA: " + camera.name + " " + entry.width + "x" + entry.height);
            }
            catch (Exception error)
            {
                if (addedBegin) camera.RemoveCommandBuffer(CameraEvent.BeforeForwardAlpha, entry.begin);
                if (addedEnd) camera.RemoveCommandBuffer(CameraEvent.AfterForwardAlpha, entry.end);
                if (entry.begin != null) entry.begin.Release();
                if (entry.end != null) entry.end.Release();
                Debug.LogError("ARM64_METAL_DEPTH_CAMERA_FALLBACK: " + error);
            }
        }

        void Remove(Camera camera)
        {
            if (ReferenceEquals(camera, null)) return;
            CameraCommands entry;
            if (!cameras.TryGetValue(camera, out entry)) return;
            if (camera)
            {
                camera.RemoveCommandBuffer(CameraEvent.BeforeForwardAlpha, entry.begin);
                camera.RemoveCommandBuffer(CameraEvent.AfterForwardAlpha, entry.end);
            }
            entry.begin.Release(); entry.end.Release(); cameras.Remove(camera);
        }

        void LateUpdate()
        {
            removed.Clear();
            foreach (var pair in cameras) if (!Supported(pair.Key)) removed.Add(pair.Key);
            foreach (Camera camera in removed) Remove(camera);
        }

        void OnDisable() { Cleanup(); }
        void OnDestroy() { Cleanup(); }
        void Cleanup()
        {
            if (subscribed) { Camera.onPreCull -= BeforeCamera; subscribed = false; }
            removed.Clear(); foreach (var pair in cameras) removed.Add(pair.Key);
            foreach (Camera camera in removed) Remove(camera);
            Shader.SetGlobalVector(SafeState, Vector4.zero);
            Shader.SetGlobalTexture(SafeDepth, Texture2D.blackTexture);
            if (copyMaterial) { Destroy(copyMaterial); copyMaterial = null; }
            if (bundle) { bundle.Unload(false); bundle = null; }
            if (instance == this) instance = null;
        }
    }
}
