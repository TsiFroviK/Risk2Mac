"""Re-encode supported Wwise 150 banks as Wwise 154 using a local wwiser parser."""

from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import subprocess
import sys


WWISER_COMMIT = "08e937b649bc7007c234bbd59e34a41d5eef3b38"
REFERENCE_ENV_SHA256 = "9578357c5542aa43a58cec5188d9589b166ed68f021c4cd8c72de0e590cf8b13"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def chunks(raw):
    offset = 0
    while offset < len(raw):
        require(offset + 8 <= len(raw), "Truncated bank chunk header")
        tag, size = struct.unpack_from("<4sI", raw, offset)
        end = offset + 8 + size
        require(end <= len(raw), f"Truncated bank chunk: {tag!r}")
        yield tag, offset, raw[offset + 8 : end]
        offset = end


def walk(node):
    yield node
    for child in node.get_children() or []:
        yield from walk(child)


def field(node, name):
    return next(child for child in node.get_children() or [] if child.get_name() == name)


def apply_edits(start, payload, edits):
    parts = []
    cursor = start
    for offset, size, replacement in sorted(edits):
        require(
            start <= offset and cursor <= offset and offset + size <= start + len(payload),
            f"Invalid bank edit at byte {offset}",
        )
        parts.extend((payload[cursor - start : offset - start], replacement))
        cursor = offset + size
    parts.append(payload[cursor - start :])
    return b"".join(parts)


class BankConverter:
    def __init__(self, checkout: Path):
        checkout = checkout.resolve(strict=True)
        git = ["git", "-C", str(checkout)]
        commit = subprocess.check_output(
            [*git, "rev-parse", "HEAD"], text=True
        ).strip()
        changes = subprocess.check_output(
            [*git, "status", "--porcelain", "--untracked-files=all"], text=True
        ).strip()
        require(
            commit == WWISER_COMMIT and not changes,
            f"Use a clean wwiser checkout at {WWISER_COMMIT}: {checkout}",
        )
        require(
            (checkout / "wwiser" / "parser" / "wparser.py").is_file(),
            f"wwiser parser missing in checkout: {checkout}",
        )
        sys.path.insert(0, str(checkout))
        from wwiser.parser import wdefs, wmodel, wparser

        self.wdefs = wdefs
        self.wmodel = wmodel
        self.wparser = wparser
        self.property_ids = {name: number for number, name in wdefs.AkPropID_154.enum.items()}

    def parse(self, path, version):
        parser = self.wparser.Parser()
        require(parser.parse_bank(str(path)), f"Cannot parse bank: {path.name}")
        banks = parser.get_banks()
        require(len(banks) == 1, f"Expected one bank: {path.name}")
        bank = banks[0]
        require(bank.get_version() == version, f"Expected Wwise {version}: {path.name}")
        require(
            bank.get_error_count() == 0 and bank.get_skip_count() == 0,
            f"Unsupported bank data: {path.name}",
        )
        return bank

    def convert(self, path: Path) -> bytes:
        old = path.read_bytes()
        bank = self.parse(path, 150)
        edits = []
        for node in walk(bank):
            if isinstance(node, self.wmodel.NodeField):
                fmt = getattr(node, "_NodeField__fmt")
                if fmt is self.wdefs.AkPropID_150:
                    name = fmt.get(node.value())
                    require(name in self.property_ids, f"Unmapped bank property: {name}")
                    require(node.get_attr("type") == "u8", f"Unexpected property format: {name}")
                    number = self.property_ids[name]
                    if number != node.value():
                        edits.append((node.get_attr("offset"), 1, bytes([number])))
            if node.get_name() == "AkMediaInformation":
                media = field(node, "sourceID").value() & 0xFFFFFFFF
                offset = field(node, "uInMemoryMediaSize").get_attr("offset")
                edits.append((offset, 0, struct.pack("<I", media)))
            if node.get_name() == "AkTrackSrcInfo":
                source = field(node, "sourceID")
                media = source.value() & 0xFFFFFFFF
                edits.append((source.get_attr("offset") + 4, 0, struct.pack("<I", media)))
            if node.get_name() == "MusicTrackInitialValues":
                flags = field(node, "uFlags")
                target = field(node, "numPlaylistItem").get_attr("offset")
                edits.append((flags.get_attr("offset"), 1, b""))
                edits.append((target, 0, bytes([flags.value()])))
            if node.get_name() == "AkSwitchNodeParams":
                fields = [child for child in node.get_children() or [] if child.get_name() == "byBitVector"]
                require(len(fields) == 2 and fields[1].value() == 1, "Unknown legacy switch mode")
                edits.append((fields[1].get_attr("offset"), 1, b""))

        parts = []
        consumed = set()
        for tag, offset, body in chunks(old):
            require(
                tag in {b"BKHD", b"INIT", b"STMG", b"HIRC", b"ENVS", b"PLAT", b"DIDX", b"DATA", b"STID"},
                f"Unknown bank chunk: {tag!r}",
            )
            if tag == b"BKHD":
                body = struct.pack("<I", 154) + body[4:]
            elif tag == b"HIRC":
                count = struct.unpack_from("<I", body)[0]
                cursor = 4
                objects = [struct.pack("<I", count)]
                for _ in range(count):
                    kind, size = struct.unpack_from("<BI", body, cursor)
                    require(1 <= kind <= 22, f"Unsupported bank object type: {kind}")
                    start = offset + 8 + cursor + 5
                    subset = [edit for edit in edits if start <= edit[0] < start + size]
                    obj = body[cursor + 5 : cursor + 5 + size]
                    require(len(obj) == size, "Truncated bank object")
                    obj = apply_edits(start, obj, subset)
                    consumed.update(edit[0] for edit in subset)
                    objects.extend((struct.pack("<BI", kind, len(obj)), obj))
                    cursor += 5 + size
                require(cursor == len(body), "Unexpected trailing bytes in bank objects")
                body = b"".join(objects)
            elif tag == b"ENVS":
                body += body
                require(
                    hashlib.sha256(body).hexdigest() == REFERENCE_ENV_SHA256,
                    "Unknown obstruction/occlusion curve layout",
                )
            parts.extend((tag, struct.pack("<I", len(body)), body))
        require(consumed == {edit[0] for edit in edits}, "Bank edit outside an object")
        return b"".join(parts)
