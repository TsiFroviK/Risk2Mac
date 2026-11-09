"""Assemble architecture-specific native components from private SDK files."""

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


UNITY_VERSION = "2023.1.0f1"
UNITY_FRAMEWORKS = (
    "UnityPlayer.dylib",
    "libmono-native.dylib",
    "libmonobdwgc-2.0.dylib",
    "libMonoPosixHelper.dylib",
)
PLAYER_NAME = "Risk of Rain 2 Player"
UNITY_RESOURCES = ("unity default resources", "MainMenu.nib")
WWISE_BUNDLE = "AkUnitySoundEngine.bundle"
WWISE_EXECUTABLE = Path("Contents/MacOS/AkUnitySoundEngine")
WWISE_RELEASE = Path("Wwise/API/Runtime/Plugins/Mac/Release") / WWISE_BUNDLE
WWISE_FILES = (Path("Contents/Info.plist"), Path("Contents/_CodeSignature/CodeResources"), WWISE_EXECUTABLE)
WWISE_SHA256 = "6a9b565ab72bcf52feda8cc429f4341cf091c16d309305a4d984ac7557d93a5e"


def require_file(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Expected a regular file: {path}")
    return path


def require_tree(path):
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f"Expected a directory: {path}")
    for entry in path.rglob("*"):
        if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
            raise ValueError(f"Unexpected entry in SDK directory: {entry}")
    return path


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(require_file(source), destination)


def copy_tree(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(require_tree(source), destination)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_unity(private, arch, supplied_support=None):
    local = private / "native/unity"
    if supplied_support is None and local.is_dir():
        # The owner can use an allowlisted native subset from a local port build.
        return local, local / "MacOS" / PLAYER_NAME, local / "MonoBleedingEdge/etc", local / "Resources/MainMenu.nib"

    support = supplied_support or private / "native/UnityMacSupport"
    if supplied_support is None and not support.is_dir():
        support = Path("/Applications/Unity/Hub/Editor") / UNITY_VERSION / "Unity.app/Contents/PlaybackEngines/MacStandaloneSupport"
    variation_arch = {"arm64": "arm64", "x86_64": "x64"}[arch]
    variations = support / "Variations"
    for variant in ("x64arm64", variation_arch):
        contents = variations / f"macos_{variant}_player_nondevelopment_mono/UnityPlayer.app/Contents"
        player = contents / "MacOS/UnityPlayer"
        if player.is_file():
            nib = support / "Source/Player/MacPlayer/MacPlayerEntryPoint/Resources/MainMenu.nib"
            return contents, player, support / "MonoBleedingEdge/etc", nib
    raise ValueError(
        f"Supply the Unity {UNITY_VERSION} macOS Mono build support directory with --unity-support "
        f"or {private / 'native/UnityMacSupport'}. Checked {variations}."
    )


def validate_unity_version(contents):
    runtime = require_file(contents / "Frameworks/UnityPlayer.dylib")
    if UNITY_VERSION.encode("ascii") not in runtime.read_bytes():
        raise ValueError(f"Expected Unity {UNITY_VERSION} in {runtime}")


def validate_wwise(bundle):
    for name in WWISE_FILES:
        require_file(bundle / name)
    with (bundle / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleExecutable") != WWISE_EXECUTABLE.name:
        raise ValueError(f"Unexpected Wwise bundle executable in {bundle}")
    if sha256(bundle / WWISE_EXECUTABLE) != WWISE_SHA256:
        raise ValueError("Expected the official Wwise Unity Integration 2024.1.18 Release macOS executable")


def prepare_wwise(private, temporary, supplied_wwise=None):
    directory = private / "native/wwise"
    candidate = supplied_wwise or directory / WWISE_BUNDLE
    if not supplied_wwise and not candidate.is_dir():
        candidate = directory / "Unity.Mac.tar.xz"
    if candidate.is_dir():
        bundle = candidate if candidate.name == WWISE_BUNDLE else candidate / WWISE_RELEASE
        validate_wwise(bundle)
        return bundle
    if not candidate.is_file():
        raise ValueError(f"Supply the official Wwise Unity Integration 2024.1.18 Mac archive at {candidate} or pass --wwise.")

    bundle = temporary / WWISE_BUNDLE
    wanted = {(WWISE_RELEASE / path).as_posix(): path for path in WWISE_FILES}
    seen = set()
    with tarfile.open(candidate, "r:*") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if name not in wanted:
                continue
            if not member.isfile() or name in seen or member.size > 32 * 1024 * 1024:
                raise ValueError(f"Invalid Wwise archive member: {member.name}")
            destination = bundle / wanted[name]
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            seen.add(name)
    validate_wwise(bundle)
    return bundle


def architectures(path):
    require_file(path)
    return subprocess.check_output(["/usr/bin/lipo", "-archs", str(path)], text=True).split()


def copy_slice(source, destination, arch):
    slices = architectures(source)
    if arch not in slices:
        raise ValueError(f"{source} has {', '.join(slices)}, expected {arch}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if slices == [arch]:
        copy_file(source, destination)
    else:
        subprocess.run(["/usr/bin/lipo", str(source), "-thin", arch, "-output", str(destination)], check=True)
    destination.chmod(0o755)
    if architectures(destination) != [arch]:
        raise ValueError(f"Failed to select {arch} in {destination}")


def build_steam(private, work, staging, arch):
    sources = Path(__file__).parent
    headers = require_tree(private / "native/steam-legacy-headers")
    manifest = json.loads(require_file(sources / "steam-legacy-headers.json").read_text(encoding="utf-8"))
    if not manifest or {path.name for path in headers.glob("*.h")} != set(manifest):
        raise ValueError("Steam legacy header inventory does not match this release")
    for name, expected in manifest.items():
        if Path(name).name != name:
            raise ValueError(f"Invalid Steam header manifest entry: {name}")
        header = require_file(headers / name)
        if sha256(header) != expected:
            raise ValueError(f"Unsupported Steam legacy header: {header}")
    generated = work / "SteamLegacyWrappers.cpp"
    subprocess.run([sys.executable, str(require_file(sources / "generate-steam-legacy.py")),
                    "--sdk", str(headers), "--output", str(generated)], check=True)
    bridge = work / "steam-bridge.o"
    common = ["/usr/bin/xcrun", "--sdk", "macosx"]
    target = ["-arch", arch, "-mmacosx-version-min=11.0"]
    subprocess.run([*common, "clang", *target, "-Wall", "-Wextra", "-Werror", "-c",
                    str(require_file(sources / "Risk2MacSteamBridge.c")), "-o", str(bridge)], check=True)
    library = staging / "Plugins/libRisk2MacSteamBridge.dylib"
    subprocess.run([*common, "clang++", *target, "-std=c++11", "-fvisibility=default", "-I", str(headers),
                    "-dynamiclib", str(bridge), str(generated), str(require_file(sources / "SteamLegacyServer.cpp")),
                    "-framework", "Foundation", "-framework", "CoreFoundation", "-framework", "Security",
                    "-install_name", "@rpath/libRisk2MacSteamBridge.dylib", "-o", str(library)], check=True)
    library.chmod(0o755)
    if architectures(library) != [arch]:
        raise ValueError(f"Steam bridge has the wrong architecture: {library}")


def build(args):
    if platform.system() != "Darwin":
        raise ValueError("The native stage requires macOS and the Xcode Command Line Tools.")
    app = args.app.resolve()
    private = args.private.resolve()
    game = args.game.resolve(strict=True)
    if app.suffix != ".app" or app.is_relative_to(private) or app.is_relative_to(game):
        raise ValueError("Use a fresh staging .app outside the Windows game and private-input directories.")
    contents = app / "Contents"
    unity, player, mono, nib = find_unity(private, args.arch, args.unity_support)
    validate_unity_version(unity)
    subprocess.run(["/usr/bin/xcrun", "--sdk", "macosx", "--find", "clang"], check=True, stdout=subprocess.DEVNULL)
    app.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="risk2mac-native-", dir=app.parent) as tmp:
        work = Path(tmp)
        staging = work / "Contents"
        copy_slice(player, staging / "MacOS" / PLAYER_NAME, args.arch)
        for filename in UNITY_FRAMEWORKS:
            copy_slice(unity / "Frameworks" / filename, staging / "Frameworks" / filename, args.arch)
        copy_tree(mono, staging / "MonoBleedingEdge/etc")
        copy_tree(nib, staging / "Resources/MainMenu.nib")
        copy_file(unity / "Resources/unity default resources", staging / "Resources/unity default resources")
        with (staging / "Resources/DefaultPreferences.plist").open("wb") as stream:
            plistlib.dump({"Screenmanager Is Fullscreen mode": "True"}, stream)

        wwise = prepare_wwise(private, work, args.wwise)
        plugin = staging / "Plugins" / WWISE_BUNDLE
        copy_file(wwise / WWISE_FILES[0], plugin / WWISE_FILES[0])
        copy_slice(wwise / WWISE_EXECUTABLE, plugin / WWISE_EXECUTABLE, args.arch)
        # The extracted slice changes the bundle seal. The main builder signs it after assembly.

        dpad = staging / "Plugins/libRoR2MacDpad.dylib"
        subprocess.run(
            ["/usr/bin/xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-arch", args.arch,
             "-mmacosx-version-min=11.0", "-dynamiclib", "-framework", "Foundation", "-framework", "GameController",
             "-install_name", "@rpath/libRoR2MacDpad.dylib", str(Path(__file__).with_name("MacDpadInput.m")), "-o", str(dpad)],
            check=True,
        )
        dpad.chmod(0o755)
        if architectures(dpad) != [args.arch]:
            raise ValueError(f"D-pad bridge has the wrong architecture: {dpad}")

        if args.steam:
            build_steam(private, work, staging, args.arch)

        # Native parts are disjoint from Resources/Data and the launcher. Check all
        # destinations before moving anything out of the temporary build directory.
        outputs = [
            Path("MacOS") / PLAYER_NAME,
            Path("Frameworks"),
            Path("MonoBleedingEdge"),
            *(Path("Resources") / name for name in UNITY_RESOURCES),
            Path("Resources/DefaultPreferences.plist"),
            Path("Plugins") / WWISE_BUNDLE,
            Path("Plugins/libRoR2MacDpad.dylib"),
        ]
        if args.steam:
            outputs.append(Path("Plugins/libRisk2MacSteamBridge.dylib"))
        for relative in outputs:
            target = contents / relative
            if target.exists() or target.is_symlink():
                raise ValueError(f"Refusing to replace an existing component: {target}")
            if not target.parent.resolve().is_relative_to(app):
                raise ValueError(f"A staging path resolves outside the app: {target}")
        for relative in outputs:
            target = contents / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / relative, target)
    print(f"Prepared Unity, Wwise and controller native components for {args.arch}.")


def export(args):
    contents = args.port_app.resolve(strict=True) / "Contents"
    validate_unity_version(contents)
    destination = args.private.resolve() / "native"
    repository = Path(__file__).resolve().parents[1]
    if destination.is_relative_to(repository):
        raise ValueError("Keep private native inputs outside the Risk2Mac repository.")
    if destination.is_relative_to(contents.parent):
        raise ValueError("Store private inputs outside the source application.")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"The private native input directory already exists: {destination}")
    source_wwise = contents / "Plugins" / WWISE_BUNDLE
    validate_wwise(source_wwise)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="risk2mac-native-inputs-", dir=destination.parent) as tmp:
        staged = Path(tmp) / "native"
        unity = staged / "unity"
        copy_file(contents / "MacOS" / PLAYER_NAME, unity / "MacOS" / PLAYER_NAME)
        for name in UNITY_FRAMEWORKS:
            copy_file(contents / "Frameworks" / name, unity / "Frameworks" / name)
        copy_tree(contents / "MonoBleedingEdge/etc", unity / "MonoBleedingEdge/etc")
        copy_tree(contents / "Resources/MainMenu.nib", unity / "Resources/MainMenu.nib")
        copy_file(contents / "Resources/unity default resources", unity / "Resources/unity default resources")
        for name in WWISE_FILES:
            copy_file(source_wwise / name, staged / "wwise" / WWISE_BUNDLE / name)
        os.replace(staged, destination)
    print(f"Saved private native inputs to {destination}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    for name in ("app", "game", "private"):
        build_parser.add_argument(f"--{name}", required=True, type=Path)
    build_parser.add_argument("--arch", required=True, choices=("arm64", "x86_64"))
    build_parser.add_argument("--unity-support", type=Path)
    build_parser.add_argument("--wwise", type=Path)
    build_parser.add_argument("--steam", action="store_true")
    build_parser.set_defaults(run=build)
    export_parser = commands.add_parser("export-private")
    export_parser.add_argument("--port-app", required=True, type=Path)
    export_parser.add_argument("--private", required=True, type=Path)
    export_parser.set_defaults(run=export)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        parser.exit(1, f"Risk2Mac native: {exc}\n")


if __name__ == "__main__":
    main()
