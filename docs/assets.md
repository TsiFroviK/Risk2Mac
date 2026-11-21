# Asset inputs

[Русская версия](assets.ru.md)

Keep `boot.config` and `RuntimeInitializeOnLoads.json` in the Windows data folder for generation. Existing kits with verified macOS copies of those two files can still supply them.

`manifests/assets.json` describes the 2,503 non-managed files in `Contents/Resources/Data` by relative path, size and SHA-256. Use a matching Windows installation as `--game`. The asset stage copies 2,158 files, normalizes the Addressables catalog and cache line endings, generates two Unity startup files and prepares 247 sound banks. It requires 94 additional local files from the matching port.

The private files include 83 modified Addressables bundles, a Metal depth-copy bundle and 10 startup or resource files produced while reconstructing the Unity player. The shader work translated Windows Direct3D bytecode to Metal Shading Language via SPIR-V, restored Unity variant and binding metadata, and applied targeted fixes for depth, cloud effects and post-processing. The current builder verifies those prepared bundles. Reconstruction of those bundles and the remaining startup files is a manual process.

For each `kind: private` entry, place the exact file under `PRIVATE/assets/Contents/Resources/Data/` using its manifest path. If you already have the matching reviewed port, extract the 94 files locally with this command.

```bash
python3 scripts/build-assets.py --export-private "$PORT" --private "$PRIVATE"
```

`build.sh` downloads the pinned commit of [wwiser](https://github.com/bnnm/wwiser) directly from upstream into the tool cache when converted banks and a local checkout are unavailable. The conversion takes the original Windows banks and verifies each output with the manifest. For an offline build, use either input below.

1. Append `--include-banks` to that export command to include all 247 converted `.bnk` files. The resulting asset input contains 341 files. Keep it private.
2. Supply a clean upstream checkout at commit `08e937b649bc7007c234bbd59e34a41d5eef3b38` using `--wwiser /path/to/wwiser`. The builder also finds a matching checkout at `PRIVATE/wwiser`.

Validate before building.

```bash
python3 scripts/build-assets.py --game "$GAME" --private "$PRIVATE" --tools "$HOME/Library/Caches/Risk2Mac" --check
```
