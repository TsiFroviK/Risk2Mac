"""Convert startup texture streams from the matching Windows Unity data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT = Path(__file__).resolve().parents[1] / "shaders/startup-textures"
DECODER_NUGET = "assetripper.texturedecoder.2.6.3.nupkg"
DECODER_URL = "https://api.nuget.org/v3-flatcontainer/assetripper.texturedecoder/2.6.3/" + DECODER_NUGET
DECODER_SHA256 = "6e7912b23979d3ba22f07620db54a8699d2f31375eac43dcd0f7f8c06b554980"


@dataclass(frozen=True)
class Stream:
    source_path_id: int
    offset: int
    size: int
    format: int | None
    mip_count: int
    sprite: bool
    linear: bool = False
    source_asset: str | None = None


def recipes() -> dict:
    return json.loads((PROJECT / "recipes.json").read_text(encoding="utf-8"))


def compile_textures(editor: Path, stage: Path, plan: list[dict]) -> Path:
    output = stage / "Output"
    log = stage / "Unity.log"
    plan_path = stage / "Textures.json"
    plan_path.write_text(json.dumps({"textures": plan}), encoding="utf-8")
    args = [str(editor), "-batchmode", "-nographics", "-quit", "-projectPath", str(stage / "Project"),
            "-buildTarget", "StandaloneOSX", "-executeMethod", "BuildTextureStreams.Build",
            "-logFile", str(log)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    environment = dict(os.environ, RISK2MAC_TEXTURE_STREAM_OUTPUT=str(output),
                       RISK2MAC_TEXTURE_STREAM_PLAN=str(plan_path))
    result = subprocess.run(args, env=environment, creationflags=flags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bundle = output / "textures.bundle"
    if result.returncode or not bundle.is_file():
        if log.is_file():
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]), file=sys.stderr, flush=True)
        raise ValueError("Unity could not convert the startup textures. Check the Unity 2023.1.0f1 license and macOS build support.")
    return bundle


def decode_cubemap(texture, stage: Path, dotnet: str | None):
    from PIL import Image

    compiler = dotnet or shutil.which("dotnet")
    curl = shutil.which("curl")
    if not compiler or not curl:
        raise ValueError("The cubemap conversion requires the .NET 8 SDK and curl")
    if texture.m_TextureFormat != 24 or texture.m_ImageCount != 6:
        raise ValueError("The Windows cubemap must contain six BC6H faces")

    tool = stage / "Decoder"
    tool.mkdir()
    archive = tool / DECODER_NUGET
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run([curl, "--fail", "--silent", "--show-error", "--location", "--retry", "2",
                    "--proto", "=https", "--proto-redir", "=https", "--output", str(archive), DECODER_URL],
                   check=True, creationflags=flags)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != DECODER_SHA256:
        raise ValueError("AssetRipper.TextureDecoder failed SHA-256 verification")

    project = tool / "CubeDecoder.csproj"
    shutil.copyfile(PROJECT / "Tools/CubeDecoder.csproj.txt", project)
    shutil.copyfile(PROJECT / "Tools/CubeDecoder.cs", tool / "Program.cs")
    source = stage / "Cube.bc6"
    output = stage / "Cube.rgba"
    source.write_bytes(texture.get_image_data())
    width, height = texture.m_Width, texture.m_Height
    commands = (
        [compiler, "restore", str(project), "--source", str(tool), "--packages", str(tool / "Packages"), "-v", "quiet"],
        [compiler, "build", str(project), "--no-restore", "--configuration", "Release", "-v", "quiet"],
        [compiler, str(tool / "bin/Release/net8.0/CubeDecoder.dll"), str(source), str(output),
         str(width), str(height), str(texture.m_CompleteImageSize)],
    )
    for command in commands:
        result = subprocess.run(command, creationflags=flags, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
        if result.returncode:
            print(result.stdout, file=sys.stderr)
            raise ValueError("The .NET cubemap decoder could not process the Windows startup texture")
    return Image.frombytes("RGBA", (width, height * 6), output.read_bytes())


def build_texture_stream(asset: str, game_data: Path, editor: Path, dotnet: str | None = None) -> bytes:
    import UnityPy

    recipe = recipes()[asset]
    for name, expected in recipe["inputs"].items():
        path = game_data / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Unsupported Windows input for the startup texture stream: {path}")

    print(f"Converting the startup texture stream {asset}", file=sys.stderr, flush=True)
    streams = [Stream(*row) for row in recipe["streams"]]
    sources = {stream.source_asset or recipe["source"] for stream in streams}
    objects = {}
    for name in sources:
        source = UnityPy.load(str(game_data / name))
        objects[name] = {obj.path_id: obj for obj in source.objects if obj.type.name in ("Texture2D", "Cubemap")}
    result = bytearray(recipe["size"])
    stage = Path(tempfile.mkdtemp(prefix="risk2mac-startup-textures-")).resolve()
    try:
        project = stage / "Project"
        shutil.copytree(PROJECT, project)
        images = project / "Assets/Textures"
        images.mkdir()
        plan = []
        payloads = {}
        for index, stream in enumerate(streams):
            source = objects[stream.source_asset or recipe["source"]][stream.source_path_id]
            texture = source.read()
            if stream.format is None:
                payloads[index] = texture.get_image_data()
                continue
            cube = source.type.name == "Cubemap"
            image = decode_cubemap(texture, stage, dotnet) if cube else texture.image.convert("RGBA")
            name = f"Texture_{index}"
            image.save(images / (name + ".png"))
            plan.append({"name": name, "mipmaps": stream.mip_count > 1, "sprite": stream.sprite,
                         "linear": stream.linear, "cube": cube, "format": stream.format})

        compiled = UnityPy.load(str(compile_textures(editor, stage, plan)))
        textures = (obj.read() for obj in compiled.objects if obj.type.name in ("Texture2D", "Cubemap"))
        converted = {texture.m_Name: texture for texture in textures}
        end = 0
        for index, stream in enumerate(streams):
            if stream.format is not None:
                texture = converted[f"Texture_{index}"]
                if (texture.m_TextureFormat, texture.m_MipCount) != (stream.format, stream.mip_count):
                    raise ValueError(f"Unity produced an unexpected texture format for source object {stream.source_path_id}")
                payloads[index] = texture.get_image_data()
            payload = payloads[index]
            if stream.offset < end or stream.offset + stream.size > len(result) or len(payload) != stream.size:
                raise ValueError(f"Unexpected texture stream layout for source object {stream.source_path_id}")
            end = stream.offset + stream.size
            result[stream.offset:end] = payload
    finally:
        shutil.rmtree(stage, ignore_errors=os.name == "nt")

    if hashlib.sha256(result).hexdigest() != recipe["sha256"]:
        raise ValueError(f"The generated texture stream {asset} differs from the reviewed port")
    return bytes(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path, required=True)
    parser.add_argument("--editor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--asset", choices=recipes(), required=True)
    parser.add_argument("--dotnet")
    args = parser.parse_args()
    payload = build_texture_stream(args.asset, args.game_data.resolve(), args.editor.resolve(), args.dotnet)
    with args.output.open("xb") as destination:
        destination.write(payload)
    print(json.dumps({"asset": args.asset, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
                     separators=(",", ":")))
