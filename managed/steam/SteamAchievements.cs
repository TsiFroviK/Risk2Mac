using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Facepunch.Steamworks;
using UnityEngine;

namespace Risk2Mac
{
    public static class SteamAchievements
    {
        private enum StageResult { Retry, AlreadyUnlocked, Staged, Unknown }

        private static readonly HashSet<string> pending = new HashSet<string>(StringComparer.Ordinal);
        private static Client owner;
        private static ulong ownerId;
        private static int staged;
        private static float nextAttempt;

        [DllImport("Risk2MacSteamBridge", CallingConvention = CallingConvention.Cdecl)]
        private static extern StageResult Risk2MacSteamStageAchievement(string name);

        [DllImport("Risk2MacSteamBridge", CallingConvention = CallingConvention.Cdecl)]
        private static extern int Risk2MacSteamStoreAchievements();

        public static void Enqueue(string name)
        {
            if (string.IsNullOrEmpty(name) || !SteamCompatibility.IsSteamMode) return;
            var client = Client.Instance;
            if (client == null || !client.IsValid || client.AppId != 632360U || client.SteamId == 0) return;
            if (client != owner || client.SteamId != ownerId)
            {
                pending.Clear();
                staged = 0;
                nextAttempt = 0;
                owner = client;
                ownerId = client.SteamId;
            }
            pending.Add(name);
        }

        public static void Flush()
        {
            if (pending.Count == 0 && staged == 0) return;
            var client = Client.Instance;
            if (client == null || client != owner || client.SteamId != ownerId || !client.IsValid || !client.IsLoggedOn)
                return;
            float now = Time.realtimeSinceStartup;
            if (now < nextAttempt) return;

            // Profile login can replay multiple awards in the same frame.
            var batch = new List<string>(pending);
            foreach (string name in batch)
            {
                StageResult result = Risk2MacSteamStageAchievement(name);
                if (result == StageResult.Retry) continue;
                pending.Remove(name);
                if (result == StageResult.Staged) staged++;
            }

            // SetAchievement changes the local Steam cache. Keep a failed store
            // pending even if GetAchievement already reports those IDs unlocked.
            if (staged > 0 && Risk2MacSteamStoreAchievements() == 1)
            {
                Debug.Log("RISK2MAC_STEAM_ACHIEVEMENTS_SUBMITTED: " + staged);
                staged = 0;
            }
            nextAttempt = now + (pending.Count != 0 || staged != 0 ? 10f : 1f);
        }
    }
}
