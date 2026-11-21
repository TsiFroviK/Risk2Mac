"""Generate the reviewed startup settings from matching Windows Unity metadata."""

from __future__ import annotations

import json
from pathlib import Path


# The Unity Editor writes a fresh build identifier for each player build.
# Keep the identifier belonging to the reviewed native startup files.
MAC_BUILD_GUID = "b48044e9a7e343cdbcd1bf9b7f168c98"


def initializer_index(initializers, assembly, class_name, method):
    matches = [
        index
        for index, entry in enumerate(initializers)
        if (entry["assemblyName"], entry["className"], entry["methodName"])
        == (assembly, class_name, method)
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one Unity startup initializer for {assembly}.{class_name}.{method}")
    return matches[0]


def runtime_initializers(raw: bytes) -> bytes:
    document = json.loads(raw)
    initializers = document["root"]
    moved = [
        initializers.pop(initializer_index(initializers, *identity))
        for identity in (
            ("Unity.Collections", "$BurstDirectCallInitializer", "Initialize"),
            ("Unity.MemoryProfiler", "MetadataInjector", "PlayerInitMetadata"),
        )
    ]
    del initializers[initializer_index(initializers, "Rewired_Android", "AndroidUnityInputHelper", "Initialize")]
    index = initializer_index(initializers, "Unity.RenderPipelines.Core.Runtime", "DebugUpdater", "RuntimeInit")
    initializers[index:index] = [
        {
            "assemblyName": "RoR2Arm64.ManagedSolo",
            "nameSpace": "RoR2Arm64",
            "className": "ManagedSoloBootstrap",
            "methodName": "Install",
            "loadTypes": 4,
            "isUnityClass": False,
        },
        *moved,
    ]
    return (json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\r\n").encode("utf-8")


def boot_configuration(raw: bytes) -> bytes:
    settings = dict(row.split("=", 1) for row in raw.decode("ascii").splitlines())
    return (
        "gfx-threading-mode=4\n"
        f"wait-for-native-debugger={settings['wait-for-native-debugger']}\n"
        f"hdr-display-enabled={settings['hdr-display-enabled']}\n"
        f"build-guid={MAC_BUILD_GUID}\n"
    ).encode("ascii")


def transform_startup(name: str, source: Path) -> bytes:
    """Transform one Windows file already verified against the asset manifest."""
    if name == "RuntimeInitializeOnLoads.json":
        return runtime_initializers(source.read_bytes())
    if name == "boot.config":
        return boot_configuration(source.read_bytes())
    raise ValueError(f"Unsupported Unity startup file: {name}")
