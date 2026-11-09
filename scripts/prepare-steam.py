#!/usr/bin/env python3
"""Download and verify private Steamworks headers for the optional Steam build."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "605054339ad88fd09eeb7e0a82ca0eb78737b334"
BASE_URL = f"https://raw.githubusercontent.com/Facepunch/Facepunch.Steamworks/{COMMIT}/Generator/steam_sdk/"
MAX_HEADER_BYTES = 1024 * 1024


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def lock_inputs(path):
    if path.is_symlink():
        raise ValueError(f"The preparation lock must be a regular file: {path}")
    with path.open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def download_header(item, staging):
    name, expected = item
    request = Request(BASE_URL + name, headers={"User-Agent": "Risk2Mac-private-header-preparation"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                data = response.read(MAX_HEADER_BYTES + 1)
            break
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    if len(data) > MAX_HEADER_BYTES or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Downloaded Steam header failed SHA-256 verification: {name}")
    (staging / name).write_bytes(data)


def prepare(private):
    private = private.expanduser().resolve()
    if private == ROOT or ROOT in private.parents:
        raise ValueError("Keep private Steamworks headers outside the Risk2Mac repository.")
    manifest = json.loads((ROOT / "native/steam-legacy-headers.json").read_text(encoding="utf-8"))
    if not manifest or any(
        not re.fullmatch(r"[A-Za-z0-9_]+\.h", name) or
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
        for name, value in manifest.items()
    ):
        raise ValueError("Invalid Steamworks header manifest")
    native = private / "native"
    if native.is_symlink():
        raise ValueError(f"Use a regular private native directory: {native}")
    native.mkdir(parents=True, exist_ok=True)
    target = native / "steam-legacy-headers"
    with lock_inputs(native / ".steam-legacy-headers.lock"):
        if target.is_symlink():
            raise ValueError(f"Use a regular Steamworks header directory: {target}")
        target.mkdir(exist_ok=True)
        for path in target.iterdir():
            if path.name not in manifest or path.is_symlink() or not path.is_file():
                raise ValueError(f"Unexpected entry in the private header directory: {path}")
            if digest(path) != manifest[path.name]:
                raise ValueError(f"Existing Steam header differs from this recipe: {path}")
        missing = [(name, expected) for name, expected in manifest.items() if not (target / name).exists()]
        with tempfile.TemporaryDirectory(prefix=".steam-headers-", dir=native) as temporary:
            staging = Path(temporary)
            with ThreadPoolExecutor(max_workers=4) as workers:
                list(workers.map(lambda item: download_header(item, staging), missing))
            for name, expected in missing:
                destination = target / name
                if destination.exists() or destination.is_symlink():
                    if destination.is_symlink() or not destination.is_file() or digest(destination) != expected:
                        raise ValueError(f"Steam header changed during preparation: {destination}")
                    continue
                os.replace(staging / name, destination)
        for name, expected in manifest.items():
            if digest(target / name) != expected:
                raise ValueError(f"Steam header failed final verification: {name}")
    print(f"Verified {len(manifest)} private Steamworks headers in {target}")
    print(f"Downloaded {len(missing)} headers from Facepunch commit {COMMIT}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", required=True, type=Path, help="Existing or new private prerequisite directory outside the repository")
    options = parser.parse_args()
    try:
        prepare(options.private)
    except (OSError, ValueError, URLError) as error:
        parser.exit(1, f"Risk2Mac Steam preparation: {error}\n")


if __name__ == "__main__":
    main()
