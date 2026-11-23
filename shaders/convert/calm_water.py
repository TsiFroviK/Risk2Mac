"""Recover the non-tessellated forward variants used by the three Moon water materials."""

import struct

from UnityPy.helpers import CompressionHelper

from third_party.entrytools import build_code_entry, parse_code_entry


def program_entries(tree):
    if tree["platforms"] != [4] or tree["offsets"] != [[0]] or len(tree["decompressedLengths"][0]) != 1:
        raise ValueError("Unexpected Windows water program layout")
    blob = CompressionHelper.decompress_lz4(bytes(tree["compressedBlob"]), tree["decompressedLengths"][0][0])
    count = struct.unpack_from("<I", blob)[0]
    entries = []
    for index in range(count):
        start, size, segment = struct.unpack_from("<III", blob, 4 + 12 * index)
        if segment or start + size > len(blob):
            raise ValueError("Invalid water program entry")
        entries.append(blob[start:start + size])
    return entries


def forward_pass(tree):
    passes = [p for sub in tree["m_ParsedForm"]["m_SubShaders"] for p in sub["m_Passes"] if p["m_State"]["m_Name"] == "FORWARD"]
    if len(passes) != 1:
        raise ValueError("Expected one forward water pass")
    return passes[0]


def restore_moon_water(source, fallback):
    """Add exact no-depth-fog selectors. Keep the non-tessellated fallback vertex path."""
    original = source.read_typetree()
    tree = fallback.read_typetree()
    names = tree["m_ParsedForm"]["m_KeywordNames"]
    if original["m_ParsedForm"]["m_KeywordNames"] != names:
        raise ValueError("Water shader keyword indices differ")
    src, dst = forward_pass(original), forward_pass(tree)
    originals, entries = program_entries(original), program_entries(tree)
    required = {names.index(k) for k in ("_BUMPLARGE_ON", "_REFLECTIONTYPE_CUBEMAP", "_FOAM_ON")}
    quality = {names.index(k) for k in ("_DISTORTIONQUALITY_HIGH", "_DISTORTIONQUALITY_LOW")}
    fog = names.index("_DEPTHFOG_ON")
    for stage, expected in (("Vertex", 64), ("Fragment", 32)):
        src_program = src["prog" + stage]
        dst_program = dst["prog" + stage]
        added = 0
        for group, choices in enumerate(dst_program["m_PlayerSubPrograms"]):
            if not choices:
                continue
            source_by_key = {tuple(v["m_KeywordIndices"]): v for v in src_program["m_PlayerSubPrograms"][group]}
            params = dst_program["m_ParameterBlobIndices"][group]
            variants, bindings = [], []
            for choice, param in zip(choices, params):
                keys = choice["m_KeywordIndices"]
                if fog in keys and required.issubset(keys) and quality.intersection(keys):
                    exact = tuple(key for key in keys if key != fog)
                    donor = source_by_key[exact]
                    if stage == "Vertex":
                        # In the original pair the depth-fog keyword changes only the fragment.
                        code = parse_code_entry(entries[choice["m_BlobIndex"]])
                        keywords = [k for k in code["keywords"] if k != "_DEPTHFOG_ON"]
                        raw = build_code_entry(code["type"], code["stats"], keywords, code["payload"], code["trailing"])
                        gpu_type = choice["m_GpuProgramType"]
                    else:
                        # Exact source fragment and the nearest fallback have the same stage
                        # interface and effective texture/sampler/constant bindings.
                        raw = originals[donor["m_BlobIndex"]]
                        gpu_type = donor["m_GpuProgramType"]
                    variants.append({**choice, "m_KeywordIndices": list(exact), "m_BlobIndex": len(entries),
                                     "m_GpuProgramType": gpu_type})
                    entries.append(raw)
                    bindings.append(param)
                    added += 1
                variants.append(choice)
                bindings.append(param)
            dst_program["m_PlayerSubPrograms"][group] = variants
            dst_program["m_ParameterBlobIndices"][group] = bindings
        if added != expected:
            raise ValueError(f"Unexpected number of restored water {stage} variants: {added}")

    blob = bytearray(4 + 12 * len(entries))
    struct.pack_into("<I", blob, 0, len(entries))
    for i, raw in enumerate(entries):
        struct.pack_into("<III", blob, 4 + 12 * i, len(blob) if raw else 0, len(raw), 0)
        blob.extend(raw)
    packed = CompressionHelper.compress_lz4(bytes(blob))
    tree.update(compressedBlob=packed, compressedLengths=[[len(packed)]], decompressedLengths=[[len(blob)]])
    fallback.save_typetree(tree)
