using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using Rewired;
using RoR2;
using RoR2.UI;
using UnityEngine;

namespace RoR2Arm64
{
    // This is a layout repair for the observed macOS Unity-input Xbox device.
    // It never polls or injects input through a second controller backend.
    public sealed class MacInputCompatibility : MonoBehaviour
    {
        private const string MapName = "RoR2 macOS Xbox Unity layout v1";
        private static readonly Guid XboxGuid = new Guid("19002688-7406-4f4a-8340-8d25335406c8");
        private static readonly Guid TemplateGuid = new Guid("83b427e4-086f-47f3-bb06-be266abd1ca5");
        private static readonly BindingFlags Fields = BindingFlags.Instance | BindingFlags.NonPublic;
        private static MacInputCompatibility instance;
        private readonly HashSet<ControllerMap> inspectedMouseMaps = new HashSet<ControllerMap>();
        private readonly HashSet<ControllerMap> inspectedJoystickMaps = new HashSet<ControllerMap>();
        private readonly HashSet<string> reportedErrors = new HashSet<string>();
        private float nextScan;

        public static void InstallIfRequested()
        {
            if (Application.platform != RuntimePlatform.OSXPlayer || !ManagedSoloBootstrap.IsRequested() || instance) return;
            var owner = new GameObject("RoR2 Mac Input Compatibility");
            UnityEngine.Object.DontDestroyOnLoad(owner);
            instance = owner.AddComponent<MacInputCompatibility>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        private void Update()
        {
            if (!ReInput.isReady) return;
            int matchedId = -1, matchedCount = 0;
            foreach (Joystick joystick in ReInput.controllers.Joysticks)
                if (IsObservedXbox(joystick)) { matchedId = joystick.unityId; matchedCount++; }
            RoR2Arm64.Input.MacDpadInput.AuthorizeUnknownXbox(matchedCount == 1 ? matchedId : -1);
            if (Time.realtimeSinceStartup < nextScan) return;
            nextScan = Time.realtimeSinceStartup + 0.5f;
            if (InputMapperHelper.anyRemapperListening) return;
            bool changed = false;
            foreach (Player player in ReInput.players.Players)
            {
                try
                {
                    LocalUser localUser = LocalUserManager.FindLocalUser(player);
                    UserProfile profile = localUser == null ? null : localUser.userProfile;
                    if (profile != null) changed |= AddMissingMousePing(profile.mouseMap, player.id);
                    var maps = new List<ControllerMap>(player.controllers.maps.GetAllMaps());
                    foreach (ControllerMap map in maps)
                        if (map.controllerType == ControllerType.Mouse && map.categoryId == 0)
                            changed |= AddMissingMousePing(map, player.id);

                    foreach (Joystick joystick in player.controllers.Joysticks)
                    {
                        if (!IsObservedXbox(joystick)) continue;
                        NormalizeSignedTrigger(joystick, 4);
                        NormalizeSignedTrigger(joystick, 5);
                        ControllerMap game = FindMap(maps, joystick, 0);
                        ControllerMap menu = FindMap(maps, joystick, 2);
                        JoystickMap profileMap = RegisterProfileMap(profile, joystick, game);
                        // Wait for the selected profile before creating game
                        // defaults, so a saved Xbox remap wins on first login.
                        if (profileMap != null) changed |= EnsureMap(player, joystick, game, 0, profileMap);
                        changed |= EnsureMap(player, joystick, menu, 2, null);
                    }
                }
                catch (Exception exception)
                {
                    string key = player.id + ":" + exception.GetType().Name + ":" + exception.Message;
                    if (reportedErrors.Add(key)) Debug.LogWarning("MAC_INPUT_COMPATIBILITY_ERROR: " + key);
                }
            }
            if (changed && InputBindingDisplayController.onBindingsChanged != null)
                InputBindingDisplayController.onBindingsChanged();
        }

        private static bool IsObservedXbox(Joystick joystick)
        {
            return joystick.hardwareTypeGuid == Guid.Empty &&
                joystick.name.IndexOf("Xbox Wireless Controller", StringComparison.OrdinalIgnoreCase) >= 0 &&
                joystick.axisCount >= 8 && joystick.buttonCount >= 15;
        }

        private static ControllerMap FindMap(List<ControllerMap> maps, Joystick joystick, int category)
        {
            foreach (ControllerMap map in maps)
                if (map.controller == joystick && map.controllerType == ControllerType.Joystick &&
                    map.categoryId == category && map.layoutId == 0) return map;
            return null;
        }

        // Adding only missing profile entries lets the game's own remapper and
        // serializer retain changes. It otherwise refuses to save Guid.Empty.
        // Existing maps, including intentionally empty maps, are never replaced.
        private static JoystickMap RegisterProfileMap(UserProfile profile, Joystick joystick, ControllerMap activeGame)
        {
            if (profile == null || !RoR2Application.loadFinished) return null;
            if (profile.HardwareJoystickMaps2.Count == 0) profile.FillDefaultJoystickMaps();
            var defaults = DefaultControllerMaps.GetDefaultJoystickMaps();
            JoystickMap originalDefault = ReadOriginalMap(XboxGuid, 0);
            if (originalDefault == null) return null;
            // Register on every process lifetime, including when this profile
            // already has a saved Mac map, so Reset to Defaults remains valid.
            if (!defaults.ContainsKey(Guid.Empty)) defaults.Add(Guid.Empty, ConvertMap(originalDefault, joystick));
            JoystickMap saved;
            if (profile.HardwareJoystickMaps2.TryGetValue(Guid.Empty, out saved))
            {
                if (saved.hardwareGuid == Guid.Empty) return saved;
                // Preserve bindings from a source-layout map mistakenly saved
                // against unknown hardware, but translate their physical IDs.
                saved = ConvertMap(saved, joystick);
                profile.HardwareJoystickMaps2[Guid.Empty] = saved;
                return saved;
            }
            JoystickMap source;
            if (profile.HardwareJoystickMaps2.TryGetValue(XboxGuid, out source))
            {
                source = new JoystickMap(source);
                SetField(source, "_hardwareGuid", XboxGuid);
            }
            else source = originalDefault;
            if (activeGame != null && activeGame.AllMaps.Count > 0 && activeGame.hardwareGuid == Guid.Empty && activeGame.name != MapName)
                saved = new JoystickMap((JoystickMap)activeGame);
            else
            {
                saved = ConvertMap(source, joystick);
            }
            profile.HardwareJoystickMaps2.Add(Guid.Empty, saved);
            Debug.Log("MAC_XBOX_PROFILE_MAP: registered missing mapping; existing profile mappings preserved");
            return saved;
        }

        private bool EnsureMap(Player player, Joystick joystick, ControllerMap existing, int category, JoystickMap saved)
        {
            // An explicitly saved empty map is an intentional user choice.
            if (category == 0 && saved != null && saved.AllMaps.Count == 0) return false;
            if (existing != null)
            {
                if (inspectedJoystickMaps.Contains(existing)) return false;
                // RoR2 applies an Xbox hardware map to this unknown device.
                // Rewired drops its incompatible button identifiers, leaving
                // six axes: nonempty is not proof of a valid physical layout.
                if (existing.AllMaps.Count != 0 && existing.hardwareGuid != XboxGuid && existing.hardwareGuid != TemplateGuid)
                {
                    inspectedJoystickMaps.Add(existing);
                    return false;
                }
            }
            JoystickMap replacement;
            if (category == 0 && saved != null)
                replacement = new JoystickMap(saved);
            else
            {
                Guid sourceGuid = category == 0 ? XboxGuid : TemplateGuid;
                JoystickMap source = ReadOriginalMap(sourceGuid, category);
                if (source == null) return false;
                replacement = ConvertMap(source, joystick);
            }
            if (existing != null) inspectedJoystickMaps.Add(existing);
            replacement.enabled = existing == null || existing.enabled;
            player.controllers.maps.AddMap(joystick, replacement);
            Debug.Log("MAC_XBOX_LAYOUT: player=" + player.id + " category=" + category + " bindings=" + replacement.AllMaps.Count);
            return true;
        }

        private bool AddMissingMousePing(ControllerMap map, int playerId)
        {
            if (map == null || map.controllerType != ControllerType.Mouse || map.categoryId != 0 ||
                !inspectedMouseMaps.Add(map)) return false;
            foreach (ActionElementMap binding in map.AllMaps)
            {
                // A user-chosen Ping binding or occupied middle button wins.
                if (binding.actionId == 28 ||
                    (binding.elementType == ControllerElementType.Button && binding.elementIdentifierId == 5)) return false;
            }
            ActionElementMap created;
            if (!map.CreateElementMap(28, Pole.Positive, 5, ControllerElementType.Button, AxisRange.Full, false, out created))
                throw new InvalidOperationException("Could not add missing middle mouse Ping");
            Debug.Log("MAC_MOUSE_PING: player=" + playerId + " added missing middle mouse binding");
            return true;
        }

        private static void NormalizeSignedTrigger(Joystick joystick, int axisIndex)
        {
            AxisCalibration calibration = joystick.calibrationMap.GetAxis(axisIndex);
            if (calibration == null || !calibration.enabled || calibration.invert) return;
            // Do not recalibrate custom ranges, and do not infer the resting
            // value from a held trigger. The observed device releases at -1.
            if (Math.Abs(calibration.calibratedZero) > 0.001f ||
                Math.Abs(calibration.calibratedMin + 1f) > 0.001f ||
                Math.Abs(calibration.calibratedMax - 1f) > 0.001f ||
                joystick.GetAxisRaw(axisIndex) > -0.9f) return;
            calibration.calibratedZero = -1f;
            calibration.applyRangeCalibration = true;
            Debug.Log("MAC_XBOX_TRIGGER: axis=" + axisIndex + " release=-1 calibrated=0 pressed=1");
        }

        private static JoystickMap ConvertMap(JoystickMap source, Joystick joystick)
        {
            if (source == null || (source.hardwareGuid != XboxGuid && source.hardwareGuid != TemplateGuid))
                throw new InvalidOperationException("Unsupported source layout for Mac Xbox conversion: " +
                    (source == null ? "null" : source.hardwareGuid + "/" + source.categoryId + "/" + source.AllMaps.Count));
            bool template = source.hardwareGuid == TemplateGuid;
            var result = new JoystickMap();
            SetField(result, "_hardwareGuid", Guid.Empty);
            SetField(result, "_categoryId", source.categoryId);
            SetField(result, "_layoutId", source.layoutId);
            SetField(result, "_name", MapName);
            foreach (ActionElementMap binding in source.AllMaps)
            {
                if (binding.actionId < 0) continue;
                int index;
                ControllerElementType type;
                AxisRange range;
                bool invert;
                TranslateElement(template, binding.elementType, binding.elementIdentifierId,
                    binding.axisRange, binding.invert, out type, out index, out range, out invert);
                int identifier = ElementId(joystick, type, index);
                if (identifier < 0) throw new InvalidOperationException("Missing Mac Xbox element " + type + " " + index);
                ActionElementMap converted;
                if (!result.CreateElementMap(binding.actionId, binding.axisContribution, identifier, type, range, invert, out converted))
                    throw new InvalidOperationException("Could not convert Mac Xbox action " + binding.actionId);
                // This shipped Rewired overload does not consume its invert
                // argument. The public property applies it after construction.
                converted.invert = invert;
                converted.enabled = binding.enabled;
            }
            return result;
        }

        private static JoystickMap ReadOriginalMap(Guid guid, int category)
        {
            // GetJoystickMapInstance performs hardware-template conversion for
            // the active backend, which drops the template's elements when that
            // backend does not recognize Xbox. Read the original prefab map.
            var manager = UnityEngine.Object.FindObjectOfType<InputManager>();
            if (!manager || manager.userData == null) return null;
            var original = manager.userData.GetJoystickMap(category, guid, 0);
            if (original == null || original.hardwareGuid != guid || original.categoryId != category || original.layoutId != 0)
                return null;
            var result = new JoystickMap();
            SetField(result, "_hardwareGuid", guid);
            SetField(result, "_categoryId", category);
            SetField(result, "_layoutId", 0);
            foreach (ActionElementMap binding in original.actionElementMaps)
            {
                if (binding.actionId < 0) continue;
                ActionElementMap copied;
                if (!result.CreateElementMap(binding.actionId, binding.axisContribution, binding.elementIdentifierId,
                    binding.elementType, binding.axisRange, binding.invert, out copied))
                    throw new InvalidOperationException("Could not read original controller map");
                copied.invert = binding.invert;
                copied.enabled = binding.enabled;
            }
            return result;
        }

        // Public for the offline semantic-map acceptance check. Index means raw
        // Unity joystick index; ElementId resolves it to actual Rewired IDs.
        public static void TranslateElement(bool template, ControllerElementType sourceType, int sourceId,
            AxisRange sourceRange, bool sourceInvert, out ControllerElementType type, out int index,
            out AxisRange range, out bool invert)
        {
            type = sourceType;
            range = sourceRange;
            invert = sourceInvert;
            index = -1;
            if (sourceType == ControllerElementType.Axis && sourceId >= 0 && sourceId <= 3)
            {
                index = sourceId;
                if (sourceId == 1 || sourceId == 3)
                {
                    // Split axes select the raw half before inversion.
                    if (range == AxisRange.Positive) range = AxisRange.Negative;
                    else if (range == AxisRange.Negative) range = AxisRange.Positive;
                    else invert = !invert;
                }
                return;
            }
            if ((!template && sourceType == ControllerElementType.Axis && (sourceId == 4 || sourceId == 5)) ||
                (template && (sourceId == 11 || sourceId == 13)))
            {
                type = ControllerElementType.Axis;
                index = template ? (sourceId == 11 ? 4 : 5) : sourceId;
                range = AxisRange.Positive;
                return;
            }
            if (sourceType != ControllerElementType.Button)
                throw new InvalidOperationException("Unknown source axis " + sourceId);

            if (template)
            {
                switch (sourceId)
                {
                    case 4: index = 0; break; // A
                    case 5: index = 1; break; // B
                    case 7: index = 3; break; // X
                    case 8: index = 4; break; // Y
                    case 10: index = 6; break; // LB
                    case 12: index = 7; break; // RB
                    case 14: index = 10; break; // View
                    case 15: index = 11; break; // Menu
                    case 17: index = 13; break; // L3
                    case 18: index = 14; break; // R3
                    case 19: Dpad(7, AxisRange.Negative, out type, out index, out range); break; // Up
                    case 20: Dpad(6, AxisRange.Positive, out type, out index, out range); break; // Right
                    case 21: Dpad(7, AxisRange.Positive, out type, out index, out range); break; // Down
                    case 22: Dpad(6, AxisRange.Negative, out type, out index, out range); break; // Left
                }
            }
            else
            {
                switch (sourceId)
                {
                    case 6: index = 0; break;
                    case 7: index = 1; break;
                    case 8: index = 3; break;
                    case 9: index = 4; break;
                    case 10: index = 6; break;
                    case 11: index = 7; break;
                    case 12: index = 10; break;
                    case 13: index = 11; break;
                    case 14: index = 13; break;
                    case 15: index = 14; break;
                    case 16: Dpad(7, AxisRange.Negative, out type, out index, out range); break;
                    case 17: Dpad(6, AxisRange.Positive, out type, out index, out range); break;
                    case 18: Dpad(7, AxisRange.Positive, out type, out index, out range); break;
                    case 19: Dpad(6, AxisRange.Negative, out type, out index, out range); break;
                }
            }
            if (index < 0) throw new InvalidOperationException("Unknown source button " + sourceId);
        }

        private static void Dpad(int rawAxis, AxisRange rawRange, out ControllerElementType type, out int index, out AxisRange range)
        {
            type = ControllerElementType.Axis;
            index = rawAxis;
            range = rawRange;
        }

        private static int ElementId(Joystick joystick, ControllerElementType type, int index)
        {
            if (type == ControllerElementType.Axis)
            {
                foreach (ControllerElementIdentifier element in joystick.AxisElementIdentifiers)
                    if (joystick.GetAxisIndexById(element.id) == index) return element.id;
            }
            else
            {
                foreach (ControllerElementIdentifier element in joystick.ButtonElementIdentifiers)
                    if (joystick.GetButtonIndexById(element.id) == index) return element.id;
            }
            return -1;
        }

        private static void SetField(ControllerMap map, string name, object value)
        {
            FieldInfo field = typeof(ControllerMap).GetField(name, Fields);
            if (field == null) throw new MissingFieldException("Rewired.ControllerMap", name);
            field.SetValue(map, value);
        }
    }
}
