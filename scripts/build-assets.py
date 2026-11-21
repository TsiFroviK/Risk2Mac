#!/usr/bin/env python3
"""Assemble the game data for the reviewed Risk2Mac release."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile

from risk2mac_banks import BankConverter, download_wwiser
from risk2mac_depth import build_depth_bundle, find_unity_editor
from risk2mac_shaders import build_shader_bundles, prepare_asset_python, shader_recipes
from risk2mac_splash import build_splash_stream
from risk2mac_startup import transform_startup
from risk2mac_texture_streams import recipes as texture_recipes


REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "manifests" / "assets.json"
DATA = Path("Contents/Resources/Data")
RUNTIME_PATH = "{UnityEngine.AddressableAssets.Addressables.RuntimePath}"
BUFFER = 1024 * 1024
EDITOR_GENERATORS = {"depth-copy": build_depth_bundle, "unity-splash": build_splash_stream}
EDITOR_ASSETS = {"unity-textures", *EDITOR_GENERATORS}
ASSET_KINDS = {"copy", "bank", "catalog", "line-endings", "startup", "private", *EDITOR_ASSETS}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(BUFFER):
            digest.update(block)
    return digest.hexdigest()


def within(base: Path, relative: str | Path) -> Path:
    result = base / relative
    if not result.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"File escapes its input or output directory: {result}")
    return result


def load_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["format"] != 1:
        raise ValueError("Unsupported asset manifest version")
    rows = manifest["files"]
    seen = set()
    for row in rows:
        relative = PurePosixPath(row["path"])
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or "\\" in row["path"]
            or relative.parts[0] == "Managed"
            or row["kind"] not in ASSET_KINDS
        ):
            raise ValueError(f"Invalid asset manifest entry: {row['path']}")
        key = str(relative).casefold()
        if key in seen:
            raise ValueError(f"Duplicate asset manifest entry: {relative}")
        seen.add(key)
    return rows


def check_file(path: Path, expected: str, size: int | None = None):
    if not path.is_file():
        raise FileNotFoundError(f"Required asset missing: {path}")
    if (size is not None and path.stat().st_size != size) or sha256_file(path) != expected:
        raise ValueError(f"Asset differs from the supported Windows build or local port data: {path}")


def verify_all(jobs):
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Consuming the iterator propagates any missing file or mismatch.
        for _ in executor.map(lambda job: check_file(*job), jobs):
            pass


def output_file(path: Path, row, *, source: Path | None = None, data: bytes | None = None):
    if path.exists() or path.is_symlink():
        check_file(path, row["sha256"], row["bytes"])
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("xb") as destination:
            created = True
            if source is not None:
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, destination, BUFFER)
            else:
                destination.write(data)
        check_file(path, row["sha256"], row["bytes"])
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


def normalize_catalog(source: Path) -> bytes:
    document = json.loads(source.read_text(encoding="utf-8-sig"))
    ids = document["m_InternalIds"]
    replaced = 0
    for index, value in enumerate(ids):
        if isinstance(value, str) and RUNTIME_PATH in value and "\\" in value:
            ids[index] = value.replace("\\", "/")
            replaced += 1
    if not replaced:
        raise ValueError("No Windows Addressables paths found in catalog")
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def prepare_assets(game: Path, app: Path | None, private: Path, wwiser: Path | None,
                   check_only: bool, tool_cache: Path | None = None, unity_editor: Path | None = None,
                   dotnet: str | None = None):
    data = game if game.name == "Risk of Rain 2_Data" else game / "Risk of Rain 2_Data"
    private_data = within(private, Path("assets") / DATA)
    rows = load_manifest()
    shaders = shader_recipes()
    textures = texture_recipes()
    checks = []
    prepared_startup = set()
    missing_shaders = {}
    missing_editor_assets = set()
    asset_editor = None
    if wwiser is None and (private / "wwiser" / ".git").exists():
        wwiser = private / "wwiser"
    fetch_wwiser = wwiser is None and tool_cache is not None and any(
        row["kind"] == "bank" and not within(private_data, row["path"]).is_file() for row in rows
    )
    for row in rows:
        kind = row["kind"]
        relative = row["path"]
        if kind in EDITOR_ASSETS:
            local = within(private_data, relative)
            if not local.is_file():
                asset_editor = asset_editor or find_unity_editor(unity_editor)
                if asset_editor is None:
                    raise ValueError(f"Generating {relative} requires Unity Editor 2023.1.0f1 (./build.sh --setup unity), or supply the prepared copy at {local}.")
                if kind == "unity-textures":
                    recipe = textures.get(relative)
                    if not recipe or recipe["sha256"] != row["sha256"] or recipe["size"] != row["bytes"]:
                        raise ValueError(f"Texture conversion recipe disagrees with asset manifest: {relative}")
                    checks.extend((within(data, name), digest, None) for name, digest in recipe["inputs"].items())
                missing_editor_assets.add(relative)
            else:
                checks.append((local, row["sha256"], row["bytes"]))
            continue
        if kind == "startup" and within(private_data, relative).is_file():
            # Earlier recipes accepted Windows input sets without startup metadata.
            checks.append((within(private_data, relative), row["sha256"], row["bytes"]))
            prepared_startup.add(relative)
            continue
        if kind == "private":
            local = within(private_data, relative)
            bundle = Path(relative).name
            recipe = shaders.get(bundle)
            if recipe is not None and not local.is_file():
                if recipe["output"] != row["sha256"] or recipe["size"] != row["bytes"]:
                    raise ValueError(f"Shader conversion manifest disagrees with asset manifest: {relative}")
                checks.append((within(data, relative), recipe["input"], None))
                missing_shaders[relative] = bundle
            else:
                checks.append((local, row["sha256"], row["bytes"]))
        else:
            checks.append(
                (
                    within(data, relative),
                    row.get("input_sha256", row["sha256"]),
                    row["bytes"] if kind == "copy" else None,
                )
            )
        if kind == "bank" and wwiser is None and not fetch_wwiser:
            checks.append((within(private_data, relative), row["sha256"], row["bytes"]))
    verify_all(checks)
    compute_editor = None
    if any(shaders[name]["mode"] == "compute" for name in missing_shaders.values()):
        compute_editor = asset_editor or find_unity_editor(unity_editor)
        if compute_editor is None:
            raise ValueError("Missing shader bundles require an activated Unity 2023.1.0f1 Editor with Mac Build Support (./build.sh --setup unity). Use --unity-editor for a custom installation.")
    if fetch_wwiser:
        wwiser = download_wwiser(tool_cache)
    converter = BankConverter(wwiser) if wwiser is not None else None
    counts = Counter(row["kind"] for row in rows)
    print(f"Asset inputs verified: {len(rows)} files, {dict(counts)}", flush=True)
    if missing_shaders:
        print(f"{len(missing_shaders)} shader bundles will be converted from the Windows installation", flush=True)
    if check_only:
        return

    assert app is not None
    destination = within(app, DATA)
    app.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="risk2mac-converted-assets-", dir=app.parent) as temporary:
        stage = Path(temporary)
        cache = tool_cache or Path.home() / "Library/Caches/Risk2Mac"
        generated = None
        if missing_shaders:
            generated = build_shader_bundles(data, stage, cache, missing_shaders.values(), compute_editor)
        for row in rows:
            kind = row["kind"]
            relative = row["path"]
            source = within(data, relative)
            target = within(destination, relative)
            if kind == "catalog":
                output_file(target, row, data=normalize_catalog(source))
            elif kind == "line-endings":
                output_file(target, row, data=source.read_bytes().replace(b"\r\n", b"\n"))
            elif kind == "startup" and relative not in prepared_startup:
                output_file(target, row, data=transform_startup(relative, source))
            elif relative in missing_editor_assets and kind == "unity-textures":
                python = prepare_asset_python(stage, cache)
                stream = within(stage, relative)
                command = [str(python), "-u", str(REPO / "scripts/risk2mac_texture_streams.py"),
                           "--game-data", str(data), "--editor", str(asset_editor),
                           "--output", str(stream), "--asset", relative]
                if dotnet and textures[relative].get("needs_dotnet"):
                    command.extend(("--dotnet", dotnet))
                result = subprocess.run(command)
                if result.returncode:
                    raise ValueError(f"Unity could not generate {relative}. Check the build log, Editor license and Mac Build Support (./build.sh --setup unity).")
                output_file(target, row, source=stream)
            elif relative in missing_editor_assets:
                output_file(target, row, data=EDITOR_GENERATORS[kind](asset_editor))
            elif kind == "bank" and converter is not None:
                output_file(target, row, data=converter.convert(source))
            else:
                if relative in missing_shaders:
                    source = within(generated, missing_shaders[relative])
                elif kind in {"private", "bank", "startup", *EDITOR_ASSETS}:
                    source = within(private_data, relative)
                output_file(target, row, source=source)
    print(f"Verified assembled assets: {len(rows)}", flush=True)


def export_private(source_app: Path, private: Path, include_banks: bool):
    # The owner-provided kit is deliberately separate from the public checkout.
    if private.resolve().is_relative_to(REPO):
        raise ValueError("Place the private inputs outside the Risk2Mac checkout")
    source = within(source_app, DATA)
    destination = within(private, Path("assets") / DATA)
    if destination.resolve().is_relative_to(source.resolve()):
        raise ValueError("Private inputs must be stored separately from the source .app")
    kinds = {"private", *EDITOR_ASSETS}
    if include_banks:
        kinds.add("bank")
    rows = [row for row in load_manifest() if row["kind"] in kinds]
    verify_all(
        (within(source, row["path"]), row["sha256"], row["bytes"])
        for row in rows
    )
    for row in rows:
        output_file(
            within(destination, row["path"]), row, source=within(source, row["path"])
        )
    print(f"Exported {len(rows)} private asset inputs outside the checkout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--game", type=Path, help="Exact Windows game installation")
    operation.add_argument("--export-private", type=Path, metavar="APP", help="Existing reviewed port .app")
    parser.add_argument("--app", type=Path, help="Staged macOS .app output")
    parser.add_argument("--private", required=True, type=Path, help="Private inputs directory")
    parser.add_argument("--wwiser", type=Path, help="Optional pinned local wwiser Git checkout")
    parser.add_argument("--tools", type=Path, help="Fetch and cache the pinned upstream wwiser if converted banks are missing")
    parser.add_argument("--unity-editor", type=Path, help="Unity 2023.1.0f1 app or executable for building the depth-copy shader")
    parser.add_argument("--dotnet", help=".NET 8 executable for startup texture decoding")
    parser.add_argument("--check", action="store_true", help="Validate build inputs without assembling")
    parser.add_argument("--include-banks", action="store_true", help="Export the 247 converted audio banks too")
    args = parser.parse_args()
    if args.export_private:
        if args.app or args.wwiser or args.tools or args.unity_editor or args.dotnet or args.check:
            parser.error("--export-private only accepts --private and --include-banks")
        export_private(args.export_private, args.private, args.include_banks)
        return
    if args.include_banks or (not args.app and not args.check):
        parser.error("Building requires --app or --check. --include-banks is for export only.")
    if args.app:
        if args.app.suffix != ".app" or args.app.is_symlink():
            parser.error("--app must name a local .app staging directory")
        for source in (args.game, args.private):
            if args.app.resolve().is_relative_to(source.resolve()) or source.resolve().is_relative_to(args.app.resolve()):
                parser.error("--app and its input directories must be separate")
    prepare_assets(args.game, args.app, args.private, args.wwiser, args.check, args.tools, args.unity_editor, args.dotnet)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"Risk2Mac assets: {error}")
