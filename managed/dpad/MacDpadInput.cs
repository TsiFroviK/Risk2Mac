using System;
using System.Runtime.InteropServices;
using UnityEngine;

// Input-boundary repair only. No Rewired dependency or alternate controller maps.
namespace RoR2Arm64.Input
{
    public static class MacDpadInput
    {
        [DllImport("RoR2MacDpad", CallingConvention = CallingConvention.Cdecl)]
        private static extern int ror2_mac_dpad(out float x, out float y);
        private static int authorizedId = -1, authorizedFrame = -100, polledFrame = -100;
        private static bool failed, announced, usable;
        private static float horizontal, vertical;

        // The compatibility owner checks Rewired's unknown-hardware identity.
        // This authorization is renewed every frame and expires if that owner stops.
        public static void AuthorizeUnknownXbox(int unityJoystickId)
        {
            if (authorizedId != unityJoystickId)
            {
                horizontal = vertical = 0;
                polledFrame = -100;
            }
            authorizedId = unityJoystickId;
            authorizedFrame = Time.frameCount;
        }

        public static bool TryReadAxis(int unityJoystickId, int axisIndex, out float value)
        {
            value = 0;
            if (Application.platform != RuntimePlatform.OSXPlayer || failed ||
                (axisIndex != 6 && axisIndex != 7) || unityJoystickId <= 0 ||
                unityJoystickId != authorizedId || Time.frameCount - authorizedFrame > 2) return false;
            try
            {
                if (polledFrame != Time.frameCount)
                {
                    polledFrame = Time.frameCount;
                    usable = false;
                    horizontal = vertical = 0;
                    string[] names = UnityEngine.Input.GetJoystickNames();
                    int count = 0, slot = -1;
                    for (int i = 0; i < names.Length; i++)
                        if (IsXboxName(names[i])) { count++; slot = i + 1; }
                    // Do not redirect another device that reuses a disconnected slot.
                    if (count != 1 || slot != authorizedId) return false;
                    float x, y;
                    int nativeCount = ror2_mac_dpad(out x, out y);
                    if (nativeCount > 1) return false;
                    usable = true;
                    // When native enumeration has not caught up, consume a neutral
                    // value instead of returning Unity's known stuck hat state.
                    if (nativeCount == 1 && Application.isFocused)
                    {
                        horizontal = Mathf.Clamp(x, -1f, 1f);
                        vertical = -Mathf.Clamp(y, -1f, 1f);
                        if (!announced)
                        {
                            announced = true;
                            Debug.Log("MAC_XBOX_DPAD_NATIVE: matched unknown Xbox; axes6=x axis7=-y; original maps retained");
                        }
                    }
                }
                if (!usable) return false;
                value = axisIndex == 6 ? horizontal : vertical;
                return true;
            }
            catch (Exception exception)
            {
                failed = true;
                Debug.LogWarning("MAC_XBOX_DPAD_UNAVAILABLE: " + exception.GetType().Name + ": " + exception.Message);
                return false;
            }
        }

        private static bool IsXboxName(string name)
        {
            return string.Equals(name, "Microsoft Xbox Wireless Controller", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(name, "Xbox Wireless Controller", StringComparison.OrdinalIgnoreCase);
        }
    }
}
