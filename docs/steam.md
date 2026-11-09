# Steam integration

[Русская инструкция](steam.ru.md)

The optional Steam build connects the native macOS player to the Steam client installed on that Mac. It uses the account that owns Risk of Rain 2, checks DLC ownership against the content present in the local build, and selects the game's Steam profile storage. The native compatibility library adapts the game's older Steamworks interfaces to the current client.

## Prepare and build

Complete the normal [private input preparation](../README.md#prepare-private-inputs) first. Steam integration uses the same pinned Windows game version and private graphics, audio and managed inputs.

From the Risk2Mac repository, set the paths for your machine and run the additional preparation step.

```bash
GAME="/path/to/Windows/Risk of Rain 2"
PRIVATE="/path/to/Prerequisites"
OUTPUT="$HOME/Risk2Mac Builds/Steam/Risk of Rain 2.app"

python3 scripts/prepare-steam.py --private "$PRIVATE"
bash build.sh --game "$GAME" --private "$PRIVATE" --output "$OUTPUT" --steam
```

`prepare-steam.py` downloads 37 matching legacy SDK headers from a pinned Facepunch commit and verifies each SHA-256 against `native/steam-legacy-headers.json`. It stores them under `PRIVATE/native/steam-legacy-headers/`, reuses verified files, and stops if an existing file differs. The build generates its native wrappers locally. The headers retain Valve's copyright and the applicable Steamworks SDK terms. [Pinned upstream headers](https://github.com/Facepunch/Facepunch.Steamworks/tree/605054339ad88fd09eeb7e0a82ca0eb78737b334/Generator/steam_sdk), [Steamworks SDK documentation](https://partner.steamgames.com/doc/sdk)

The output directory must support Unix permissions and the `.app` path must be new. Architecture selection follows the normal builder behavior. Use `--arch arm64` or `--arch x86_64` to select it explicitly.

## Start the game

Install the native Steam client normally, sign in to an account that owns Risk of Rain 2, and leave Steam running. Open the generated `.app` in Finder. The port loads Valve-signed libraries from `~/Library/Application Support/Steam/Steam.AppBundle/`. Keep the Steam client up to date.

Steam mode uses the game's Steam account and cloud profile path. The local profile remains in its separate local storage. Switching modes selects the corresponding profiles without merging their progress. DLC availability follows Steam ownership and the expansion content included in the build.

When Steam initialization, account access or required interface checks fail, the app automatically selects local mode during startup. To explicitly launch in local mode for troubleshooting, run the bundle launcher with `RISK2MAC_FORCE_LOCAL=1`.

```bash
RISK2MAC_FORCE_LOCAL=1 "/Applications/Risk of Rain 2.app/Contents/MacOS/Risk of Rain 2"
```

## Multiplayer and validation

This integration targets Steam P2P multiplayer with Windows players using a matching game version. It preserves the game's version, mod compatibility and authentication checks. Use Steam networking on both sides and disable the Epic Games crossplay option.

On Apple Silicon, the port joined a real public Steam session, authenticated, loaded a multiplayer level, and the tester confirmed that gameplay worked. The remote host's operating system was not exposed, so this was not a separately verified test against a known Windows machine. Native Steam initialization, game ownership checks and cloud profile reads have also been confirmed. The played profile's changes persisted and were read back through Steam after restarting the client; the other profile remained unchanged.

Current limitations:

- Direct-IP / UDP dedicated servers are unsupported. Selecting one now ends the connection attempt with an error and returns to the menu instead of remaining on the loading screen. Use a Steam P2P lobby.
- Epic Games / EOS crossplay is unsupported.
- Cloud synchronization to another machine has not been verified.
- The native Steam bridge compiles for both ARM64 and x86_64. Intel gameplay still requires hardware testing.

Automatic fallback was also tested with Steam fully closed: the existing local profile loaded into character selection. An intermittent loading stall around 28% reproduced the same native Unity shader-compilation wait seen before Steam integration; a subsequent automatic local launch succeeded. This shader-loading issue remains unresolved. If it occurs, close the game and try launching it again.

## Logs

Launcher and Unity logs are written to `~/Library/Logs/Risk Of Rain 2/`. `Latest-Unity.log` contains the selected platform and any Steam initialization error. Include that file and `Latest-Launcher.log` when reporting a problem. Review logs before posting them publicly because they can contain account identifiers and local paths.
