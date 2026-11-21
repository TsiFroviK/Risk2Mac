"""Build Risk2Mac's Metal depth-copy shader with an installed Unity Editor."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


PROJECT = Path(__file__).resolve().parents[1] / "shaders/depth-copy"
EDITOR = Path("/Applications/Unity/Hub/Editor/2023.1.0f1/Unity.app/Contents/MacOS/Unity")


def find_unity_editor(supplied: Path | None = None) -> Path | None:
    editor = supplied.expanduser().resolve() if supplied else EDITOR
    if editor.suffix == ".app":
        editor = editor / "Contents/MacOS/Unity"
    if editor.is_file():
        return editor
    if supplied:
        raise ValueError(f"Unity Editor was not found at {editor}")
    return None


def build_depth_bundle(editor: Path) -> bytes:
    print("Building the Risk2Mac Metal depth-copy shader", flush=True)
    stage = Path(tempfile.mkdtemp(prefix="risk2mac-depth-")).resolve()
    try:
        project = stage / "Project"
        output = stage / "Bundle"
        log = stage / "Unity.log"
        shutil.copytree(PROJECT, project)
        args = [str(editor), "-batchmode", "-nographics", "-quit", "-projectPath", str(project),
                "-executeMethod", "BuildSafeDepth.Build", "-logFile", str(log)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(args, env=dict(os.environ, SAFE_DEPTH_OUT=str(output)),
                                creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        bundle = output / "safe-depth-copy.bundle"
        if result.returncode or not bundle.is_file():
            if log.is_file():
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]), flush=True)
            raise ValueError("Unity could not compile the Metal depth-copy shader. Check the Unity 2023.1.0f1 license and macOS build support.")
        return bundle.read_bytes()
    finally:
        # Windows Unity subprocesses can briefly hold the Editor log after exit.
        shutil.rmtree(stage, ignore_errors=os.name == "nt")
