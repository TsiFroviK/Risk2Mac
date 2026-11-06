# Native inputs

[Русская версия](README.ru.md)

Risk2Mac uses the macOS Mono player from **Unity 2023.1.0f1** and the **Wwise Unity Integration 2024.1.18 Release** macOS plugin. Obtain these inputs under your own vendor terms. Keep them in your private build directory outside the Git checkout.

Install the exact Unity version and its macOS Mono build support through Unity Hub. A standard installation at `/Applications/Unity/Hub/Editor/2023.1.0f1` is detected automatically. For a different installation, place or link its `MacStandaloneSupport` directory at `<private>/native/UnityMacSupport`. The source directory must contain the following components.

```text
MacStandaloneSupport/
  Variations/macos_x64arm64_player_nondevelopment_mono/UnityPlayer.app/
  MonoBleedingEdge/etc/
  Source/Player/MacPlayer/MacPlayerEntryPoint/Resources/MainMenu.nib/
```

The stage can also use the corresponding single-architecture non-development Mono variation, `macos_arm64_player_nondevelopment_mono` or `macos_x64_player_nondevelopment_mono`. See the [Unity Editor archive](https://unity.com/releases/editor/archive).

Get the matching `Unity.Mac.tar.xz` using your Audiokinetic Launcher installation or your licensed integration download. Put it at `<private>/native/wwise/Unity.Mac.tar.xz`. A previously extracted Release `AkUnitySoundEngine.bundle` from the same archive can go at `<private>/native/wwise/AkUnitySoundEngine.bundle`. The stage verifies the known Release executable hash before selecting a slice. See [Audiokinetic downloads](https://www.audiokinetic.com/en/download/).

Run `xcode-select --install` if the Xcode Command Line Tools are missing. The stage uses `lipo` to select the requested architecture in each Unity and Wwise binary and builds the D-pad bridge from the Objective-C source in this repository. The bridge is built with a macOS 11 deployment target. The final assembly stage signs the complete application. See [Apple command-line tools installation](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools).

If you already have the exact private port build and are authorized to use its components locally, you can extract just its native inputs. Run this from the repository root with a new destination for the `native` subdirectory.

```bash
bash scripts/build-native-inputs.sh \
  --port-app "/path/to/Risk of Rain 2.app" \
  --private "/path/to/private-build-inputs"
```

The helper copies the Unity player and its four framework libraries, Mono configuration, two Unity resources, and the Wwise bundle. Store that output privately. The public repository contains the builder and D-pad bridge source.

The top-level builder calls the native stage automatically. For separate stage use, run the following command against a fresh staging application. You can add `--unity-support /path/to/MacStandaloneSupport` or `--wwise /path/to/Unity.Mac.tar.xz` to override the default locations.

```bash
bash scripts/build-native.sh \
  --game "/path/to/Windows/Risk of Rain 2" \
  --app "/path/to/staging/Risk of Rain 2.app" \
  --private "/path/to/private-build-inputs" \
  --arch arm64
```

Use `x86_64` for Intel. Native components alone are an intermediate. Complete the asset, managed and signing stages using the main build instructions.
