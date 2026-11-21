"""Maintain chromatic packing and the independent cloud depth fallback."""

import copy
import hashlib
import re
import struct

import UnityPy
from UnityPy.helpers import CompressionHelper

from shader_programs import seq, sha
from third_party.entrytools import parse_code_entry, build_code_entry
from third_party.paramblob import parse_params_entry, build_params_entry

PARAM = "_ChromaticAberration_Amount"


def pack_chromatic_parameters(tree):
    tree = copy.deepcopy(tree)
    assert tree["platforms"] == [14], tree["platforms"]
    blob = bytes(tree["compressedBlob"])
    segments = [
        CompressionHelper.decompress_lz4(blob[o : o + n], z)
        for o, n, z in zip(
            seq(tree["offsets"][0]),
            seq(tree["compressedLengths"][0]),
            seq(tree["decompressedLengths"][0]),
        )
    ]
    count = struct.unpack_from("<I", segments[0])[0]
    entries = []
    for i in range(count):
        off, length, seg = struct.unpack_from("<III", segments[0], 4 + 12 * i)
        assert not length or off + length <= len(segments[seg])
        entries.append(bytes(segments[seg][off : off + length]))
    code_changes = {}
    param_changes = {}
    variants = 0
    for sub in tree["m_ParsedForm"]["m_SubShaders"]:
        for ps in sub["m_Passes"]:
            fragment = ps["progFragment"]
            for group_index, group in enumerate(fragment["m_PlayerSubPrograms"]):
                for variant_index, variant in enumerate(group):
                    pidx = fragment["m_ParameterBlobIndices"][group_index][variant_index]
                    params = parse_params_entry(entries[pidx])
                    found = [
                        (cb, v) for cb in params["cbs"] for v in cb["vec"] if v["name"] == PARAM
                    ]
                    if not found:
                        continue
                    assert len(found) == 1
                    cb, amount = found[0]
                    oldsize = cb["size"]
                    oldoff = amount["offset"]
                    assert cb["name"] == "$Globals" and oldsize in (688, 704)
                    assert oldoff in (572, 588) and oldoff == oldsize - 116
                    assert amount["dim"] == 1 and amount["arraySize"] == 0
                    assert variant["m_GpuProgramType"] == 24
                    code_index = variant["m_BlobIndex"]
                    change = (oldoff, oldsize)
                    assert code_index not in code_changes or code_changes[code_index] == change
                    code_changes[code_index] = change
                    amount["offset"] = oldsize
                    cb["size"] = oldsize + 16
                    newparams = build_params_entry(params)
                    assert pidx not in param_changes or param_changes[pidx] == newparams
                    param_changes[pidx] = newparams
                    variants += 1
    assert variants == 1152 and len(code_changes) == 1152, (variants, len(code_changes))
    for index, (oldoff, oldsize) in code_changes.items():
        code = parse_code_entry(entries[index])
        payload = code["payload"]
        assert code["type"] == 24
        start = payload.index(b"#include <metal_stdlib>")
        text = payload[start:].decode("utf-8")
        oldreg = oldoff // 16
        newreg = oldsize // 16
        assert oldoff % 16 == 12
        arrays = re.findall(r"float4 _m0\[(\d+)\];", text)
        assert len(arrays) == 1 and oldreg < int(arrays[0]) <= newreg, (
            index,
            "source array",
            arrays,
        )
        # vkd3d may trim the unused tail of the declared constant buffer.
        text, n = re.subn(r"float4 _m0\[\d+\];", "float4 _m0[" + str(newreg + 1) + "];", text)
        assert n == 1, (index, "array", n)
        pattern = r"cb0_0\._m0\[" + str(oldreg) + r"u\]\.(w+)\b"
        text, n = re.subn(
            pattern, lambda m: "cb0_0._m0[" + str(newreg) + "u]." + ("x" * len(m.group(1))), text
        )
        assert n == 1, (index, "read", n)
        assert not re.search(r"cb0_0\._m0\[" + str(oldreg) + r"u\]\.[xyzw]*w", text)
        replacement = payload[:start] + text.encode("utf-8")
        while len(replacement) % 4 != len(payload) % 4:
            replacement += b"\n"
        entries[index] = build_code_entry(
            code["type"], code["stats"], code["keywords"], replacement, code["trailing"]
        )
    for index, raw in param_changes.items():
        entries[index] = raw
    rebuilt = bytearray(4 + count * 12)
    struct.pack_into("<I", rebuilt, 0, count)
    for i, raw in enumerate(entries):
        struct.pack_into("<III", rebuilt, 4 + i * 12, len(rebuilt) if raw else 0, len(raw), 0)
        rebuilt.extend(raw)
    packed = CompressionHelper.compress_lz4(bytes(rebuilt))
    tree.update(
        offsets=[[0]],
        compressedLengths=[[len(packed)]],
        decompressedLengths=[[len(rebuilt)]],
        compressedBlob=packed,
    )
    return tree, {
        "fragment_variants": variants,
        "code_entries": len(code_changes),
        "parameter_entries": len(param_changes),
        "new_amount_offsets": [688, 704],
    }


SAFE_DEPTH_GUARD = b"""    const float4 safeState = cb0_0._m0[12u];
    bool safeValid = safeState.x > 0.5 && safeState.y == float(t5.get_width()) && safeState.z == float(t5.get_height());
    safeValid = safeValid && in.safePosition.x >= 0.0 && in.safePosition.y >= 0.0 && in.safePosition.x < safeState.y && in.safePosition.y < safeState.z;
    if (safeValid) {
        uint2 pixel = uint2(in.safePosition.xy);
        float opaqueDepth = t5.read(pixel).x;
        bool reversedZ = cb1_0._m0[7u].x > 0.0;
        const float epsilon = 0.000001;
        if ((reversedZ && in.safePosition.z + epsilon < opaqueDepth) || (!reversedZ && in.safePosition.z - epsilon > opaqueDepth)) discard_fragment();
    }
"""


def guard_cloud_depth(env):
    obj = next(
        x for x in env.objects if x.type.name == "Shader" and x.path_id == -15541403510422607
    )
    key = (obj.assets_file.name, obj.path_id, obj.type.name)
    before = {
        (x.assets_file.name, x.path_id, x.type.name): hashlib.sha256(x.get_raw_data()).hexdigest()
        for x in env.objects
        if (x.assets_file.name, x.path_id, x.type.name) != key
    }
    tree = obj.read_typetree()
    shader = tree["m_ParsedForm"]
    assert len(shader["m_SubShaders"]) == 1 and len(shader["m_SubShaders"][0]["m_Passes"]) == 1
    ps = shader["m_SubShaders"][0]["m_Passes"][0]
    program = ps["progFragment"]
    targets = {v["m_BlobIndex"] for tier in program["m_PlayerSubPrograms"] for v in tier}
    parameters = {v for tier in program["m_ParameterBlobIndices"] for v in tier}
    names = dict(ps["m_NameIndices"])
    safe_name = max(names.values()) + 1
    state_name = safe_name + 1
    ps["m_NameIndices"] += [("_RoR2SafeDepth", safe_name), ("_RoR2SafeDepthState", state_name)]
    ps["m_NameIndices"].sort(key=lambda x: x[0])
    common = program["m_CommonParameters"]
    assert max(x["m_Index"] for x in common["m_TextureParams"]) == 4
    common["m_TextureParams"].append(
        {
            "m_NameIndex": safe_name,
            "m_Index": 5,
            "m_SamplerIndex": 4,
            "m_MultiSampled": False,
            "m_Dim": 2,
        }
    )
    globals_cb = next(
        x for x in common["m_ConstantBuffers"] if x["m_NameIndex"] == names["$Globals"]
    )
    assert globals_cb["m_Size"] == 192
    globals_cb["m_Size"] = 208
    globals_cb["m_VectorParams"].append(
        {"m_NameIndex": state_name, "m_Index": 192, "m_ArraySize": 0, "m_Type": 0, "m_Dim": 4}
    )

    packed = bytes(tree["compressedBlob"])
    segments = [
        CompressionHelper.decompress_lz4(packed[o : o + n], z)
        for o, n, z in zip(
            tree["offsets"][0], tree["compressedLengths"][0], tree["decompressedLengths"][0]
        )
    ]
    count = struct.unpack_from("<i", segments[0], 0)[0]
    entries = [struct.unpack_from("<iii", segments[0], 4 + i * 12) for i in range(count)]
    result = bytearray(4 + 12 * count)
    struct.pack_into("<i", result, 0, count)
    guard = SAFE_DEPTH_GUARD
    changed = []
    for index, (offset, size, segment) in enumerate(entries):
        if not size:
            struct.pack_into("<iii", result, 4 + 12 * index, 0, 0, 0)
            continue
        payload = bytes(segments[segment][offset : offset + size])
        if index in parameters:
            metadata = parse_params_entry(payload)
            for cb in metadata["cbs"]:
                if cb["name"] == "$Globals":
                    assert cb["size"] <= 192
                    cb["size"] = 208
            payload = build_params_entry(metadata)
        if index in targets:
            assert struct.unpack_from("<i", payload, 4)[0] == 24
            pos = 24
            keywords = struct.unpack_from("<i", payload, pos)[0]
            pos += 4
            for _ in range(keywords):
                n = struct.unpack_from("<i", payload, pos)[0]
                pos = (pos + 4 + n + 3) & ~3
            n = struct.unpack_from("<i", payload, pos)[0]
            code = payload[pos + 4 : pos + 4 + n]
            cbtype = re.search(rb"constant (\w+)& cb0_0 \[\[buffer\(0\)\]\]", code).group(1)
            assert not re.search(rb"constant " + cbtype + rb"& cb1_0", code)
            pattern = rb"(struct " + cbtype + rb"\s*\{\s*float4 _m0\[)\d+(\];)"
            code, matches = re.subn(pattern, rb"\g<1>13\g<2>", code)
            assert matches == 1
            assert code.count(b"struct main0_in\n{") == 1
            code = code.replace(
                b"struct main0_in\n{", b"struct main0_in\n{\n    float4 safePosition [[position]];"
            )
            marker = b"texture2d<float> t4 [[texture(4)]]"
            assert code.count(marker) == 1
            code = code.replace(marker, marker + b", texture2d<float> t5 [[texture(5)]]")
            assert code.count(b"    main0_out out = {};") == 1
            code = code.replace(b"    main0_out out = {};", b"    main0_out out = {};\n" + guard)
            sample = b"r1 = t3.sample(s4, r1.xyxx.xy);"
            assert code.count(sample) == 1
            code = code.replace(
                sample,
                b"if (safeValid) { r1 = t5.sample(s4, r1.xyxx.xy); } else { " + sample + b" }",
            )
            while len(code) % 4 != n % 4:
                code += b"\n"
            payload = payload[:pos] + struct.pack("<i", len(code)) + code + payload[pos + 4 + n :]
            assert struct.unpack_from("<I", code, 0)[0] == 0xF00DCAFE
            changed.append(index)
        struct.pack_into("<iii", result, 4 + 12 * index, len(result), len(payload), 0)
        result.extend(payload)
    assert set(changed) == targets and len(changed) == 32
    compressed = CompressionHelper.compress_lz4(bytes(result))
    tree["offsets"] = [[0]]
    tree["compressedLengths"] = [[len(compressed)]]
    tree["decompressedLengths"] = [[len(result)]]
    tree["compressedBlob"] = compressed
    obj.save_typetree(tree)
    result = env.file.save(packer="lz4")
    check = UnityPy.load(result)
    after = {
        (x.assets_file.name, x.path_id, x.type.name): sha(x.get_raw_data())
        for x in check.objects
        if (x.assets_file.name, x.path_id, x.type.name) != key
    }
    if before != after:
        raise ValueError("Cloud depth rewrite changed another bundle object")
    return result
