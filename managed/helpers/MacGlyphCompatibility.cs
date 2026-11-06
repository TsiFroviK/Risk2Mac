using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using Rewired;
using RoR2;
using RoR2.UI;
using UnityEngine;

namespace RoR2Arm64
{
    // Glyphs keys its stock sprite table by device name and physical element ID.
    // Unity's unknown Xbox uses different IDs; alias only that observed layout.
    public sealed class MacGlyphCompatibility : MonoBehaviour
    {
        private static MacGlyphCompatibility instance;
        private readonly HashSet<Joystick> inspected = new HashSet<Joystick>();
        private float nextScan;
        private bool failed;

        public static void InstallIfRequested()
        {
            if (Application.platform != RuntimePlatform.OSXPlayer || !ManagedSoloBootstrap.IsRequested() || instance) return;
            var owner = new GameObject("RoR2 Mac Xbox Glyph Compatibility");
            UnityEngine.Object.DontDestroyOnLoad(owner);
            instance = owner.AddComponent<MacGlyphCompatibility>();
        }

        private void Update()
        {
            if (failed || !ReInput.isReady || !RoR2Application.loadFinished || Time.realtimeSinceStartup < nextScan) return;
            nextScan = Time.realtimeSinceStartup + 0.5f;
            try
            {
                bool changed = false;
                foreach (Joystick joystick in ReInput.controllers.Joysticks)
                {
                    if (joystick.hardwareTypeGuid != Guid.Empty || joystick.axisCount < 8 || joystick.buttonCount < 15 ||
                        (!string.Equals(joystick.name, "Microsoft Xbox Wireless Controller", StringComparison.OrdinalIgnoreCase) &&
                         !string.Equals(joystick.name, "Xbox Wireless Controller", StringComparison.OrdinalIgnoreCase)) ||
                        inspected.Contains(joystick)) continue;
                    changed |= AddAliases(joystick);
                    inspected.Add(joystick);
                }
                if (changed)
                {
                    MPEventSystem.RefreshAllControllerGlyphs();
                    if (InputBindingDisplayController.onBindingsChanged != null) InputBindingDisplayController.onBindingsChanged();
                }
            }
            catch (Exception exception)
            {
                failed = true;
                Debug.LogWarning("MAC_XBOX_GLYPHS_UNAVAILABLE: " + exception.GetType().Name + ": " + exception.Message);
            }
        }

        private static bool AddAliases(Joystick joystick)
        {
            Type keyType = typeof(Glyphs).GetNestedType("GlyphKey", BindingFlags.NonPublic);
            FieldInfo mapField = typeof(Glyphs).GetField("glyphMap", BindingFlags.NonPublic | BindingFlags.Static);
            if (keyType == null || mapField == null) throw new MissingMemberException("Expected shipped Glyphs table not found");
            ConstructorInfo constructor = keyType.GetConstructor(new Type[] { typeof(string), typeof(int) });
            IDictionary table = mapField.GetValue(null) as IDictionary;
            if (constructor == null || table == null) throw new InvalidOperationException("Unexpected shipped Glyphs table shape");

            // Source strings remain owned by the game's original Xbox sprite table.
            // Resolve every source and physical ID before adding any aliases.
            var aliases = new Dictionary<int, string>();
            for (int axis = 0; axis < 6; axis++)
                aliases.Add(ElementId(joystick, ControllerElementType.Axis, axis), ReadOriginal(table, constructor, axis));
            int[] rawButtons = { 0, 1, 3, 4, 6, 7, 10, 11, 13, 14 };
            int[] originalButtons = { 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 };
            for (int i = 0; i < rawButtons.Length; i++)
                aliases.Add(ElementId(joystick, ControllerElementType.Button, rawButtons[i]), ReadOriginal(table, constructor, originalButtons[i]));

            // The stock lookup has no axis-half key. A two-arrow glyph describes
            // each shared D-pad axis without falsely labelling both halves alike.
            aliases.Add(ElementId(joystick, ControllerElementType.Axis, 6),
                ReadOriginal(table, constructor, 19) + ReadOriginal(table, constructor, 17));
            aliases.Add(ElementId(joystick, ControllerElementType.Axis, 7),
                ReadOriginal(table, constructor, 16) + ReadOriginal(table, constructor, 18));

            int added = 0;
            foreach (KeyValuePair<int, string> alias in aliases)
            {
                object key = constructor.Invoke(new object[] { joystick.name, alias.Key });
                if (table.Contains(key)) continue; // Preserve an existing/custom glyph.
                table.Add(key, alias.Value);
                added++;
            }
            Debug.Log("MAC_XBOX_GLYPHS: name=" + joystick.name + " aliases=" + added + " source=original Xbox sprites");
            return added > 0;
        }

        private static string ReadOriginal(IDictionary table, ConstructorInfo constructor, int originalId)
        {
            object key = constructor.Invoke(new object[] { DefaultControllerMaps.xboxOneControllerName, originalId });
            string glyph = table[key] as string;
            if (string.IsNullOrEmpty(glyph)) throw new InvalidOperationException("Missing original Xbox glyph " + originalId);
            return glyph;
        }

        private static int ElementId(Joystick joystick, ControllerElementType type, int rawIndex)
        {
            if (type == ControllerElementType.Axis)
            {
                foreach (ControllerElementIdentifier element in joystick.AxisElementIdentifiers)
                    if (joystick.GetAxisIndexById(element.id) == rawIndex) return element.id;
            }
            else
            {
                foreach (ControllerElementIdentifier element in joystick.ButtonElementIdentifiers)
                    if (joystick.GetButtonIndexById(element.id) == rawIndex) return element.id;
            }
            throw new InvalidOperationException("Missing observed Xbox glyph element " + type + " " + rawIndex);
        }
    }
}
