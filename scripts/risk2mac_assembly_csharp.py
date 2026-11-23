"""Regenerate the matched Assembly-CSharp locally for Unity 2023."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile

from risk2mac_ai_navigation import find_ai_navigation_analyzer, response_path


OUTPUT_NAME = "Assembly-CSharp.dll"
INPUT_SHA256 = "22bd24084b3f0d10658c737115b2866d9e717188ded6ef8e0375647cf9fe9091"
OUTPUT_SHA256 = "2d6200b5c4a746d50dcc7a5ff4b5cc5d2c939f27fbd8d03275fc181c89094ebf"
SOURCES_SHA256 = "f77de0f723e9fd376e890e62440bd8fe9c6e6e2c301fcec0681f73e22122c705"
COMPILED_SHAPE_SHA256 = "3f121711edc9926dd9de44c39a639ca137c2abe598fe57edf9e5b135cf8be008"

ILSPY_VERSION = "9.1.0.7988"
ILSPY_NAME = f"ilspycmd.{ILSPY_VERSION}.nupkg"
ILSPY_URL = f"https://api.nuget.org/v3-flatcontainer/ilspycmd/{ILSPY_VERSION}/{ILSPY_NAME}"
ILSPY_SIZE = 4183395
ILSPY_SHA256 = "2b5058f5ccc164c33b7aabf1a5eb0cf3d3a6af6c145aaf58efd3ed891443af7c"

WINDOWS_REFERENCES = (
    "AK.Wwise.Unity.API.dll", "AK.Wwise.Unity.API.WwiseTypes.dll", "AK.Wwise.Unity.MonoBehaviour.dll",
    "HGCSharpUtils.dll", "LegacyResourcesAPI.dll", "RoR2.dll", "Unity.Addressables.dll",
    "Unity.ResourceManager.dll", "Unity.TextMeshPro.dll", "UnityEngine.UI.dll",
)
UNITY_REFERENCES = (
    "UnityEngine.CoreModule.dll", "UnityEngine.TextRenderingModule.dll", "UnityEngine.dll",
    "netstandard.dll", "mscorlib.dll", "System.Core.dll", "System.dll",
)
QUALIFY_NAMES = {
    "Properties/AssemblyInfo.cs": (
        (b"typeof(Monitor))", b"typeof(EntityStates.QuestVolatileBattery.Monitor))"),
        (b"typeof(DebugOverlay))", b"typeof(RoR2.DebugOverlay))"),
    ),
    "HealthBarTypeCheck.cs": ((b"private Event ", b"private AK.Wwise.Event "),),
    "AffixBeadProjectileSound.cs": ((b"private Event ", b"private AK.Wwise.Event "),),
}
# Normalize the reviewed build's timestamp and debug identifiers so each Mac
# produces the same assembly from the Steam inputs.
BUILD_METADATA = {
    0x88: bytes.fromhex("366b046b"),
    0x1EFB8: bytes.fromhex("1596de1653a05042a48700f1dca4025b"),
    0x21520: bytes.fromhex("1800fba3"),
    0x21558: bytes.fromhex("846d386a77d553498eabd1e99d73a714"),
    0x2156C: b".\\Library\\Bee\\artifacts\\200b0aP.dag\\Assembly-CSharp.pdb".ljust(260, b"\0"),
    0x21677: bytes.fromhex("846d386a77d553298eabd1e99d73a7141800fb23ade70f0bd76073107e42ad7c"),
}


def require_ilspy_package(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) != ILSPY_SIZE or hashlib.sha256(data).hexdigest() != ILSPY_SHA256:
        raise ValueError(f"ILSpy {ILSPY_VERSION} package failed SHA-256 verification: {path}")
    return data


def prepare_ilspy(cache: Path, scratch: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    saved = cache / ILSPY_NAME
    if saved.is_file():
        content = require_ilspy_package(saved)
    else:
        with tempfile.TemporaryDirectory(prefix=".ilspy-download-", dir=cache) as directory:
            archive = Path(directory) / ILSPY_NAME
            print(f"Downloading the official ILSpy {ILSPY_VERSION} .NET tool", flush=True)
            subprocess.run([
                "curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                "--retry", "2", "--connect-timeout", "15", "--max-time", "90",
                "--max-filesize", str(ILSPY_SIZE), "--silent", "--show-error",
                "--output", str(archive), ILSPY_URL,
            ], check=True)
            content = require_ilspy_package(archive)
            archive.replace(saved)
    tool = scratch / "ILSpy"
    prefix = "tools/net8.0/any/"
    with ZipFile(BytesIO(content)) as package:
        for member in package.infolist():
            if member.is_dir() or not member.filename.startswith(prefix):
                continue
            relative = Path(member.filename.removeprefix(prefix))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid ILSpy package path.")
            output = tool / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(package.read(member))
    return tool / "ilspycmd.dll"


def extract_assembly_csharp_sources(dotnet: str | Path, windows: Path, destination: Path,
                                    scratch: Path, cache: Path) -> list[Path]:
    source = windows / OUTPUT_NAME
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != INPUT_SHA256:
        raise ValueError(f"Unsupported Windows {OUTPUT_NAME}: {source}")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Choose a new local folder to stage the scripts: {destination}")
    tool = prepare_ilspy(cache, scratch)
    subprocess.run([
        str(dotnet), str(tool), "--disable-updatecheck", "-p", "-lv", "CSharp9_0", "-r", str(windows),
        "-o", str(destination), str(source),
    ], check=True)
    files = sorted(destination.rglob("*.cs"), key=lambda path: path.relative_to(destination).as_posix())
    tree = hashlib.sha256()
    for path in files:
        relative = path.relative_to(destination).as_posix()
        data = path.read_bytes().replace(b"\r\n", b"\n")
        tree.update(relative.encode() + b"\0" + data + b"\0")
        for old, new in QUALIFY_NAMES.get(relative, ()):
            data = data.replace(old, new)
        path.write_bytes(data)
    if len(files) != 23 or tree.hexdigest() != SOURCES_SHA256:
        raise ValueError("Unexpected scripts extracted from the matched Windows Assembly-CSharp.")
    # The ILSpy project describes the original Windows target. The compiler
    # below uses the explicitly checked macOS Unity framework and engine.
    (destination / "Assembly-CSharp.csproj").unlink()
    return files


def canonical_assembly(assembly: bytes) -> bytes:
    if len(assembly) != 140800:
        raise ValueError(f"Unexpected compiled {OUTPUT_NAME} size: {len(assembly)}")
    data = bytearray(assembly)
    # Restore the visibility of two synthesized static-array carrier types.
    for offset in (0x4CAE, 0x4CBC):
        if data[offset] not in (0x13, 0x15):
            raise ValueError("Unexpected compiler visibility flags in Assembly-CSharp.")
        data[offset] = 0x13
    for offset, value in BUILD_METADATA.items():
        data[offset:offset + len(value)] = bytes(len(value))
    shape = hashlib.sha256(data).hexdigest()
    if shape != COMPILED_SHAPE_SHA256:
        raise ValueError(f"Unexpected compiled {OUTPUT_NAME} content: {shape}")
    for offset, value in BUILD_METADATA.items():
        data[offset:offset + len(value)] = value
    if hashlib.sha256(data).hexdigest() != OUTPUT_SHA256:
        raise ValueError(f"Built {OUTPUT_NAME} failed SHA-256 verification.")
    return bytes(data)


def build_assembly_csharp(dotnet: str | Path, csc: Path, editor: Path, windows: Path,
                          managed: Path, output: Path, scratch: Path, cache: Path) -> None:
    analyzer = find_ai_navigation_analyzer(editor)
    if analyzer is None:
        raise ValueError("Use the official Unity 2023.1.0f1 Editor to generate Assembly-CSharp.")
    refs = [*(windows / name for name in WINDOWS_REFERENCES), *(managed / name for name in UNITY_REFERENCES)]
    with tempfile.TemporaryDirectory(prefix="assembly-csharp-", dir=scratch) as directory:
        root = Path(directory).resolve()
        source_dir = Path("Assets/RestoredAssemblyCSharp")
        intermediate = Path("Library/Bee/artifacts/200b0aP.dag")
        (root / intermediate).mkdir(parents=True)
        print("Retargeting Assembly-CSharp from the supplied Windows game installation", flush=True)
        files = extract_assembly_csharp_sources(dotnet, windows, root / source_dir, root, cache)
        raw_dll = intermediate / OUTPUT_NAME
        ref_dll = intermediate / "Assembly-CSharp.ref.dll"
        additional_file = intermediate / "Assembly-CSharp.UnityAdditionalFile.txt"
        (root / additional_file).write_text(str(root), encoding="utf-8")
        args = [
            "-target:library", f"-out:{response_path(raw_dll)}", f"-refout:{response_path(ref_dll)}",
            *(f"-r:{response_path(path.resolve())}" for path in refs),
            f"-analyzer:{response_path(analyzer)}",
            *(response_path(path.relative_to(root)) for path in files),
            "-langversion:9.0", "/unsafe+", "/optimize+", "/debug:portable", "/nologo", "/warn:0",
            "/RuntimeMetadataVersion:v4.0.30319", "/utf8output", "/preferreduilang:en-US",
            f"/additionalfile:{response_path(additional_file)}",
        ]
        response = root / "compile.rsp"
        response.write_text("\n".join(args), encoding="utf-8")
        subprocess.run([
            str(dotnet), str(csc.resolve()), "/noconfig", f"/pathmap:{root}=.", f"@{response}",
        ], cwd=root, check=True)
        result = canonical_assembly((root / raw_dll).read_bytes())
        with output.open("xb") as destination:
            destination.write(result)
