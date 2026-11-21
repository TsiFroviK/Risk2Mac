"""Run the local Windows-to-Metal shader conversion with pinned build tools."""

import json
from pathlib import Path
import subprocess
import sys

from risk2mac_shader_tools import prepare_tools


CONVERTER = Path(__file__).resolve().parents[1] / "shaders/convert"


def shader_recipes():
    recipe = json.loads((CONVERTER / "manifest.json").read_text(encoding="utf-8"))
    if recipe["schema"] != 1:
        raise ValueError("Unsupported shader conversion manifest")
    return recipe["bundles"]


def build_shader_bundles(game_data, stage, cache, bundles, editor=None):
    compiler, cross = prepare_tools(cache)
    environment = stage / "ShaderPython"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / "bin/python3"
    print("Preparing Python libraries for Unity shader conversion", flush=True)
    subprocess.run([str(python), "-m", "pip", "--isolated", "--disable-pip-version-check",
                    "--cache-dir", str(cache / "pip"), "install", "--index-url", "https://pypi.org/simple",
                    "-r", str(CONVERTER / "requirements.txt")], check=True)

    output = stage / "ConvertedShaders"
    command = [str(python), "-u", str(CONVERTER / "build-shaders.py"),
               "--game-data", str(game_data), "--assets-out", str(output),
               "--staging", str(stage), "--vkd3d-compiler", str(compiler), "--spirv-cross", str(cross)]
    if editor:
        donor = stage / "PostProcessing.bundle"
        subprocess.run([sys.executable, "-u", str(CONVERTER / "prepare_compute.py"),
                        "--editor", str(editor), "--output", str(donor)], check=True)
        command.extend(("--compute-donor", str(donor)))
    for bundle in bundles:
        command.extend(("--bundle", bundle))
    subprocess.run(command, check=True)
    return output
