#!/usr/bin/env python3
"""Assemble the reviewed macOS port from local inputs."""

import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile

from icon import install_icon


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


def assemble_metadata(app, game):
    contents = app / "Contents"
    launcher = contents / "MacOS" / TITLE
    shutil.copyfile(ROOT / "scripts" / "launch.sh", launcher)
    launcher.chmod(0o755)
    icon = contents / "Resources" / "RiskOfRain2.icns"
    info = {
        "CFBundleDevelopmentRegion": "en", "CFBundleDisplayName": TITLE,
        "CFBundleExecutable": TITLE, "CFBundleIdentifier": "com.Hopoo-Games--LLC.Risk-of-Rain-2",
        "CFBundleName": TITLE, "CFBundlePackageType": "APPL", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": "1.5.0", "CFBundleVersion": "1",
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
        "Risk2Mac local build\nGame data profile 1.5.0 / Unity 2023.1.0f1\n", encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, type=Path, help="Windows game folder containing Risk of Rain 2_Data")
    parser.add_argument("--private", required=True, type=Path, help="Directory of local prerequisite files")
    parser.add_argument("--output", required=True, type=Path, help="New .app path on a Mac filesystem")
    parser.add_argument("--arch", choices=("arm64", "x86_64"), help="Override the default host architecture")
    parser.add_argument("--dotnet", type=Path, help="Use a local dotnet executable with the .NET 8 SDK")
    parser.add_argument("--tools", type=Path, default=Path.home() / "Library/Caches/Risk2Mac", help="Local SDK download cache")
    parser.add_argument("--wwiser", type=Path, help="Local wwiser checkout for sound bank conversion")
    parser.add_argument("--unity-support", type=Path, help="Official Unity 2023.1.0f1 MacStandaloneSupport directory")
    parser.add_argument("--wwise", type=Path, help="Official Wwise 2024.1.18 macOS integration archive or directory")
    parser.add_argument("--steam", action="store_true", help="Enable Steam integration using the Steam client installed on the destination Mac")
    options = parser.parse_args()
    host = host_architecture()
    arch = options.arch or host
    game, private, output, cache = (p.expanduser().resolve() for p in (options.game, options.private, options.output, options.tools))
    if not (game / (TITLE + "_Data") / "StreamingAssets").is_dir():
        raise ValueError(f"Windows game data not found in {game}")
    if not private.is_dir():
        raise ValueError(f"Private prerequisites directory not found: {private}")
    if private == ROOT or ROOT in private.parents:
        raise ValueError("Keep private prerequisites outside the Risk2Mac repository.")
    if output.suffix != ".app" or output.exists():
        raise ValueError(f"Choose a new .app output path: {output}")
    for location in (output, cache):
        if any(location == path or path in location.parents for path in (ROOT, game)):
            raise ValueError(f"Choose output and tool cache paths outside the repository and the game: {location}")
    if private in output.parents:
        raise ValueError("Choose an output path outside the private inputs directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    run("/usr/bin/xcode-select", "-p")
    print(f"Host: {host}. Target: {arch}.", flush=True)
    with tempfile.TemporaryDirectory(prefix=".risk2mac-", dir=output.parent) as tmp:
        stage = Path(tmp)
        probe = stage / "permissions"
        probe.touch()
        probe.chmod(0o600)
        if stat.S_IMODE(probe.stat().st_mode) != 0o600:
            raise ValueError("The output volume must preserve Unix permissions. Use APFS, Mac OS Extended, or a mounted APFS disk image.")
        app = stage / output.name
        app.mkdir()
        common = ["--game", str(game), "--app", str(app), "--private", str(private)]
        print("[1/4] Native runtime", flush=True)
        native_args = []
        for flag, path in (("--unity-support", options.unity_support), ("--wwise", options.wwise)):
            if path:
                native_args.extend((flag, str(path.expanduser().resolve())))
        if options.steam:
            native_args.append("--steam")
        run("/bin/bash", str(ROOT / "scripts/build-native.sh"), *common, "--arch", arch, *native_args)
        print("[2/4] Game data", flush=True)
        extra = ["--wwiser", str(options.wwiser.expanduser().resolve())] if options.wwiser else []
        run(sys.executable, str(ROOT / "scripts/build-assets.py"), *common, *extra)
        print("[3/4] Managed assemblies", flush=True)
        dotnet = dotnet_sdk(host, cache, options.dotnet.expanduser().resolve() if options.dotnet else None)
        environment = dict(os.environ, DOTNET_NOLOGO="1", DOTNET_CLI_TELEMETRY_OPTOUT="1",
                           DOTNET_GENERATE_ASPNET_CERTIFICATE="false", DOTNET_ADD_GLOBAL_TOOLS_TO_PATH="false",
                           DOTNET_CLI_HOME=str(cache / "dotnet-home"), NUGET_PACKAGES=str(cache / "nuget"))
        managed_args = ["--steam"] if options.steam else []
        subprocess.run([sys.executable, str(ROOT / "scripts/build-managed.py"), *common, "--dotnet", dotnet, *managed_args],
                       check=True, env=environment)
        print("[4/4] App bundle and signature", flush=True)
        assemble_metadata(app, game)
        run("/usr/bin/codesign", "--force", "--sign", "-", "--deep", str(app))
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
        if output.exists():
            raise ValueError(f"Output was created during this build: {output}")
        app.rename(output)
    print(f"Built {output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Risk2Mac: {error}")
