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

from risk2mac_depth import find_unity_editor
from risk2mac_ai_navigation import (
    OUTPUT_NAME as AI_NAVIGATION, OUTPUT_SHA256 as AI_NAVIGATION_SHA256,
    REFERENCE_SHA256 as AI_NAVIGATION_REFERENCES,
    build_ai_navigation, find_ai_navigation_analyzer,
)
from risk2mac_assembly_csharp import (
    INPUT_SHA256 as ASSEMBLY_CSHARP_INPUT_SHA256, OUTPUT_NAME as ASSEMBLY_CSHARP,
    OUTPUT_SHA256 as ASSEMBLY_CSHARP_SHA256, WINDOWS_REFERENCES as ASSEMBLY_CSHARP_WINDOWS,
    build_assembly_csharp,
)
from risk2mac_memory_profiler import (
    OUTPUT_NAME as MEMORY_PROFILER, OUTPUT_SHA256 as MEMORY_PROFILER_SHA256,
    REFERENCE_SHA256 as MEMORY_PROFILER_REFERENCES, build_memory_profiler,
)


SOURCE = Path(__file__).resolve().parents[1] / "managed"
WINDOWS_DATA = "Risk of Rain 2_Data"
MANAGED_PATH = Path("Contents/Resources/Data/Managed")
RUNTIME_REFS = ("mscorlib.dll", "System.dll", "System.Core.dll")
UNITY_REFS = ("UnityEngine.dll", "UnityEngine.CoreModule.dll")
UNITY_VERSION = "2023.1.0f1"
UNITY_CONTENTS = Path("/Applications/Unity/Hub/Editor") / UNITY_VERSION / "Unity.app/Contents"
UNITY_MAC_MODULE = Path("PlaybackEngines/MacStandaloneSupport")
UNITY_MAC_MONO_PROFILE = Path("MonoBleedingEdge/lib/mono/unityjit-macos")
UNSAFE_ASSEMBLY = "System.Runtime.CompilerServices.Unsafe.dll"
GAME_ASSEMBLY = "RoR2.dll"
OFFLINE_PLATFORM = "RoR2Arm64.OfflinePlatform.dll"


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
    allowed = (expected,) if isinstance(expected, str) else expected
    if actual not in allowed:
        raise ValueError(f"Unsupported input: {path}\nExpected SHA-256 {' or '.join(allowed)}\nFound {actual}")


def accepted_input_hashes(entry):
    baseline = entry.get("input_sha256", entry["sha256"])
    generated = entry.get("generated_input_sha256", entry.get("generated_sha256"))
    return (baseline, generated) if generated is not None else (baseline,)


def read_recipe():
    recipe = json.loads((SOURCE / "inputs.json").read_text(encoding="utf-8"))
    if recipe["schema"] != 1:
        raise ValueError("Unsupported managed input manifest")
    recipe["windows_reemit"] = json.loads((SOURCE / "reemit/inputs.json").read_text(encoding="utf-8"))
    recipe["unsafe_reemit"] = json.loads((SOURCE / "reemit/unsafe.json").read_text(encoding="utf-8"))["input_sha256"]
    recipe["compatibility"] = json.loads((SOURCE / "compat/inputs.json").read_text(encoding="utf-8"))["windows"]
    return recipe


def unity_managed_directories(private, unity_support, unity_editor=None):
    if unity_support is None:
        local = private / "native/UnityMacSupport"
        unity_support = local if local.is_dir() else UNITY_CONTENTS / UNITY_MAC_MODULE

    # A complete Editor and a separately installed Mac Build Support module
    # can supply the runtime DLLs independently. Reference DLLs are excluded.
    editor = unity_support.parent.parent if unity_support.parent.name == "PlaybackEngines" else None
    profiles = [unity_support / UNITY_MAC_MONO_PROFILE, UNITY_CONTENTS / UNITY_MAC_MONO_PROFILE]
    if editor is not None:
        profiles.insert(0, editor / UNITY_MAC_MONO_PROFILE)
    if unity_editor is not None:
        profiles.insert(0, unity_editor.parent.parent / UNITY_MAC_MONO_PROFILE)
    directories = [unity_support / "Variations/mono/Managed"]
    for profile in profiles:
        directories.extend((profile, profile / "Facades"))
    return tuple(dict.fromkeys(directories))


def resolve_private_sources(private, recipe, unity_support=None, unity_editor=None):
    directories = unity_managed_directories(private, unity_support, unity_editor)
    sources = {}
    for name, entry in recipe["files"].items():
        if entry["source"] not in {"private", "storage"}:
            continue
        local = private / "managed" / name
        if entry["source"] == "storage" or local.exists() or local.is_symlink():
            sources[name] = local
            continue
        candidates = [directory / name for directory in directories if (directory / name).is_file()]
        sources[name] = next((candidate for candidate in candidates if sha256(candidate) == entry["sha256"]),
                             candidates[0] if candidates else local)
    return sources


def needs_preparation(path):
    return not path.exists() and not path.is_symlink()


def reemit_plan(recipe, private_sources):
    plan = [
        {
            "name": name,
            "inputSha256": expected,
            "outputSha256": recipe["files"][name].get("input_sha256", recipe["files"][name]["sha256"]),
        }
        for name, expected in recipe["windows_reemit"].items()
        if needs_preparation(private_sources[name])
    ]
    if needs_preparation(private_sources[UNSAFE_ASSEMBLY]):
        plan.append({
            "name": UNSAFE_ASSEMBLY,
            "sourceName": "mscorlib.dll",
            "inputSha256": recipe["unsafe_reemit"],
            "outputSha256": recipe["files"][UNSAFE_ASSEMBLY]["sha256"],
        })
    return plan


def check_inputs(windows, private, recipe, private_sources, plan, compatibility, wwise_directory=None,
                 vendor_builds=None):
    vendor_builds = vendor_builds or {}
    errors = []

    def check(path, expected):
        try:
            assert_file(path, expected)
        except (OSError, ValueError) as error:
            errors.append(str(error))

    for name, expected in recipe["windows_anchors"].items():
        check(windows / name, expected)
    if ASSEMBLY_CSHARP in vendor_builds:
        check(windows / ASSEMBLY_CSHARP, ASSEMBLY_CSHARP_INPUT_SHA256)
        for name in ASSEMBLY_CSHARP_WINDOWS:
            if not (windows / name).is_file():
                errors.append(f"Missing Assembly-CSharp reference: {windows / name}")

    wwise = wwise_directory or private / "wwise"
    wwise_sources = recipe["optional_wwise_sources"]
    compile_wwise = all((wwise / name).is_file() for name in wwise_sources)
    if compile_wwise or wwise_directory is not None:
        for name, expected in wwise_sources.items():
            check(wwise / name, expected)

    windows_preparation = {item["name"]: (item.get("sourceName", item["name"]), item["inputSha256"])
                           for item in plan}
    windows_preparation.update({name: (name, digest) for name, digest in compatibility.items()})
    for name, entry in recipe["files"].items():
        if name in vendor_builds:
            if entry.get("generated_sha256", entry["sha256"]) != vendor_builds[name]:
                errors.append(f"The generator for {name} disagrees with the assembly manifest.")
        elif name in windows_preparation:
            source_name, expected = windows_preparation[name]
            check(windows / source_name, expected)
        elif entry["source"] == "windows":
            check(windows / name, entry["sha256"])
        elif entry["source"] == "storage":
            if name != GAME_ASSEMBLY or not needs_preparation(private_sources[name]):
                check(private_sources[name], accepted_input_hashes(entry))
        elif entry["source"] == "private":
            check(private_sources[name], accepted_input_hashes(entry))
        elif entry["source"] == "wwise" and not compile_wwise:
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


def build_assemblies(windows, private, scratch, dotnet, recipe, compile_wwise, private_sources, plan, compatibility,
                     wwise_directory=None, vendor_builds=None, editor=None, tool_cache=None):
    vendor_builds = vendor_builds or {}
    csc, sdk = locate_csc(dotnet)
    output = scratch / "Managed"
    output.mkdir()
    if plan:
        plan_file = scratch / "reemit-plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        generated = scratch / "reemit-output"
        print(f"Preparing {len(plan)} managed assemblies from the Windows installation", flush=True)
        run_patcher(dotnet, sdk, "reemit", scratch, windows, plan_file, generated)
        private_sources = {**private_sources, **{item["name"]: generated / item["name"] for item in plan}}
    if compatibility:
        generated = scratch / "compat-output"
        print(f"Adapting {len(compatibility)} Windows assemblies for Unity 2023", flush=True)
        run_patcher(dotnet, sdk, "compat", scratch, windows, private_sources["UnityEngine.CoreModule.dll"],
                    generated, *compatibility)
        private_sources = {**private_sources, **{name: generated / name for name in compatibility}}
    for name, entry in recipe["files"].items():
        if name in vendor_builds or (name == GAME_ASSEMBLY and needs_preparation(private_sources[name])):
            continue
        if entry["source"] == "windows":
            shutil.copyfile(windows / name, output / name)
        elif entry["source"] in {"private", "storage"}:
            shutil.copyfile(private_sources[name], output / name)
            assert_file(output / name, accepted_input_hashes(entry))
        elif entry["source"] == "wwise" and not compile_wwise:
            shutil.copyfile(private / "managed" / name, output / name)

    if AI_NAVIGATION in vendor_builds:
        references = {name: output / name for name in AI_NAVIGATION_REFERENCES}
        build_ai_navigation(dotnet, csc, editor, references, output / AI_NAVIGATION, scratch)
    if ASSEMBLY_CSHARP in vendor_builds:
        build_assembly_csharp(dotnet, csc, editor, windows, output, output / ASSEMBLY_CSHARP, scratch, tool_cache)
    if MEMORY_PROFILER in vendor_builds:
        references = {name: windows / name for name in MEMORY_PROFILER_REFERENCES}
        references["UnityEngine.CoreModule.dll"] = output / "UnityEngine.CoreModule.dll"
        build_memory_profiler(dotnet, csc, references, output / MEMORY_PROFILER, scratch)

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
    offline = output / OFFLINE_PLATFORM
    offline_sources = [SOURCE / "game" / name for name in ("OfflineNetworkManager.cs", "OfflinePlatform.cs", "OfflineProviders.cs")]
    compile_dll(dotnet, csc, sorted(windows.glob("*.dll"), key=lambda path: path.name.casefold()), offline_sources, offline)
    assert_file(offline, recipe["files"][OFFLINE_PLATFORM]["sha256"])
    if not (output / GAME_ASSEMBLY).is_file():
        generated_game = scratch / "game-patched"
        print("Preparing the game assembly from the Windows installation", flush=True)
        run_patcher(dotnet, sdk, "game", scratch, windows / GAME_ASSEMBLY,
                    output / "RoR2Arm64.ManagedSolo.dll", offline, generated_game)
        assert_file(generated_game / GAME_ASSEMBLY, recipe["files"][GAME_ASSEMBLY]["generated_input_sha256"])
        (generated_game / GAME_ASSEMBLY).rename(output / GAME_ASSEMBLY)

    run_patcher(dotnet, sdk, "dpad", scratch, windows / "Rewired_Core.dll", dpad, output / "Rewired_Core.dll")
    patched_storage = scratch / "storage-patched"
    run_patcher(dotnet, sdk, "storage", scratch, output, storage, patched_storage)
    for name in ("RoR2.dll", "ModLoader.dll"):
        (patched_storage / name).replace(output / name)
    assert_file(output / GAME_ASSEMBLY, recipe["files"][GAME_ASSEMBLY]["sha256"])

    if compile_wwise:
        wwise_refs = (*RUNTIME_REFS, "netstandard.dll", *UNITY_REFS,
                      "AK.Wwise.Unity.API.dll", "AK.Wwise.Unity.MonoBehaviour.dll")
        sources = [(wwise_directory or private / "wwise") / name for name in recipe["optional_wwise_sources"]]
        metadata = scratch / "Wwise2024.Mac.PInvokeMetadata.dll"
        compile_dll(dotnet, csc, [windows / name for name in wwise_refs], sources, metadata,
                    define="UNITY_STANDALONE_OSX")
        patched_wwise = scratch / "wwise-patched"
        run_patcher(dotnet, sdk, "wwise", scratch, windows / "AK.Wwise.Unity.API.dll", metadata, patched_wwise)
        (patched_wwise / "AK.Wwise.Unity.API.dll").rename(output / "AK.Wwise.Unity.API.dll")

    inventory = {path.name: sha256(path) for path in output.iterdir()}
    if inventory.keys() != recipe["files"].keys():
        raise ValueError("Generated managed assembly inventory does not match this release")
    different = [name for name, digest in inventory.items()
                 if digest not in (recipe["files"][name]["sha256"], recipe["files"][name].get("generated_sha256"))]
    if different:
        print(f"Build with .NET {sdk} re-emitted assemblies with different bytes: {', '.join(different)}")
    return output


def install(args):
    game = args.game.resolve(strict=True)
    private = args.private.resolve(strict=True)
    windows = game / WINDOWS_DATA / "Managed"
    recipe = read_recipe()
    unity_support = args.unity_support.resolve(strict=True) if args.unity_support is not None else None
    if unity_support is not None and not unity_support.is_dir():
        raise ValueError(f"Expected a Unity MacStandaloneSupport directory: {unity_support}")
    editor = find_unity_editor(args.unity_editor)
    private_sources = resolve_private_sources(private, recipe, unity_support, editor)
    plan = reemit_plan(recipe, private_sources)
    compatibility = {name: digest for name, digest in recipe["compatibility"].items()
                     if needs_preparation(private_sources[name])}
    wwise_directory = args.wwise_sources.expanduser().resolve(strict=True) if args.wwise_sources else None
    vendor_builds = {}
    if find_ai_navigation_analyzer(editor):
        if needs_preparation(private_sources[AI_NAVIGATION]):
            vendor_builds[AI_NAVIGATION] = AI_NAVIGATION_SHA256
        if needs_preparation(private_sources[ASSEMBLY_CSHARP]):
            vendor_builds[ASSEMBLY_CSHARP] = ASSEMBLY_CSHARP_SHA256
    if needs_preparation(private_sources[MEMORY_PROFILER]):
        vendor_builds[MEMORY_PROFILER] = MEMORY_PROFILER_SHA256
    compile_wwise = check_inputs(windows, private, recipe, private_sources, plan, compatibility, wwise_directory,
                                 vendor_builds)
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
        output = build_assemblies(windows, private, scratch, dotnet, recipe, compile_wwise,
                                  private_sources, plan, compatibility, wwise_directory, vendor_builds, editor,
                                  args.tools.expanduser().resolve())
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
    steam_sources = ("SteamAchievements.cs", "SteamCompatibility.cs", "SteamExternalTransport.cs")
    compile_dll(dotnet, csc, [managed / name for name in references],
                [SOURCE / "steam" / name for name in steam_sources], helper)
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
    parser.add_argument("--unity-support", type=Path, help=f"Official Unity {UNITY_VERSION} MacStandaloneSupport directory")
    parser.add_argument("--unity-editor", type=Path, help=f"Unity {UNITY_VERSION} Editor app or executable providing the Mono runtime profile")
    parser.add_argument("--wwise-sources", type=Path, help="Directory with the verified official Wwise C# source pair")
    parser.add_argument("--tools", type=Path, default=Path.home() / "Library/Caches/Risk2Mac",
                        help="Local SDK and utility download cache")
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
