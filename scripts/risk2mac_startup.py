"""Generate the reviewed startup settings from matching Windows Unity metadata."""

from __future__ import annotations

import json
from pathlib import Path


# The Unity Editor writes a fresh build identifier for each player build.
# Keep the identifier belonging to the reviewed native startup files.
MAC_BUILD_GUID = "b48044e9a7e343cdbcd1bf9b7f168c98"

# The recovered Unity 2023 player has a different ordering for user scripts.
# Indexes refer to the pinned Windows ScriptingAssemblies.json, keeping that
# file's assembly names local. The named slots are new to the reviewed build.
SCRIPT_ORDER = (
    68, "Unity.AI.Navigation.dll", "RoR2Arm64.OfflinePlatform.dll", 97, 89, 120, 100,
    "RoR2Arm64.ManagedSolo.dll", 93, 73, 104, 78, 75, 115, 117, 74, 113, 90, 122,
    112, 103, 76, 98, 110, 72, 96, 92, 116, 84, 86, 111, 119, 94, 107, 79, 105,
    85, 108, 88, 80, 81, 99, 70, 69, 118, 109, 101, 87, 106, 123, 95, 121, 77,
    82, 102, 49, 91, 71, 114, 83, "System.Runtime.CompilerServices.Unsafe.dll",
)
ADDED_ENGINE_MODULES = {
    11: "UnityEngine.CommandStateObserverModule.dll",
    12: "UnityEngine.ContentLoadModule.dll",
    19: "UnityEngine.GraphToolsFoundationModule.dll",
    28: "UnityEngine.MarshallingModule.dll",
    34: "UnityEngine.PropertiesModule.dll",
}
REMOVED_ENGINE_MODULES = {"UnityEngine.NVIDIAModule.dll", "UnityEngine.UIElementsNativeModule.dll"}


def scripting_assemblies(raw: bytes) -> bytes:
    document = json.loads(raw)
    names = document["names"]
    scripts = [names[slot] if isinstance(slot, int) else slot for slot in SCRIPT_ORDER]
    engine = [name for name, kind in zip(names, document["types"])
              if kind == 2 and name not in REMOVED_ENGINE_MODULES and name not in scripts]
    for position, name in ADDED_ENGINE_MODULES.items():
        engine.insert(position, name)
    result = {"names": engine + scripts, "types": [2] * len(engine) + [16] * len(scripts)}
    return json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
    if name == "ScriptingAssemblies.json":
        return scripting_assemblies(source.read_bytes())
    if name == "boot.config":
        return boot_configuration(source.read_bytes())
    raise ValueError(f"Unsupported Unity startup file: {name}")
