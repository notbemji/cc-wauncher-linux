#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dotnet_runtime as runtime


def make_runtime(prefix, version="8.0.32"):
    root = prefix / "pfx/drive_c/Program Files/dotnet"
    for relative in ("dotnet.exe", f"shared/Microsoft.NETCore.App/{version}/coreclr.dll",
                     f"shared/Microsoft.WindowsDesktop.App/{version}/WindowsBase.dll",
                     f"host/fxr/{version}/hostfxr.dll"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"MZ test fixture")


class Response(io.BytesIO):
    def __init__(self, content, url):
        super().__init__(content)
        self.url = url

    def geturl(self):
        return self.url


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wauncher runtime '")
        self.root = Path(self.tmp.name)
        self.prefix = self.root / "prefix with spaces"
        (self.prefix / "pfx/drive_c/windows").mkdir(parents=True)
        (self.prefix / "pfx/system.reg").touch()
        self.game = self.root / "game"
        self.game.mkdir()
        self.data = dict(prefix=self.prefix, steam_root=self.root / "Steam", game_dir=self.game,
                         log_dir=self.root / "logs", install_dotnet=True)
        self.payload = b"MZ Microsoft installer test fixture"
        self.digest = hashlib.sha512(self.payload).hexdigest()
        self.url = "https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/8.0.32/windowsdesktop-runtime-8.0.32-win-x64.exe"
        self.metadata = {"channel-version": "8.0", "latest-release": "8.0.32", "releases": [
            {"release-version": "8.0.32", "windowsdesktop": {"version": "8.0.32", "files": [
                {"name": "windowsdesktop-runtime-win-x64.exe", "rid": "win-x64",
                 "url": self.url, "hash": self.digest}]}}]}
        self.command = ["/Steam runtime/_v2-entry-point", "--verb=run", "--", "/Proton path/proton", "run"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_selects_official_windows_desktop_x64_installer(self):
        self.assertEqual(runtime.select_installer(self.metadata), ("8.0.32", self.url, self.digest))

    def test_metadata_rejects_wrong_architecture_hash_channel_or_version(self):
        for kind in ("rid", "hash", "channel", "version"):
            metadata = json.loads(json.dumps(self.metadata))
            if kind == "channel":
                metadata["channel-version"] = "9.0"
            elif kind == "version":
                metadata["latest-release"] = "8.0.33-preview.1"
            else:
                metadata["releases"][0]["windowsdesktop"]["files"][0][kind] = "invalid"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                runtime.select_installer(metadata)

    def test_rejects_untrusted_or_plaintext_download_hosts(self):
        for url in ("http://builds.dotnet.microsoft.com/file.exe", "https://example.org/file.exe",
                    "https://builds.dotnet.microsoft.com.example.org/file.exe",
                    "https://user@builds.dotnet.microsoft.com/file.exe"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                runtime.trusted_url(url)

    def test_download_verifies_hash_before_publishing_exe(self):
        destination = self.root / "installer.exe"
        with patch.object(runtime, "urlopen", return_value=Response(self.payload, self.url)):
            runtime.download_installer(self.url, destination, self.digest)
        self.assertEqual(destination.read_bytes(), self.payload)

    def test_checksum_failure_does_not_publish_or_leave_partial_download(self):
        destination = self.root / "installer.exe"
        before = set(self.root.iterdir())
        with patch.object(runtime, "urlopen", return_value=Response(b"damaged", self.url)):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                runtime.download_installer(self.url, destination, self.digest)
        self.assertFalse(destination.exists())
        self.assertEqual(set(self.root.iterdir()), before)

    def test_redirect_to_untrusted_host_is_rejected(self):
        with patch.object(runtime, "urlopen", return_value=Response(self.payload, "https://example.org/file.exe")):
            with self.assertRaises(ValueError):
                runtime.download_installer(self.url, self.root / "installer.exe", self.digest)

    def test_installed_runtime_needs_matching_complete_core_desktop_and_host(self):
        make_runtime(self.prefix)
        self.assertEqual(runtime.runtime_versions(self.prefix), ["8.0.32"])
        (self.prefix / "pfx/drive_c/Program Files/dotnet/shared/Microsoft.NETCore.App/8.0.32/coreclr.dll").unlink()
        self.assertEqual(runtime.runtime_versions(self.prefix), [])

    def test_installed_runtime_does_not_access_network_or_run_installer(self):
        make_runtime(self.prefix)
        with patch.object(runtime, "cached_installer") as cache, patch.object(runtime.subprocess, "run") as run:
            runtime.ensure_runtime(self.data, self.command)
        cache.assert_not_called()
        run.assert_not_called()

    def test_self_contained_opt_out_performs_no_download_or_install(self):
        self.data["install_dotnet"] = False
        with patch.object(runtime, "cached_installer") as cache, patch.object(runtime.subprocess, "run") as run:
            runtime.ensure_runtime(self.data, [])
        cache.assert_not_called()
        run.assert_not_called()

    def test_reuses_cached_installer_only_if_checksum_matches(self):
        cache = self.prefix / ".wauncher-runtime-cache"
        cache.mkdir()
        installer = cache / "windowsdesktop-runtime-8.0.32-win-x64.exe"
        installer.write_bytes(self.payload)
        with patch.object(runtime, "fetch_metadata", return_value=self.metadata), patch.object(runtime, "download_installer") as download:
            result = runtime.cached_installer(self.prefix)
        self.assertEqual(result, (installer, "8.0.32"))
        download.assert_not_called()
        installer.write_bytes(b"damaged")
        with patch.object(runtime, "fetch_metadata", return_value=self.metadata), patch.object(runtime, "download_installer") as download:
            runtime.cached_installer(self.prefix)
        download.assert_called_once_with(self.url, installer, self.digest)

    def test_cached_metadata_and_verified_installer_work_offline(self):
        cache = self.prefix / ".wauncher-runtime-cache"
        cache.mkdir()
        (cache / "dotnet-8-releases.json").write_text(json.dumps(self.metadata))
        installer = cache / "windowsdesktop-runtime-8.0.32-win-x64.exe"
        installer.write_bytes(self.payload)
        with patch.object(runtime, "fetch_metadata", side_effect=OSError("offline")):
            self.assertEqual(runtime.cached_installer(self.prefix), (installer, "8.0.32"))

    def test_fresh_offline_setup_reports_how_to_retry(self):
        with patch.object(runtime, "fetch_metadata", side_effect=OSError("offline")):
            with self.assertRaisesRegex(ValueError, "retry Steam Play"):
                runtime.cached_installer(self.prefix)

    def test_installs_using_exact_proton_chain_prefix_and_game_directory(self):
        installer = self.root / "installer with spaces.exe"
        installer.write_bytes(self.payload)

        def install(command, **kwargs):
            self.assertEqual(command[:len(self.command)], self.command)
            self.assertEqual(command[len(self.command)], str(installer))
            self.assertIn("/quiet", command)
            self.assertIn("/norestart", command)
            self.assertEqual(kwargs["env"]["STEAM_COMPAT_DATA_PATH"], str(self.prefix))
            self.assertEqual(kwargs["cwd"], self.game)
            make_runtime(self.prefix)
            return subprocess.CompletedProcess(command, 0)

        with patch.object(runtime, "cached_installer", return_value=(installer, "8.0.32")), patch.object(runtime.subprocess, "run", side_effect=install):
            runtime.ensure_runtime(self.data, self.command)

    def test_zero_exit_without_runtime_files_is_not_reported_as_success(self):
        with patch.object(runtime, "cached_installer", return_value=(self.root / "installer.exe", "8.0.32")), patch.object(runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(ValueError, "did not complete"):
                runtime.ensure_runtime(self.data, self.command)

    def test_nonzero_exit_reports_logs(self):
        with patch.object(runtime, "cached_installer", return_value=(self.root / "installer.exe", "8.0.32")), patch.object(runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 67)):
            with self.assertRaisesRegex(ValueError, "dotnet-installer.log"):
                runtime.ensure_runtime(self.data, self.command)

    def test_windows_restart_exit_is_accepted_only_after_runtime_verification(self):
        def install(command, **kwargs):
            make_runtime(self.prefix)
            return subprocess.CompletedProcess(command, 194)

        with patch.object(runtime, "cached_installer", return_value=(self.root / "installer.exe", "8.0.32")), patch.object(runtime.subprocess, "run", side_effect=install):
            runtime.ensure_runtime(self.data, self.command)


if __name__ == "__main__":
    unittest.main()
