"""Verify the Unity version and cross-file script bindings in a rebuilt startup scene."""

import hashlib
from pathlib import Path
import sys

import UnityPy

from risk2mac_startup_project import DATA_FILES
from risk2mac_unity import VERSION


PORT_SCRIPTS = {"RoR2Arm64.ManagedSolo.dll", "RoR2Arm64.OfflinePlatform.dll", "Risk2Mac.Steam.dll"}
# Build 25921972 adds RoR2.Items.IgnoreMapZonesUntilRemovalBehavior to the Mac script table.
STOCK_SCRIPTS_SHA256 = "009b0639aea7fd753d726a1f70406c7b1174ff519ce03a3020fdbc430624fec0"


def script_identity(record):
    data = record.read_typetree(check_read=False)
    return (data["m_AssemblyName"], data["m_Namespace"], data["m_ClassName"])


def check_output(folder):
    sizes = (18, None, 247, 1852, 163)
    files = {}
    for name, count in zip(DATA_FILES, sizes):
        asset = UnityPy.load(str(folder / name)).file
        if asset.unity_version != VERSION or asset.target_platform != 2 or (
            count is not None and len(asset.objects) != count
        ):
            raise ValueError(f"Unexpected Unity macOS startup serialization for {name}")
        files[name] = asset

    managers = files["globalgamemanagers"]
    scripts = files["globalgamemanagers.assets"]
    by_type = {record.type.name: record for record in managers.objects.values()}
    player = by_type["PlayerSettings"].read_typetree(check_read=False)
    if player["productName"] != "Risk of Rain 2":
        raise ValueError("The rebuilt startup project has unexpected player settings")

    identities = {
        record.path_id: script_identity(record)
        for record in scripts.objects.values() if record.type.name == "MonoScript"
    }
    stock = sorted(identity for identity in identities.values() if identity[0] not in PORT_SCRIPTS)
    names = "".join("\0".join(identity) + "\n" for identity in stock).encode("utf-8")
    if hashlib.sha256(names).hexdigest() != STOCK_SCRIPTS_SHA256:
        raise ValueError("The rebuilt startup project has an unexpected Unity script inventory")
    required = {
        ("RoR2Arm64.ManagedSolo.dll", "RoR2Arm64", "GraphicsCompatibility"),
        ("RoR2Arm64.OfflinePlatform.dll", "RoR2Arm64.Offline", "OfflineNetworkManager"),
    }
    if not required.issubset(identities.values()):
        raise ValueError("The rebuilt startup project is missing Risk2Mac's platform components")

    for name in DATA_FILES[2:]:
        asset = files[name]
        externals = [item.path for item in asset.externals]
        manager_index = externals.index("globalgamemanagers.assets") + 1
        for record in asset.objects.values():
            if record.type.name != "MonoBehaviour":
                continue
            pointer = record.read_typetree(check_read=False)["m_Script"]
            if pointer["m_FileID"] == manager_index and pointer["m_PathID"] not in identities:
                raise ValueError(f"Missing script for Unity object {record.path_id} in {name}")
    print("Verified the rebuilt Unity startup scene and shared script references", flush=True)


if __name__ == "__main__":
    check_output(Path(sys.argv[1]))
