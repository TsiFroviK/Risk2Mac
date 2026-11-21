# Asset inputs

[Русская версия](assets.ru.md)

Keep `boot.config`, `RuntimeInitializeOnLoads.json` and `ScriptingAssemblies.json` in the Windows data folder for generation. Existing kits can still supply verified macOS copies.

`manifests/assets.json` describes the 2,503 non-managed files in `Contents/Resources/Data` by relative path, size and SHA-256. Use a matching Windows installation as `--game`. The asset stage copies 2,158 files, normalizes the Addressables catalog and cache line endings, generates startup data and prepares 247 sound banks. Required prepared resources are the remaining `private` entries outside the shader conversion manifest.

If a prepared Addressables bundle is missing, the builder can generate it from the matching Windows bundle. It builds pinned Wine vkd3d and Khronos SPIRV-Cross from source in the tool cache to translate Direct3D shaders into Metal. Some bundles also need compute shaders compiled from Unity's official PostProcessing sources. For those bundles, use an activated Unity 2023.1.0f1 Editor with Mac Build Support. Each of the 83 generated bundles is checked against the same release SHA-256 as a prepared copy.

For the project's separate depth-copy shader, the builder uses a verified local bundle when available. Otherwise it compiles the included shader source in an activated Unity 2023.1.0f1 Editor with Mac Build Support. Select a custom editor location with `--unity-editor`.

The activated Editor can also generate the stock Unity splash stream and convert supported startup texture streams. The builder verifies their output hashes. A matching local copy can supply the same data.

Put the remaining required resources and any optional prepared bundles in `PRIVATE/assets/Contents/Resources/Data/`. The six required resources are `Resources/unity_builtin_extra`, `globalgamemanagers`, `globalgamemanagers.assets`, `level0`, `resources.assets`, and `sharedassets0.assets`. If you already have the matching reviewed port, the following command exports the prepared resources and bundles.

```bash
python3 scripts/build-assets.py --export-private "$PORT" --private "$PRIVATE"
```

`build.sh` downloads the pinned commit of [wwiser](https://github.com/bnnm/wwiser) directly from upstream into the tool cache when converted banks and a local checkout are unavailable. The conversion takes the original Windows banks and verifies each output with the manifest. For an offline build, use either input below.

1. Append `--include-banks` to that export command to include all 247 converted `.bnk` files. The resulting asset input contains 340 files. Keep it private.
2. Supply a clean upstream checkout at commit `08e937b649bc7007c234bbd59e34a41d5eef3b38` using `--wwiser /path/to/wwiser`. The builder also finds a matching checkout at `PRIVATE/wwiser`.

Validate before building.

```bash
python3 scripts/build-assets.py --game "$GAME" --private "$PRIVATE" --tools "$HOME/Library/Caches/Risk2Mac" --check
```
