# Managed inputs

[Русская версия](README.ru.md)

`inputs.json` lists the Windows input anchors and the 155 expected managed outputs. `windows` entries are copied from your own Windows data. `private` entries require the exact local assemblies by their listed SHA-256. They include runtime assemblies from the recovered macOS Unity player, compatibility baselines and the existing local platform provider. The builder compiles its own helper code and applies the storage and controller patches using Mono.Cecil. It builds for Unity Mono, so the managed outputs are shared between both Mac architectures.

Put the files marked `private`, `storage` and `wwise` in `PRIVATE/managed/`. The `storage` entries are `RoR2.dll` and `ModLoader.dll` before the storage repair. Use their `input_sha256`, then the builder creates the patched output. The Windows originals of those two assemblies have different hashes and cannot substitute for these baselines. For a matching existing port and those two backups, use the local extraction command in the main README to prepare 148 private managed inputs.

The `wwise` entry is the prepared `AK.Wwise.Unity.API.dll`. Alternatively, supply both of the following files from the matching Wwise 2024.1.18 Unity Integration downloads in `PRIVATE/wwise/`. The script checks the exact source hashes and rebuilds the adapter from the Windows assembly.

- `AkUnitySoundEnginePINVOKE_Mac.cs` from `Wwise/API/Runtime/Generated/Mac/`.
- `AkVector64.cs` from `Wwise/API/Runtime/Handwritten/Common/`.

Check the inputs before building.

```bash
python3 scripts/build-managed.py --game "$GAME" --private "$PRIVATE" --check-inputs
```
