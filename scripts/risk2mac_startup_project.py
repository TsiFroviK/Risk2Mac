"""Reimport the matched Windows startup project and build its macOS data."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from risk2mac_assembly_csharp import extract_assembly_csharp_sources
from risk2mac_export_bootstrap import export_bootstrap


ROOT = Path(__file__).resolve().parents[1]
SCENE = Path("Assets/RoR2/Base/Scenes/loadingbasic/loadingbasic.unity")
RESTORED = Path("Assets/RestoredAssemblyCSharp")
RECIPE = ROOT / "manifests/startup-project.json"
EDITOR_SOURCE = ROOT / "shaders/startup-project/BuildRisk2MacStartup.cs"
GUID_FIELD = re.compile(rb"(?m)^guid: ([a-f0-9]{32})\r?$")
GUID_TOKEN = re.compile(rb"(?<![a-f0-9])[a-f0-9]{32}(?![a-f0-9])")
DATA_FILES = (
    "globalgamemanagers", "globalgamemanagers.assets", "level0", "resources.assets", "sharedassets0.assets",
)
STREAMS = ("globalgamemanagers.assets.resS", "resources.assets.resS", "sharedassets0.assets.resS")
BUILTIN = "Resources/unity_builtin_extra"


def project_recipe():
    return json.loads(RECIPE.read_text(encoding="utf-8"))


def stabilize_export_guids(project: Path, guids: dict[str, str]):
    # AssetRipper assigns random import GUIDs. Reuse a stable ID for each exported
    # path so Unity can lay out and check the generated shader/texture streams.
    found = {
        path.relative_to(project).as_posix(): path
        for path in (project / "Assets").rglob("*.meta")
    }
    if found.keys() != guids.keys():
        raise ValueError("The Windows bootstrap export has unexpected asset paths.")
    mapping = {}
    for relative, path in found.items():
        old = GUID_FIELD.search(path.read_bytes())
        expected = guids[relative].encode("ascii")
        if old is None or mapping.setdefault(old[1], expected) != expected:
            raise ValueError(f"Could not stabilize the Unity GUID for {relative}")
    for folder in ("Assets", "ProjectSettings"):
        for path in (project / folder).rglob("*"):
            if path.suffix not in {".asset", ".unity", ".mat", ".meta", ".prefab"}:
                continue
            text = path.read_bytes()
            if path.suffix == ".meta" or text.startswith(b"%YAML"):
                updated = GUID_TOKEN.sub(lambda match: mapping.get(match[0], match[0]), text)
                if updated != text:
                    path.write_bytes(updated)


def stage_unity_project(project, windows, managed, dotnet, scratch, cache, recipe):
    stabilize_export_guids(project, recipe["export_guids"])
    plugins = project / "Assets/Plugins"
    (plugins / "Assembly-CSharp.dll").unlink()
    (plugins / "Assembly-CSharp.dll.meta").unlink()
    shutil.copyfile(windows / "UnityEngine.UNETModule.dll", plugins / "UnityEngine.UNETModule.dll")
    # The authored components contribute MonoScript metadata. The linker also
    # resolves the input and Steam integration helpers they reference.
    for name in ("RoR2Arm64.ManagedSolo.dll", "RoR2Arm64.OfflinePlatform.dll", "RoR2Arm64.MacDpad.dll"):
        shutil.copyfile(managed / name, plugins / name)
    steam = managed / "Risk2Mac.Steam.dll"
    if steam.is_file():
        shutil.copyfile(steam, plugins / steam.name)
    extracted = extract_assembly_csharp_sources(dotnet, windows, project / RESTORED, scratch, cache)
    restored_guids = recipe["source_guids"]
    if {file.relative_to(project / RESTORED).as_posix() for file in extracted} != restored_guids.keys():
        raise ValueError("The extracted startup scripts have unexpected paths.")
    for relative, guid in restored_guids.items():
        meta = project / RESTORED / (relative + ".meta")
        meta.write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="ascii")

    scene = project / SCENE
    contents = scene.read_bytes()
    original_guid = recipe["export_guids"]["Assets/Plugins/Assembly-CSharp.dll.meta"]
    for file_id, name in ((1872616690, "NGSS_Local.cs"), (686580900, "UnityGitSha_custom.cs")):
        old = f"fileID: {file_id}, guid: {original_guid}".encode("ascii")
        new = f"fileID: 11500000, guid: {restored_guids[name]}".encode("ascii")
        if contents.count(old) != 1:
            raise ValueError(f"The loading scene has an unexpected reference to {name}")
        contents = contents.replace(old, new)
    scene.write_bytes(contents)
    manifest = project / "Packages/manifest.json"
    packages = json.loads(manifest.read_bytes())
    packages["dependencies"]["com.unity.ai.navigation"] = "1.1.3"
    manifest.write_text(json.dumps(packages, indent=2), encoding="utf-8")
    entry = project / "Assets/Editor" / EDITOR_SOURCE.name
    entry.parent.mkdir()
    shutil.copyfile(EDITOR_SOURCE, entry)


def build_startup_project(game_data: Path, managed: Path, editor: Path, dotnet: str,
                          stage: Path, cache: Path) -> Path:
    from risk2mac_shaders import prepare_asset_python

    project = export_bootstrap(game_data, stage, cache)
    stage_unity_project(project, game_data / "Managed", managed, dotnet, stage, cache, project_recipe())
    output = stage / "Risk2MacStartup.app"
    log = stage / "UnityStartup.log"
    args = [str(editor), "-batchmode", "-nographics", "-quit", "-buildTarget", "StandaloneOSX",
            "-projectPath", str(project), "-executeMethod", "BuildRisk2MacStartup.Build", "-logFile", str(log)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    print("Building the macOS startup data with Unity Editor", flush=True)
    run = subprocess.run(args, env=dict(os.environ, RISK2MAC_STARTUP_OUTPUT=str(output)),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, timeout=1200)
    if run.returncode:
        if log.is_file():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in [line for line in lines if "Exception:" in line or "error CS" in line][-7:]:
                print(line, file=sys.stderr)
            for line in lines[-20:]:
                print(line, file=sys.stderr)
        raise ValueError("Unity could not generate the startup data. Check the log, Editor license and Mac Build Support (./build.sh --setup unity).")
    data = output / "Contents/Resources/Data"
    python = prepare_asset_python(stage, cache)
    subprocess.run([str(python), "-u", str(Path(__file__).with_name("risk2mac_check_startup_project.py")),
                    str(data)], check=True)
    return data
