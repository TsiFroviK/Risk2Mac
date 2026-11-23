"""Find local Wwise Unity Integration inputs obtained through Audiokinetic."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import tarfile


WWISE_VERSION = "2024.1.18"
WWISE_SETUP_URL = "https://www.audiokinetic.com/en/download/"
MAC_ARCHIVE = "Unity.Mac.tar.xz"
WINDOWS_ARCHIVE = "Unity.Windows.tar.xz"
BUNDLE = "AkUnitySoundEngine.bundle"
RUNTIME = Path("Wwise/API/Runtime")
NATIVE_PATH = Path("Plugins/Mac/Release") / BUNDLE
NATIVE_FILES = {
    "Contents/Info.plist": (1210, "6ed4123678f483944f56fc462bc8a492e1b68784903637f76f1c569bcbc55dbe"),
    "Contents/_CodeSignature/CodeResources": (2200, "6686de10a28a2fe11b36cbb86dcbacc827cfc4ea116b4dabf1845e5aee629e9b"),
    "Contents/MacOS/AkUnitySoundEngine": (9987872, "6a9b565ab72bcf52feda8cc429f4341cf091c16d309305a4d984ac7557d93a5e"),
}
SOURCE_FILES = {
    MAC_ARCHIVE: (
        Path("Generated/Mac/AkUnitySoundEnginePINVOKE_Mac.cs"),
        (326246, "295bc30dfc9ff81143a53c22bf18b48c760b1c329815d5673e07570b3b414dfa"),
    ),
    WINDOWS_ARCHIVE: (
        Path("Handwritten/Common/AkVector64.cs"),
        (1484, "e34d52b97a06c50d09ec5e55fa6ad821b4cb167e4aa1c0139d705f3740c94070"),
    ),
}
ARCHIVES = {
    MAC_ARCHIVE: (70235844, "08d754e9e24ef765d5d276030fb3d79175d314b8c21d3f18567faf8e0db0911f"),
    WINDOWS_ARCHIVE: (63847112, "4fa0766b93647508a061050a12c3b59f57d9a7c4f7e5278424f2bfa4b81f751c"),
}


@dataclass(frozen=True)
class WwiseSDK:
    native: Path
    sources: dict[str, bytes]


def matches(path, signature):
    size, digest = signature
    try:
        if not path.is_file() or path.stat().st_size != size:
            return False
        result = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                result.update(block)
        return result.hexdigest() == digest
    except OSError:
        return False


def source_bytes(path, signature):
    try:
        if path.is_file() and path.stat().st_size == signature[0]:
            with path.open("rb") as stream:
                data = stream.read(signature[0] + 1)
            if len(data) == signature[0] and hashlib.sha256(data).hexdigest() == signature[1]:
                return data
    except OSError:
        pass
    return None


def archive_source(archive, relative, signature):
    name = (RUNTIME / relative).as_posix()
    with tarfile.open(archive, "r|xz") as stream:
        for item in stream:
            if item.name.removeprefix("./") == name:
                if not item.isfile() or item.size != signature[0]:
                    break
                with stream.extractfile(item) as source:
                    data = source.read(signature[0] + 1)
                if len(data) == signature[0] and hashlib.sha256(data).hexdigest() == signature[1]:
                    return data
                break
    raise ValueError(f"Missing matching Wwise source in {archive}: {name}")


def native_bundle_matches(bundle, legacy):
    if not bundle.is_dir() or not all(
        (bundle / name).is_file() and not (bundle / name).is_symlink() for name in NATIVE_FILES
    ):
        return False
    if not legacy:
        return all(matches(bundle / name, signature) for name, signature in NATIVE_FILES.items())
    executable = "Contents/MacOS/AkUnitySoundEngine"
    if not matches(bundle / executable, NATIVE_FILES[executable]):
        return False
    try:
        with (bundle / "Contents/Info.plist").open("rb") as info:
            metadata = plistlib.load(info)
        return isinstance(metadata, dict) and metadata.get("CFBundleExecutable") == BUNDLE.removesuffix(".bundle")
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def vendor_downloads():
    home = Path.home()
    yield home / "Downloads"
    yield home / "Documents/Audiokinetic"
    yield home / "Library/Application Support/Risk2Mac/Wwise Setup"
    for library in (home / "Library/Application Support", home / "Library/Caches"):
        for name in ("Audiokinetic", "Audiokinetic Launcher", "WwiseLauncher"):
            yield library / name / "Downloads"


def download_directories(root):
    """Inspect the download folder and its immediate export subdirectories."""
    for folder, directories, _ in os.walk(root, followlinks=False):
        path = Path(folder)
        depth = len(path.relative_to(root).parts)
        directories[:] = [] if depth == 3 else sorted(name for name in directories if not name.startswith("."))
        yield path


def runtime_directories(root):
    yield root
    yield root / RUNTIME
    yield root / "Assets" / RUNTIME
    yield root / "API/Runtime"
    for packages in (root / "Packages", root / "Library/PackageCache"):
        for package in sorted(packages.glob("*wwise*")):
            yield package / RUNTIME
            yield package / "API/Runtime"
            yield package / "Runtime"


def discover_wwise(private: Path, explicit: Path | None = None,
                   search_roots: tuple[Path, ...] = (), *, want_sources: bool = True) -> WwiseSDK | None:
    """Validate available native inputs and recover the optional exact managed source pair."""
    private = private.expanduser()
    explicit = explicit.expanduser().resolve() if explicit is not None else None
    native = None
    sources = {}
    archives = {}
    inspected = set()

    def inspect(candidate, legacy=False):
        nonlocal native
        candidate = candidate.resolve()
        key = (candidate, legacy)
        if key in inspected:
            return
        inspected.add(key)
        if native is None and native_bundle_matches(candidate, legacy):
            native = candidate
            return
        for name, signature in ARCHIVES.items():
            if (want_sources or name == MAC_ARCHIVE) and name not in archives and matches(candidate, signature):
                archives[name] = candidate
                if name == MAC_ARCHIVE and native is None:
                    native = candidate
                return

    def inputs_complete():
        return native is not None and all(
            relative.name in sources or archive in archives
            for archive, (relative, _) in SOURCE_FILES.items()
        )

    if explicit is not None:
        for candidate in (explicit, explicit / MAC_ARCHIVE, *(runtime / NATIVE_PATH for runtime in runtime_directories(explicit))):
            inspect(candidate, legacy=True)
            if native is not None:
                break
        if native is None:
            raise ValueError(f"Expected the Wwise Unity Integration {WWISE_VERSION} export folder, official macOS archive or Release bundle: {explicit}")

    private_native = private / "native/wwise"
    if native is None:
        inspect(private_native / BUNDLE, legacy=True)
        if native is None:
            inspect(private_native / MAC_ARCHIVE)
    if native is not None and not want_sources:
        return WwiseSDK(native=native, sources={})

    roots = [private_native, private / "wwise", *search_roots, *vendor_downloads()]
    if explicit is not None:
        roots.insert(0, explicit if explicit.is_dir() and explicit.name != BUNDLE else explicit.parent)
        if explicit.parts[-len(NATIVE_PATH.parts):] == NATIVE_PATH.parts:
            roots.insert(0, explicit.parents[len(NATIVE_PATH.parts) - 1])
    for root in dict.fromkeys(path.expanduser().resolve() for path in roots):
        for directory in download_directories(root):
            for archive in ARCHIVES:
                inspect(directory / archive)
            inspect(directory / BUNDLE)
            runtimes = tuple(runtime_directories(directory))
            for runtime in runtimes:
                inspect(runtime / NATIVE_PATH)
            if not want_sources:
                if native is not None:
                    return WwiseSDK(native=native, sources={})
                continue
            for relative, signature in SOURCE_FILES.values():
                name = relative.name
                if name not in sources:
                    paths = [directory / name, *(runtime / relative for runtime in runtimes)]
                    for path in paths:
                        data = source_bytes(path, signature)
                        if data is not None:
                            sources[name] = data
                            break
            if inputs_complete():
                break
        if inputs_complete():
            break
    if native is None:
        return None
    for archive, (relative, signature) in SOURCE_FILES.items():
        if relative.name not in sources and archive in archives:
            sources[relative.name] = archive_source(archives[archive], relative, signature)
    return WwiseSDK(native=native, sources=sources)


def stage_sources(sdk: WwiseSDK, target: Path) -> bool:
    """Write the complete validated pair into the caller's fresh private stage."""
    names = {relative.name for relative, _ in SOURCE_FILES.values()}
    if not names <= sdk.sources.keys():
        return False
    target.mkdir()
    for name in sorted(names):
        with (target / name).open("xb") as file:
            file.write(sdk.sources[name])
    return True


def open_wwise_setup() -> None:
    """Open the installed vendor Launcher or its official download page on macOS."""
    for applications in (Path("/Applications"), Path.home() / "Applications"):
        for directory in (applications, applications / "Audiokinetic"):
            for name in ("Audiokinetic Launcher.app", "Wwise Launcher.app", "AudiokineticLauncher.app"):
                launcher = directory / name
                if (launcher / "Contents/Info.plist").is_file():
                    subprocess.run(["/usr/bin/open", str(launcher)], check=True)
                    return
    subprocess.run(["/usr/bin/open", WWISE_SETUP_URL], check=True)
