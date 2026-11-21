"""Generate the stock Unity splash stream in an empty local project."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


PROJECT = Path(__file__).resolve().parents[1] / "shaders/startup-splash"
SPLASH = Path("Fixture.app/Contents/Resources/Data/globalgamemanagers.assets.resS")


def build_splash_stream(editor: Path) -> bytes:
    """Generate the splash stream for verification against the asset manifest."""
    print("Generating the stock Unity splash resource", flush=True)
    stage = Path(tempfile.mkdtemp(prefix="risk2mac-startup-splash-")).resolve()
    try:
        project = stage / "Project"
        output = stage / "Output"
        log = stage / "Unity.log"
        shutil.copytree(PROJECT, project)
        args = [str(editor), "-batchmode", "-nographics", "-quit", "-projectPath", str(project),
                "-buildTarget", "StandaloneOSX", "-executeMethod", "BuildUnityStartupFixture.Build",
                "-logFile", str(log)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(args, env=dict(os.environ, RISK2MAC_STARTUP_FIXTURE_OUTPUT=str(output)),
                                creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        resource = output / SPLASH
        if result.returncode or not resource.is_file():
            if log.is_file():
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]), flush=True)
            raise ValueError("Unity could not generate the splash resource. Check the Unity 2023.1.0f1 license and Mac Build Support (./build.sh --setup unity).")
        return resource.read_bytes()
    finally:
        shutil.rmtree(stage, ignore_errors=os.name == "nt")
