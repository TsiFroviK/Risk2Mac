using System;
using System.Reflection;
using Rewired;
using Rewired.Data;
using Rewired.Platforms;
using UnityEngine;
using UnityEngine.Networking;

[assembly: AssemblyTitle("RoR2 ARM64 managed solo prototype")]
[assembly: AssemblyVersion("0.1.0.0")]

namespace RoR2Arm64
{
    public static class ManagedSoloBootstrap
    {
        public const string CommandLineFlag = "--arm64-solo-probe";
        public static bool Installed { get; private set; }

        public static bool IsRequested()
        {
            foreach (string arg in Environment.GetCommandLineArgs())
                if (string.Equals(arg, CommandLineFlag, StringComparison.Ordinal)) return true;
            return false;
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        public static void Install()
        {
            Installed = false;
            if (!IsRequested()) return;

            PrepareMacWorkingDirectory();

            // The normal property setter queries DefaultNetworkTransport.IsStarted,
            // which calls a native UNET binding removed from the 2023 player.
            FieldInfo field = typeof(NetworkManager).GetField("s_ActiveTransport", BindingFlags.Static | BindingFlags.NonPublic);
            if (field == null || field.FieldType != typeof(INetworkTransport))
                throw new MissingFieldException("Expected shipped HLAPI NetworkManager.s_ActiveTransport field was not found.");

            object previous = field.GetValue(null);
            if (previous != null && !(previous is ManagedSoloTransport) && previous.GetType().FullName != "UnityEngine.Networking.DefaultNetworkTransport")
                throw new InvalidOperationException("Refusing to replace an unknown network transport: " + previous.GetType().FullName);

            ManagedSoloTransport oldSolo = previous as ManagedSoloTransport;
            if (oldSolo != null) oldSolo.Shutdown();
            field.SetValue(null, new ManagedSoloTransport());
            Installed = true;
            GraphicsCompatibility.InstallIfRequested();
            MacLoadingNumberCompatibility.InstallIfRequested();
            MacInputCompatibility.InstallIfRequested();
            MacGlyphCompatibility.InstallIfRequested();
            Debug.Log("ARM64_SOLO_TRANSPORT_INSTALLED: local HLAPI only; remote networking unsupported. Steam/platform initialization is unchanged.");
        }

        private static void PrepareMacWorkingDirectory()
        {
            if (Application.platform != RuntimePlatform.OSXPlayer) return;
            // LaunchServices/Unity can reset the shell wrapper's working directory.
            // Derive the bundle location from this loaded assembly, not from a
            // possibly relative asset path, before Addressables loads begin.
            string location = typeof(ManagedSoloBootstrap).Assembly.Location;
            if (!System.IO.Path.IsPathRooted(location))
                throw new InvalidOperationException("Mac compatibility assembly path is not absolute.");
            var managed = System.IO.Directory.GetParent(System.IO.Path.GetFullPath(location));
            var data = managed == null ? null : managed.Parent;
            var resources = data == null ? null : data.Parent;
            var contents = resources == null ? null : resources.Parent;
            if (managed == null || data == null || resources == null || contents == null ||
                managed.Name != "Managed" || data.Name != "Data" || resources.Name != "Resources" || contents.Name != "Contents" ||
                !System.IO.Directory.Exists(System.IO.Path.Combine(contents.FullName, "MacOS")) ||
                System.IO.Path.GetFullPath(System.IO.Path.Combine(contents.FullName, "Resources", "Data", "Managed")) != managed.FullName)
                throw new InvalidOperationException("Unexpected Mac application bundle layout: " + location);
            string previous = System.IO.Directory.GetCurrentDirectory();
            System.IO.Directory.SetCurrentDirectory(contents.FullName);
            Debug.Log("ARM64_MAC_BUNDLE_CWD: previous=" + previous + " current=" + System.IO.Directory.GetCurrentDirectory() +
                " data=" + Application.dataPath + " streaming=" + Application.streamingAssetsPath);
        }

        // The copy-only Cecil patch invokes this immediately before the original
        // RewiredIntegrationManager.FinishInit instantiates its loaded prefab.
        public static void PrepareRewiredPrefab(GameObject prefab)
        {
            if (!IsRequested()) return;
            if (!Installed) throw new InvalidOperationException("Solo runtime registration did not execute before Rewired initialization.");
            if (prefab == null) throw new ArgumentNullException("prefab");

            InputManager[] managers = prefab.GetComponentsInChildren<InputManager>(true);
            if (managers.Length == 0) throw new InvalidOperationException("Rewired InputManager component was not found on its prefab.");
            bool useSystemXInput = false;
            foreach (string argument in Environment.GetCommandLineArgs())
                if (string.Equals(argument, "--arm64-xinput-probe", StringComparison.Ordinal)) useSystemXInput = true;
            foreach (InputManager manager in managers)
            {
                if (manager.userData == null || manager.userData.ConfigVars == null)
                    throw new InvalidOperationException("Rewired prefab userData/ConfigVars is missing.");
                ConfigVars config = manager.userData.ConfigVars;
                config.alwaysUseUnityInput = !useSystemXInput;
                config.windowsStandalonePrimaryInputSource = useSystemXInput ? WindowsStandalonePrimaryInputSource.XInput : WindowsStandalonePrimaryInputSource.Unity;
                config.useXInput = useSystemXInput;
                config.useNativeMouse = false;
                if (config.platformVars_windowsStandalone == null)
                    config.platformVars_windowsStandalone = new ConfigVars.PlatformVars_WindowsStandalone();
                config.platformVars_windowsStandalone.useNativeKeyboard = false;
                config.platformVars_windowsStandalone.useWindowsGamingInput = false;
            }
            Debug.Log(useSystemXInput
                ? "ARM64_REWIRED_XINPUT_CONFIGURED: system XInput requested before prefab Instantiate/Awake; native keyboard/mouse disabled; initialization and physical device mapping require runtime verification."
                : "ARM64_REWIRED_UNITY_INPUT_CONFIGURED: before prefab Instantiate/Awake; special controller features may be limited.");
        }
    }
}
