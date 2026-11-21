#!/usr/bin/env python3
"""Translate supported local Windows shader bundles using pinned byte expectations."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import UnityPy

from shader_programs import apply_compute_donor, convert_shader, extract_shader, sha
from special_shaders import guard_cloud_depth, pack_chromatic_parameters


HERE = Path(__file__).resolve().parent
CORE = "ror2-base-shaders_shader_assets_all_45ab8c24dd5dcd99e5cb60900de0231b.bundle"
CALMWATER = "calmwater_shader_assets_all_65622a9b043e2722235b979d6f466b7f.bundle"
UI_DONOR = "calmwater_unitybuiltinshaders_244d4ed79dda70fa38b62dcf46d4ccd7.bundle"
CORE_BASE = "25593019f571a3362341daf81d9d81860eefe7f5a3b272b4eb7106f2ccfd0a7c"
POSTPROCESS_UBER = "Hidden/PostProcessing/Uber"
PYTHON_PACKAGES = {"UnityPy": "1.25.4", "lz4": "4.4.5"}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest():
    manifest = load_json(HERE / "manifest.json")
    bundles = manifest.get("bundles")
    if manifest.get("schema") != 1 or not isinstance(bundles, dict):
        raise ValueError("Invalid shader bundle manifest")
    return bundles


def require_release(data, name, rule):
    if sha(data) != rule["output"] or len(data) != rule["size"]:
        raise ValueError(
            f"{name}: generated shader bundle disagrees with the pinned SHA-256 or size"
        )


def require_tool(path):
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"Compiler must be an executable: {resolved}")
    return resolved


def read_stock(stock, name, rule):
    path = stock / name
    if not path.is_file():
        raise ValueError(f"Missing supported Windows bundle: {path}")
    raw = path.read_bytes()
    if sha(raw) != rule["input"]:
        raise ValueError(f"Unsupported Windows SHA-256 for {name}")
    return raw


def read_compute_donors(path):
    if path is None:
        raise ValueError(
            "Supply --compute-donor for bundles that contain postprocessing compute shaders"
        )
    expected = load_json(HERE / "compute-donor.json")
    actual = {}
    for obj in UnityPy.load(str(path)).objects:
        if obj.type.name != "ComputeShader":
            continue
        tree = obj.read_typetree()
        name = tree["m_Name"]
        if name in actual or expected.get(name) != sha(obj.get_raw_data()):
            raise ValueError(f"Unexpected Unity compute donor object: {name}")
        actual[name] = tree
    if actual.keys() != expected.keys():
        raise ValueError("The donor is missing a required Unity compute shader")
    return actual


def extract(stock, names, manifest, dxbc):
    index = {}
    for name in names:
        source = read_stock(stock, name, manifest[name])
        for obj in UnityPy.load(source).objects:
            if obj.type.name == "Shader":
                key = sha(obj.get_raw_data())
                if key not in index:
                    index[key] = extract_shader(obj, dxbc)
    return index


def run_compiler(argv):
    result = subprocess.run(argv, capture_output=True, timeout=120)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-1200:]
        raise ValueError(f"{Path(argv[0]).name} failed: {detail}")


def translate(dxbc, metal, vkd3d, cross, jobs):
    def program(source):
        spirv = metal / source.with_suffix(".spv").name
        output = metal / source.with_suffix(".metal").name
        run_compiler(
            [str(vkd3d), "-x", "dxbc-tpf", "-b", "spirv-binary", "-o", str(spirv), str(source)]
        )
        run_compiler([str(cross), str(spirv), "--msl", "--output", str(output)])
        if not output.is_file() or not output.stat().st_size:
            raise ValueError(f"Compiler returned an empty shader for {source.stem}")
        spirv.unlink()

    sources = sorted(dxbc.glob("*.dxbc"))
    print(f"Translating {len(sources)} distinct DXBC programs", flush=True)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        try:
            for count, _ in enumerate(pool.map(program, sources), start=1):
                if count % 1000 == 0:
                    print(f"Translated {count}/{len(sources)}", flush=True)
        except Exception:
            pool.shutdown(wait=True, cancel_futures=True)
            raise


def build_bundle(data, index, dxbc, metal, compute, cache):
    env = UnityPy.load(data)
    for obj in env.objects:
        if compute and obj.type.name == "ComputeShader":
            apply_compute_donor(obj, compute)
        if obj.type.name != "Shader":
            continue
        key = (sha(obj.get_raw_data()), bool(compute))
        selected = index.get(key[0])
        if selected is None:
            continue
        if key not in cache:
            tree = convert_shader(obj, selected, dxbc, metal)
            if compute and tree["m_ParsedForm"]["m_Name"] == POSTPROCESS_UBER:
                tree, _report = pack_chromatic_parameters(tree)
            cache[key] = tree
        obj.save_typetree(copy.deepcopy(cache[key]))
    return env


def shader(bundle, name):
    matching = [
        obj
        for obj in bundle.objects
        if obj.type.name == "Shader" and obj.read_typetree()["m_ParsedForm"]["m_Name"] == name
    ]
    if len(matching) != 1:
        raise ValueError(f"Expected one local shader named {name}")
    return matching[0]


def apply_calmwater_fallback(env):
    target = shader(env, "CalmWater/Calm Water [DX11] [Double Sided]")
    fallback = shader(env, "CalmWater/Calm Water [Double Sided]")
    tree = target.read_typetree()
    if tree["m_Dependencies"] or tree["m_ParsedForm"]["m_FallbackName"] != "Legacy/Diffuse":
        raise ValueError("CalmWater fallback source differs from the supported input")
    tree["m_ParsedForm"]["m_FallbackName"] = fallback.read_typetree()["m_ParsedForm"]["m_Name"]
    tree["m_Dependencies"] = [{"m_FileID": 0, "m_PathID": fallback.path_id}]
    target.save_typetree(tree)


def apply_core_fallback(env, ui_bytes):
    donor = UnityPy.load(ui_bytes)
    target = shader(env, "UI/Healthbar")
    base = target.read_typetree()
    replacement = copy.deepcopy(shader(donor, "UI/Default").read_typetree())
    if base["platforms"] != [14] or replacement["platforms"] != [14]:
        raise ValueError("Core UI shaders must already be translated")
    if replacement["m_Dependencies"] or replacement["m_NonModifiableTextures"]:
        raise ValueError("The local UI donor unexpectedly references another asset")
    replacement["m_Name"] = base["m_Name"]
    replacement["m_ParsedForm"]["m_Name"] = base["m_ParsedForm"]["m_Name"]
    target.save_typetree(replacement)
    intermediate = env.file.save(packer="lz4")
    if sha(intermediate) != CORE_BASE:
        raise ValueError("The core UI fallback did not match the pinned intermediate")
    return guard_cloud_depth(UnityPy.load(intermediate))


def build(args):
    for package, expected in PYTHON_PACKAGES.items():
        if version(package) != expected:
            raise ValueError(f"Install {package} {expected} before generating shader bundles")
    manifest = load_manifest()
    stock = args.game_data.resolve(strict=True) / "StreamingAssets/aa/StandaloneWindows64"
    if not stock.is_dir():
        raise ValueError(f"Windows Addressables not found: {stock}")
    requested = tuple(dict.fromkeys(args.bundle or manifest.keys()))
    if any(name not in manifest or Path(name).name != name for name in requested):
        raise ValueError("Requested bundle is not in the pinned shader manifest")
    out = args.assets_out.resolve()
    if out == stock or out.is_relative_to(stock) or stock.is_relative_to(out):
        raise ValueError("Choose a shader output outside the stock Windows bundle directory")
    out.mkdir(parents=True, exist_ok=True)
    pending = []
    for name in requested:
        path = out / name
        if path.is_symlink():
            raise ValueError(f"Unexpected symbolic link in shader output: {path}")
        if path.exists():
            require_release(path.read_bytes(), name, manifest[name])
        else:
            pending.append(name)
    if not pending:
        return
    staging_parent = args.staging.resolve(strict=True) if args.staging else out
    if staging_parent.stat().st_dev != out.stat().st_dev or staging_parent.is_relative_to(stock):
        raise ValueError(
            "Shader staging must be outside the Windows installation and on the output volume"
        )
    if args.jobs < 1:
        raise ValueError("--jobs must be positive")
    vkd3d = require_tool(args.vkd3d_compiler)
    cross = require_tool(args.spirv_cross)
    donors = (
        read_compute_donors(args.compute_donor)
        if any(manifest[name]["mode"] == "compute" for name in pending)
        else {}
    )
    to_build = pending.copy()
    if CORE in to_build:
        to_build.remove(CORE)
        if UI_DONOR not in to_build:
            # Verify the local translated UI bundle in this invocation before using it.
            to_build.append(UI_DONOR)
        to_build.append(CORE)
    with tempfile.TemporaryDirectory(prefix=".risk2mac-shaders-", dir=staging_parent) as temporary:
        work = Path(temporary)
        dxbc = work / "dxbc"
        metal = work / "metal"
        dxbc.mkdir()
        metal.mkdir()
        index = extract(stock, to_build, manifest, dxbc)
        translate(dxbc, metal, vkd3d, cross, args.jobs)
        cache = {}
        for name in to_build:
            rule = manifest[name]
            env = build_bundle(
                read_stock(stock, name, rule),
                index,
                dxbc,
                metal,
                donors if rule["mode"] == "compute" else {},
                cache,
            )
            if name == CORE:
                translated = UnityPy.load(env.file.save(packer="lz4"))
                raw = apply_core_fallback(translated, (work / UI_DONOR).read_bytes())
            else:
                if name == CALMWATER:
                    apply_calmwater_fallback(env)
                raw = env.file.save(packer="lz4")
            require_release(raw, name, rule)
            (work / name).write_bytes(raw)
            print(f"Verified {name}", flush=True)
        for name in pending:
            os.link(work / name, out / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path, required=True)
    parser.add_argument("--assets-out", type=Path, required=True)
    parser.add_argument("--vkd3d-compiler", type=Path, required=True)
    parser.add_argument("--spirv-cross", type=Path, required=True)
    parser.add_argument("--compute-donor", type=Path)
    parser.add_argument("--staging", type=Path)
    parser.add_argument("--bundle", action="append")
    parser.add_argument("--jobs", type=int, default=4)
    try:
        build(parser.parse_args())
    except (OSError, ValueError, AssertionError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Risk2Mac shaders: {error}\n")


if __name__ == "__main__":
    main()
