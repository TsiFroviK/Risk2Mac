# Asset inputs

[Русская версия](assets.ru.md)

Keep `boot.config`, `RuntimeInitializeOnLoads.json` and `ScriptingAssemblies.json` in the Windows data folder. The builder uses the matching Windows data and the activated Unity Editor to generate the macOS startup files.

`manifests/assets.json` describes the files in `Contents/Resources/Data` by relative path, size and SHA-256. Use a matching Windows installation as `--game`. The asset stage copies the original files, adjusts the Addressables catalog and cache, generates startup data and prepares 247 sound banks.

If a prepared Addressables bundle is missing, the builder can generate it from the matching Windows bundle. It builds pinned Wine vkd3d and Khronos SPIRV-Cross from source in the tool cache to translate Direct3D shaders into Metal. Some bundles also need compute shaders compiled from Unity's official PostProcessing sources. For those bundles, use an activated Unity 2023.1.0f1 Editor with Mac Build Support. Each of the 83 generated bundles is checked against the same release SHA-256 as a prepared copy.

For the project's separate depth-copy shader, the builder uses a verified local bundle when available. Otherwise it compiles the included shader source in an activated Unity 2023.1.0f1 Editor with Mac Build Support. Select a custom editor location with `--unity-editor`.

The activated Editor also supplies the built-in Unity resources and generates the splash and startup texture streams. The remaining startup asset files come from a temporary Unity project built from the matching Windows data. The manifest records the accepted output hashes.

## Reuse prepared assets

The standard build prepares these files automatically. If you have a matching local Mac build, you can export verified assets for reuse with the optional `--private` input. `PORT` points to the existing `.app` and `PRIVATE` points to a separate directory outside the repository. The export places the files in `PRIVATE/assets/Contents/Resources/Data/`.

```bash
python3 scripts/build-assets.py --export-private "$PORT" --private "$PRIVATE"
```

`build.sh` downloads the pinned commit of wwiser into the tool cache when it needs to convert the original Windows banks. It verifies each output against the manifest. To reuse prepared banks or a local copy of the converter, use one of these options. [wwiser upstream](https://github.com/bnnm/wwiser)

1. Append `--include-banks` to that export command to include all 247 converted `.bnk` files. Keep the exported game files local.
2. Supply a clean upstream checkout at commit `08e937b649bc7007c234bbd59e34a41d5eef3b38` using `--wwiser /path/to/wwiser`. The builder also finds a matching checkout at `PRIVATE/wwiser`.

Check a prepared asset directory separately with the following command. [Main build instructions](../README.md#build)

```bash
python3 scripts/build-assets.py --game "$GAME" --private "$PRIVATE" --tools "$HOME/Library/Caches/Risk2Mac" --check
```
