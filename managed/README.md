# Managed inputs

[Русская версия](README.ru.md)

`inputs.json` lists the Windows input anchors and the 155 expected managed outputs. `windows` entries are copied from your own Windows data. `private` entries require the exact local assemblies by their listed SHA-256. They include runtime assemblies from the recovered macOS Unity player, compatibility baselines and the existing local platform provider. The builder compiles its own helper code and applies the storage and controller patches using Mono.Cecil. It builds for Unity Mono, so the managed outputs are shared between both Mac architectures.

Put prepared files marked `private`, `storage` and `wwise` in `PRIVATE/managed/`. The `storage` entries are `RoR2.dll` and `ModLoader.dll` before the storage repair. Supply the `input_sha256` versions when using prepared files. The main README has an extraction command for owners of the matching port who have both backups. It exports 148 managed inputs.

For missing inputs, Unity 2023.1.0f1 Mac Mono Build Support supplies 70 DLLs. The full editor's macOS Mono runtime profile can supply 22 more. The matching Windows installation provides 48 DLLs through verified PE generation with [AsmResolver.DotNet 6.0.1](https://www.nuget.org/packages/AsmResolver.DotNet/6.0.1), including the baseline `ModLoader.dll`. Two further compatibility patches prepare `HGUnityUtils.dll` and `Unity.RenderPipelines.Core.Runtime.dll`. All paths enforce the manifest SHA-256. Use `--unity-support /path/to/MacStandaloneSupport` if the module is installed outside its default Unity Hub location.

With the complete Unity Mono profile and Unity 2023.1.0f1 Editor available, the builder compiles Unity AI Navigation from the official package using the Editor's source generator. If the prepared Memory Profiler DLL is absent, it builds the player metadata provider from the official Unity Memory Profiler 1.0.0 package. The remaining prepared game assemblies are `Assembly-CSharp.dll`, `RoR2Arm64.OfflinePlatform.dll` and the modified baseline `RoR2.dll`.

The main builder rebuilds `AK.Wwise.Unity.API.dll` from the Windows assembly when it finds both verified Wwise Unity Integration archives exported by Audiokinetic Launcher. A matching prepared adapter DLL or the following two files in `PRIVATE/wwise/` also work.

- `AkUnitySoundEnginePINVOKE_Mac.cs` from `Wwise/API/Runtime/Generated/Mac/`.
- `AkVector64.cs` from `Wwise/API/Runtime/Handwritten/Common/`.

Check the inputs before building.

```bash
python3 scripts/build-managed.py --game "$GAME" --private "$PRIVATE" --check-inputs
```
