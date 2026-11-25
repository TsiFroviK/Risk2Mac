#!/usr/bin/env python3
"""Assemble the reviewed macOS port from local inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile

from icon import install_icon
from risk2mac_depth import find_unity_editor
from risk2mac_unity import MANAGED_DIRECTORIES, managed_modules_match, open_unity_setup, prepare_unity, sha256
from risk2mac_wwise_sdk import SOURCE_FILES, discover_wwise, open_wwise_setup, stage_sources
from steam_install import PLAY_SHORTCUT_HINT, install_destination, print_shortcut_instructions, register_shortcut, steam_root


ROOT = Path(__file__).resolve().parent.parent
TITLE = "Risk of Rain 2"
SDK_VERSION = "8.0.427"
SDK_HASHES = {
    "arm64": "79786b93f249d233b15f1d6338d4798bd71c8143f267c5e84de76c9eb8a1054920e56ea5478f7bddfb74b951cc58aaca11fbd780cf134350b7cb7cdcb42a8c8c",
    "x64": "a6c6d0a3708b15e20285f4f662195b6fd276e3df2fc91c0a38f30681ff8a23d5e322ada8a92e9b410343449eab635d01b30a4f55aeef6f884651a559cce07707",
}


def run(*args):
    subprocess.run(args, check=True)


def host_architecture():
    if sys.platform != "darwin":
        raise ValueError("Run this builder on macOS.")
    # Detect Apple silicon even when Terminal is running through Rosetta.
    arm = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
        capture_output=True, text=True, check=False,
    )
    if arm.stdout.strip() == "1":
        return "arm64"
    machine = os.uname().machine
    if machine in ("arm64", "x86_64"):
        return machine
    raise ValueError(f"Unsupported Mac architecture: {machine}")


def has_sdk(dotnet):
    if not dotnet:
        return False
    try:
        check = subprocess.run([dotnet, "--list-sdks"], capture_output=True, text=True)
    except OSError:
        return False
    return check.returncode == 0 and any(line.startswith("8.0.") for line in check.stdout.splitlines())


def dotnet_sdk(host, cache, specified):
    installed = str(specified) if specified else shutil.which("dotnet")
    if has_sdk(installed):
        return installed
    if specified:
        raise ValueError(f"The supplied dotnet has no .NET 8 SDK: {specified}")
    rid = "arm64" if host == "arm64" else "x64"
    target = cache / f"dotnet-{SDK_VERSION}-osx-{rid}"
    if (target / "dotnet").is_file() and has_sdk(str(target / "dotnet")):
        return str(target / "dotnet")
    if target.exists():
        raise ValueError(f"The SDK cache is incomplete. Move it aside before retrying: {target}")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sdk-", dir=cache) as tmp:
        archive = Path(tmp) / "sdk.tar.gz"
        expanded = Path(tmp) / "sdk"
        expanded.mkdir()
        url = f"https://builds.dotnet.microsoft.com/dotnet/Sdk/{SDK_VERSION}/dotnet-sdk-{SDK_VERSION}-osx-{rid}.tar.gz"
        print(f"Downloading .NET SDK {SDK_VERSION} from Microsoft ({rid})", flush=True)
        run("/usr/bin/curl", "--fail", "--location", "--proto", "=https", "--retry", "2", "--progress-bar", "-o", str(archive), url)
        digest = hashlib.sha512()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != SDK_HASHES[rid]:
            raise ValueError("Microsoft SDK archive failed SHA-512 verification.")
        run("/usr/bin/tar", "-xzf", str(archive), "-C", str(expanded))
        if not has_sdk(str(expanded / "dotnet")):
            raise ValueError("The downloaded .NET 8 SDK could not run on this host.")
        expanded.rename(target)
    return str(target / "dotnet")


def check_windows_depot(game):
    data = game / (TITLE + "_Data")
    managed = json.loads((ROOT / "managed/inputs.json").read_text(encoding="utf-8"))
    assets = json.loads((ROOT / "manifests/assets.json").read_text(encoding="utf-8"))
    steam = assets["steam"]
    catalog = next(row for row in assets["files"] if row["kind"] == "catalog")
    anchors = (
        (data / "Managed/RoR2.dll", managed["windows_anchors"]["RoR2.dll"]),
        (data / catalog["path"], catalog["input_sha256"]),
    )
    for path, expected in anchors:
        if path.is_file() and sha256(path) == expected:
            continue
        raise ValueError(
            "The selected Windows game files do not match the supported Steam depot.\n"
            f"Expected {path.relative_to(data)} from Steam build {steam['build_id']}. "
            "Move any earlier depot download aside, then enter this command in the Steam console:\n"
            f"download_depot {steam['app_id']} {steam['depot_id']} {steam['manifest_id']}\n"
            f"Select the completed depot_{steam['depot_id']} folder printed by Steam."
        )
    return steam


def assemble_metadata(app, game, steam_build):
    contents = app / "Contents"
    launcher = contents / "MacOS" / TITLE
    shutil.copyfile(ROOT / "scripts" / "launch.sh", launcher)
    launcher.chmod(0o755)
    icon = contents / "Resources" / "RiskOfRain2.icns"
    info = {
        "CFBundleDevelopmentRegion": "en", "CFBundleDisplayName": TITLE,
        "CFBundleExecutable": TITLE, "CFBundleIdentifier": "com.Hopoo-Games--LLC.Risk-of-Rain-2",
        "CFBundleName": TITLE, "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": steam_build["game_version"], "CFBundleVersion": str(steam_build["game_build"]),
        "CFBundleSupportedPlatforms": ["MacOSX"], "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.games", "NSMainNibFile": "MainMenu",
        "NSPrincipalClass": "PlayerApplication", "UnityBuildNumber": "a008fa768e6c",
    }
    if install_icon(game / (TITLE + ".exe"), icon):
        info["CFBundleIconFile"] = icon.name
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    (contents / "Config").mkdir(exist_ok=True)
    (contents / "Config" / "config.cfg").write_text("vsync_count 0;\nfps_max -1;\n", encoding="utf-8")
    (contents / "Mods").mkdir(exist_ok=True)
    (contents / "Mods" / "enabled_mods.txt").touch()
    (contents / "Resources" / "PortBuild.txt").write_text(
        f"Risk2Mac local build\nGame data profile {steam_build['game_version']}#{steam_build['game_build']} / Unity 2023.1.0f1\n"
        f"Steam build {steam_build['build_id']}, Windows manifest {steam_build['manifest_id']}\n", encoding="utf-8",
    )


def unity_support_for_build(options, private, cache, editor):
    """Select native and managed inputs separately for partially prepared builds."""
    if options.unity_support:
        support = options.unity_support.expanduser().resolve()
        return support, support
    support = editor.parent.parent / "PlaybackEngines/MacStandaloneSupport" if editor else None
    manifest = ROOT / "managed/inputs.json"
    if support is not None and support.is_dir():
        if not managed_modules_match(support / MANAGED_DIRECTORIES[0], manifest):
            print("The Editor's Mac support modules differ from the pinned runtime. Using alternate Mac support.", flush=True)
            support = None
    else:
        support = None
    if options.unity_editor and support:
        return support, support
    private_player = (private / "native/unity").is_dir()
    if private_player and managed_modules_match(private / "managed", manifest):
        return None, None
    local = private / "native/UnityMacSupport"
    if local.is_dir():
        support = local
    if support is None:
        support = prepare_unity(cache)
    return (None if private_player else support), support


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", choices=("unity", "wwise"), help="Open the official SDK setup and sign-in flow")
    parser.add_argument("--game", type=Path, help="Required for a build. Windows game folder containing Risk of Rain 2_Data")
    parser.add_argument("--private", type=Path, help="Optional compatibility inputs from an earlier local build")
    parser.add_argument("--output", type=Path, help="New .app path for a local build on a Mac filesystem")
    parser.add_argument("--arch", choices=("arm64", "x86_64"), help="Override the default host architecture")
    parser.add_argument("--dotnet", type=Path, help="Use a local dotnet executable with the .NET 8 SDK")
    parser.add_argument("--tools", type=Path, default=Path.home() / "Library/Caches/Risk2Mac", help="Local SDK download cache")
    parser.add_argument("--wwiser", type=Path, help="Local wwiser checkout for sound bank conversion")
    parser.add_argument("--unity-support", type=Path, help="Official Unity 2023.1.0f1 MacStandaloneSupport directory")
    parser.add_argument("--unity-editor", type=Path, help="Unity 2023.1.0f1 app or executable for generating the depth-copy shader")
    parser.add_argument("--wwise", type=Path, help="Wwise 2024.1.18 export folder, macOS archive, extracted integration, or Unity project")
    parser.add_argument("--steam", action="store_true", help="Enable Steam integration using the Steam client installed on the destination Mac")
    parser.add_argument("--steam-library", type=Path, help="Existing Steam library root (Steam Settings > Storage)")
    options = parser.parse_args()
    if options.setup:
        host_architecture()
        if options.setup == "unity":
            try:
                editor = find_unity_editor(options.unity_editor)
            except ValueError:
                editor = find_unity_editor()
            open_unity_setup(editor is not None)
        else:
            open_wwise_setup()
            print("Sign in to Audiokinetic Launcher. In Unity > Offline Integration Files, export Wwise Unity Integration 2024.1.18 for macOS and Windows into Downloads. Then retry the build.")
        return
    if not options.game:
        parser.error("A build requires --game. Use --setup unity or --setup wwise to prepare an SDK.")
    if options.steam and options.output:
        parser.error("--steam selects the output from Steam's libraries. Omit --output and optionally supply --steam-library.")
    if not options.steam and (not options.output or options.steam_library):
        parser.error("Use --output for a local build. --steam-library requires --steam.")
    host = host_architecture()
    arch = options.arch or host
    game, cache = (p.expanduser().resolve() for p in (options.game, options.tools))
    supplied = options.private.expanduser().resolve() if options.private else None
    steam = steam_root() if options.steam else None
    output = install_destination(steam, options.steam_library) if steam else options.output.expanduser().resolve()
    if not (game / (TITLE + "_Data") / "StreamingAssets").is_dir():
        raise ValueError(f"Windows game data not found in {game}")
    if supplied is None and any(not (game / name).is_file() for name in (TITLE + ".exe", "UnityPlayer.dll")):
        raise ValueError(f"Select the complete Windows installation with {TITLE}.exe and UnityPlayer.dll: {game}")
    steam_build = check_windows_depot(game)
    if supplied and not supplied.is_dir():
        raise ValueError(f"Local compatibility input directory not found: {supplied}")
    if supplied and supplied.is_relative_to(ROOT):
        raise ValueError("Keep local compatibility inputs outside the Risk2Mac repository.")
    if output.suffix != ".app" or output.exists() or output.is_symlink():
        raise ValueError(f"Choose a new .app output path: {output}")
    # A Steam build may read an existing Windows install in its intended game
    # folder. Keep every subprocess's staging files outside that input tree.
    staging_parent = output.parent.parent if steam else output.parent
    if any(location.is_relative_to(source) for location in (staging_parent, cache) for source in (ROOT, game)):
        raise ValueError("Choose build and tool cache paths outside the repository and the game.")
    if output.is_relative_to(ROOT):
        raise ValueError("Choose an output path outside the repository.")
    if supplied and (output.is_relative_to(supplied) or staging_parent.is_relative_to(supplied)):
        raise ValueError("Choose an output path outside the local compatibility inputs directory.")
    editor = find_unity_editor(options.unity_editor)
    if not supplied and editor is None:
        raise ValueError("This build requires the activated Unity Editor 2023.1.0f1. Use ./build.sh --setup unity.")
    staging_parent.mkdir(parents=True, exist_ok=True)
    run("/usr/bin/xcode-select", "-p")
    print(f"Host: {host}. Target: {arch}.\nOutput: {output}", flush=True)
    with tempfile.TemporaryDirectory(prefix=".risk2mac-", dir=staging_parent) as tmp:
        stage = Path(tmp)
        private = supplied or stage / "inputs"
        private.mkdir(exist_ok=True)
        prepared_wwise = (private / "managed/AK.Wwise.Unity.API.dll").is_file()
        private_sources = all((private / "wwise" / relative.name).is_file() for relative, _ in SOURCE_FILES.values())
        needs_wwise_sources = not (prepared_wwise or private_sources)
        wwise = discover_wwise(private, options.wwise, want_sources=needs_wwise_sources)
        if wwise is None:
            raise ValueError("Wwise Unity Integration 2024.1.18 was not found. Run ./build.sh --setup wwise or select an official archive with --wwise.")
        probe = stage / "permissions"
        probe.touch()
        probe.chmod(0o600)
        if stat.S_IMODE(probe.stat().st_mode) != 0o600:
            raise ValueError("The output volume must preserve Unix permissions. Use APFS, Mac OS Extended, or a mounted APFS disk image.")
        app = stage / output.name
        app.mkdir()
        common = ["--game", str(game), "--app", str(app), "--private", str(private)]
        sources = stage / "wwise-sources"
        if needs_wwise_sources and not stage_sources(wwise, sources):
            raise ValueError("Wwise C# inputs are missing. Run ./build.sh --setup wwise and export both the macOS and Windows Unity Integration archives into Downloads.")
        print("[1/4] Native runtime", flush=True)
        native_support, managed_support = unity_support_for_build(options, private, cache, editor)
        native_args = ["--wwise", str(wwise.native)]
        if native_support:
            native_args.extend(("--unity-support", str(native_support)))
        if options.steam:
            run(sys.executable, str(ROOT / "scripts/prepare-steam.py"), "--private", str(private))
            native_args.append("--steam")
        run("/bin/bash", str(ROOT / "scripts/build-native.sh"), *common, "--arch", arch, *native_args)
        print("[2/4] Managed assemblies", flush=True)
        specified_dotnet = options.dotnet.expanduser().resolve() if options.dotnet else None
        dotnet = dotnet_sdk(host, cache, specified_dotnet)
        environment = dict(os.environ, DOTNET_NOLOGO="1", DOTNET_CLI_TELEMETRY_OPTOUT="1",
                           DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_ADD_GLOBAL_TOOLS_TO_PATH="false",
                           DOTNET_CLI_HOME=str(cache / "dotnet-home"), NUGET_PACKAGES=str(cache / "nuget"))
        managed_args = ["--steam"] if options.steam else []
        if managed_support:
            managed_args.extend(("--unity-support", str(managed_support)))
        if editor:
            managed_args.extend(("--unity-editor", str(editor)))
        if needs_wwise_sources:
            managed_args.extend(("--wwise-sources", str(sources)))
        subprocess.run([sys.executable, str(ROOT / "scripts/build-managed.py"), *common, "--dotnet", dotnet,
                        "--tools", str(cache), *managed_args],
                       check=True, env=environment)
        print("[3/4] Game data", flush=True)
        extra = ["--wwiser", str(options.wwiser.expanduser().resolve())] if options.wwiser else []
        if editor:
            extra.extend(("--unity-editor", str(editor)))
        subprocess.run([sys.executable, str(ROOT / "scripts/build-assets.py"), *common, "--arch", arch, "--dotnet", dotnet,
                        "--tools", str(cache), *extra],
                       check=True, env=environment)
        print("[4/4] App bundle and signature", flush=True)
        assemble_metadata(app, game, steam_build)
        run("/usr/bin/codesign", "--force", "--sign", "-", "--deep", str(app))
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
        if steam and install_destination(steam, options.steam_library) != output:
            raise ValueError("The selected Steam library changed during the build")
        if output.exists() or output.is_symlink():
            raise ValueError(f"Output was created during this build: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        app.rename(output)
    print(f"Built {output}", flush=True)
    if steam:
        try:
            print(register_shortcut(steam, output), flush=True)
            print(PLAY_SHORTCUT_HINT, flush=True)
        except (OSError, ValueError, plistlib.InvalidFileException) as error:
            print(f"Steam shortcut could not be registered automatically: {error}", flush=True)
            print_shortcut_instructions(output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Risk2Mac: {error}")
