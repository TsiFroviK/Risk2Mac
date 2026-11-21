"""Compile the pinned Unity AI Navigation player assembly from official inputs."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tarfile
import tempfile


ARCHIVE_SHA256 = "edbc740b754d7f8e601dd90aa6ad569dc0a4301018e7c3ab2056f143c4ab9582"
ARCHIVE_SIZE = 8663000
ARCHIVE_URL = (
    "https://download.packages.unity.com/com.unity.ai.navigation/-/"
    "com.unity.ai.navigation-1.1.3.tgz"
)
SOURCE_NAMES = (
    "HelpUrls.cs", "NavMeshLink.cs", "NavMeshModifier.cs",
    "NavMeshModifierVolume.cs", "NavMeshSurface.cs",
)
ANALYZER_PATH = Path("Tools/Unity.SourceGenerators/Unity.SourceGenerators.dll")
ANALYZER_SHA256 = "63a4164de64c919a7c2ec41cd7d43210ba4c4f3caa255a559755cb1efc18259f"
REFERENCE_SHA256 = {
    "UnityEngine.AIModule.dll": "2a526d1dc8d2b5228cc423192ca3990aa19ba7d45e95f9b98055bc1cb279836d",
    "UnityEngine.CoreModule.dll": "9ef5b07bfd9136a3036a21c3645ed2580e8752bfea227060929183bb1aeabdf1",
    "UnityEngine.TerrainModule.dll": "ca974e5765f989d3dea03fcc31a1408a25e82bb0b74d69da954bca1bbf88b4f8",
    "mscorlib.dll": "f175689d29103828314171aba03eabb23cfdc24c3a4d9066f2f5033848bf87a2",
    "System.Core.dll": "1b18ed6c3c8791a2be4605e2331e871d6aa4baa46100b1a0517ba2d82d95cc9a",
    "System.dll": "461ac915a62d1762b626588c7055a02eabf0dc744c27825bfff6e10f45ad2e38",
    "netstandard.dll": "bf0b7eac9010b75413e4ec1a07a3453bc6a68eeb8e916fbed7c1f2777841f7c7",
}
OUTPUT_NAME = "Unity.AI.Navigation.dll"
OUTPUT_SHA256 = "3e7a05cede9407b2f323350db533e1d145158488129424c0431f6832a788a555"
COMPILED_SHAPE_SHA256 = "d2e0e17ad55b925e70688633c95affd9e7a516574e8afcc2855e7ae47ec859a0"
# The original player's PE timestamp, MVID, and portable PDB identifiers.
PLAYER_BUILD_IDS = {
    0x88: "267de16a",
    0x3B04: "057aef01c7e4744a88fc3b8fe1efdbae",
    0x4484: "38666ac3",
    0x44BC: "819af68340c1564e895941b1bdc40fb7",
    0x45DB: "819af68340c1565e495941b1bdc40fb738666a434797598c7c3c959efb435228",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_ai_navigation_analyzer(editor: Path | None) -> Path | None:
    if editor is None:
        return None
    analyzer = Path(editor).resolve().parent.parent / ANALYZER_PATH
    if analyzer.is_file() and sha256(analyzer.read_bytes()) == ANALYZER_SHA256:
        return analyzer
    return None


def response_path(path: Path) -> str:
    return f'"{path.as_posix()}"'


def download_sources(root: Path, source_dir: Path) -> None:
    archive = root / "com.unity.ai.navigation-1.1.3.tgz"
    print("Downloading official Unity AI Navigation 1.1.3 sources", flush=True)
    subprocess.run([
        "curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
        "--retry", "2", "--connect-timeout", "15", "--max-time", "90",
        "--max-filesize", str(ARCHIVE_SIZE), "--silent", "--show-error",
        "--output", str(archive), ARCHIVE_URL,
    ], check=True)
    if archive.stat().st_size != ARCHIVE_SIZE or sha256(archive.read_bytes()) != ARCHIVE_SHA256:
        raise ValueError("Official Unity AI Navigation package failed SHA-256 verification.")
    (root / source_dir).mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as package:
        for name in SOURCE_NAMES:
            member = package.getmember(f"package/Runtime/{name}")
            if not member.isfile():
                raise ValueError(f"Unexpected source entry in Unity package: {member.name}")
            with package.extractfile(member) as source:
                (root / source_dir / name).write_bytes(source.read())


def restore_player_build_ids(assembly: bytes) -> bytes:
    if len(assembly) != 20480:
        raise ValueError(f"Unexpected Unity AI Navigation assembly size: {len(assembly)}")
    normalized = bytearray(assembly)
    # SDK 8 Roslyn uses internal visibility for two synthesized static-array
    # carriers. The original compiler kept them private to their containing type.
    for offset in (0x171A, 0x1728):
        if normalized[offset] not in (0x13, 0x15):
            raise ValueError("Unexpected Unity AI Navigation compiler visibility flags.")
        normalized[offset] = 0x13
    # Match the original CodeView path. The PDB is never staged into the app.
    for offset in (0x44D1, 0x44D9, 0x44DD, 0x44E7, 0x44F3):
        if normalized[offset] not in (ord("/"), ord("\\")):
            raise ValueError("Unexpected Unity AI Navigation CodeView path.")
        normalized[offset] = ord("\\")
    for offset, hex_value in PLAYER_BUILD_IDS.items():
        size = len(hex_value) // 2
        normalized[offset:offset + size] = bytes(size)
    shape = sha256(normalized)
    if shape != COMPILED_SHAPE_SHA256:
        raise ValueError(f"Unexpected compiled Unity AI Navigation assembly: {shape}")
    for offset, hex_value in PLAYER_BUILD_IDS.items():
        value = bytes.fromhex(hex_value)
        normalized[offset:offset + len(value)] = value
    if sha256(normalized) != OUTPUT_SHA256:
        raise ValueError("Rebuilt Unity AI Navigation failed SHA-256 verification.")
    return bytes(normalized)


def build_ai_navigation(dotnet: str | Path, csc: Path, editor: Path, references: dict[str, Path],
                        output: Path, scratch: Path) -> None:
    analyzer = find_ai_navigation_analyzer(editor)
    if analyzer is None:
        raise ValueError(
            "Install the official Unity 2023.1.0f1 Editor with its source generator, "
            "or supply the verified Unity.AI.Navigation.dll in the prepared inputs."
        )
    reference_paths = []
    for name, expected in REFERENCE_SHA256.items():
        reference = references.get(name)
        if reference is None or not reference.is_file() or sha256(reference.read_bytes()) != expected:
            raise ValueError(f"Unity AI Navigation needs the verified macOS Unity reference {name}.")
        reference_paths.append(reference.resolve())

    with tempfile.TemporaryDirectory(prefix="unity-navigation-", dir=scratch) as directory:
        # Resolve the /var alias on macOS so Roslyn can map the project's real path.
        root = Path(directory).resolve()
        intermediate = Path("Library/Bee/artifacts/200b0aP.dag")
        source_dir = Path("Library/PackageCache/com.unity.ai.navigation@1.1.3/Runtime")
        (root / intermediate).mkdir(parents=True)
        download_sources(root, source_dir)
        raw_dll = intermediate / OUTPUT_NAME
        ref_dll = intermediate / "Unity.AI.Navigation.ref.dll"
        additional_file = intermediate / "Unity.AI.Navigation.UnityAdditionalFile.txt"
        (root / additional_file).write_text(str(root), encoding="utf-8")
        arguments = [
            "-target:library", f"-out:{response_path(raw_dll)}", f"-refout:{response_path(ref_dll)}",
            "-define:UNITY_2022_2_OR_NEWER", "-define:NMC_CAN_ACCESS_TERRAIN",
            *(f"-r:{response_path(reference)}" for reference in reference_paths),
            f"-analyzer:{response_path(analyzer)}",
            *(response_path(source_dir / name) for name in SOURCE_NAMES),
            "-langversion:9.0", "/optimize+", "/debug:portable", "/nologo",
            "/RuntimeMetadataVersion:v4.0.30319", "/utf8output", "/preferreduilang:en-US",
            "-warn:0", f"/additionalfile:{response_path(additional_file)}",
        ]
        response = root / "compile.rsp"
        response.write_text("\n".join(arguments), encoding="utf-8")
        subprocess.run([
            str(dotnet), str(csc.resolve()), "/noconfig", f"/pathmap:{root}=.", f"@{response}",
        ], cwd=root, check=True)
        result = restore_player_build_ids((root / raw_dll).read_bytes())
        with output.open("xb") as destination:
            destination.write(result)
