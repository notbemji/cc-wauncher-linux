#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression checks using a fake Steam/Proton chain; no Steam account required."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

LINUX_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LINUX_DIR))
WRAPPER = LINUX_DIR / "wauncher-linux"
spec = importlib.util.spec_from_file_location("manager", LINUX_DIR / "manager.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wauncher test '")
        self.root = Path(self.tmp.name)
        self.game = self.root / "game $(touch UNEXPECTED)"
        self.game.mkdir()
        for name in ("wauncher.exe", "csgo.exe", "cc.exe", "platform/steam_api64.dll"):
            path = self.game / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        self.steam = self.root / "Steam client"
        (self.steam / "steamapps").mkdir(parents=True)
        (self.steam / "config").mkdir()
        self.prefix = self.root / "portable prefix"
        self.log_dir = self.root / "logs"
        self.bootstrap = self.root / "bootstrap/steam.exe"
        self.bootstrap.parent.mkdir()
        pe = bytearray(90)
        pe[:2] = b"MZ"
        struct.pack_into("<I", pe, 60, 64)
        pe[64:70] = b"PE\0\0d\x86"
        pe[88:90] = b"\x0b\x02"
        self.bootstrap.write_bytes(pe)
        self.config = self.root / "config with spaces.json"
        self.data = dict(version=1, game_dir=str(self.game), prefix=str(self.prefix),
                         bootstrap=str(self.bootstrap), steam_root=str(self.steam),
                         log_dir=str(self.log_dir), gc=True, install_dotnet=False)
        self.config.write_text(json.dumps(self.data))
        self.trace = self.root / "trace.jsonl"
        self.proton = self.root / "Proton with spaces/proton"
        self.proton.parent.mkdir()
        self.proton.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
prefix = pathlib.Path(os.environ["STEAM_COMPAT_DATA_PATH"])
with open(os.environ["TEST_TRACE"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                       "appid": os.environ["SteamAppId"],
                       "mounts": os.environ["STEAM_COMPAT_MOUNTS"],
                       "dll_overrides": os.environ["WINEDLLOVERRIDES"]}) + "\\n")
if "wineboot.exe" in sys.argv:
    (prefix / "pfx/drive_c/windows").mkdir(parents=True)
    (prefix / "pfx/drive_c/users/steamuser").mkdir(parents=True)
    (prefix / "pfx/system.reg").touch()
else:
    sys.exit(int(os.environ.get("TEST_GAME_EXIT", "0")))
''')
        self.proton.chmod(0o755)
        self.runtime = self.root / "Steam Runtime/_v2-entry-point"
        self.runtime.parent.mkdir()
        self.runtime.write_text('''#!/usr/bin/env bash
[[ "$1" == --verb=run ]] || exit 88
shift
[[ "$1" == -- ]] || exit 89
shift
exec "$@"
''')
        self.runtime.chmod(0o755)
        self.env = os.environ.copy()
        for key in ("SteamAppId", "STEAM_COMPAT_APP_ID", "STEAM_COMPAT_CLIENT_INSTALL_PATH", "WAUNCHER_STEAM_ROOT", "WAUNCHER_PROTON_LOG"):
            self.env.pop(key, None)
        self.env.update(SteamAppId="730", STEAM_COMPAT_APP_ID="730", TEST_TRACE=str(self.trace))
        self.command = [str(self.runtime), "--verb=waitforexitandrun", "--",
                        str(self.proton), "waitforexitandrun", "original cs2.exe", "-steam", "discard me"]

    def tearDown(self):
        self.tmp.cleanup()

    def run_wrapper(self, *options, command=None):
        return subprocess.run(["bash", str(WRAPPER), "--config", str(self.config), *options,
                               "--", *(self.command if command is None else command)],
                              env=self.env, text=True, capture_output=True, timeout=15)

    def test_dry_run_handles_spaces_and_metacharacters_without_writes(self):
        before = sorted(str(p) for p in self.root.rglob("*"))
        result = self.run_wrapper("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("steam.exe", result.stdout)
        self.assertNotIn("discard", result.stdout)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))
        self.assertFalse((self.game / "UNEXPECTED").exists())

    def test_rejects_non_steam_shortcut(self):
        self.env["SteamAppId"] = "999999"
        result = self.run_wrapper("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No AppID 730 session", result.stderr)
        self.assertFalse(self.prefix.exists())

    def test_rejects_mismatched_compat_id_and_reaper(self):
        self.env["STEAM_COMPAT_APP_ID"] = "999999"
        self.assertNotEqual(self.run_wrapper("--dry-run").returncode, 0)
        self.env["STEAM_COMPAT_APP_ID"] = "730"
        result = self.run_wrapper("--dry-run", command=["reaper", "SteamLaunch", "AppId=123", *self.command])
        self.assertIn("different AppID", result.stderr)

    def test_rejects_native_or_malformed_proton_command(self):
        for command in (["native-game"], [str(self.proton)], [str(self.proton), "destroy", "game"],
                        [str(self.proton), "run", "--"]):
            with self.subTest(command=command):
                self.assertNotEqual(self.run_wrapper("--dry-run", command=command).returncode, 0)

    def test_fresh_prefix_boots_then_enables_gc_and_propagates_exit(self):
        self.env["TEST_GAME_EXIT"] = "23"
        self.env["WINEDLLOVERRIDES"] = "example=n,b"
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 23, result.stderr)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertEqual(calls[0]["argv"], ["run", "wineboot.exe", "-u"])
        self.assertEqual(calls[1]["argv"], ["run", str(self.bootstrap)])
        self.assertEqual(calls[1]["cwd"], str(self.game))
        self.assertIn(str(self.game), calls[1]["mounts"])
        self.assertEqual(calls[1]["dll_overrides"], "example=n,b;*steam.exe=n")
        settings = self.prefix / "pfx/drive_c/users/steamuser/AppData/Local/ClassicCounter/Wauncher/config/wauncher_settings.cfg"
        self.assertEqual(settings.read_text(), "EnableGc=true\n")

    def test_existing_prefix_preserves_preferences_and_skips_boot(self):
        (self.prefix / "pfx/drive_c/windows").mkdir(parents=True)
        (self.prefix / "pfx/system.reg").touch()
        settings = self.prefix / "pfx/drive_c/users/steamuser/AppData/Local/ClassicCounter/Wauncher/config/wauncher_settings.cfg"
        settings.parent.mkdir(parents=True)
        original = "color_accent_green=#ffffff\nLaunchOptions=+set key=value\nEnableGc=false\n"
        settings.write_text(original)
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.trace.read_text().splitlines()), 1)
        self.assertEqual(settings.read_text(), original.replace("EnableGc=false", "EnableGc=true"))
        self.assertEqual(Path(str(settings) + ".linux-wrapper.bak").read_text(), original)

    def test_prefix_lock_prevents_concurrent_launch(self):
        import fcntl
        with Path(str(self.prefix) + ".wauncher-linux.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already in use", result.stderr)

    def test_setup_with_xdg_paths_and_explicit_prefix(self):
        self.env.update(XDG_CONFIG_HOME=str(self.root / "xdg config"), XDG_DATA_HOME=str(self.root / "xdg data"), XDG_STATE_HOME=str(self.root / "xdg state"))
        result = subprocess.run(["bash", str(WRAPPER), "setup", "--game-dir", str(self.game),
                                 "--steam-root", str(self.steam), "--bootstrap", str(self.bootstrap),
                                 "--prefix", str(self.prefix)], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / "xdg config/cc-wauncher-linux/config.json"
        data = json.loads(path.read_text())
        self.assertTrue(data["gc"])
        self.assertEqual(data["prefix"], str(self.prefix))
        self.assertIn("%command%", result.stdout)
        self.assertIn("Steam configuration was not changed", result.stdout)

    def test_config_is_data_and_rejects_unsupported_paths(self):
        self.config.write_text('$(touch UNEXPECTED)')
        self.assertNotEqual(self.run_wrapper("--dry-run").returncode, 0)
        self.assertFalse((self.game / "UNEXPECTED").exists())
        self.data["prefix"] = str(self.root / "path:with:colon")
        self.config.write_text(json.dumps(self.data))
        self.assertNotEqual(self.run_wrapper("--dry-run").returncode, 0)

    def test_missing_bootstrap_or_game_fails_clearly(self):
        self.bootstrap.unlink()
        self.assertNotEqual(self.run_wrapper("--dry-run").returncode, 0)
        self.bootstrap.touch()
        (self.game / "cc.exe").unlink()
        self.assertIn("Missing", self.run_wrapper("--dry-run").stderr)

    def test_doctor_runs_without_prefix_or_steam_session(self):
        self.env.pop("SteamAppId")
        result = subprocess.run(["bash", str(WRAPPER), "doctor", "--config", str(self.config)],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Prefix initialized: False", result.stdout)
        self.assertFalse(self.prefix.exists())

    def test_optional_separator_after_proton_verb(self):
        result = self.run_wrapper(command=[str(self.proton), "run", "--", "game.exe"])
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertEqual(calls[-1]["argv"], ["run", str(self.bootstrap)])

    def test_native_account_metadata_is_linked_without_copying_or_logging_contents(self):
        source = self.steam / "config/loginusers.vdf"
        source.write_text('"users" { "TEST_PRIVATE_ACCOUNT" {} }')
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        link = self.prefix / "pfx/drive_c/Program Files (x86)/Steam/config/loginusers.vdf"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), source)
        self.assertNotIn("TEST_PRIVATE_ACCOUNT", (self.log_dir / "runtime.log").read_text())

    def test_empty_xdg_environment_uses_fallback(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"XDG_DATA_HOME": ""}):
            self.assertEqual(manager.xdg("XDG_DATA_HOME", self.root), self.root)

    def test_launch_with_installed_runtime_skips_installer(self):
        from test_dotnet_runtime import make_runtime
        (self.prefix / "pfx/system.reg").parent.mkdir(parents=True)
        (self.prefix / "pfx/system.reg").touch()
        (self.prefix / "pfx/drive_c/windows").mkdir(parents=True)
        (self.prefix / "pfx/drive_c/users/steamuser").mkdir(parents=True)
        make_runtime(self.prefix)
        self.data["install_dotnet"] = True
        self.config.write_text(json.dumps(self.data))
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.trace.read_text().splitlines()), 1)
        self.assertIn("skipping download/installer", (self.log_dir / "runtime.log").read_text())


if __name__ == "__main__":
    unittest.main()
