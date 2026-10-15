"""Install the Windows .NET 8 Desktop Runtime in the configured Proton prefix."""
# SPDX-License-Identifier: MIT
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen

METADATA_URL = "https://builds.dotnet.microsoft.com/dotnet/release-metadata/8.0/releases.json"
DOWNLOAD_HOSTS = {"builds.dotnet.microsoft.com", "download.visualstudio.microsoft.com",
                  "dotnetcli.azureedge.net"}
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_INSTALLER_BYTES = 256 * 1024 * 1024


def runtime_versions(prefix):
    """Require a complete matching Core/Desktop/host installation, not a marker."""
    root = Path(prefix) / "pfx/drive_c/Program Files/dotnet"
    if not (root / "dotnet.exe").is_file():
        return []
    versions = []
    shared = root / "shared/Microsoft.WindowsDesktop.App"
    if not shared.is_dir():
        return []
    for desktop in shared.iterdir():
        if not re.fullmatch(r"8\.0\.\d+", desktop.name):
            continue
        if ((desktop / "WindowsBase.dll").is_file()
                and (root / "shared/Microsoft.NETCore.App" / desktop.name / "coreclr.dll").is_file()
                and (root / "host/fxr" / desktop.name / "hostfxr.dll").is_file()):
            versions.append(desktop.name)
    return sorted(versions, key=lambda value: tuple(map(int, value.split("."))))


def trusted_url(url):
    if not isinstance(url, str):
        raise ValueError("Invalid Microsoft runtime URL")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in DOWNLOAD_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError(f"Runtime download must use an official Microsoft HTTPS host: {url}")
    return url


def select_installer(metadata):
    if not isinstance(metadata, dict) or metadata.get("channel-version") != "8.0":
        raise ValueError("Expected Microsoft's .NET 8 release metadata")
    latest = metadata.get("latest-release", "")
    if not re.fullmatch(r"8\.0\.\d+", latest):
        raise ValueError("Metadata does not identify a stable .NET 8 release")
    for release in metadata.get("releases", []):
        if release.get("release-version") != latest:
            continue
        desktop = release.get("windowsdesktop", {})
        version = desktop.get("version", "")
        if not re.fullmatch(r"8\.0\.\d+", version):
            break
        for entry in desktop.get("files", []):
            if entry.get("rid") == "win-x64" and entry.get("name") == "windowsdesktop-runtime-win-x64.exe":
                digest = entry.get("hash", "")
                if not re.fullmatch(r"[a-fA-F0-9]{128}", digest):
                    raise ValueError("Missing or invalid SHA-512 checksum in Microsoft metadata")
                url = trusted_url(entry.get("url"))
                if not urlparse(url).path.endswith(f"/windowsdesktop-runtime-{version}-win-x64.exe"):
                    raise ValueError("Microsoft runtime URL does not match the expected version/architecture")
                return version, url, digest.lower()
    raise ValueError("Windows Desktop Runtime win-x64 installer was not found in Microsoft metadata")


def sha512(path):
    digest = hashlib.sha512()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_metadata():
    with urlopen(METADATA_URL, timeout=45) as response:
        trusted_url(response.geturl())
        body = response.read(MAX_METADATA_BYTES + 1)
    if len(body) > MAX_METADATA_BYTES:
        raise ValueError("Microsoft release metadata exceeds the size limit")
    return json.loads(body)


def download_installer(url, destination, digest):
    """Publish a cached EXE only after the full file passes checksum validation."""
    destination = Path(destination)
    descriptor, temporary = tempfile.mkstemp(prefix=".dotnet-download-", dir=destination.parent)
    try:
        size = 0
        with os.fdopen(descriptor, "wb") as output, urlopen(trusted_url(url), timeout=45) as response:
            trusted_url(response.geturl())
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_INSTALLER_BYTES:
                    raise ValueError("Runtime installer exceeds the size limit")
                output.write(chunk)
        if sha512(temporary) != digest:
            raise ValueError("Microsoft runtime SHA-512 checksum mismatch; installer will not be executed")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cached_installer(prefix):
    cache = Path(prefix) / ".wauncher-runtime-cache"
    cache.mkdir(parents=True, exist_ok=True)
    metadata_cache = cache / "dotnet-8-releases.json"
    try:
        metadata = fetch_metadata()
        version, url, digest = select_installer(metadata)
        # Cache only metadata whose intended installer has been validated.
        descriptor, temporary = tempfile.mkstemp(prefix=".metadata-", dir=cache)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(metadata, output)
            os.replace(temporary, metadata_cache)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except OSError:
        if not metadata_cache.is_file():
            raise ValueError("Cannot download .NET release metadata. Check your connection and retry Steam Play; a fresh prefix needs internet for its first runtime installation.") from None
        print("Microsoft metadata unavailable; using cached release metadata", flush=True)
        version, url, digest = select_installer(json.loads(metadata_cache.read_text(encoding="utf-8")))
    installer = cache / f"windowsdesktop-runtime-{version}-win-x64.exe"
    if installer.is_file() and sha512(installer) == digest:
        print(f"Using verified cached Windows Desktop Runtime {version} x64", flush=True)
    else:
        print(f"Downloading Windows Desktop Runtime {version} x64 from Microsoft...", flush=True)
        download_installer(url, installer, digest)
    return installer, version


def ensure_runtime(data, command):
    if not data.get("install_dotnet", True):
        print("Automatic .NET installation disabled (self-contained/manual-runtime mode)", flush=True)
        return
    versions = runtime_versions(data["prefix"])
    if versions:
        print(f"Windows .NET 8 x64 is already installed ({', '.join(versions)}); skipping download/installer", flush=True)
        return
    if not command:
        raise ValueError("Runtime installation requires the Proton command supplied by Steam")
    if os.name != "posix":
        raise ValueError("Runtime installation requires Linux/Proton")
    pfx = data["prefix"] / "pfx"
    if not (pfx / "system.reg").is_file():
        raise ValueError("Initialize the Proton prefix before installing .NET")
    installer, version = cached_installer(data["prefix"])
    logs = data["log_dir"]
    logs.mkdir(parents=True, exist_ok=True)
    process_log = logs / "dotnet-installer.log"
    installer_log = pfx / "drive_c/wauncher-dotnet-install.log"
    env = os.environ.copy()
    # The selected Proton/runtime and the exact configured prefix are mandatory.
    # Never invoke the distro's wine or let the installer fall back to ~/.wine.
    env.update(STEAM_COMPAT_DATA_PATH=str(data["prefix"]),
               STEAM_COMPAT_CLIENT_INSTALL_PATH=str(data["steam_root"]),
               STEAM_COMPAT_INSTALL_PATH=str(data["game_dir"]), PROTON_LOG="0")
    print(f"Installing .NET Desktop Runtime {version} in {data['prefix']}...", flush=True)
    print(f"Installer logs: {process_log} and {installer_log}", flush=True)
    with process_log.open("a", encoding="utf-8") as output:
        try:
            result = subprocess.run([*command, str(installer), "/install", "/quiet", "/norestart",
                                     "/log", r"C:\wauncher-dotnet-install.log"],
                                    cwd=data["game_dir"], env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=300, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError(f".NET installer timed out after 5 minutes. See {process_log} and {installer_log}") from None
    # Unix process exits truncate Windows 3010 (success/restart) to 194.
    if result.returncode not in (0, 194, 3010) or not runtime_versions(data["prefix"]):
        raise ValueError(f".NET installation did not complete (exit {result.returncode}). See {process_log} and {installer_log}; Wauncher was not started. Retry Steam Play after resolving the installer error.")
    print(f"Windows .NET Desktop Runtime {version} installed and verified", flush=True)
