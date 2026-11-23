"""Prepare a private cache from Unity's official macOS Mono support package."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


VERSION = "2023.1.0f1"
REVISION = "a008fa768e6c"
EDITOR_RELEASE_URL = f"https://unity.com/releases/editor/whats-new/{VERSION}"
HUB_INSTALL_URL = f"unityhub://{VERSION}/{REVISION}"
PACKAGE_URL = (
    f"https://download.unity3d.com/download_unity/{REVISION}/MacEditorTargetInstaller/"
    f"UnitySetup-Mac-Mono-Support-for-Editor-{VERSION}.pkg"
)
PACKAGE_SIZE = 574289947
PACKAGE_SHA256 = "0e18f0165a7f5aedf84f52b31618653ac1c549146c3f409dea37fcb9c2feca01"
CACHE_NAME = f"unity-mac-mono-{VERSION}-{REVISION}"
PLAYER = Path("Variations/macos_x64arm64_player_nondevelopment_mono/UnityPlayer.app/Contents")
NATIVE_FILES = (
    PLAYER / "MacOS/UnityPlayer",
    PLAYER / "Frameworks/UnityPlayer.dylib",
    PLAYER / "Frameworks/libmono-native.dylib",
    PLAYER / "Frameworks/libmonobdwgc-2.0.dylib",
    PLAYER / "Frameworks/libMonoPosixHelper.dylib",
    PLAYER / "Resources/unity default resources",
)
NATIVE_DIRECTORIES = (
    Path("MonoBleedingEdge/etc"),
    Path("Source/Player/MacPlayer/MacPlayerEntryPoint/Resources/MainMenu.nib"),
)
MANAGED_DIRECTORIES = (
    Path("Variations/mono/Managed"),
    Path("MonoBleedingEdge/lib/mono/unityjit-macos"),
    Path("MonoBleedingEdge/lib/mono/unityjit-macos/Facades"),
)


def open_unity_setup(editor_installed: bool) -> None:
    """Open Unity's own installer or license manager via Launch Services."""
    if sys.platform != "darwin":
        raise ValueError("Open Unity SDK setup on macOS.")
    target = ["-a", "Unity Hub"] if editor_installed else [HUB_INSTALL_URL]
    result = subprocess.run(["/usr/bin/open", *target], capture_output=True)
    if result.returncode:
        subprocess.run(["/usr/bin/open", EDITOR_RELEASE_URL], check=True)
    print(f"Sign in to Unity Hub, install Unity {VERSION} if needed, and activate your Editor license. Then retry the build.")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verified_editor_package(editor: Path | None, scratch: Path, url: str, size: int, digest: str) -> Path:
    name = url.rsplit("/", 1)[1]
    if editor is not None:
        executable = editor.resolve()
        contents = executable.parent / "Data" if executable.suffix.lower() == ".exe" else executable.parent.parent
        bundled = contents / "Resources/PackageManager/Editor" / name
        try:
            if bundled.is_file() and bundled.stat().st_size == size and sha256(bundled) == digest:
                print(f"Using {name} from the selected Unity Editor", flush=True)
                return bundled
        except OSError:
            pass  # A missing or unreadable SDK copy can be downloaded below.
    archive = scratch / name
    print(f"Downloading official Unity package {name}", flush=True)
    subprocess.run([
        "curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
        "--retry", "2", "--connect-timeout", "15", "--max-time", "90",
        "--max-filesize", str(size), "--silent", "--show-error", "--output", str(archive), url,
    ], check=True)
    if archive.stat().st_size != size or sha256(archive) != digest:
        raise ValueError(f"Official Unity package failed SHA-256 verification: {name}")
    return archive


def managed_modules_match(managed: Path, manifest: Path) -> bool:
    """The Apple silicon Hub Editor can ship a different build of these same DLLs."""
    files = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    for name, entry in files.items():
        if entry["source"] != "private" or not (
            name == "UnityEngine.dll" or (name.startswith("UnityEngine.") and name.endswith("Module.dll"))
        ):
            continue
        module = managed / name
        if not module.is_file() or sha256(module) != entry["sha256"]:
            return False
    return True


def real(path: Path) -> Path:
    if path.resolve(strict=True) != path:
        raise ValueError(f"Unexpected link in Unity Mac support: {path}")
    return path


def support_files(root: Path) -> list[Path]:
    real(root)
    files = []
    for relative in NATIVE_FILES:
        source = real(root / relative)
        if not source.is_file():
            raise ValueError(f"Expected a Unity Mac runtime file: {source}")
        files.append(source)
    for relative in NATIVE_DIRECTORIES:
        directory = real(root / relative)
        if not directory.is_dir():
            raise ValueError(f"Expected a Unity Mac runtime directory: {directory}")
        entries = [real(entry) for entry in directory.rglob("*")]
        if any(not (entry.is_file() or entry.is_dir()) for entry in entries):
            raise ValueError(f"Unexpected file type in {directory}")
        files.extend(entry for entry in entries if entry.is_file())
    for relative in MANAGED_DIRECTORIES:
        directory = root / relative
        if directory.exists() or directory.is_symlink():
            real(directory)
            files.extend(real(file) for file in directory.glob("*.dll") if file.is_file() or file.is_symlink())
    if not any(file.parent == root / MANAGED_DIRECTORIES[0] for file in files):
        raise ValueError(f"Unity Mac managed engine modules are missing in {root}")
    if any(not file.is_file() for file in files):
        raise ValueError(f"Unexpected file type in Unity Mac managed modules: {root}")
    return sorted(set(files))


def inventory(root: Path) -> dict[str, str]:
    files = support_files(root)
    return {p.relative_to(root).as_posix(): sha256(p) for p in files}


def verified_cache(directory: Path) -> Path:
    root = real(directory / "MacStandaloneSupport")
    receipt = json.loads(real(directory / "receipt.json").read_text(encoding="utf-8"))
    if receipt.get("source") != PACKAGE_SHA256 or receipt.get("files") != inventory(root):
        raise ValueError(f"Unity Mac support cache failed verification: {directory}")
    return root


def prepare_unity(cache: Path) -> Path:
    """Return a verified MacStandaloneSupport directory without installing Unity."""
    if sys.platform != "darwin":
        raise ValueError("Extract Unity Mac support on macOS.")

    import fcntl

    cache = cache.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / CACHE_NAME
    lock = cache / f".{CACHE_NAME}.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if destination.exists() or destination.is_symlink():
            return verified_cache(destination)

        with tempfile.TemporaryDirectory(prefix=".unity-mac-mono-", dir=cache) as temporary:
            staging = Path(temporary)
            package = staging / "UnityMono.pkg"
            print(f"Downloading official Unity {VERSION} Mac Mono Build Support", flush=True)
            subprocess.run([
                "/usr/bin/curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                "--retry", "2", "--max-filesize", str(PACKAGE_SIZE), "--progress-bar",
                "--output", str(package), PACKAGE_URL,
            ], check=True)
            if package.stat().st_size != PACKAGE_SIZE or sha256(package) != PACKAGE_SHA256:
                raise ValueError("Official Unity Mac Mono package failed SHA-256 verification.")

            expanded = staging / "Expanded"
            print("Extracting Unity Mac Mono Build Support into the local tool cache", flush=True)
            subprocess.run(["/usr/sbin/pkgutil", "--expand-full", str(package), str(expanded)], check=True)
            source = real(expanded / "TargetSupport.pkg.tmp/Payload")
            prepared = staging / "Prepared"
            support = prepared / "MacStandaloneSupport"
            for file in support_files(source):
                target = support / file.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
            receipt = {"source": PACKAGE_SHA256, "files": inventory(support)}
            (prepared / "receipt.json").write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
            prepared.rename(destination)

        return verified_cache(destination)
