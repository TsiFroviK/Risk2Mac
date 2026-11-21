"""Repack program bytes from local compiler output and Unity compute data."""

import hashlib
import re
import struct

from UnityPy.export.ShaderConverter import EndianBinaryReader, ShaderSubProgram
from UnityPy.helpers import CompressionHelper

from third_party.dxbc import SEM_CHAN, parse_container, parse_isgn

METAL_HEADER = struct.pack("<12I", 0xF00DCAFE, 48, 5, 60, 0, 0, 0, 0, 0, 5, 0xFFFFFFFF, 0)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def seq(value):
    return value if isinstance(value, list) else [value]


def extract_shader(obj, output):
    shader = obj.read()
    tree = obj.read_typetree()
    if list(shader.platforms) != [4]:
        return None
    compressed = bytes(shader.compressedBlob)
    segments = [
        CompressionHelper.decompress_lz4(compressed[offset : offset + length], size)
        for offset, length, size in zip(
            seq(shader.offsets[0]),
            seq(shader.compressedLengths[0]),
            seq(shader.decompressedLengths[0]),
        )
    ]
    count = struct.unpack_from("<i", segments[0], 0)[0]
    entries = [struct.unpack_from("<iii", segments[0], 4 + i * 12) for i in range(count)]
    variants = []
    payloads = {}
    for subshader in tree["m_ParsedForm"]["m_SubShaders"]:
        for shader_pass in subshader["m_Passes"]:
            for stage in ("Vertex", "Fragment", "Geometry", "Hull", "Domain", "RayTracing"):
                for group in (shader_pass.get("prog" + stage) or {}).get(
                    "m_PlayerSubPrograms"
                ) or []:
                    for choice in group:
                        index = choice.get("m_BlobIndex")
                        if index is None or not 0 <= index < count:
                            continue
                        offset, length, segment = entries[index]
                        if length <= 0:
                            continue
                        if index not in payloads:
                            payload = segments[segment][offset : offset + length]
                            program = ShaderSubProgram(EndianBinaryReader(payload, endian="<"))
                            if "DX11" not in program.m_ProgramType.name:
                                continue
                            code = bytes(program.m_ProgramCode)
                            start = code.find(b"DXBC")
                            if not 0 <= start <= 256:
                                raise ValueError("Invalid DXBC magic")
                            size = struct.unpack_from("<I", code, start + 24)[0]
                            if size < 32 or size > len(code) - start:
                                raise ValueError("Invalid DXBC size")
                            payloads[index] = code[start : start + size]
                        code = payloads[index]
                        variants.append(
                            {"stage": stage, "blob_index": index, "dxbc_sha256": sha(code)}
                        )
    if not variants or any(item["stage"] not in ("Vertex", "Fragment") for item in variants):
        return None
    for code in payloads.values():
        out = output / (sha(code) + ".dxbc")
        if not out.exists():
            out.write_bytes(code)
    return {"variants": variants}


def apply_compute_donor(obj, donors):
    tree = obj.read_typetree()
    name = tree["m_Name"]
    previous = tree["variants"][0]
    donor = donors[name]["variants"][0]
    if previous["targetRenderer"] != 2 or donor["targetRenderer"] != 16:
        raise ValueError("Unexpected compute program backends")

    def buffers(variant):
        sizes = {}
        for buffer in variant["constantBuffers"]:
            sizes[buffer["name"]] = max(sizes.get(buffer["name"], 0), len(buffer["params"]))
        return {
            buffer["name"]: (buffer["byteSize"], {p["name"]: p for p in buffer["params"]})
            for buffer in variant["constantBuffers"]
            if len(buffer["params"]) == sizes[buffer["name"]]
        }

    previous_buffers = buffers(previous)
    donor_buffers = buffers(donor)
    if name == "MultiScaleVORender":
        donor_size, donor_fields = donor_buffers["CB1"]
        if donor_size != 120 or previous_buffers["CB1"] != (128, donor_fields):
            raise ValueError("Unexpected volumetric shader constant buffer layout")
        donor_buffers["CB1"] = (128, donor_fields)
    if previous_buffers != donor_buffers:
        raise ValueError("Donor constant buffers differ")

    new_kernels = {kernel["name"]: kernel for kernel in donor["kernels"]}
    if len(new_kernels) != len(previous["kernels"]):
        raise ValueError("Donor kernel count differs")

    def resources(variant):
        return sorted(
            (kind, entry["name"], entry["texDimension"])
            for kind in ("cbs", "textures", "inBuffers", "outBuffers")
            for entry in variant[kind]
        )

    kernels = []
    for old in previous["kernels"]:
        new = new_kernels[old["name"]]
        old_variants = dict(old["variantMap"])
        new_variants = {key: new["uniqueVariants"][index] for key, index in new["variantIndices"]}
        if old_variants.keys() != new_variants.keys():
            raise ValueError("Donor kernel variant keys differ")
        for key, variant in new_variants.items():
            old_variant = old_variants[key]
            if (
                name not in ("AutoExposure", "ExposureHistogram")
                and variant["threadGroupSize"] != old_variant["threadGroupSize"]
            ):
                raise ValueError("Donor kernel thread group size differs")
            if resources(variant) != resources(old_variant):
                raise ValueError("Donor kernel resources differ")
        kernels.append(
            {
                "name": old["name"],
                "variantMap": list(new_variants.items()),
                "globalKeywords": old["globalKeywords"],
                "localKeywords": old["localKeywords"],
            }
        )
    tree["variants"] = [
        {
            "targetRenderer": donor["targetRenderer"],
            "targetLevel": donor["targetLevel"],
            "kernels": kernels,
            "constantBuffers": donor["constantBuffers"],
            "resourcesResolved": donor["resourcesResolved"],
        }
    ]
    obj.save_typetree(tree)


def convert_shader(obj, item, dxbc_directory, metal_directory):
    shader = obj.read()
    tree = obj.read_typetree()
    if any(v["stage"] not in ("Vertex", "Fragment") for v in item["variants"]):
        raise ValueError("Geometry/tessellation shader needs separate Metal adaptation")
    segments = [
        CompressionHelper.decompress_lz4(bytes(shader.compressedBlob)[o : o + n], z)
        for o, n, z in zip(
            seq(shader.offsets[0]),
            seq(shader.compressedLengths[0]),
            seq(shader.decompressedLengths[0]),
        )
    ]
    count = struct.unpack_from("<i", segments[0], 0)[0]
    entries = [struct.unpack_from("<iii", segments[0], 4 + i * 12) for i in range(count)]
    targets = {}
    for v in item["variants"]:
        identity = (v["dxbc_sha256"], v["stage"])
        idx = v["blob_index"]
        if idx in targets and targets[idx] != identity:
            raise ValueError("Conflicting shader blob index")
        targets[idx] = identity
    result = bytearray(4 + 12 * count)
    struct.pack_into("<i", result, 0, count)
    for i, (off, length, segment) in enumerate(entries):
        if not length:
            struct.pack_into("<iii", result, 4 + 12 * i, 0, 0, 0)
            continue
        if (
            segment < 0
            or segment >= len(segments)
            or off < 0
            or off + length > len(segments[segment])
        ):
            raise ValueError("Invalid program bounds")
        payload = bytearray(segments[segment][off : off + length])
        if i in targets:
            sha, stage = targets[i]
            version, kind = struct.unpack_from("<ii", payload, 0)
            if version != 202012090 or kind not in ((15, 16) if stage == "Vertex" else (17, 18)):
                raise ValueError("Unexpected GPU program header")
            struct.pack_into("<i", payload, 4, 23 if stage == "Vertex" else 24)
            pos = 24
            kw = struct.unpack_from("<i", payload, pos)[0]
            pos += 4
            if kw < 0 or kw > 4096:
                raise ValueError("Invalid keyword count")
            for _ in range(kw):
                n = struct.unpack_from("<i", payload, pos)[0]
                pos = (pos + 4 + n + 3) & ~3
            old_len = struct.unpack_from("<i", payload, pos)[0]
            if old_len < 1 or pos + 4 + old_len > len(payload):
                raise ValueError("Invalid program code length")
            metal = metal_directory / (sha + ".metal")
            dxbc = dxbc_directory / (sha + ".dxbc")
            msl = metal.read_text(encoding="utf8")
            msl, n = re.subn(r"\bmain0\b", "xlatMtlMain", msl)
            if not n:
                raise ValueError("Missing Metal shader entry")
            code = METAL_HEADER + b"xlatMtlMain\0" + msl.encode("utf8")
            while len(code) % 4 != old_len % 4:
                code += b"\n"
            trailing = payload[pos + 4 + old_len :]
            if len(trailing) < 8:
                raise ValueError("Missing Unity channel table")
            if stage == "Vertex":
                pad = len(trailing) % 4
                mask, pair_count = struct.unpack_from("<II", trailing, pad)
                if len(trailing) != pad + 8 + 8 * pair_count:
                    raise ValueError("Invalid Unity channel table")
                attrs = {
                    int(r): int(a)
                    for r, a in re.findall(r"\bv(\d+)\s*\[\[\s*attribute\((\d+)\)\s*\]\]", msl)
                }
                chunks = parse_container(dxbc.read_bytes())
                signature = parse_isgn(chunks[b"ISGN"])
                pairs = []
                remaining = set(attrs)
                for (semantic, semidx), reg in signature.items():
                    if reg not in attrs:
                        continue
                    channel = SEM_CHAN.get((semantic, semidx))
                    if channel is None:
                        raise ValueError(f"Unsupported vertex semantic {semantic}{semidx}")
                    pairs.append((channel, attrs[reg] + 13))
                    remaining.discard(reg)
                    mask |= 1 << channel
                if remaining:
                    raise ValueError(f"Unmapped vertex registers {remaining}")
                pairs.sort(key=lambda x: x[1])
                trailing = (
                    trailing[:pad]
                    + struct.pack("<II", mask, len(pairs))
                    + b"".join(struct.pack("<II", *x) for x in pairs)
                )
            payload = payload[:pos] + struct.pack("<i", len(code)) + code + trailing
        struct.pack_into("<iii", result, 4 + 12 * i, len(result), len(payload), 0)
        result.extend(payload)
    packed = CompressionHelper.compress_lz4(bytes(result))
    tree["platforms"] = [14]
    tree["offsets"] = [[0]]
    tree["compressedLengths"] = [[len(packed)]]
    tree["decompressedLengths"] = [[len(result)]]
    tree["compressedBlob"] = packed
    changed = 0
    for sub in tree["m_ParsedForm"]["m_SubShaders"]:
        for ps in sub["m_Passes"]:
            for stage in ("Vertex", "Fragment", "Geometry", "Hull", "Domain", "RayTracing"):
                for group in (ps.get("prog" + stage) or {}).get("m_PlayerSubPrograms", []):
                    for choice in group:
                        if choice.get("m_BlobIndex") in targets:
                            kind = choice.get("m_GpuProgramType")
                            if kind in (15, 16):
                                choice["m_GpuProgramType"] = 23
                            elif kind in (17, 18):
                                choice["m_GpuProgramType"] = 24
                            else:
                                raise ValueError("Unexpected serialized GPU type")
                            changed += 1
    if changed != len(item["variants"]):
        raise ValueError(f'Variant count differs: {changed} vs {len(item["variants"])}')
    return tree
