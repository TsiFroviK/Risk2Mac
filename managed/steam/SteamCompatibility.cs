using System;
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.Networking;

namespace Risk2Mac
{
    public static class SteamCompatibility
    {
        private static bool selected;
        private static bool steamMode;
        private static Facepunch.Steamworks.Client preparedClient;

        [DllImport("Risk2MacSteamBridge", CallingConvention = CallingConvention.Cdecl)]
        private static extern int Risk2MacSteamInitialize();

        [DllImport("Risk2MacSteamBridge", CallingConvention = CallingConvention.Cdecl)]
        private static extern int Risk2MacSteamValidateApi();

        public static bool IsSteamMode
        {
            get
            {
                if (selected) return steamMode;
                selected = true;
                if (Application.platform != RuntimePlatform.OSXPlayer ||
                    Environment.GetEnvironmentVariable("RISK2MAC_FORCE_LOCAL") == "1") return false;
                try
                {
                    if (Risk2MacSteamInitialize() == 1)
                    {
                        Facepunch.Steamworks.Config.ForUnity(Application.platform.ToString());
                        var client = new Facepunch.Steamworks.Client(632360U);
                        if (client.IsValid && client.IsLoggedOn && client.App.IsSubscribed(632360U))
                        {
                            preparedClient = client;
                            steamMode = true;
                        }
                        else
                        {
                            client.Dispose();
                        }
                    }
                }
                catch (Exception error)
                {
                    // The platform providers have not been installed yet. Close
                    // any partly constructed client before choosing local mode.
                    var partialClient = Facepunch.Steamworks.Client.Instance;
                    if (partialClient != null) partialClient.Dispose();
                    preparedClient = null;
                    steamMode = false;
                    Debug.LogWarning("RISK2MAC_STEAM_UNAVAILABLE: " + error);
                }
                if (steamMode)
                {
                    // This prompt opts into EOS and exits to restart the game.
                    // The macOS integration supplies Steam networking only.
                    PlayerPrefs.SetInt("HasShownFirstTimePopup", 1);
                }
                Debug.Log("RISK2MAC_PLATFORM_SELECTED: " + (steamMode ? "Steam" : "Local"));
                return steamMode;
            }
        }

        public static bool ShouldUseLocalPlatform()
        {
            foreach (string argument in Environment.GetCommandLineArgs())
                if (argument == "--arm64-solo-probe") return !IsSteamMode;
            return false;
        }

        public static Facepunch.Steamworks.Client TakePreparedClient(uint appId)
        {
            if (appId != 632360U || !IsSteamMode)
                throw new InvalidOperationException("Steam client requested outside the selected Steam mode.");
            if (preparedClient == null) return new Facepunch.Steamworks.Client(appId);
            var result = preparedClient;
            preparedClient = null;
            return result;
        }

        public static INetworkTransport CreateTransport()
        {
            if (IsSteamMode)
            {
                return new SteamExternalTransport(message => Debug.LogWarning(message));
            }
            return new RoR2Arm64.ManagedSoloTransport();
        }

        public static bool ValidateSteamLibraries()
        {
            return IsSteamMode && Risk2MacSteamValidateApi() == 1;
        }

        public static bool IsOwnedContentInstalled(Facepunch.Steamworks.App app, uint appId)
        {
            if (!IsSteamMode || app == null || !app.IsSubscribed(appId)) return false;
            var expansions = RoR2.ContentManagement.ContentManager.expansionDefs;
            if (expansions == null) return false;
            foreach (var expansion in expansions)
                if (expansion != null && expansion.requiredEntitlement != null &&
                    expansion.requiredEntitlement.steamAppId == appId) return true;
            return false;
        }
    }
}
