#!/usr/bin/env python3
"""Prepare private managed inputs from an existing authorized local build."""

import argparse
from pathlib import Path
import runpy
import shutil
import tempfile


builder = runpy.run_path(str(Path(__file__).with_name("build-managed.py")))


def export(args):
    app = args.port_app.resolve(strict=True)
    original = args.pre_storage.resolve(strict=True)
    private = args.private.resolve()
    repository = Path(__file__).resolve().parents[1]
    if private.is_relative_to(repository) or private.is_relative_to(app) or private.is_relative_to(original):
        raise ValueError("Use a private input directory outside the repository, app and pre-storage sources")
    managed = private / "managed"
    if managed.exists() or managed.is_symlink():
        raise ValueError(f"Managed destination already exists: {managed}")

    recipe = builder["read_recipe"]()
    source_dir = app / builder["MANAGED_PATH"]
    files = {}
    for name, entry in recipe["files"].items():
        if entry["source"] == "storage":
            source = original / name
            expected = entry["input_sha256"]
        elif entry["source"] in ("private", "wwise"):
            source = source_dir / name
            expected = entry["sha256"]
        else:
            continue
        builder["assert_file"](source, expected)
        files[name] = source

    private.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="risk2mac-inputs-", dir=private) as directory:
        staging = Path(directory) / "managed"
        staging.mkdir()
        for name, source in files.items():
            shutil.copyfile(source, staging / name)
        staging.rename(managed)
    print(f"Prepared {len(files)} private inputs in {managed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-app", type=Path, required=True)
    parser.add_argument("--pre-storage", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Risk2Mac input export: {error}\n")


if __name__ == "__main__":
    main()
