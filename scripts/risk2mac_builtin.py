"""Generate Unity's built-in shader file from the matching Windows data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT = Path(__file__).resolve().parents[1] / "shaders/startup-builtin"
BUILTIN = "Resources/unity_builtin_extra"
SHADER_ASSET = "globalgamemanagers.assets"
BUILTIN_GUID = "0000000000000000f000000000000000"
OUTPUT_SHA256 = "e2227b2affa5d251dd8eb8ff3cdf240d5d616e964bd6ee4182323823aead749d"
WINDOWS_INPUTS = {
    "globalgamemanagers": "f2f9c607432e42db6385a11574528a7c9cafdcd190a9f5ef7e1fbd011f48f85a",
    SHADER_ASSET: "988453c04c5cae9d724a21012e818ff0317bcbde95076bc67f495df3c1fb8278",
    BUILTIN: "3437af0a10a2fa400cc88d8aacc147043c908da9cdcc515a46ad78b4a8b0c1a7",
}

# AssetRipper's GPL-3.0 generic shader templates are fetched unchanged and used locally.
TEMPLATE_COMMIT = "1ac666f47d8e9dedf96afb0b914c70d7656151ea"
TEMPLATE_URL = (
    f"https://raw.githubusercontent.com/AssetRipper/AssetRipper/{TEMPLATE_COMMIT}/"
    "Source/AssetRipper.Export.UnityProjects/Shaders/Templates/"
)
TEMPLATES = {
    "TransparentDiffuse.txt": "ceed4bd0bd18e0e2a56a1399ff37e13b1fe9a569e45b145ef6ad851425cfdc0a",
    "Default.txt": "f719eed3344dcbee3c438803a7518fe548b8906f6e18020f3b4b26d47293f266",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_shader_template(cache: Path, name: str) -> str:
    directory = cache / f"assetripper-templates-{TEMPLATE_COMMIT}"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    if not destination.is_file() or sha256(destination.read_bytes()) != TEMPLATES[name]:
        with tempfile.TemporaryDirectory(prefix=".template-", dir=directory) as scratch:
            download = Path(scratch) / name
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "2",
                            "--proto", "=https", "--proto-redir", "=https", "--output", str(download), TEMPLATE_URL + name],
                           check=True, creationflags=flags)
            if sha256(download.read_bytes()) != TEMPLATES[name]:
                raise ValueError(f"AssetRipper template failed SHA-256 verification: {name}")
            download.replace(destination)
    return destination.read_text(encoding="utf-8-sig").rstrip("\n")


def shader_source(shader: dict, cache: Path) -> str:
    fields = shader["m_PropInfo"]["m_Props"]
    material = {field["m_Name"] for field in fields}
    template = "TransparentDiffuse.txt" if {"_Color", "_MainTex"} <= material else "Default.txt"
    lines = [f'Shader "{shader["m_Name"]}" {{', "\tProperties {"]
    for field in fields:
        if field["m_Flags"] or field["m_Attributes"]:
            raise ValueError("Unexpected shader property flags in the Windows data")
        label = f'{field["m_Name"]} ("{field["m_Description"]}", '
        if field["m_Type"] == 0:
            values = ",".join(format(field[f"m_DefValue[{index}]"], "g") for index in range(4))
            value = f"Vector) = ({values})"
        elif field["m_Type"] == 4 and field["m_DefTexture"]["m_TexDim"] in (1, 2):
            shape = {1: "any", 2: "2D"}[field["m_DefTexture"]["m_TexDim"]]
            value = f'{shape}) = "{field["m_DefTexture"]["m_DefaultName"]}" {{}}'
        else:
            raise ValueError("Unexpected shader property in the Windows data")
        lines.append("\t\t" + label + value)
    lines.extend(["\t}", "\t//DummyShaderTextExporter", read_shader_template(cache, template), "}"])
    return "\n".join(lines)


def graphics_tiers() -> str:
    tiers = []
    for tier, realtime_gi in enumerate((25, 25, 50)):
        tiers.append(f"""  - serializedVersion: 5
    m_BuildTarget: 1
    m_Tier: {tier}
    m_Settings:
      standardShaderQuality: 2
      renderingPath: 3
      hdrMode: 1
      realtimeGICPUUsage: {realtime_gi}
      useReflectionProbeBoxProjection: 1
      useReflectionProbeBlending: 1
      useHDR: 1
      useDetailNormalMap: 1
      useCascadedShadowMaps: 1
      prefer32BitShadowMaps: 0
      enableLPPV: 0
      useDitherMaskForAlphaBlendedShadows: 1
    m_Automatic: 0""")
    return "\n".join(tiers)


def configure_project(game_data: Path, cache: Path, project: Path) -> None:
    import UnityPy

    original = UnityPy.load(str(game_data / "globalgamemanagers"))
    graphics = next(obj.read_typetree() for obj in original.objects if obj.type.name == "GraphicsSettings")
    externals = {item.path: index for index, item in enumerate(original.file.externals, start=1)}
    builtin_index = externals[BUILTIN]
    game_index = externals[SHADER_ASSET]
    shadow = graphics["m_ScreenSpaceShadows"]["m_Shader"]
    included = graphics["m_AlwaysIncludedShaders"]
    identifiers = {pointer["m_PathID"] for pointer in included if pointer["m_FileID"] == game_index}
    if shadow["m_FileID"] != game_index:
        raise ValueError("Unexpected Windows shadow shader reference")
    identifiers.add(shadow["m_PathID"])

    shaders = UnityPy.load(str(game_data / SHADER_ASSET))
    objects = {obj.path_id: obj for obj in shaders.objects if obj.type.name == "Shader"}
    assets = project / "Assets"
    shader_dir = assets / "Source"
    editor_dir = assets / "Editor"
    settings = project / "ProjectSettings"
    packages = project / "Packages"
    for path in (shader_dir, editor_dir, settings, packages):
        path.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT / "BuildUnityBuiltinFixture.cs", editor_dir / "BuildUnityBuiltinFixture.cs")
    (packages / "manifest.json").write_text('{"dependencies": {}}', encoding="utf-8")
    (settings / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2023.1.0f1\nm_EditorVersionWithRevision: 2023.1.0f1 (a008fa768e6c)\n", encoding="utf-8")

    guids = {}
    for path_id in sorted(identifiers):
        definition = objects[path_id].read_typetree()["m_ParsedForm"]
        code = shader_source(definition, cache)
        guid = sha256(code.encode("utf-8"))[:32]
        guids[path_id] = guid
        source = shader_dir / f"WindowsShader{path_id}.shader"
        source.write_text(code, encoding="utf-8")
        source.with_suffix(".shader.meta").write_text(
            f"fileFormatVersion: 2\nguid: {guid}\nShaderImporter:\n  externalObjects: {{}}\n  defaultTextures: []\n",
            encoding="utf-8")
    rows = []
    for pointer in included:
        path_id = pointer["m_PathID"]
        if pointer["m_FileID"] == builtin_index:
            rows.append(f"  - {{fileID: {path_id}, guid: {BUILTIN_GUID}, type: 0}}")
        elif pointer["m_FileID"] == game_index:
            rows.append(f"  - {{fileID: 4800000, guid: {guids[path_id]}, type: 3}}")
        else:
            raise ValueError("Unexpected Windows included shader reference")
    config = (PROJECT / "GraphicsSettings.txt").read_text(encoding="utf-8")
    config = config.replace("@SHADOW_GUID@", guids[shadow["m_PathID"]])
    config = config.replace("@INCLUDED_SHADER_ROWS@", "\n".join(rows))
    config = config.replace("@GRAPHICS_TIER_ROWS@", graphics_tiers())
    (settings / "GraphicsSettings.asset").write_text(config, encoding="utf-8")


def build_builtin_extra(game_data: Path, editor: Path, cache: Path) -> bytes:
    """Compile and verify the native Unity built-in shader file."""
    for name, expected in WINDOWS_INPUTS.items():
        path = game_data / name
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise ValueError(f"Unsupported Windows input for the built-in shaders: {path}")
    print("Compiling the Unity built-in shader resource", file=sys.stderr, flush=True)
    stage = Path(tempfile.mkdtemp(prefix="risk2mac-startup-builtin-")).resolve()
    try:
        project = stage / "Project"
        output = stage / "Output"
        log = stage / "Unity.log"
        configure_project(game_data, cache, project)
        args = [str(editor), "-batchmode", "-nographics", "-quit", "-projectPath", str(project),
                "-buildTarget", "StandaloneOSX", "-executeMethod", "BuildUnityBuiltinFixture.Build",
                "-logFile", str(log)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(args, env=dict(os.environ, RISK2MAC_BUILTIN_FIXTURE_OUTPUT=str(output)),
                                creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        resource = output / "Fixture.app/Contents/Resources/Data" / BUILTIN
        if result.returncode or not resource.is_file():
            if log.is_file():
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]), file=sys.stderr)
            raise ValueError("Unity could not generate the built-in shaders. Check the Unity 2023.1.0f1 license and macOS build support.")
        payload = resource.read_bytes()
        if sha256(payload) != OUTPUT_SHA256:
            raise ValueError("The generated built-in shader resource differs from the reviewed port")
        return payload
    finally:
        shutil.rmtree(stage, ignore_errors=os.name == "nt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path, required=True)
    parser.add_argument("--editor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    payload = build_builtin_extra(args.game_data.resolve(), args.editor.resolve(), args.cache.resolve())
    with args.output.open("xb") as destination:
        destination.write(payload)
    print(json.dumps({"asset": BUILTIN, "bytes": len(payload), "sha256": sha256(payload)}, separators=(",", ":")))
