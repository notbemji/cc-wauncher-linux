#!/usr/bin/env python3
"""Local configuration and diagnostics for the Steam/Proton wrapper (stdlib only)."""
# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile

LINUX_DIR = Path(__file__).resolve().parent


def xdg(variable, fallback):
    value = Path(os.environ.get(variable) or fallback).expanduser()
    if not value.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return value


def default_config():
    return xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "cc-wauncher-linux/config.json"


def path_value(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Configuration paths must be nonempty strings")
    # pressure-vessel uses colon-delimited mount paths; no escaping is supported.
    if any(c in value for c in ("\x00", "\n", "\r", ":")):
        raise ValueError(f"Path contains an unsupported colon or control character: {value!r}")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"Expected an absolute path: {value!r}")
    return path.resolve()


def steam_candidates():
    home = Path.home()
    candidates = [os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH"),
                  home / ".steam/root", home / ".steam/steam",
                  home / ".local/share/Steam", home / ".steam/debian-installation",
                  xdg("XDG_DATA_HOME", home / ".local/share") / "Steam",
                  home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    for candidate in candidates:
        if candidate:
            yield Path(candidate).expanduser().resolve()


def valid_steam(path):
    return (path / "steamapps").is_dir() and (path / "config").is_dir()


def find_steam(explicit=None):
    if explicit:
        root = path_value(explicit)
        if not valid_steam(root):
            raise ValueError(f"Not a Steam client directory (expected config/ and steamapps/): {root}")
        return root
    for candidate in steam_candidates():
        if valid_steam(candidate):
            return path_value(str(candidate))
    raise ValueError("Steam was not found. Pass --steam-root /path/to/Steam during setup.")


def validate_game(game):
    for name in ("wauncher.exe", "csgo.exe", "cc.exe", "platform/steam_api64.dll"):
        if not (game / name).is_file():
            raise ValueError(f"Missing {game / name}. Choose the ClassicCounter game directory with Wauncher beside csgo.exe and cc.exe.")


def validate_pe(path):
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) < 64 or header[:2] != b"MZ":
            raise ValueError(f"Not a Windows executable: {path}")
        stream.seek(struct.unpack_from("<I", header, 60)[0])
        pe = stream.read(26)
        if len(pe) < 26 or pe[:6] != b"PE\0\0d\x86" or pe[24:26] != b"\x0b\x02":
            raise ValueError(f"Expected an x86_64 PE32+ bootstrap: {path}")


def validate_bootstrap(path):
    if path.name != "steam.exe":
        raise ValueError("The process-name bootstrap must be named steam.exe")
    validate_pe(path)


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_config(filename):
    path_value(str(LINUX_DIR))
    filename = path_value(str(filename))
    try:
        data = json.loads(filename.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"No configuration at {filename}; run linux/wauncher-linux setup --game-dir /path/to/ClassicCounter") from None
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported config schema (expected version 1)")
    for key in ("game_dir", "prefix", "bootstrap", "log_dir"):
        data[key] = path_value(data.get(key))
    # A launch-time override also supports moving a Steam installation.
    data["steam_root"] = find_steam(os.environ.get("WAUNCHER_STEAM_ROOT") or
                                    os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH") or data.get("steam_root"))
    if not isinstance(data.get("gc", True), bool):
        raise ValueError("gc must be true or false")
    data.setdefault("gc", True)
    validate_game(data["game_dir"])
    validate_bootstrap(data["bootstrap"])
    prefix = data["prefix"]
    if prefix == Path("/") or prefix.name == "pfx":
        raise ValueError("Use a dedicated compatibility-data directory, not / or its pfx/ subdirectory")
    if prefix == data["steam_root"] or prefix == data["game_dir"]:
        raise ValueError("The Proton prefix must be separate from the Steam and game directories")
    return data


def launch_option(config):
    # Steam expands %command%, then invokes /bin/sh. shlex.quote handles spaces,
    # quotes and shell metacharacters in both the checkout and config paths.
    return f"{shlex.quote(str(LINUX_DIR / 'wauncher-linux'))} --config {shlex.quote(str(config))} -- %command%"


def setup(args):
    game = path_value(args.game_dir)
    validate_game(game)
    config = path_value(str(args.config))
    path_value(str(LINUX_DIR))
    if config.exists() and not args.force:
        raise ValueError(f"Configuration already exists: {config}. Use --force to replace it (a backup is saved).")
    steam = find_steam(args.steam_root)
    data_dir = xdg("XDG_DATA_HOME", Path.home() / ".local/share") / "cc-wauncher-linux"
    game_id = hashlib.sha256(os.fsencode(str(game))).hexdigest()[:16]
    prefix = path_value(args.prefix or str(data_dir / "prefixes" / game_id))
    logs = path_value(args.log_dir or str(xdg("XDG_STATE_HOME", Path.home() / ".local/state") / "cc-wauncher-linux" / game_id))
    bootstrap = path_value(args.bootstrap or str(data_dir / "bootstrap/steam.exe"))
    if prefix.name == "pfx" or prefix == Path("/") or prefix in (steam, game):
        raise ValueError("--prefix must name a separate compatibility-data directory containing pfx/, not pfx/ itself")
    # Build our own bootstrap; never copy Steam binaries or fetch unsigned helpers.
    packaged_bootstrap = LINUX_DIR / "build/steam.exe"
    if args.bootstrap:
        validate_bootstrap(bootstrap)
    elif packaged_bootstrap.is_file():
        validate_bootstrap(packaged_bootstrap)
        bootstrap.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(packaged_bootstrap, bootstrap)
    else:
        subprocess.run(["bash", str(LINUX_DIR / "scripts/build-bootstrap.sh"), str(bootstrap)], check=True)
        validate_bootstrap(bootstrap)
    data = dict(version=1, game_dir=str(game), prefix=str(prefix), steam_root=str(steam),
                bootstrap=str(bootstrap), log_dir=str(logs), gc=not args.no_gc)
    if config.exists():
        shutil.copy2(config, str(config) + ".bak")
    atomic_write(config, json.dumps(data, indent=2) + "\n")
    print(f"Configuration: {config}\nPrefix: {prefix}\n")
    print("In Steam → Counter-Strike 2 → Properties:")
    print("1. Compatibility: force Proton Experimental (or a tested compatible version).")
    print("2. General → Launch Options: paste this entire line:\n")
    print(launch_option(config))
    print("\nStart using Counter-Strike 2's Play button. Steam configuration was not changed.")


def prepare(data):
    pfx = data["prefix"] / "pfx"
    if not (pfx / "system.reg").is_file() or not (pfx / "drive_c/windows").is_dir():
        raise ValueError(f"Proton did not initialize {pfx}; see runtime.log")
    # Upstream reads this Windows Steam path before its Steamworks fallback.
    # Share current account metadata, not a stale copy or a hard-coded Steam ID.
    login_source = data["steam_root"] / "config/loginusers.vdf"
    login_link = pfx / "drive_c/Program Files (x86)/Steam/config/loginusers.vdf"
    if login_source.is_file():
        login_link.parent.mkdir(parents=True, exist_ok=True)
        if not login_link.is_symlink() or login_link.resolve() != login_source.resolve():
            backup = login_link.with_suffix(".vdf.linux-wrapper.bak")
            if login_link.exists() and not login_link.is_symlink() and not backup.exists():
                shutil.copy2(login_link, backup)
            descriptor, temporary = tempfile.mkstemp(prefix=".loginusers.", dir=login_link.parent)
            os.close(descriptor)
            os.unlink(temporary)
            try:
                os.symlink(login_source, temporary)
                os.replace(temporary, login_link)
            finally:
                if os.path.lexists(temporary):
                    os.unlink(temporary)
        print("Linked native Steam account metadata into the Proton prefix")
    else:
        print("Native Steam loginusers.vdf is unavailable; Wauncher will use its Steamworks fallback")
    users = pfx / "drive_c/users"
    user = users / "steamuser"
    if not user.is_dir():
        candidates = [p for p in users.iterdir() if p.is_dir() and p.name.lower() not in
                      ("public", "default", "default user", "all users")]
        if len(candidates) != 1:
            raise ValueError(f"Cannot determine the Proton user in {users}")
        user = candidates[0]
    settings = user / "AppData/Local/ClassicCounter/Wauncher/config/wauncher_settings.cfg"
    original = settings.read_bytes().decode("utf-8-sig") if settings.exists() else ""
    lines = original.splitlines(keepends=True)
    updated = "".join(line for line in lines if line.partition("=")[0].strip() != "EnableGc")
    if updated and not updated.endswith(("\n", "\r")):
        updated += "\n"
    updated += f"EnableGc={str(data['gc']).lower()}\n"
    if updated != original:
        backup = settings.with_suffix(settings.suffix + ".linux-wrapper.bak")
        if settings.exists() and not backup.exists():
            shutil.copy2(settings, backup)
        atomic_write(settings, updated)
    print(f"GC mode: {data['gc']}; settings: {settings}")


def doctor(args):
    print(f"Host: {platform.system()} {platform.machine()}")
    ok = platform.system() == "Linux" and platform.machine() == "x86_64"
    for command in ("bash", "python3", "flock", "mktemp", "stat", "install"):
        found = shutil.which(command)
        print(f"{command}: {found or 'MISSING'}")
        ok = ok and bool(found)
    data = load_config(args.config)
    for key in ("game_dir", "steam_root", "prefix", "bootstrap", "log_dir", "gc"):
        print(f"{key}: {data[key]}")
    prefix = data["prefix"]
    print(f"Prefix initialized: {(prefix / 'pfx/system.reg').is_file()}")
    print("Steam-session authentication and GPU/driver support require an actual launch and server test.")
    if "com.valvesoftware.Steam" in str(data["steam_root"]) or os.environ.get("FLATPAK_ID"):
        print("Flatpak detected: wrapper, Python, compiler (during setup), game, prefix and logs must be accessible inside Steam's sandbox; see README.")
    print(f"\nLaunch option:\n{launch_option(Path(args.config).expanduser().resolve())}")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description="Portable Linux wrapper for ClassicCounter Wauncher. Launch: wauncher-linux [--config PATH] [--debug] [--dry-run] -- %command%")
    sub = parser.add_subparsers(dest="action", required=True)
    setup_parser = sub.add_parser("setup", help="build the bootstrap and save local paths; print Steam launch options")
    setup_parser.add_argument("--game-dir", required=True)
    setup_parser.add_argument("--prefix", help="reuse a compatibility-data directory, NOT its pfx/ child")
    setup_parser.add_argument("--steam-root")
    setup_parser.add_argument("--bootstrap", help="use an already built steam.exe from this repository")
    setup_parser.add_argument("--log-dir")
    setup_parser.add_argument("--no-gc", action="store_true", help="diagnostic only: disable the ClassicCounter coordinator")
    setup_parser.add_argument("--force", action="store_true", help="replace config, preserving config.json.bak")
    for name in ("doctor", "resolve", "prepare"):
        child = sub.add_parser(name, help={"doctor": "check local prerequisites and show launch options", "resolve": "internal: read config without shell evaluation", "prepare": "internal: enable GC after Proton initialization"}[name])
        child.add_argument("--config", default=os.environ.get("WAUNCHER_LINUX_CONFIG", str(default_config())))
    setup_parser.add_argument("--config", default=os.environ.get("WAUNCHER_LINUX_CONFIG", str(default_config())))
    args = parser.parse_args()
    if args.action == "setup":
        setup(args)
    elif args.action == "doctor":
        return doctor(args)
    elif args.action == "prepare":
        prepare(load_config(args.config))
    elif args.action == "resolve":
        data = load_config(args.config)
        for key in ("game_dir", "prefix", "steam_root", "bootstrap", "log_dir", "gc"):
            sys.stdout.buffer.write((str(data[key]).lower() if key == "gc" else str(data[key])).encode() + b"\0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Wauncher Linux: {error}", file=sys.stderr)
        sys.exit(1)
