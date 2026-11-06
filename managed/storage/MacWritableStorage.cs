using System;
using System.IO;
using UnityEngine;

namespace RoR2Arm64.Storage
{
    // Only legacy mutable directories move. Addressables and the process working
    // directory keep their existing, independently validated bundle paths.
    public static class MacWritableStorage
    {
        private const string ActivationFlag = "--arm64-solo-probe";
        private const string SeedMarker = ".seed-complete-v1";
        private static readonly object Sync = new object();
        private static readonly string[] MutableDirectories = { "Config", "Mods", "RunReports" };
        private static string preparedRoot;

        public static string ApplicationFileSystemRoot()
        {
            return IsEnabled() ? EnsureRoot() : Application.dataPath;
        }

        public static string ModLoaderWorkingDirectory()
        {
            return IsEnabled() ? EnsureRoot() : Environment.CurrentDirectory;
        }

        public static string ConVarCacheRoot()
        {
            if (!IsEnabled()) return Application.streamingAssetsPath;
            string root = Path.Combine(EnsureRoot(), "ConVarCache");
            Directory.CreateDirectory(root);
            string source = Path.Combine(Application.streamingAssetsPath, "ConVarNames.txt");
            // The generated cache has synchronous and coroutine readers. Seed
            // this one file for either reader; the stock writer then refreshes it.
            if (File.Exists(source) && !IsLink(source))
                SeedFile(source, Path.Combine(root, "ConVarNames.txt"));
            return root;
        }

        private static bool IsEnabled()
        {
            if (Application.platform != RuntimePlatform.OSXPlayer) return false;
            foreach (string argument in Environment.GetCommandLineArgs())
                if (string.Equals(argument, ActivationFlag, StringComparison.Ordinal)) return true;
            return false;
        }

        private static string EnsureRoot()
        {
            lock (Sync)
            {
                if (preparedRoot != null) return preparedRoot;
                string source = Path.GetFullPath(Application.dataPath);
                string root = Path.GetFullPath(Path.Combine(Application.persistentDataPath, "ARM64Solo", "Runtime"));
                bool previouslySeeded = File.Exists(Path.Combine(root, SeedMarker));
                int count = PrepareRoot(source, root);
                preparedRoot = root;
                Debug.Log("ARM64_MAC_WRITABLE_STATE: root=" + root + " source=" + source +
                    " seededFiles=" + count + " previousSeed=" + previouslySeeded);
                return root;
            }
        }

        // Also exercised directly by the bounded IO test, using the production
        // implementation and ordinary files instead of a running Unity player.
        private static int PrepareRoot(string source, string destination)
        {
            source = Path.GetFullPath(source);
            destination = Path.GetFullPath(destination);
            string sourcePrefix = source.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (destination == source || destination.StartsWith(sourcePrefix, StringComparison.Ordinal))
                throw new InvalidOperationException("Writable state must be outside the application bundle.");
            Directory.CreateDirectory(destination);
            if (IsLink(destination)) throw new IOException("Writable state root must not be a symbolic link: " + destination);
            foreach (string directory in MutableDirectories)
                Directory.CreateDirectory(Path.Combine(destination, directory));

            string marker = Path.Combine(destination, SeedMarker);
            if (File.Exists(marker)) return 0;
            int written = 0;
            foreach (string directory in MutableDirectories)
                written += SeedDirectory(Path.Combine(source, directory), Path.Combine(destination, directory));

            // A failed/interrupted migration leaves no marker. Retrying fills
            // missing files without overwriting anything the user already saved.
            try
            {
                using (var stream = new FileStream(marker, FileMode.CreateNew, FileAccess.Write, FileShare.Read))
                using (var writer = new StreamWriter(stream)) writer.WriteLine("RoR2 macOS mutable state v1");
            }
            catch (IOException) { if (!File.Exists(marker)) throw; }
            return written;
        }

        private static int SeedDirectory(string source, string destination)
        {
            if (!Directory.Exists(source) || IsLink(source)) return 0;
            Directory.CreateDirectory(destination);
            if (IsLink(destination)) throw new IOException("Seed destination must not be a symbolic link: " + destination);
            int written = 0;
            foreach (string path in Directory.GetFiles(source))
            {
                if (IsLink(path)) continue;
                string target = Path.Combine(destination, Path.GetFileName(path));
                if (SeedFile(path, target)) written++;
            }
            foreach (string path in Directory.GetDirectories(source))
                if (!IsLink(path)) written += SeedDirectory(path, Path.Combine(destination, Path.GetFileName(path)));
            return written;
        }

        private static bool SeedFile(string source, string target)
        {
            if (File.Exists(target)) return false;
            string temporary = target + ".seed-" + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read))
                using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    input.CopyTo(output);
                try { File.Move(temporary, target); return true; }
                catch (IOException) { if (!File.Exists(target)) throw; }
                return false;
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        private static bool IsLink(string path)
        {
            return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
        }
    }
}
