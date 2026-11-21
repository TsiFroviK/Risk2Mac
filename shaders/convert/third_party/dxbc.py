"""DXBC metadata helpers from Andreansx. See LICENSE in this directory."""
import struct

def parse_container(dxbc):
    assert dxbc[:4] == b"DXBC", dxbc[:4]
    nch = struct.unpack_from("<I", dxbc, 28)[0]
    offs = struct.unpack_from(f"<{nch}I", dxbc, 32)
    chunks = {}
    for o in offs:
        four = dxbc[o:o+4]
        size = struct.unpack_from("<I", dxbc, o+4)[0]
        chunks[four] = dxbc[o+8:o+8+size]
    return chunks

CHAN_SEM = {0: ("POSITION", 0), 1: ("NORMAL", 0), 2: ("TANGENT", 0), 3: ("COLOR", 0),
            4: ("TEXCOORD", 0), 5: ("TEXCOORD", 1), 6: ("TEXCOORD", 2), 7: ("TEXCOORD", 3),
            8: ("TEXCOORD", 4), 9: ("TEXCOORD", 5), 10: ("TEXCOORD", 6), 11: ("TEXCOORD", 7)}

def parse_isgn(data):
    cnt = struct.unpack_from("<I", data, 0)[0]
    out = {}
    for i in range(cnt):
        noff, semidx, _, _, reg, _ = struct.unpack_from("<6I", data, 8 + i * 24)
        name = data[noff:data.index(b"\0", noff)].decode()
        out[(name.upper(), semidx)] = reg
    return out

SEM_CHAN = {v: k for k, v in CHAN_SEM.items()}
