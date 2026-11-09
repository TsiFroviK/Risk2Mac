#!/usr/bin/env python3
"""Build and install the Mono assemblies in a fresh, staged Risk2Mac app."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


SOURCE = Path(__file__).resolve().parents[1] / "managed"
WINDOWS_DATA = "Risk of Rain 2_Data"
MANAGED_PATH = Path("Contents/Resources/Data/Managed")
RUNTIME_REFS = ("mscorlib.dll", "System.dll", "System.Core.dll")
UNITY_REFS = ("UnityEngine.dll", "UnityEngine.CoreModule.dll")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_file(path, expected):
    if not path.is_file():
        raise ValueError(f"Missing input: {path}")
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"Unsupported input: {path}\nExpected SHA-256 {expected}\nFound {actual}")


def read_recipe():
    recipe = json.loads((SOURCE / "inputs.json").read_text(encoding="utf-8"))
    if recipe["schema"] != 1:
        raise ValueError("Unsupported managed input manifest")
    return recipe


def check_inputs(windows, private, recipe):
    errors = []

    def check(path, expected):
        try:
            assert_file(path, expected)
        except (OSError, ValueError) as error:
            errors.append(str(error))

    for name, expected in recipe["windows_anchors"].items():
        check(windows / name, expected)

    wwise = private / "wwise"
    wwise_sources = recipe["optional_wwise_sources"]
    compile_wwise = all((wwise / name).is_file() for name in wwise_sources)
    if compile_wwise:
        for name, expected in wwise_sources.items():
            check(wwise / name, expected)

    for name, entry in recipe["files"].items():
        if entry["source"] == "windows":
            check(windows / name, entry["sha256"])
        elif entry["source"] == "storage":
            check(private / "managed" / name, entry["input_sha256"])
        elif entry["source"] == "private" or (entry["source"] == "wwise" and not compile_wwise):
            check(private / "managed" / name, entry["sha256"])
    if errors:
        raise ValueError("Managed prerequisites did not match the supported release:\n" + "\n".join(errors))
    return compile_wwise


def locate_csc(dotnet):
    listing = subprocess.check_output([dotnet, "--list-sdks"], text=True)
    versions = []
    for line in listing.splitlines():
        match = re.fullmatch(r"(8\.0\.\d+) \[(.+)\]", line)
        if match:
            version, path = match.groups()
            versions.append((int(version.split(".")[-1]), Path(path) / version))
    if not versions:
        raise ValueError("Install the .NET 8 SDK or pass --dotnet with its executable path")
    sdk = max(versions)[1]
    csc = sdk / "Roslyn/bincore/csc.dll"
    if not csc.is_file():
        raise ValueError(f".NET 8 SDK compiler missing: {csc}")
    return csc, sdk.name


def compile_dll(dotnet, csc, references, sources, output, define=None):
    args = [dotnet, str(csc), "/noconfig", "/nostdlib+", "/target:library", "/platform:anycpu",
            "/langversion:7.3", "/optimize+", "/deterministic+", f"/out:{output}"]
    if define:
        args.append(f"/define:{define}")
    args.extend(f"/reference:{path}" for path in references)
    args.extend(str(path) for path in sources)
    subprocess.run(args, check=True)


def run_patcher(dotnet, sdk, name, scratch, *args):
    project = scratch / f"{name}-tool"
    project.mkdir()
    for filename in ("Patcher.csproj", "Program.cs"):
        shutil.copyfile(SOURCE / name / filename, project / filename)
    (project / "global.json").write_text(json.dumps({"sdk": {"version": sdk, "rollForward": "disable"}}),
                                         encoding="utf-8")
    output = scratch / f"{name}-bin"
    command = [dotnet, "build", str(project / "Patcher.csproj"), "-c", "Release", "-o", str(output),
               "--configfile", str(SOURCE / "NuGet.Config"), "--nologo"]
    subprocess.run(command, check=True, cwd=project)
    binary = output / f"Risk2Mac.{name.capitalize()}Patcher.dll"
    result = subprocess.run([dotnet, str(binary), *(str(arg) for arg in args)], check=True,
                            text=True, stdout=subprocess.PIPE)
    (scratch / f"{name}-patch.json").write_text(result.stdout, encoding="utf-8")


def build_assemblies(windows, private, scratch, dotnet, recipe, compile_wwise):
    csc, sdk = locate_csc(dotnet)
    output = scratch / "Managed"
    output.mkdir()
    for name, entry in recipe["files"].items():
        if entry["source"] == "windows":
            shutil.copyfile(windows / name, output / name)
        elif entry["source"] == "private" or (entry["source"] == "wwise" and not compile_wwise):
            shutil.copyfile(private / "managed" / name, output / name)

    # Compile against the same Unity 2021 Windows reference assembly versions
    # used for the reviewed helpers. The app uses its supplied macOS Mono runtime.
    dpad = output / "RoR2Arm64.MacDpad.dll"
    compile_dll(dotnet, csc, [windows / name for name in (*RUNTIME_REFS[:2], *UNITY_REFS,
                "UnityEngine.InputLegacyModule.dll")], [SOURCE / "dpad/MacDpadInput.cs"], dpad)
    storage = output / "RoR2Arm64.MacStorage.dll"
    compile_dll(dotnet, csc, [windows / name for name in (*RUNTIME_REFS, "UnityEngine.CoreModule.dll")],
                [SOURCE / "storage/MacWritableStorage.cs"], storage)
    solo_files = ("ManagedSoloTransport.cs", "ManagedSoloBootstrap.cs", "GraphicsCompatibility.cs",
                  "MetalDepthCompatibility.cs", "MacLoadingNumberCompatibility.cs",
                  "MacInputCompatibility.cs", "MacGlyphCompatibility.cs")
    solo_refs = (*RUNTIME_REFS, "netstandard.dll", *UNITY_REFS, "UnityEngine.AssetBundleModule.dll",
                 "UnityEngine.UIModule.dll", "UnityEngine.UI.dll", "UnityEngine.UNETModule.dll",
                 "com.unity.multiplayer-hlapi.Runtime.dll", "Rewired_Core.dll", "Rewired_CSharp.dll",
                 "RoR2.dll", "LegacyResourcesAPI.dll")
    compile_dll(dotnet, csc, [*(windows / name for name in solo_refs), dpad],
                [SOURCE / "helpers" / name for name in solo_files], output / "RoR2Arm64.ManagedSolo.dll")

    run_patcher(dotnet, sdk, "dpad", scratch, windows / "Rewired_Core.dll", dpad, output / "Rewired_Core.dll")
    patched_storage = scratch / "storage-patched"
    run_patcher(dotnet, sdk, "storage", scratch, private / "managed", storage, patched_storage)
    for name in ("RoR2.dll", "ModLoader.dll"):
        (patched_storage / name).rename(output / name)

    if compile_wwise:
        wwise_refs = (*RUNTIME_REFS, "netstandard.dll", *UNITY_REFS,
                      "AK.Wwise.Unity.API.dll", "AK.Wwise.Unity.MonoBehaviour.dll")
        sources = [private / "wwise" / name for name in recipe["optional_wwise_sources"]]
        metadata = scratch / "Wwise2024.Mac.PInvokeMetadata.dll"
        compile_dll(dotnet, csc, [windows / name for name in wwise_refs], sources, metadata,
                    define="UNITY_STANDALONE_OSX")
        patched_wwise = scratch / "wwise-patched"
        run_patcher(dotnet, sdk, "wwise", scratch, windows / "AK.Wwise.Unity.API.dll", metadata, patched_wwise)
        (patched_wwise / "AK.Wwise.Unity.API.dll").rename(output / "AK.Wwise.Unity.API.dll")

    inventory = {path.name: sha256(path) for path in output.iterdir()}
    if inventory.keys() != recipe["files"].keys():
        raise ValueError("Generated managed assembly inventory does not match this release")
    different = [name for name, digest in inventory.items() if digest != recipe["files"][name]["sha256"]]
    if different:
        print(f"Build with .NET {sdk} re-emitted assemblies with different bytes: {', '.join(different)}")
    return output


def install(args):
    game = args.game.resolve(strict=True)
    private = args.private.resolve(strict=True)
    windows = game / WINDOWS_DATA / "Managed"
    recipe = read_recipe()
    compile_wwise = check_inputs(windows, private, recipe)
    if args.check_inputs:
        print("Managed prerequisites match the release manifest")
        return

    app = args.app.resolve(strict=True)
    if app.suffix != ".app" or not (app / "Contents").is_dir():
        raise ValueError("--app must be a staged macOS app with a Contents directory")
    if any(app.is_relative_to(path) or path.is_relative_to(app) for path in (game, private)):
        raise ValueError("Place the staged app outside the game and private input directories")
    managed = app / MANAGED_PATH
    if managed.exists() or managed.is_symlink() or not managed.resolve().is_relative_to(app):
        raise ValueError("Managed output must be an absent path inside the staged app")
    dotnet = shutil.which(args.dotnet)
    if not dotnet:
        raise ValueError("The .NET 8 SDK is required. Pass --dotnet or add it to PATH")

    with tempfile.TemporaryDirectory(prefix="risk2mac-managed-", dir=app.parent) as directory:
        scratch = Path(directory)
        output = build_assemblies(windows, private, scratch, dotnet, recipe, compile_wwise)
        if args.steam:
            install_steam(output, scratch, dotnet)
        managed.parent.mkdir(parents=True, exist_ok=True)
        output.rename(managed)
    print(f"Prepared {len(recipe['files']) + int(args.steam)} Mono assemblies")


def install_steam(managed, scratch, dotnet):
    csc, sdk = locate_csc(dotnet)
    helper = scratch / "Risk2Mac.Steam.dll"
    references = (*RUNTIME_REFS, "netstandard.dll", "UnityEngine.CoreModule.dll",
                  "UnityEngine.UNETModule.dll", "com.unity.multiplayer-hlapi.Runtime.dll",
                  "RoR2Arm64.ManagedSolo.dll", "RoR2.dll", "Facepunch.Steamworks.dll")
    compile_dll(dotnet, csc, [managed / name for name in references],
                [SOURCE / "steam" / name for name in ("SteamCompatibility.cs", "SteamExternalTransport.cs")], helper)
    patched = scratch / "steam-patched"
    run_patcher(dotnet, sdk, "steam", scratch, managed, helper, patched)
    report = json.loads((patched / "patch-report.json").read_text(encoding="utf-8"))
    expected = {"RoR2.dll", "RoR2Arm64.OfflinePlatform.dll", "RoR2Arm64.ManagedSolo.dll", "Facepunch.Steamworks.dll"}
    if len(report) != len(expected) or {item["file"] for item in report} != expected:
        raise ValueError("Steam patch report has an unexpected assembly inventory")
    if {path.name for path in patched.iterdir()} != expected | {helper.name, "patch-report.json"}:
        raise ValueError("Steam patch output has an unexpected file inventory")
    for item in report:
        name = item["file"]
        assert_file(managed / name, item["sourceSha256"])
        assert_file(patched / name, item["candidateSha256"])
    assert_file(patched / helper.name, sha256(helper))
    for name in sorted(expected | {helper.name}):
        (patched / name).replace(managed / name)
    print("Prepared Steam integration with verified managed patches")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument("--steam", action="store_true")
    args = parser.parse_args()
    if not args.check_inputs and args.app is None:
        parser.error("--app is required unless --check-inputs is used")
    try:
        install(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Risk2Mac managed stage: {error}\n")


if __name__ == "__main__":
    main()
