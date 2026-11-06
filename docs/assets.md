# Asset inputs

[Русская версия](assets.ru.md)

`manifests/assets.json` describes the 2,503 non-managed files in `Contents/Resources/Data` by relative path, size and SHA-256. Use a matching Windows installation as `--game`. The asset stage copies 2,158 files from it, normalizes the Addressables catalog and cache line endings, and prepares 247 sound banks. It requires 96 additional local files from the matching port.

The private files include 83 modified Addressables bundles, a Metal depth-copy bundle and 12 startup or resource files produced while reconstructing the Unity player. The shader work translated Windows Direct3D bytecode to Metal Shading Language via SPIR-V, restored Unity variant and binding metadata, and applied targeted fixes for depth, cloud effects and post-processing. The current builder verifies those prepared bundles. The complete shader and Unity startup reconstruction is a separate workflow that this repository does not automate.

For each `kind: private` entry, place the exact file under `PRIVATE/assets/Contents/Resources/Data/` using its manifest path. If you already have the matching reviewed port, extract the 96 files locally with this command.

```bash
python3 scripts/build-assets.py --export-private "$PORT" --private "$PRIVATE"
```

For banks, choose one of two supported inputs.

1. Append `--include-banks` to that export command to include all 247 converted `.bnk` files. The resulting asset input contains 343 files. Keep it private.
2. Supply your own checkout of [wwiser](https://github.com/bnnm/wwiser) at commit `08e937b649bc7007c234bbd59e34a41d5eef3b38` using `--wwiser /path/to/wwiser`. The builder runs its original bank conversion code against the Windows banks and validates each result against the manifest. The repository contains no wwiser files. An exact checkout at `PRIVATE/wwiser` is also detected.

Validate before building.

```bash
python3 scripts/build-assets.py --game "$GAME" --private "$PRIVATE" --check
```
