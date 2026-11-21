# Managed inputs

[Русская версия](README.ru.md)

`inputs.json` lists the Windows input anchors and the 155 expected managed outputs. `windows` entries are copied from your own Windows data. `private` entries require the exact local assemblies by their listed SHA-256. They include runtime assemblies from the recovered macOS Unity player, compatibility baselines and the existing local platform provider. The builder compiles its own helper code and applies the storage and controller patches using Mono.Cecil. It builds for Unity Mono, so the managed outputs are shared between both Mac architectures.

Put prepared files marked `private`, `storage` and `wwise` in `PRIVATE/managed/`. The `storage` entries are `RoR2.dll` and `ModLoader.dll` before the storage repair. Supply the `input_sha256` versions when using prepared files. The main README has an extraction command for owners of the matching port who have both backups. It exports 148 managed inputs.

For missing inputs, the installed Unity 2023.1.0f1 macOS Mono Build Support and Mono runtime provide up to 92 DLLs. The matching Windows installation provides another 42 through verified PE re-emission with [AsmResolver.DotNet 6.0.1](https://www.nuget.org/packages/AsmResolver.DotNet/6.0.1), including the baseline `ModLoader.dll`. Both paths enforce the manifest SHA-256. Use `--unity-support /path/to/MacStandaloneSupport` if the module is installed outside its default Unity Hub location.

With both sources available, the builder still requires 12 prepared private DLLs, the modified baseline `RoR2.dll` and the Wwise adapter below.

The `wwise` entry is the prepared `AK.Wwise.Unity.API.dll`. Alternatively, supply both of the following files from the matching Wwise 2024.1.18 Unity Integration downloads in `PRIVATE/wwise/`. The script checks the exact source hashes and rebuilds the adapter from the Windows assembly.

- `AkUnitySoundEnginePINVOKE_Mac.cs` from `Wwise/API/Runtime/Generated/Mac/`.
- `AkVector64.cs` from `Wwise/API/Runtime/Handwritten/Common/`.

Check the inputs before building.

```bash
python3 scripts/build-managed.py --game "$GAME" --private "$PRIVATE" --check-inputs
```
