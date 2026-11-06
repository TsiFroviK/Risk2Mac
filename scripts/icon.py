"""Extract the known Windows build's icon locally, without a bundled image."""

import hashlib
import struct
import zlib


EXE_HASH = "0c34bfeefa1cbe8b38bdb99637ef1225835bf3b3b47a3996d76138662b8ab5e1"
# The offsets are PE resource locations in the exact source hash above.
FRAMES = ((16, 648144, b"icp4"), (32, 641440, b"icp5"), (64, 614864, b"icp6"),
          (128, 509184, b"ic07"), (256, 86704, b"ic08"))


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def dib_to_png(executable, offset, width):
    size, w, h, planes, bits, compression = struct.unpack_from("<IiiHHI", executable, offset)
    if (size, w, h, planes, bits, compression) != (40, width, width * 2, 1, 32, 0):
        raise ValueError("The Windows icon does not match the expected 32-bit DIB format.")
    stride = width * 4
    pixels = executable[offset + size:offset + size + stride * width]
    rows = bytearray()
    for row in range(width - 1, -1, -1):
        rows.append(0)
        start = row * stride
        for column in range(start, start + stride, 4):
            blue, green, red, alpha = pixels[column:column + 4]
            rows.extend((red, green, blue, alpha))
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, width, 8, 6, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(rows, 9)) + png_chunk(b"IEND", b""))


def install_icon(source, output):
    if not source.is_file() or source.stat().st_size != 653824:
        return False
    executable = source.read_bytes()
    if hashlib.sha256(executable).hexdigest() != EXE_HASH:
        return False
    chunks = bytearray()
    for width, offset, kind in FRAMES:
        png = dib_to_png(executable, offset, width)
        chunks.extend(kind + struct.pack(">I", len(png) + 8) + png)
    output.write_bytes(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)
    return True
