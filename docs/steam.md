# Steam integration

[Русская инструкция](steam.ru.md)

The optional Steam build connects the native macOS player to the Steam client installed on that Mac. It uses the account that owns Risk of Rain 2, checks DLC ownership against the content present in the local build, and selects the game's Steam profile storage. The native compatibility library adapts the game's older Steamworks interfaces to the current client.

## Prepare and build

Install the Steam client, prepare the matching Windows game folder and set up Unity and Wwise. The graphical Builder enables Steam integration by default. [Build requirements](../README.md#requirements)

To build from Terminal, enter the Risk2Mac repository and run the following command with your game path.

```bash
GAME="/path/to/Windows/Risk of Rain 2"
bash build.sh --game "$GAME" --steam
```

The builder downloads the matching legacy SDK headers from a pinned Facepunch commit, verifies each SHA-256 against `native/steam-legacy-headers.json` and generates the native wrappers locally. The headers retain Valve's copyright and the applicable Steamworks SDK terms. [Pinned upstream headers](https://github.com/Facepunch/Facepunch.Steamworks/tree/605054339ad88fd09eeb7e0a82ca0eb78737b334/Generator/steam_sdk) · [Steamworks SDK documentation](https://partner.steamgames.com/doc/sdk)

With `--steam`, the builder chooses Steam's library and writes `steamapps/common/Risk of Rain 2/Risk of Rain 2.app`. It uses Steam's registered game directory when present, otherwise the default library. To choose another library already listed under **Steam → Settings → Storage**, pass `--steam-library "/path/to/SteamLibrary"`. Omit `--output` in this mode. The output volume must support Unix permissions and the `.app` path must be new. Use `--arch arm64` or `--arch x86_64` to select the architecture explicitly.

## Start the game

Install the native Steam client and sign in to an account that owns Risk of Rain 2. In the Steam Library, select **Risk of Rain 2 (Risk2Mac)** and click **Play**. The publisher's **Risk of Rain 2** entry launches the Windows release. [Steam store](https://store.steampowered.com/app/632360/) · [Steam Support](https://help.steampowered.com/en/faqs/view/4B8B-9697-2338-40EC)

If Steam is closed when the build finishes, the builder registers the shortcut for the most recent account on that Mac. If Steam is running, use **Games → Add a Non-Steam Game → Browse** and select the built `.app` using the path in the build log. Name the shortcut **Risk of Rain 2 (Risk2Mac)** in its properties so it is easy to find in the library. You can also quit Steam and rerun only the shortcut registration step.

```bash
python3 scripts/steam_install.py --register-shortcut "$HOME/Library/Application Support/Steam/steamapps/common/Risk of Rain 2/Risk of Rain 2.app"
```

Use the actual output path if you selected a different library. Launch the game from the library shortcut or Finder with Steam running. The port loads Valve-signed libraries from `~/Library/Application Support/Steam/Steam.AppBundle/`. Keep the Steam client up to date.

The launcher also loads Steam's installed overlay before the Metal device is created. Shift+Tab opens it when the overlay is enabled in Steam settings. The launcher verifies Valve's signature for the current Mac architecture; it continues without the overlay if Steam is closed or the renderer is missing or fails verification. Forced local mode skips overlay loading. No Valve overlay binaries are included in the repository or generated app. This early-loading fix was verified on Apple Silicon; Intel overlay behavior still needs hardware testing. [Steam overlay requirements](https://partner.steamgames.com/doc/features/overlay)

Steam mode uses the game's Steam account and cloud profile path. Local play uses a separate profile with its own progress. The base game runs in local mode. Expansions require Steam to verify your ownership and the matching expansion content to be present in the build.

When Steam initialization, account access or required interface checks fail, the app automatically selects local mode during startup. To explicitly launch in local mode for troubleshooting, run the bundle launcher with `RISK2MAC_FORCE_LOCAL=1`.

```bash
RISK2MAC_FORCE_LOCAL=1 "/path/to/Risk of Rain 2.app/Contents/MacOS/Risk of Rain 2"
```

## Multiplayer and validation

This integration targets Steam P2P multiplayer with Windows players using a matching game version. It preserves the game's version, mod compatibility and authentication checks. Use Steam networking on both sides and disable the Epic Games crossplay option.

On Apple Silicon, the port joined a real public Steam session, authenticated, loaded a multiplayer level, and the tester confirmed that gameplay worked. The remote host's operating system was not exposed, so this was not a separately verified test against a known Windows machine. Native Steam initialization, game ownership checks and cloud profile reads have also been confirmed. The played profile's changes persisted and were read back through Steam after restarting the client; the other profile remained unchanged.

Current limitations:

- Direct-IP / UDP dedicated servers are unsupported. Selecting one now ends the connection attempt with an error and returns to the menu instead of remaining on the loading screen. Use a Steam P2P lobby.
- Epic Games / EOS crossplay is unsupported.
- Cloud synchronization to another machine has not been verified.
- The native Steam bridge compiles for both ARM64 and x86_64. Intel gameplay still requires hardware testing.

Automatic fallback was also tested with Steam fully closed. The existing local profile loaded into character selection.

## If loading stops before the menu

Builder 0.1.13 enables Unity's direct rendering mode in games built for Apple Silicon. It avoids the Metal render worker that crashed while finishing geometry buffers in two M1 Pro combat sessions. The setting also applies when a launcher starts the Unity player directly. [Crash reports](https://github.com/TsiFroviK/Risk2Mac/issues/4)

To enable the same mode in an existing build after a combat crash or a repeated hang during shader loading, quit the game. In Steam, open **Properties → Shortcut → Launch Options** for **Risk of Rain 2 (Risk2Mac)** and add `-force-gfx-direct`. For a standalone copy, run the following in Terminal using the actual path to the app.

```bash
open "/Applications/Risk of Rain 2.app" --args -force-gfx-direct
```

For a one-off launch of a Steam-integrated copy, use its full path in the same command and leave Steam running. On older builds, clearing the Steam launch option or opening the app normally restores the previous mode. Frame rates can differ between modes.

In two sampled M1 stalls, Unity's main thread waited for the graphics worker while creating a shader program, and the worker waited for another command. Single-threaded rendering avoids that dependency. A local M1 test reached the menu in this mode even though the log still contained `Desired shader compiler platform 14 is not available in shader blob`. That message alone does not identify a hang. The M2 Pro report has no thread sample yet. For a persistent stall, use Activity Monitor to sample the running game before quitting and include the sample with that run's logs. [Unity player launch options](https://docs.unity3d.com/2023.1/Documentation/Manual/PlayerCommandLineArguments.html)

## Logs

Launcher and Unity logs are written to `~/Library/Logs/Risk Of Rain 2/`. `Latest-Unity.log` contains the selected platform and any Steam initialization error. Include that file and `Latest-Launcher.log` when reporting a problem. Review logs before posting them publicly because they can contain account identifiers and local paths.
