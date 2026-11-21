#!/usr/bin/env python3
"""Package the universal, locally signed Risk2Mac Builder for macOS."""

import argparse
import hashlib
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile


BUILDER = Path(__file__).resolve().parent
ROOT = BUILDER.parent
TITLE = "Risk2Mac Builder"
RECIPE_SOURCE = {
    "scripts": {".py", ".sh"},
    "manifests": {".json"},
    "native": {".py", ".c", ".cpp", ".h", ".m", ".json"},
    "managed": {".cs", ".csproj", ".json", ".config"},
}


def run(*args):
    subprocess.run(args, check=True)


def copy_recipe(resources):
    recipe = resources / "Recipe"
    for dirname, suffixes in RECIPE_SOURCE.items():
        source = ROOT / dirname
        for item in sorted(source.rglob("*")):
            relative = item.relative_to(ROOT)
            if any(part.startswith(".") or part in {"bin", "obj", "__pycache__"} for part in relative.parts):
                continue
            if item.is_symlink() or not item.is_file() or item.suffix.lower() not in suffixes:
                continue
            destination = recipe / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, destination)
    shutil.copyfile(ROOT / "LICENSE", resources / "LICENSE.txt")


def make_icon(stage, resources):
    icons = stage / "R2M.iconset"
    icons.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            pixels = str(size * scale)
            run("/usr/bin/sips", "-z", pixels, pixels, str(BUILDER / "R2M.png"), "--out", str(icons / name))
    run("/usr/bin/iconutil", "-c", "icns", str(icons), "-o", str(resources / "R2M.icns"))


def package(output, version, staging=None):
    if sys.platform != "darwin":
        raise ValueError("The builder must be packaged on macOS.")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Expected a numeric major.minor.patch version.")
    output.mkdir(parents=True, exist_ok=True)
    name = f"Risk2Mac-Builder-{version}-macOS-universal.dmg"
    if (output / name).exists():
        raise ValueError(f"Release image already exists: {output / name}")
    with tempfile.TemporaryDirectory(prefix="risk2mac-builder-", dir=staging) as temp:
        stage = Path(temp)
        volume = stage / "volume"
        app = volume / f"{TITLE}.app"
        contents = app / "Contents"
        macos = contents / "MacOS"
        resources = contents / "Resources"
        macos.mkdir(parents=True)
        resources.mkdir()
        for arch in ("arm64", "x86_64"):
            run("/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-parse-as-library", "-O",
                "-target", f"{arch}-apple-macos11.0", str(BUILDER / "Risk2MacBuilder.swift"),
                "-o", str(stage / arch))
        executable = macos / "Risk2MacBuilder"
        run("/usr/bin/lipo", "-create", str(stage / "arm64"), str(stage / "x86_64"), "-output", str(executable))
        executable.chmod(0o755)
        metadata = {
            "CFBundleName": TITLE, "CFBundleDisplayName": TITLE, "CFBundleIdentifier": "io.github.tsifrovik.risk2mac.builder",
            "CFBundlePackageType": "APPL", "CFBundleExecutable": executable.name, "CFBundleIconFile": "R2M",
            "CFBundleShortVersionString": version, "CFBundleVersion": version, "LSMinimumSystemVersion": "11.0",
            "CFBundleDevelopmentRegion": "en", "CFBundleLocalizations": ["en", "ru"],
            "LSApplicationCategoryType": "public.app-category.utilities", "NSHighResolutionCapable": True,
        }
        (contents / "Info.plist").write_bytes(plistlib.dumps(metadata))
        copy_recipe(resources)
        make_icon(stage, resources)
        (volume / "Applications").symlink_to("/Applications")
        run("/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app))
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
        built = stage / name
        run("/usr/bin/hdiutil", "create", "-volname", TITLE, "-srcfolder", str(volume),
            "-format", "UDZO", "-fs", "HFS+", str(built))
        run("/usr/bin/hdiutil", "verify", str(built))
        if (output / name).exists():
            raise ValueError(f"Output was created during packaging: {output / name}")
        shutil.copyfile(built, output / name)
        digest = hashlib.sha256(built.read_bytes()).hexdigest()
        (output / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="ascii")
    print(f"Built {output / name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--staging", type=Path, help="Temporary build directory on an APFS volume")
    args = parser.parse_args()
    try:
        package(args.output.expanduser().resolve(), args.version, args.staging)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Risk2Mac Builder: {error}\n")
