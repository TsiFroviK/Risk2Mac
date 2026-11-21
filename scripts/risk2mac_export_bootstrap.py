"""Export only the Windows game's bootstrap Unity data through AssetRipper."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlencode
import zipfile


VERSION = "2.0.0"
RELEASE = f"https://github.com/AssetRipper/AssetRipper/releases/download/{VERSION}/"
EXECUTABLE = "AssetRipper.GUI.Free"
WINDOWS_DATA = "Risk of Rain 2_Data"
WINDOWS_ROOT_FILES = ("Risk of Rain 2.exe", "UnityPlayer.dll")
INPUTS = {
    "globalgamemanagers": "292966bcba420ae931250b19633717684d0add5277abec3e9d3c4605cc5cd236",
    "globalgamemanagers.assets": "82fb8e1e720300f289636d22aa2aea9d3c2871f4734fe81ca14e869a2b4b2b53",
    "Resources/unity_builtin_extra": "3437af0a10a2fa400cc88d8aacc147043c908da9cdcc515a46ad78b4a8b0c1a7",
}
SETTINGS = {
    "Import": {"ScriptContentLevel": 2, "StreamingAssetsMode": 1, "DefaultVersion": "2021.3.45f2",
               "TargetVersion": "0.0.0a0"},
    "Processing": {"EnablePrefabOutlining": False, "EnableStaticMeshSeparation": False,
                   "EnableAssetDeduplication": False, "RemoveNullableAttributes": False,
                   "PublicizeAssemblies": False, "BundledAssetsExportMode": 2},
    "Export": {"AudioExportFormat": 2, "ImageExportFormat": 4, "LightmapTextureExportFormat": 2,
               "ScriptExportMode": 3, "ScriptLanguageVersion": -1, "ScriptTypesFullyQualified": False,
               "ShaderExportMode": 0, "SpriteExportMode": 0, "TextExportMode": 2, "ExportUnreadableAssets": False,
               "PreferOriginalTextureExtension": True, "SaveSettingsToDisk": True, "LanguageCode": None},
}
WINDOWS_FILES = {
    "x64": ("58bb4c6a78507d77ea115db236ae7286b097979fba7f77aa247c16a471499fff",
            "f03321188a1615d044314b1183dcd9a7ffda09286c31c369d109165d4892dcbb"),
    "arm64": ("5bce23555675be93e91adf265a3cf9dd80f88a02cef4fc439fabb8da4a7a1728",
              "5d697c69379a679987540fe00a0136a510f3349f91b16054b6c75df9944b9142"),
}
MAX_ARCHIVE_CONTENT = 256 * 1024**2
MAX_BOOTSTRAP_INPUT = 512 * 1024**2


@dataclass(frozen=True)
class ReleaseArchive:
    name: str
    size: int
    sha256: str


# SHA-256 values and sizes from the official GitHub Releases API for this tag.
ARCHIVES = {
    ("Darwin", "arm64"): ReleaseArchive("AssetRipper_mac_arm64.tar.xz", 27205056,
        "237a6da404bf089c5e5c71a5a9a698c2ea580872292dfa5ce21e25fd1dbe9045"),
    ("Darwin", "x64"): ReleaseArchive("AssetRipper_mac_x64.tar.xz", 31545636,
        "1b3836f135d16845cb57595fadff5739cbb86d28caaf621005b4301dba9b5a56"),
    ("Windows", "arm64"): ReleaseArchive("AssetRipper_win_arm64.zip", 42493451,
        "c2c3a335948aa0ecaf26baf22ac77e36993d1a1695b5db291cb63f66872627f1"),
    ("Windows", "x64"): ReleaseArchive("AssetRipper_win_x64.zip", 44439367,
        "9a7ef0e7c5c3ea5b90b4e6d855e2d98d5f7ec8c3f9e26fccbc194c6a7b01baf7"),
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def host() -> tuple[str, str]:
    arch = platform.machine().lower()
    kind = (platform.system(), {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(arch, arch))
    if kind not in ARCHIVES:
        raise ValueError("AssetRipper bootstrap requires macOS or Windows on x64 or ARM64")
    return kind


def archive_valid(path: Path, release: ReleaseArchive) -> bool:
    return path.is_file() and path.stat().st_size == release.size and file_hash(path) == release.sha256


def prepare_archive(cache: Path, release: ReleaseArchive) -> Path:
    directory = cache / f"assetripper-{VERSION}"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / release.name
    if archive_valid(destination, release):
        return destination
    print(f"Downloading the official AssetRipper {VERSION} archive", file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=directory) as scratch:
        download = Path(scratch) / release.name
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "2",
                        "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "15", "--max-time", "600",
                        "--max-filesize", str(release.size), "--output", str(download), RELEASE + release.name],
                       check=True, creationflags=flags)
        if not archive_valid(download, release):
            raise ValueError(f"The official AssetRipper download failed SHA-256 verification: {release.name}")
        download.replace(destination)
    return destination


def unpack_runner(archive: Path, release: ReleaseArchive, runner: Path, windows: bool) -> Path:
    if not archive_valid(archive, release):
        raise ValueError(f"Supplied AssetRipper archive does not match the official {release.name} release")
    executable = EXECUTABLE + (".exe" if windows else "")
    library = "capstone.dll" if windows else "libcapstone.dylib"
    names = {executable, library, "compile_time.txt"}
    written = set()
    total = 0

    def extract(name, size, is_file, open_member):
        nonlocal total
        filename = PurePosixPath(name).name
        if PurePosixPath(name).parts != (filename,) or not is_file or filename not in names or filename in written:
            raise ValueError("Unexpected entry in the official AssetRipper archive")
        total += size
        if size < 0 or total > MAX_ARCHIVE_CONTENT:
            raise ValueError("AssetRipper archive exceeded the extraction size limit")
        with open_member() as source, (runner / filename).open("xb") as target:
            shutil.copyfileobj(source, target)
        if (runner / filename).stat().st_size != size:
            raise ValueError(f"Incomplete AssetRipper archive entry: {filename}")
        written.add(filename)

    if windows:
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                file_type = stat.S_IFMT(entry.external_attr >> 16)
                extract(entry.filename, entry.file_size, not entry.is_dir() and file_type in (0, stat.S_IFREG),
                        lambda: source.open(entry))
    else:
        with tarfile.open(archive, "r:xz") as source:
            for entry in source:
                extract(entry.name, entry.size, entry.isfile(), lambda: source.extractfile(entry))
        (runner / executable).chmod(0o700)
    if executable not in written or library not in written:
        raise ValueError("The AssetRipper archive did not contain its executable and support library")
    return runner / executable


def copy_windows_runner(executable: Path, arch: str, runner: Path) -> Path:
    support = executable.with_name("capstone.dll")
    paths = (executable, support)
    names = (EXECUTABLE + ".exe", support.name)
    for file, name, expected in zip(paths, names, WINDOWS_FILES[arch]):
        if not file.is_file() or file_hash(file) != expected:
            raise ValueError(f"Expected the official AssetRipper {VERSION} Windows {arch} file: {file}")
        destination = runner / name
        shutil.copyfile(file, destination)
        if file_hash(destination) != expected:
            raise ValueError(f"AssetRipper file changed during staging: {file}")
    return runner / names[0]


def stage_bootstrap_data(game_data: Path, game: Path) -> None:
    data = game / WINDOWS_DATA
    data.mkdir(parents=True)
    copied = 0
    total = 0

    def copy(source, destination):
        nonlocal copied, total
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Expected a regular Windows input: {source}")
        length = source.stat().st_size
        copied += 1
        total += length
        if copied > 4096 or total > MAX_BOOTSTRAP_INPUT:
            raise ValueError("The Windows bootstrap input exceeded the local staging limit")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if destination.stat().st_size != length:
            raise ValueError(f"Windows input changed during staging: {source}")

    for name in WINDOWS_ROOT_FILES:
        copy(game_data.parent / name, game / name)
    for file in sorted(game_data.iterdir()):
        if file.is_file() and file.name.casefold() != "streamingassets":
            copy(file, data / file.name)
    for name in ("Resources", "Managed"):
        root = game_data / name
        if not root.is_dir() or root.is_symlink():
            raise ValueError(f"Expected a Windows data directory: {root}")
        for directory, subdirectories, files in os.walk(root):
            subdirectories[:] = sorted(name for name in subdirectories if name.casefold() != "streamingassets")
            current = Path(directory)
            for subdirectory in subdirectories:
                if (current / subdirectory).is_symlink():
                    raise ValueError(f"Unexpected link in Windows data: {current / subdirectory}")
            for name in sorted(files):
                if name.casefold() != "streamingassets":
                    source = current / name
                    copy(source, data / source.relative_to(game_data))
    for name, expected in INPUTS.items():
        if not (data / name).is_file() or file_hash(data / name) != expected:
            raise ValueError(f"Unsupported Windows game input for bootstrap export: {game_data / name}")


def export_commands(process: subprocess.Popen, journal: Path, game: Path, export: Path) -> None:
    deadline = time.monotonic() + 30
    address = None
    while process.poll() is None and time.monotonic() < deadline:
        with journal.open("rb") as stream:
            found = re.search(rb"Now listening on: http://127\.0\.0\.1:([0-9]{1,5})(?:\r?\n)", stream.read(65536))
        if found:
            address = int(found[1])
            break
        time.sleep(0.15)
    if address is None or not 1 <= address <= 65535:
        raise RuntimeError("AssetRipper did not start its local export service")

    for route, path in (("/LoadFolder", game), ("/Export/UnityProject", export)):
        connection = http.client.HTTPConnection("127.0.0.1", address, timeout=180)
        try:
            body = urlencode({"Path": str(path)})
            connection.request("POST", route, body, {"Content-Type": "application/x-www-form-urlencoded"})
            response = connection.getresponse()
            if response.status != 302 or response.getheader("Location") != "/":
                raise RuntimeError(f"AssetRipper command {route} failed with HTTP {response.status}")
        finally:
            connection.close()


def run_export(executable: Path, runner: Path, game: Path, export: Path, journal: Path) -> None:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    environment = dict(os.environ, DOTNET_BUNDLE_EXTRACT_BASE_DIR=str(runner / "DotnetBundle"))
    with journal.open("wb") as log:
        process = subprocess.Popen([str(executable), "--headless", "--port", "0"], cwd=runner, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=flags)
        try:
            export_commands(process, journal, game, export)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def export_bootstrap(game_data: Path, workspace: Path, cache: Path, executable: Path | None = None,
                     archive: Path | None = None) -> Path:
    """Return a private AssetRipper 2.0.0 bootstrap export inside the caller's workspace."""
    if executable is not None and archive is not None:
        raise ValueError("Supply an AssetRipper executable or an archive")
    system, arch = host()
    game_data = game_data.resolve(strict=True)
    workspace = workspace.resolve()
    cache = cache.resolve()
    if workspace.is_relative_to(game_data) or cache.is_relative_to(game_data):
        raise ValueError("Choose a workspace and tool cache outside the Windows data directory")
    workspace.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="risk2mac-bootstrap-", dir=workspace)).resolve()
    runner = stage / "Runner"
    runner.mkdir()
    game = stage / "Game"
    export = stage / "Export"
    journal = stage / "AssetRipper.log"
    try:
        stage_bootstrap_data(game_data, game)
        if executable is not None:
            if system != "Windows":
                raise ValueError("Use the pinned AssetRipper archive on macOS")
            player = copy_windows_runner(executable.resolve(strict=True), arch, runner)
        else:
            release = ARCHIVES[(system, arch)]
            player = unpack_runner(archive or prepare_archive(cache, release), release, runner, system == "Windows")
        (runner / "AssetRipper.Settings.json").write_text(json.dumps(SETTINGS, indent=2), encoding="utf-8")
        print("Exporting the local Unity bootstrap data", file=sys.stderr, flush=True)
        run_export(player, runner, game, export, journal)
        result = export / "ExportedProject"
        if not (result / "ProjectSettings/ProjectVersion.txt").is_file() or not (result / "Assets").is_dir():
            raise RuntimeError("AssetRipper did not produce the expected Unity bootstrap project")
        return result
    except BaseException:
        if journal.is_file():
            with journal.open("rb") as stream:
                stream.seek(max(0, journal.stat().st_size - 4096))
                print(stream.read().decode("utf-8", errors="replace"), file=sys.stderr)
        if stage != workspace and stage.is_relative_to(workspace):
            shutil.rmtree(stage, ignore_errors=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    override = parser.add_mutually_exclusive_group()
    override.add_argument("--assetripper-exe", type=Path)
    override.add_argument("--assetripper-archive", type=Path)
    args = parser.parse_args()
    output = export_bootstrap(args.game_data, args.workspace, args.cache, args.assetripper_exe, args.assetripper_archive)
    print(json.dumps({"project": str(output)}, separators=(",", ":")))
