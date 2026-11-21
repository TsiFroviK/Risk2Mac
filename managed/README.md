# Managed inputs

[Русская версия](README.ru.md)

`inputs.json` lists the Windows input anchors and the 155 base managed outputs. The builder copies matching Windows assemblies, selects vendor runtime assemblies, builds its helpers and applies local compatibility patches. The managed assemblies use Unity Mono and are shared between the two Mac architectures. Steam builds also compile the Steam compatibility assembly.

The standard build uses the matching Windows installation and licensed Unity and Wwise SDKs. Manifest hashes identify compatible prebuilt files and generated variants. [Main build instructions](../README.md#build)

For missing inputs, Unity 2023.1.0f1 Mac Mono Build Support supplies 70 DLLs. The full editor's macOS Mono runtime profile can supply 22 more. The matching Windows installation provides 48 DLLs through verified PE generation with [AsmResolver.DotNet 6.0.1](https://www.nuget.org/packages/AsmResolver.DotNet/6.0.1), including the baseline `ModLoader.dll`. Two further compatibility patches prepare `HGUnityUtils.dll` and `Unity.RenderPipelines.Core.Runtime.dll`. All paths enforce the manifest SHA-256. Use `--unity-support /path/to/MacStandaloneSupport` if the module is installed outside its default Unity Hub location.

The builder compiles Unity AI Navigation and Memory Profiler from official Unity packages. It rebuilds `Assembly-CSharp.dll` from the matched Windows assembly using a pinned ILSpy version and the Unity Editor source generator. The generated `RoR2.dll` starts from the original Windows assembly and receives the port's compatibility and storage patches. The builder compiles a local platform provider for base-game play and local profiles. Steam checks DLC ownership when available.

The main builder rebuilds `AK.Wwise.Unity.API.dll` from the Windows assembly and the official sources in the verified Wwise Unity Integration archives. Export both the macOS and Windows versions from Audiokinetic Launcher. [SDK setup](../native/README.md)

## Reuse prepared assemblies

To reuse compatible earlier outputs with `--private`, put prepared `private`, `storage` and `wwise` entries in `PRIVATE/managed/`. The `storage` entries are `RoR2.dll` and `ModLoader.dll` before the storage patch. Use the compatible baseline hash from the manifest. If you have an existing matching `.app` and backups of both pre-storage DLLs, the following command exports the managed inputs.

```bash
python3 scripts/build-managed-inputs.py --port-app "$PORT" --pre-storage "$PRE_STORAGE" --private "$PRIVATE"
```

A matching prepared Wwise adapter DLL or the following two verified vendor files in `PRIVATE/wwise/` can also supply the Wwise inputs.

- `AkUnitySoundEnginePINVOKE_Mac.cs` from `Wwise/API/Runtime/Generated/Mac/`.
- `AkVector64.cs` from `Wwise/API/Runtime/Handwritten/Common/`.

Check a prepared directory separately with the following command.

```bash
python3 scripts/build-managed.py --game "$GAME" --private "$PRIVATE" --check-inputs
```
