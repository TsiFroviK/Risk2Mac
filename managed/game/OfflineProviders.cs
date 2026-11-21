using System;
using System.Collections.Generic;
using System.IO;
using RoR2;
using RoR2.EntitlementManagement;
using UnityEngine;
using PlatformID = RoR2.PlatformID;
using Path = System.IO.Path;

namespace RoR2Arm64.Offline
{
    public sealed class OfflineUserManager : UserManager
    {
        public override int GetUserID() { return 1; }
        public override string GetUserName()
        {
            LocalUser user = LocalUserManager.GetFirstLocalUser();
            string profileName = user == null || user.userProfile == null ? null : user.userProfile.name;
            return string.IsNullOrEmpty(profileName) ? Environment.UserName : profileName;
        }
        public override string GetUserName(PlatformID id) { return id == OfflinePlatform.LocalIdentity ? GetUserName() : string.Empty; }
        public override string GetUserDisplayName(PlatformID id) { return GetUserName(id); }
        public override void GetAvatar(PlatformID id, GameObject sender, Texture2D texture, AvatarSize size, Action<Texture2D> callback)
        {
            if (callback != null) callback(null);
        }
    }

    // The shipped SaveSystemSteam implementation serializes profiles locally
    // through their supplied Zio IFileSystem. Its only live Steam access is the
    // username getter, overridden here. It is not a Steam/cloud provider now.
    public sealed class OfflineSaveSystem : SaveSystemSteam
    {
        public override string GetPlatformUsernameOrDefault(string defaultName)
        {
            string name = Environment.UserName;
            return string.IsNullOrEmpty(name) ? defaultName : name;
        }

        public override void SaveHistory(byte[] data, string fileName)
        {
            if (data == null) throw new ArgumentNullException("data");
            string folder = Path.Combine(OfflinePlatform.SaveRoot, "History");
            Directory.CreateDirectory(folder);
            File.WriteAllBytes(Path.Combine(folder, Path.GetFileName(fileName)), data);
        }

        public override Dictionary<string, byte[]> LoadHistory()
        {
            var result = new Dictionary<string, byte[]>();
            string folder = Path.Combine(OfflinePlatform.SaveRoot, "History");
            if (!Directory.Exists(folder)) return result;
            foreach (string file in Directory.GetFiles(folder)) result[Path.GetFileName(file)] = File.ReadAllBytes(file);
            return result;
        }
    }

    public sealed class OfflineAchievementSystem : AchievementSystem
    {
        public override void AddAchievement(string achievementName)
        {
            // RoR2's UserProfile owns local achievement/progression persistence.
            // This method is the platform-service reporting hook only.
            Debug.Log("ARM64_OFFLINE_ACHIEVEMENT: no external platform report: " + achievementName);
        }
    }

    public sealed class OfflinePlatformManager : PlatformManager
    {
        public override bool IsNetworkAvailable() { return false; }
    }

    public sealed class OfflineEntitlements : IUserEntitementsResolverNetworkAndLocal
    {
        public event Action OnPlatformShopClosed { add { } remove { } }
        event Action IUserEntitlementResolver<LocalUser>.onEntitlementsChanged { add { } remove { } }
        event Action IUserEntitlementResolver<NetworkUser>.onEntitlementsChanged { add { } remove { } }
        bool IUserEntitlementResolver<LocalUser>.CheckUserHasEntitlement(LocalUser user, EntitlementDef entitlement) { return false; }
        bool IUserEntitlementResolver<NetworkUser>.CheckUserHasEntitlement(NetworkUser user, EntitlementDef entitlement) { return false; }
        public string[] BuildEntitlements() { return new string[0]; }
        public void LaunchPlatformShop(EntitlementDef entitlement) { throw new NotSupportedException("Platform store is unavailable in the offline prototype."); }
        public void LaunchPlatformShopAllProducts() { throw new NotSupportedException("Platform store is unavailable in the offline prototype."); }
    }

    public sealed class OfflineLobbyManager : LobbyManager
    {
        public override int calculatedTotalPlayerCount { get; protected set; }
        public override int calculatedExtraPlayersCount { get; protected set; }
        public override bool isInLobby { get; protected set; }
        public override bool ownsLobby { get; protected set; }
        public override bool IsBusy { get; set; }
        public override bool hasMinimumPlayerCount { get { return LocalUserManager.isAnyUserSignedIn; } }
        public override LobbyType currentLobbyType { get; set; }
        public override LobbyData newestLobbyData { get; protected set; }
        public OfflineLobbyManager() { newestLobbyData = new LobbyData(); }
        public override MPFeatures GetPlatformMPFeatureFlags() { return MPFeatures.None; }
        public override MPLobbyFeatures GetPlatformMPLobbyFeatureFlags() { return MPLobbyFeatures.None; }
        public override int GetLobbyMemberPlayerCountByIndex(int memberIndex) { return 0; }
        private static NotSupportedException Unavailable() { return new NotSupportedException("Online lobbies, matchmaking and invites are unavailable in the offline prototype."); }
        public override void CreateLobby() { throw Unavailable(); }
        public override string GetLobbyID() { return string.Empty; }
        public override bool IsNetworkTypeInternet() { return false; }
        public override void LeaveLobby() { isInLobby = false; ownsLobby = false; }
        public override void JoinLobby(PlatformID join) { throw Unavailable(); }
        public override void OnStartPrivateGame() { throw Unavailable(); }
        public override void AutoMatchmake() { throw Unavailable(); }
        public override void ToggleQuickplay() { throw Unavailable(); }
        public override void OnCutoffTimerComplete() { throw Unavailable(); }
        public override bool ShouldEnableQuickplayButton() { return false; }
        public override bool IsLobbyOwner(PlatformID user) { return false; }
        public override string GetUserDisplayName(PlatformID user) { return PlatformSystems.userManager.GetUserDisplayName(user); }
        public override bool IsLobbyOwner() { return false; }
        public override PlatformID[] GetLobbyMembers() { return new PlatformID[0]; }
        public override int GetLobbyMemberCount() { return 0; }
        public override bool ShouldShowPromoteButton() { return false; }
        public override void CheckIfInitializedAndValid() { if (!OfflinePlatform.Ready) throw new InvalidOperationException("Offline platform has not initialized."); }
        public override void CheckIfInvited() { }
        public override bool CanInvite() { return false; }
        public override void CheckBusyTimer() { }
        public override bool ShouldEnableStartPrivateGameButton() { return false; }
    }
}
