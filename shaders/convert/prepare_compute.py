"""Compile the official Unity PostProcessing compute shaders locally."""

import argparse
import io
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile


POSTPROCESSING = "https://github.com/Unity-Technologies/PostProcessing.git"
REVISION = "32c3155207d3fac4138b24af5c7e0e43805c6f2b"
SOURCE_ROOT = PurePosixPath("PostProcessing/Shaders")
UNITY_PATH = "Packages/com.unity.postprocessing/PostProcessing/Shaders/"
ENTRYPOINT = Path(__file__).resolve().parent / "BuildComputeDonor.cs"


def prepare_project(project, staged):
    checkout = staged / "upstream"
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
    git = ["git", "-C", str(checkout)]
    subprocess.run([*git, "fetch", "--quiet", "--depth=1", POSTPROCESSING, REVISION], check=True)
    if subprocess.check_output([*git, "rev-parse", "FETCH_HEAD"], text=True).strip() != REVISION:
        raise ValueError("Unexpected Unity PostProcessing revision")
    shader_tar = subprocess.check_output([*git, "archive", "FETCH_HEAD", SOURCE_ROOT.as_posix()])
    for folder in ("Assets/Editor", "Packages", "ProjectSettings"):
        (project / folder).mkdir(parents=True)
    shutil.copyfile(ENTRYPOINT, project / "Assets/Editor/BuildComputeDonor.cs")
    (project / "Packages/manifest.json").write_text('{"dependencies": {}}', encoding="utf-8")
    (project / "ProjectSettings/ProjectVersion.txt").write_text(
        "m_EditorVersion: 2023.1.0f1\nm_EditorVersionWithRevision: 2023.1.0f1 (a008fa768e6c)\n", encoding="utf-8"
    )
    count = 0
    with tarfile.open(fileobj=io.BytesIO(shader_tar)) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.suffix not in {".compute", ".hlsl", ".cginc"}:
                continue
            if not path.is_relative_to(SOURCE_ROOT) or ".." in path.parts:
                raise ValueError("Unexpected path in the Unity PostProcessing archive")
            destination = project / "Assets/ComputeDonor" / path.relative_to(SOURCE_ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as stream:
                source = stream.read().decode("utf-8").replace("\r\n", "\n")
            destination.write_text(source.replace(UNITY_PATH, "Assets/ComputeDonor/"), encoding="utf-8")
            count += path.suffix == ".compute"
    if count != 12:
        raise ValueError(f"Expected 12 Unity compute shaders, found {count}")


def build_compute_donor(editor, destination):
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Choose a new compute bundle path: {destination}")
    stage = Path(tempfile.mkdtemp(prefix="risk2mac-compute-")).resolve()
    try:
        project = stage / "Project"
        output = stage / "Output"
        log = stage / "Unity.log"
        prepare_project(project, stage)
        print("Compiling the official Unity PostProcessing compute shaders for Metal", flush=True)
        arguments = [str(editor), "-batchmode", "-nographics", "-quit", "-projectPath", str(project),
                     "-executeMethod", "BuildComputeDonor.Build", "-logFile", str(log)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.run(arguments, env=dict(os.environ, ROR2_MAC_COMPUTE_DONOR_OUTPUT=str(output)),
                                 creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = output / "compute-donor.bundle"
        if process.returncode or not result.is_file():
            if log.is_file():
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]), flush=True)
            raise ValueError("Unity could not compile PostProcessing. Check the editor license and Mac Build Support.")
        with result.open("rb") as bundle, destination.open("xb") as target:
            shutil.copyfileobj(bundle, target)
    finally:
        shutil.rmtree(stage, ignore_errors=os.name == "nt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_compute_donor(args.editor.resolve(strict=True), args.output.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Risk2Mac: {error}\n")
