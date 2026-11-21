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
INPUT_SHA256 = "ed84d52196945af9fcb5e987e5acec8f115ddacf339fa054c6c556531a245272"
OUTPUT_SHA256 = "2d22027dbf5cfb2f862028c571752620ba53a96e7865426b036e4c9a0af89038"
SOURCES_SHA256 = "f77de0f723e9fd376e890e62440bd8fe9c6e6e2c301fcec0681f73e22122c705"
COMPILED_SHAPE_SHA256 = "6bde114fae5c37825d8ea4711c55160329e7d414b3f0e44056b58e54d97efd6e"

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
# Keep the historical assembly identity and debug identifiers. Use a relative
# CodeView path in place of the historical machine-specific absolute path.
BUILD_METADATA = {
    0x88: bytes.fromhex("277de16a"),
    0x1EF9C: bytes.fromhex("08f43f1831dfba40a22426788ae93783"),
    0x21504: bytes.fromhex("fbc9cfd3"),
    0x2153C: bytes.fromhex("b08c6abb50cc1944a686e79d1a24378a"),
    0x21550: b".\\Library\\Bee\\artifacts\\200b0aP.dag\\Assembly-CSharp.pdb".ljust(260, b"\0"),
    0x2165B: bytes.fromhex("b08c6abb50cc19b42686e79d1a24378afbc9cf53e9090d5300e35066489bba35"),
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
