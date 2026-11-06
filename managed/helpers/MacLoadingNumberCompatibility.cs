using System.Runtime.CompilerServices;
using RoR2;
using UnityEngine;
using UnityEngine.UI;

namespace RoR2Arm64
{
    // Keep the game's number sprites and progress logic; give only its loading
    // percentage the explicit UI material demonstrated in the accepted Mac test.
    public sealed class MacLoadingNumberCompatibility : MonoBehaviour
    {
        private static bool installed;
        private Material numberMaterial;

        public static void InstallIfRequested()
        {
            if (installed || Application.platform != RuntimePlatform.OSXPlayer ||
                !ManagedSoloBootstrap.IsRequested()) return;
            installed = true;
            var owner = new GameObject("RoR2 Mac Loading Number Material");
            Object.DontDestroyOnLoad(owner);
            owner.AddComponent<MacLoadingNumberCompatibility>();
        }

        // Defer RoR2 references until its normal startup has begun, matching the
        // graphics compatibility bootstrap's SubsystemRegistration separation.
        [MethodImpl(MethodImplOptions.NoInlining)]
        private void LateUpdate()
        {
            if (RoR2Application.loadFinished)
            {
                Object.Destroy(gameObject);
                return;
            }
            var canvas = LoadingScreenCanvas.Instance;
            var number = canvas ? canvas.percentage : null;
            if (!number) return;
            if (!numberMaterial)
            {
                var shader = Shader.Find("UI/Default");
                if (!shader || !shader.isSupported) return;
                numberMaterial = new Material(shader);
                numberMaterial.name = "RoR2 Mac Loading Number UI";
            }

            // SpriteAsNumberManager.LoadAnyExistingChildren and
            // InstantiateNewImage use exactly these direct Image children.
            // Including inactive children also covers digits needed later.
            var parent = number.transform;
            for (int i = 0; i < parent.childCount; ++i)
            {
                var glyph = parent.GetChild(i).GetComponent<Image>();
                if (glyph && glyph.material != numberMaterial)
                    glyph.material = numberMaterial;
            }
        }

        private void OnDestroy()
        {
            if (numberMaterial) Object.Destroy(numberMaterial);
        }
    }
}
