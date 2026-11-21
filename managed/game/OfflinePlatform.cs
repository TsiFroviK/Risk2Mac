using System;
using System.IO;
using System.Reflection;
using Assets.RoR2.Scripts.Platform;
using RoR2;
using RoR2.EntitlementManagement;
using RoR2.Networking;
using UnityEngine;
using UnityEngine.Networking;
using Zio.FileSystems;
using PlatformID = RoR2.PlatformID;
using Path = System.IO.Path;

namespace RoR2Arm64.Offline
{
    public static class OfflinePlatform
    {
        public const string ActivationFlag = "--arm64-solo-probe";
        public static readonly PlatformID LocalIdentity = new PlatformID(1UL);
        public static string SaveRoot { get; private set; }
        public static bool Ready { get; private set; }

        public static bool IsRequested()
        {
            foreach (string argument in Environment.GetCommandLineArgs())
                if (string.Equals(argument, ActivationFlag, StringComparison.Ordinal)) return true;
            return false;
        }

        // Injected at the entry of PlatformSystems.Init. False preserves the
        // original path. True means an explicitly separate local platform was set.
        public static bool TryInitialize()
        {
            if (!IsRequested()) return false;
            if (Ready) return true;
            INetworkTransport transport = NetworkManager.activeTransport;
            if (transport == null || transport.GetType().FullName != "RoR2Arm64.ManagedSoloTransport")
                throw new InvalidOperationException("Managed solo transport was not registered before platform initialization. Check the SubsystemRegistration build entry.");
            SaveRoot = Path.Combine(Application.persistentDataPath, "ARM64Solo");
            Directory.CreateDirectory(SaveRoot);
            var physical = new PhysicalFileSystem();
            RoR2Application.cloudStorage = new SubFileSystem(physical, physical.ConvertPathFromInternal(SaveRoot));
            PlatformSystems.platformStrings = new string[] { "pc" };
            PlatformSystems.crossPlayEnabledOnStartup = false;
            PlatformSystems.EgsToggleConVar.value = 0;
            PlatformSystems.userManager = new OfflineUserManager();
            PlatformSystems.lobbyManager = new OfflineLobbyManager();
            PlatformSystems.textDataManager = new StreamingAssetsTextDataManager();
            PlatformSystems.saveSystem = new OfflineSaveSystem();
            PlatformSystems.achievementSystem = new OfflineAchievementSystem();
            PlatformSystems.entitlementsSystem = new OfflineEntitlements();
            PlatformSystems.platformManager = new OfflinePlatformManager();
            PlatformSystems.activityManager = new ActivityManager();
            PlatformSystems.activityManager.Initialize();
            PlatformSystems.saveSystem.InitializeSaveSystem();
            UserProfile.GenerateSaveFieldFunctions();
            RoR2Application.onUpdate += PlatformSystems.saveSystem.StaticUpdate;
            var resolver = PlatformSystems.entitlementsSystem;
            EntitlementManager.collectLocalUserEntitlementResolvers += delegate(Action<IUserEntitlementResolver<LocalUser>> add) { add(resolver); };
            EntitlementManager.collectNetworkUserEntitlementResolvers += delegate(Action<IUserEntitlementResolver<NetworkUser>> add) { add(resolver); };
            RoR2Application.onShutDown += Shutdown;

            // Legacy RoR2 uses this delegate as its generic startup-success gate.
            // It validates this local provider; it creates no Steam Client and
            // does not report any online/Steam service as present.
            RoR2Application.loadSteamworksClient = ValidateLocalProvider;
            RoR2Application.unloadSteamworksClient = delegate { };
            RoR2Application.steamBuildId = "ARM64_OFFLINE_NO_STEAM";
            Ready = true;
            Debug.Log("ARM64_OFFLINE_PLATFORM_READY: no Steam/EOS services; local identity #1; saves=" + SaveRoot);
            return true;
        }

        private static bool ValidateLocalProvider()
        {
            if (!Ready || PlatformSystems.saveSystem == null || !Directory.Exists(SaveRoot))
                throw new InvalidOperationException("Offline platform failed its startup validation.");
            Debug.Log("ARM64_OFFLINE_STARTUP_GATE: local provider validated; Steam client is absent.");
            return true;
        }

        // UserProfile.OnLogin unconditionally calls the shipped Steam portrait
        // loader. Give local profiles a built-in, non-owned fallback texture
        // without constructing a Steam Client or leaving the callback pending.
        public static bool TryLoadLocalPortrait(UserProfile profile, Action<Texture> callback)
        {
            if (!IsRequested()) return false;
            if (profile == null) throw new ArgumentNullException("profile");
            PropertyInfo property = typeof(UserProfile).GetProperty("portraitTexture", BindingFlags.Instance | BindingFlags.Public);
            FieldInfo ownership = typeof(UserProfile).GetField("ownsPortrait", BindingFlags.Instance | BindingFlags.NonPublic);
            MethodInfo setter = property == null ? null : property.GetSetMethod(true);
            if (setter == null || ownership == null) throw new MissingMemberException("Expected UserProfile portrait members were not found.");
            if ((bool)ownership.GetValue(profile) && profile.portraitTexture != null)
                UnityEngine.Object.Destroy(profile.portraitTexture);
            Texture texture = Texture2D.grayTexture;
            setter.Invoke(profile, new object[] { texture });
            ownership.SetValue(profile, false);
            if (callback != null) callback(texture);
            Debug.Log("ARM64_OFFLINE_PROFILE_PORTRAIT: built-in local fallback; no Steam avatar request.");
            return true;
        }

        public static string ResolveLocalPlayerName(PlatformID id)
        {
            if (!IsRequested()) throw new InvalidOperationException("Local player-name resolver used without the prototype flag.");
            if (id != LocalIdentity) return string.Empty;
            return PlatformSystems.userManager == null ? Environment.UserName : PlatformSystems.userManager.GetUserDisplayName(id);
        }

        public static bool TryInitializeNetworkManager(GameObject managerObject)
        {
            if (!IsRequested()) return false;
            if (!Ready) throw new InvalidOperationException("Offline platform must initialize before its network manager.");
            if (managerObject == null) throw new ArgumentNullException("managerObject");
            NetworkManagerSystem existing = managerObject.GetComponent<NetworkManagerSystem>();
            if (existing != null && !(existing is OfflineNetworkManager))
                throw new InvalidOperationException("An incompatible network manager is already attached: " + existing.GetType().FullName);
            var manager = existing as OfflineNetworkManager ?? managerObject.AddComponent<OfflineNetworkManager>();
            var configuration = managerObject.GetComponent<NetworkManagerConfiguration>();
            if (configuration == null) throw new InvalidOperationException("NetworkManagerConfiguration is missing from the recovered prefab.");
            PlatformSystems.networkManager = manager;
            manager.Init(configuration);
            NetworkServer.dontListen = true;
            Debug.Log("ARM64_OFFLINE_NETWORK_MANAGER_READY: HLAPI local host only.");
            return true;
        }

        private static void Shutdown()
        {
            if (!Ready) return;
            PlatformSystems.saveSystem.Shutdown();
            PlatformSystems.lobbyManager.Shutdown();
            Ready = false;
        }
    }
}
