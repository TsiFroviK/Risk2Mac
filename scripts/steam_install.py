"""Find local Steam libraries and register the Risk2Mac library shortcut."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import tempfile
import zlib


APP_ID = "632360"
APP_BUNDLE = "Risk of Rain 2.app"
GAME_DIR = "Risk of Rain 2"
SHORTCUT_NAME = "Risk of Rain 2 (Risk2Mac)"
PLAY_SHORTCUT_HINT = f'In the Steam Library, play the Risk2Mac shortcut ("{SHORTCUT_NAME}" by default).'
SHORTCUT_HEADER = b"\x00shortcuts\0"
VDF_LIMIT = 8 * 1024 * 1024
STEAM_ID_BASE = 76561197960265728
KV_TOKEN = re.compile(r'\s+|//[^\r\n]*|"(?:[^"\\]|\\.)*"|[{}]|[^"\s{}]+')


def steam_root():
    return (Path.home() / "Library/Application Support/Steam").resolve()


def read_small(path):
    with path.open("rb") as file:
        data = file.read(VDF_LIMIT + 1)
    if len(data) > VDF_LIMIT:
        raise ValueError(f"Steam configuration exceeds the supported size: {path.name}")
    return data


def parse_keyvalues(data):
    """Read Steam's text KeyValues files without treating their values as paths or commands."""
    tokens = iter(token for token in KV_TOKEN.findall(data) if not token.isspace() and not token.startswith("//"))

    def string(token):
        if token.startswith('"'):
            return re.sub(r'\\([\\"])', r'\1', token[1:-1])
        return token

    def node(nested=False, depth=0):
        result = {}
        if depth > 16:
            raise ValueError("Steam configuration is nested too deeply")
        for key in tokens:
            if key == "}" and nested:
                return result
            if key in ("{", "}"):
                raise ValueError("Invalid Steam configuration key")
            value = next(tokens, None)
            if value is None or value == "}":
                raise ValueError("Missing Steam configuration value")
            result[string(key).casefold()] = node(True, depth + 1) if value == "{" else string(value)
        if nested:
            raise ValueError("Incomplete Steam configuration")
        return result

    return node()


def read_keyvalues(path):
    return parse_keyvalues(read_small(path).decode("utf-8-sig"))


def libraries(root):
    """Return registered library roots and which one Steam associates with RoR2."""
    if not (root / "steamapps").is_dir():
        raise ValueError("Open the native Steam client at least once before building with Steam integration.")
    result = {root.resolve(): False}
    settings = root / "steamapps/libraryfolders.vdf"
    if settings.is_file():
        folders = read_keyvalues(settings).get("libraryfolders", {})
        if not isinstance(folders, dict):
            raise ValueError("Invalid Steam library list")
        for key, entry in folders.items():
            if not key.isdecimal():
                continue
            path = entry.get("path") if isinstance(entry, dict) else entry
            apps = entry.get("apps") if isinstance(entry, dict) else None
            if isinstance(path, str) and Path(path).is_absolute():
                resolved = Path(path).resolve()
                if (resolved / "steamapps").is_dir():
                    result[resolved] = isinstance(apps, dict) and APP_ID in apps
    return result


def install_destination(root, selected=None):
    registered = libraries(root)
    if selected is None:
        selected = next((path for path, has_game in registered.items() if has_game), root.resolve())
    else:
        selected = selected.expanduser().resolve()
        if selected not in registered:
            raise ValueError(f"Choose a library root already registered in Steam Settings → Storage: {selected}")
    steamapps = selected / "steamapps"
    directory_name = GAME_DIR
    manifest = steamapps / f"appmanifest_{APP_ID}.acf"
    if manifest.is_file():
        appstate = read_keyvalues(manifest).get("appstate", {})
        if isinstance(appstate, dict) and appstate.get("appid") == APP_ID:
            directory_name = appstate.get("installdir", GAME_DIR)
    if not isinstance(directory_name, str) or directory_name in ("", ".", "..") or any(c in directory_name for c in "/\\\0"):
        raise ValueError("Invalid Risk of Rain 2 folder in the Steam manifest")
    common = steamapps / "common"
    game = common / directory_name
    output = game / APP_BUNDLE
    if any(path.is_symlink() for path in (steamapps, common, game, output)):
        raise ValueError("The Steam game destination must be a real directory inside the registered library")
    return output


def parse_shortcuts(data):
    """Index the existing records while preserving their original bytes for insertion."""
    if not data.startswith(SHORTCUT_HEADER):
        raise ValueError("Unrecognized Steam shortcuts file")
    offset = len(SHORTCUT_HEADER)

    def read_string():
        nonlocal offset
        end = data.index(0, offset)
        value = data[offset:end]
        offset = end + 1
        return value

    def read_fields(depth):
        nonlocal offset
        result = {}
        if depth > 8:
            raise ValueError("Steam shortcuts file is nested too deeply")
        while offset < len(data):
            kind = data[offset]
            offset += 1
            if kind == 8:
                return result
            name = read_string().lower()
            if name in result:
                raise ValueError("Duplicate key in Steam shortcuts")
            if kind == 0:
                result[name] = read_fields(depth + 1)
            elif kind == 1:
                result[name] = read_string()
            elif kind in (2, 3, 4, 6, 7):
                size = 8 if kind == 7 else 4
                if offset + size > len(data):
                    raise ValueError("Truncated Steam shortcuts record")
                result[name] = struct.unpack_from("<I" if size == 4 else "<Q", data, offset)[0]
                offset += size
            else:
                raise ValueError(f"Unsupported Steam shortcut field type {kind}")
        raise ValueError("Incomplete Steam shortcuts record")

    records = read_fields(0)
    if data[offset:] != b"\x08" or any(not key.isdigit() or not isinstance(fields, dict) for key, fields in records.items()):
        raise ValueError("Unexpected Steam shortcuts file format")
    return records, offset - 1


def with_shortcut(data, app):
    records, insertion = parse_shortcuts(data)
    title = SHORTCUT_NAME.encode("utf-8")
    # Steam's app bundle target retains native architecture selection on macOS.
    executable = f'"{app}"'.encode("utf-8")
    other_targets = (executable.strip(b'"'), os.fsencode(app / "Contents/MacOS/Risk of Rain 2"))
    if any(isinstance(fields.get(b"exe"), bytes) and fields[b"exe"].strip(b'"') in other_targets for fields in records.values()):
        return data
    app_id = zlib.crc32(executable + title) | 0x80000000
    if any(fields.get(b"appid") == app_id for fields in records.values()):
        raise ValueError("Steam already has a different shortcut with this local identifier")
    index = str(max((int(key) for key in records), default=-1) + 1).encode("ascii")

    def string(key, value):
        return b"\x01" + key + b"\0" + value + b"\0"

    def integer(key, value):
        return b"\x02" + key + b"\0" + struct.pack("<I", value)

    icon_path = app / "Contents/Resources/RiskOfRain2.icns"
    entry = b"".join((
        b"\x00" + index + b"\0",
        integer(b"appid", app_id),
        string(b"AppName", title),
        string(b"Exe", executable),
        string(b"StartDir", f'"{app.parent}"'.encode("utf-8")),
        string(b"icon", os.fsencode(icon_path) if icon_path.is_file() else b""),
        string(b"ShortcutPath", b""),
        string(b"LaunchOptions", b""),
        integer(b"IsHidden", 0),
        integer(b"AllowDesktopConfig", 1),
        integer(b"AllowOverlay", 1),
        integer(b"OpenVR", 0),
        integer(b"Devkit", 0),
        string(b"DevkitGameID", b""),
        integer(b"DevkitOverrideAppID", 0),
        integer(b"LastPlayTime", 0),
        string(b"FlatpakAppID", b""),
        b"\x00tags\0\x08\x08",
    ))
    return data[:insertion] + entry + data[insertion:]


def steam_is_open():
    result = subprocess.run(["/usr/bin/pgrep", "-u", str(os.getuid()), "-x", "steam_osx"], stdout=subprocess.DEVNULL)
    if result.returncode not in (0, 1):
        raise ValueError("Could not confirm that Steam is closed")
    return result.returncode == 0


def shortcut_file(root):
    accounts = read_keyvalues(root / "config/loginusers.vdf").get("users", {})
    if not isinstance(accounts, dict):
        raise ValueError("Invalid Steam account metadata")
    candidates = [(int(key) - STEAM_ID_BASE, user) for key, user in accounts.items()
                  if key.isdecimal() and 0 < int(key) - STEAM_ID_BASE < 2**32 and isinstance(user, dict)]
    recent = [account for account, user in candidates if user.get("mostrecent") == "1"]
    if not recent and len(candidates) == 1:
        recent = [candidates[0][0]]
    if len(recent) != 1:
        raise ValueError("Could not choose the most recent local Steam account")
    config = root / "userdata" / str(recent[0]) / "config"
    target = config / "shortcuts.vdf"
    if not config.is_dir() or config.resolve() != config or target.is_symlink():
        raise ValueError("Steam's local shortcuts directory is unavailable")
    return target


def register_shortcut(root, app):
    import fcntl

    app = app.expanduser().absolute()
    if len(app.parents) < 4 or app != install_destination(root, app.parents[3]) or not app.is_dir():
        raise ValueError("Select the Risk2Mac app inside a registered Steam library")
    if any(char in str(app) for char in '"\r\n'):
        raise ValueError("Steam shortcuts require a path without quotes or newlines")
    with (app / "Contents/Info.plist").open("rb") as file:
        info = plistlib.load(file)
    if (info.get("CFBundleIdentifier") != "com.Hopoo-Games--LLC.Risk-of-Rain-2"
            or not (app / "Contents/Plugins/libRisk2MacSteamBridge.dylib").is_file()):
        raise ValueError("Choose a Risk2Mac build with Steam integration")
    if steam_is_open():
        raise ValueError("Quit Steam before registering the shortcut automatically")
    destination = shortcut_file(root)
    lock_path = destination.with_name(".risk2mac-shortcuts.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return save_shortcut(destination, app)


def save_shortcut(destination, app):
    original = read_small(destination) if destination.exists() else None
    data = original if original is not None else SHORTCUT_HEADER + b"\x08\x08"
    updated = with_shortcut(data, app)
    if updated == data:
        return "Steam shortcut was already registered."
    backup = None
    with tempfile.NamedTemporaryFile(prefix=".risk2mac-shortcuts-", dir=destination.parent, delete=False) as stage:
        proposed = Path(stage.name)
        stage.write(updated)
    try:
        if steam_is_open() or destination.is_symlink() or (read_small(destination) if destination.exists() else None) != original:
            raise ValueError("Steam shortcuts changed during registration. Quit Steam and retry.")
        if original is not None:
            with tempfile.NamedTemporaryFile(prefix="shortcuts.risk2mac-", suffix=".vdf.bak", dir=destination.parent, delete=False) as copy:
                backup = Path(copy.name)
                copy.write(original)
        os.replace(proposed, destination)
    finally:
        proposed.unlink(missing_ok=True)
    return "Steam shortcut registered." + (f" Previous shortcuts backed up at {backup}." if backup else "")


def print_shortcut_instructions(app):
    print("In Steam, choose Games → Add a Non-Steam Game → Browse, and select:", flush=True)
    print(str(app), flush=True)
    print(f'In the shortcut properties, name it "{SHORTCUT_NAME}" to identify the macOS port.', flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--register-shortcut", metavar="APP", type=Path)
    action.add_argument("--list-libraries", action="store_true")
    args = parser.parse_args()
    try:
        root = steam_root()
        if args.list_libraries:
            print(json.dumps([str(path) for path in libraries(root)]))
        else:
            print(register_shortcut(root, args.register_shortcut))
            print(PLAY_SHORTCUT_HINT)
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        if args.register_shortcut:
            print_shortcut_instructions(args.register_shortcut)
        parser.exit(1, f"Risk2Mac Steam: {error}\n")
