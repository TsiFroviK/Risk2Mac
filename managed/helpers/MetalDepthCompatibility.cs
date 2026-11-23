using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

namespace RoR2Arm64
{
    // The matched cloud shader consumes this snapshot only during this camera's alpha pass.
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
        readonly HashSet<string> loggedFallbacks = new HashSet<string>();
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

        static string FallbackReason(Camera camera)
        {
            if (!camera || !camera.isActiveAndEnabled || camera.cameraType != CameraType.Game) return "inactive or non-game camera";
            if (camera.actualRenderingPath != RenderingPath.DeferredShading) return "rendering path";
            if (camera.stereoEnabled) return "stereo camera";
            if ((camera.depthTextureMode & DepthTextureMode.Depth) == 0) return "no depth texture";
            if (camera.allowDynamicResolution && (ScalableBufferManager.widthScaleFactor != 1f || ScalableBufferManager.heightScaleFactor != 1f)) return "dynamic scaling";
            if (camera.scaledPixelWidth != camera.pixelWidth || camera.scaledPixelHeight != camera.pixelHeight) return "scaled viewport";
            Rect viewport = camera.rect;
            if (viewport.x != 0 || viewport.y != 0 || viewport.width != 1 || viewport.height != 1) return "partial viewport";
            if (camera.pixelWidth <= 0 || camera.pixelHeight <= 0) return "empty viewport";
            var target = camera.targetTexture;
            // A full-size offscreen camera has its own pixel space. Screen dimensions
            // describe the display and can differ from the actual depth attachment.
            if (target && (target.dimension != TextureDimension.Tex2D ||
                target.antiAliasing != 1 || target.useDynamicScale ||
                camera.pixelWidth != target.width || camera.pixelHeight != target.height)) return "offscreen layout";
            return null;
        }

        static string Describe(Camera camera)
        {
            var target = camera.targetTexture;
            return camera.name + " pixels=" + camera.pixelWidth + "x" + camera.pixelHeight +
                " scaled=" + camera.scaledPixelWidth + "x" + camera.scaledPixelHeight +
                " screen=" + Screen.width + "x" + Screen.height + " viewport=" + camera.rect +
                " target=" + (target ? target.width + "x" + target.height + " AA=" + target.antiAliasing : "display " + camera.targetDisplay) +
                " path=" + camera.actualRenderingPath + " depth=" + camera.depthTextureMode;
        }

        void BeforeCamera(Camera camera)
        {
            // The guard must be off for every other camera, including cameras
            // that have never acquired our command buffers.
            Shader.SetGlobalVector(SafeState, Vector4.zero);
            var reason = FallbackReason(camera);
            if (!copyMaterial || reason != null)
            {
                if (camera && camera.isActiveAndEnabled && camera.cameraType == CameraType.Game &&
                    reason != null && loggedFallbacks.Add(reason))
                    Debug.Log("ARM64_METAL_DEPTH_FALLBACK: " + reason + " " + Describe(camera));
                Remove(camera);
                return;
            }
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
                int snapshot = Shader.PropertyToID("_RoR2OpaqueDepthCamera" + camera.GetInstanceID());
                var texture = new RenderTargetIdentifier(snapshot);
                entry.begin.SetGlobalVector(SafeState, Vector4.zero);
                entry.begin.GetTemporaryRT(snapshot, entry.width, entry.height, 0, FilterMode.Point, RenderTextureFormat.RFloat, RenderTextureReadWrite.Linear, 1);
                entry.begin.Blit(BuiltinRenderTextureType.None, texture, copyMaterial, 0);
                entry.begin.SetGlobalTexture(SafeDepth, texture);
                entry.begin.SetGlobalVector(SafeState, new Vector4(1, entry.width, entry.height, SystemInfo.usesReversedZBuffer ? 1 : -1));
                entry.end.SetGlobalVector(SafeState, Vector4.zero);
                entry.end.SetGlobalTexture(SafeDepth, Texture2D.blackTexture);
                entry.end.ReleaseTemporaryRT(snapshot);
                camera.AddCommandBuffer(CameraEvent.BeforeForwardAlpha, entry.begin); addedBegin = true;
                camera.AddCommandBuffer(CameraEvent.AfterForwardAlpha, entry.end); addedEnd = true;
                cameras.Add(camera, entry);
                Debug.Log("ARM64_METAL_DEPTH_CAMERA: " + Describe(camera));
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
            foreach (var pair in cameras) if (FallbackReason(pair.Key) != null) removed.Add(pair.Key);
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
