"""Build Unity's official 2023.1 player memory metadata provider locally."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tarfile
import tempfile

from risk2mac_unity import sha256, verified_editor_package


PACKAGE_NAME = "com.unity.memoryprofiler-1.0.0.tgz"
PACKAGE_URL = f"https://download.packages.unity.com/com.unity.memoryprofiler/-/{PACKAGE_NAME}"
PACKAGE_SIZE = 1176268
PACKAGE_SHA256 = "8423c0e204050cd760350b6ab1f1026f1aa37353f93b29ec614293d0b74feeab"
OUTPUT_NAME = "Unity.MemoryProfiler.dll"
OUTPUT_SHA256 = "3f1f712c6b175ec154c7fd2e32770147b0a0b3886f8d819426c357f9cf5b4442"
# The vendor's runtime uses the 2023 CoreModule memory metadata event. The
# original Windows Unity reference profile supplies its framework interfaces.
REFERENCE_SHA256 = {
    "mscorlib.dll": "066a409f9228c9478d506d769978f0065fa42f9ccc97bfa266ee4451f4cbafad",
    "System.dll": "b271ae651c463425d5f4e55579bd1fba4af246cce549e322e47f5b463783b326",
    "System.Core.dll": "771dbf3f43fe24a8849ae78dc9640e3db9127d543f121e9a00740d71ef9ccab6",
    "netstandard.dll": "6ae62e082dc494a2433984177f60ca4db5fae69b1f360a8b33754172b310b8c5",
    "UnityEngine.CoreModule.dll": "9ef5b07bfd9136a3036a21c3645ed2580e8752bfea227060929183bb1aeabdf1",
}


def build_memory_profiler(dotnet: str | Path, csc: Path, references: dict[str, Path],
                          output: Path, scratch: Path, editor: Path | None = None) -> None:
    paths = []
    for name, expected in REFERENCE_SHA256.items():
        reference = references.get(name)
        if reference is None or not reference.is_file() or sha256(reference) != expected:
            raise ValueError(f"Unity Memory Profiler needs the verified Unity reference {name}.")
        paths.append(reference.resolve())

    with tempfile.TemporaryDirectory(prefix="unity-memory-profiler-", dir=scratch) as directory:
        root = Path(directory)
        package = verified_editor_package(editor, root, PACKAGE_URL, PACKAGE_SIZE, PACKAGE_SHA256)
        source = root / "MetadataInjector.cs"
        with tarfile.open(package, "r:gz") as archive:
            member = archive.getmember("package/Runtime/MetadataInjector.cs")
            if not member.isfile():
                raise ValueError("Unexpected source entry in the Unity Memory Profiler package.")
            with archive.extractfile(member) as stream:
                source.write_bytes(stream.read())

        candidate = root / OUTPUT_NAME
        subprocess.run([
            str(dotnet), str(csc), "/nologo", "/noconfig", "/nostdlib+", "/target:library",
            "/platform:anycpu", "/langversion:7.3", "/optimize+", "/deterministic+",
            "/define:MEMORY_PROFILER_API_PUBLIC", f"/out:{candidate}",
            *(f"/reference:{reference}" for reference in paths), str(source),
        ], check=True)
        if sha256(candidate) != OUTPUT_SHA256:
            raise ValueError("Built Unity Memory Profiler assembly failed SHA-256 verification.")
        with output.open("xb") as destination:
            destination.write(candidate.read_bytes())
