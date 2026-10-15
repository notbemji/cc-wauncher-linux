# ClassicCounter Wauncher on Linux

Run the Windows Wauncher, ClassicCounter coordinator (`cc.exe`) and legacy CS:GO through Steam's selected Proton. This is an unofficial Linux integration for [ClassicCounter/launcher](https://github.com/ClassicCounter/launcher).

## Repository structure

This repository is the main fork. Upstream Wauncher source and history stay in place; Linux integration lives in `linux/`. There is no Git submodule and no recursive clone requirement. Upstream changes can be merged into the fork without maintaining a second embedded launcher checkout. The Windows launcher is still built for Proton; a native launcher rewrite is outside this wrapper's scope.

```text
linux/
  wauncher-linux              Steam entry point; setup and doctor commands
  manager.py                 JSON configuration, discovery, prefix settings
  native/steam-bootstrap.c   Windows process-name bootstrap, built from source
  scripts/build-bootstrap.sh
  scripts/publish-wauncher.sh
  tests/test_wrapper.py
```

## Requirements

- x86_64 Linux with a working Steam client and its required graphics drivers, including 32-bit Vulkan support for legacy CS:GO. ARM hosts and other operating systems are not currently supported.
- Counter-Strike 2 installed in Steam under its official AppID **730**. Steam may update its installed depots when switching compatibility tools.
- Proton installed through Steam. Proton Experimental is the known working starting point; the wrapper uses the version Steam supplies, with no fixed version or library location.
- Bash 4.4+, Python 3.8+, `flock` (util-linux), and common GNU coreutils. No Python packages are required.
- A writable ClassicCounter game directory with `wauncher.exe`, `csgo.exe`, `cc.exe`, and `platform/steam_api64.dll`. Obtain game files and whitelist access through ClassicCounter; they are not included here.
- For a source checkout: MinGW-w64's x86_64 GCC, **or** Clang + LLD (`lld-link`) + LLVM (`llvm-dlltool`) to build the small Windows bootstrap. Packaged wrapper artifacts include this bootstrap and do not need a compiler during setup.

Typical source-build dependencies (install Steam and graphics drivers through your distro's instructions):

| Distro family | Wrapper/build packages |
| --- | --- |
| Debian / Ubuntu | `bash python3 util-linux coreutils gcc-mingw-w64-x86-64` |
| Arch / CachyOS | `bash python util-linux coreutils mingw-w64-gcc` |
| Fedora | `bash python3 util-linux coreutils mingw64-gcc` |

Package names describe prerequisites, not confirmed gameplay support. The setup script does not invoke a package manager or require root.

Wauncher also needs its Windows .NET runtime. Prefer the self-contained Windows build from this fork's Linux workflow, or publish one using the script below. A framework-dependent upstream build requires the corresponding Windows .NET Desktop Runtime inside the same Proton prefix; installing Linux .NET does not satisfy that requirement.

## Quick start

```bash
git clone https://github.com/notbemji/cc-wauncher-linux.git
cd cc-wauncher-linux
./linux/wauncher-linux setup --game-dir "/path/to/ClassicCounter"
```

Setup validates the game files, discovers Steam, builds/installs the bootstrap, and saves a local JSON configuration. It prints a complete launch-options line for this checkout's absolute path. It does **not** change Steam's configuration or launch a game.

In Steam → **Counter-Strike 2 → Properties**:

1. In **Compatibility**, force **Proton Experimental**.
2. In **General → Launch Options**, paste the entire line printed by setup. It ends in `-- %command%`.
3. Press **Play** on Counter-Strike 2. If shader processing appears, it can be skipped for this alternate game executable.
4. Wauncher opens; select a server and launch. The wrapper enables **Enable In-Game Inventory (Beta)** / `EnableGc=true`, so the game starts through `cc.exe`.

The Counter-Strike 2 Play button now starts Wauncher while these launch options are installed. Clear that launch option and restore your previous Compatibility setting to play regular CS2 again. Do not use Wauncher's **Add to Steam** button for this workflow: a non-Steam shortcut does not establish the required AppID 730 session.

Keep this checkout at the same location. If you move it, run setup again with `--force` and replace the Steam launch-options line.

## Existing prefix or custom locations

```bash
./linux/wauncher-linux setup \
  --game-dir "/games/ClassicCounter" \
  --prefix "/path/to/steamapps/compatdata/OLD_SHORTCUT_ID" \
  --steam-root "/path/to/Steam" \
  --config "/path/to/local-config.json"
```

`--prefix` names the compatibility-data directory **containing** `pfx/`, not `pfx/` itself. Existing prefixes retain their settings and installed runtimes. A fresh prefix is initialized by Steam's Proton on first launch. The wrapper changes only the GC preference in Wauncher's settings and saves an original `.linux-wrapper.bak` when needed; themes and game launch flags are preserved. It also links native Steam's current `config/loginusers.vdf` into the Windows Steam directory, with a backup if replacing an old regular file. This lets Wauncher find the signed-in account without storing a fixed Steam ID or copying account metadata into this repository. `--no-gc` exists for diagnostics and disables the GC preference explicitly.

Defaults follow XDG conventions:

| Item | Default |
| --- | --- |
| Config | `$XDG_CONFIG_HOME/cc-wauncher-linux/config.json` (fallback `~/.config`) |
| Bootstrap | `$XDG_DATA_HOME/cc-wauncher-linux/bootstrap/steam.exe` (fallback `~/.local/share`) |
| Prefix | `$XDG_DATA_HOME/cc-wauncher-linux/prefixes/<game-path-hash>` |
| Logs | `$XDG_STATE_HOME/cc-wauncher-linux/<game-path-hash>` (fallback `~/.local/state`) |

The hash separates installations; the code contains no username, drive path, non-Steam shortcut ID, or distro check. The generated JSON contains only that machine's local paths. Do not commit it. Re-run setup after moving a game, or pass `--prefix` to retain its old prefix.

Additional options: `--bootstrap /path/to/steam.exe` uses this project's prebuilt bootstrap; `--log-dir` relocates logs; `--force` backs up and replaces an existing config. `WAUNCHER_LINUX_CONFIG` can select a default config. `WAUNCHER_STEAM_ROOT` overrides Steam discovery. At launch, Steam's `STEAM_COMPAT_CLIENT_INSTALL_PATH` takes precedence over the saved client path unless this explicit override is set.

## How it works

Steam creates the real AppID 730 compatibility session. The wrapper preserves Steam's reaper, runtime, overlay and Proton executable, substitutes our `steam.exe` bootstrap for the CS2 executable, and runs from the ClassicCounter game directory. The bootstrap starts `wauncher.exe` and stays alive while Wauncher runs, satisfying its Windows Steam process-name check. **The bootstrap does not authenticate or emulate Steam**; Proton's Steam bridge still communicates with the native Steam client.

Proton normally replaces executables named `steam.exe` with its own builtin. The wrapper adds `*steam.exe=n` to Wine's DLL overrides so an external, explicit-path `steam.exe` loads natively. Proton's exact builtin override still wins for its system-directory Steam helper, preserving the Steam bridge. Other overrides are retained. This follows [Wine's module load-order rules](https://github.com/ValveSoftware/wine/blob/bleeding-edge/dlls/ntdll/unix/loadorder.c) and is verified by an isolated Proton runtime test. The bootstrap only imports Windows kernel APIs.

The wrapper uses a single launch chain and normalizes Proton's `waitforexitandrun` verb to `run` after taking its own per-prefix lock. This avoids waiting for a second background shim in the same prefix. Before the first launch, it initializes the prefix and enables the ClassicCounter coordinator. Game, prefix, helper, and log paths are added to `STEAM_COMPAT_MOUNTS` for the Steam Linux Runtime.

Paths with spaces, apostrophes and shell metacharacters are passed as arguments without `eval`. Colons and line breaks in paths are rejected because runtime mount lists use colon separators.

## Steam Flatpak and unusual distributions

Native/package-manager Steam is the tested installation type. Standard Steam paths, custom client roots and secondary game-library locations are supported by discovery/configuration.

Flatpak Steam is **experimental and has not been gameplay-tested**. Discovering its client directory does not grant access through Flatpak's sandbox. The checkout, game, config, bootstrap, prefix and logs must all be visible inside the Steam sandbox, and Bash/Python must be available there. Grant access to those specific directories using Flatseal or targeted Flatpak filesystem permissions. Use paths as seen inside Flatpak and, if necessary, run setup/doctor there. Steam's own pressure-vessel mount list cannot override Flatpak permissions. The wrapper never grants broad filesystem access automatically.

NixOS, immutable distributions, containers, Steam Deck and other Steam packaging arrangements need their normal Steam/32-bit graphics runtime setup and have not been tested here. No distro should be marked confirmed solely because a dry-run or unit test passes.

## Diagnostics

```bash
./linux/wauncher-linux doctor
# Or:
./linux/wauncher-linux doctor --config "/path/to/local-config.json"
```

Doctor checks paths, host architecture, the PE bootstrap and basic utilities without starting Steam or writing a prefix. It cannot prove Steam login, GPU support, server authentication, or network access.

For one detailed Proton trace, add `--debug` before `-- %command%` in Steam's launch-options line (or set `WAUNCHER_PROTON_LOG=1`). Logs are `runtime.log` and, in debug mode, `steam-730.log` in the configured log directory. Runtime logs rotate at 10 MiB on the next launch; Proton's detailed trace is disabled by default and can grow quickly.

For the exact game disconnect reason, add `-condebug -conclearlog` in Wauncher's game launch options, reproduce once, and inspect `csgo/console.log`. Remove those temporary flags afterward. ClassicCounter's coordinator writes `bin/gc_log.txt`. A successful GC test includes `we have connected to the GC`, matchmaking hello/cache replies, and continued keepalives. A successful server test also requires a loaded map and an active player session without the original disconnect. Logs can include Steam IDs, server addresses and local paths; redact them before sharing.

For command inspection without launching or writing a prefix, add `--dry-run` before `-- %command%` and start from Steam. To exercise parsing from a terminal, supply `SteamAppId=730 STEAM_COMPAT_APP_ID=730` and a real Proton command; those variables only allow command inspection and do not create Steam authentication.

If Wauncher reports no local Steam process, confirm that you used this wrapper's generated launch option. If it reports no logged-in account, confirm Steam is online and the correct account is signed in. If a community server rejects authentication, verify GC mode is enabled and inspect the game/coordinator logs. Changing AppID environment variables alone cannot repair a missing native Steam session.

## Confirmed working distros

| Distro | Architecture / kernel | Steam / Proton | Observed result | Date |
| --- | --- | --- | --- | --- |
| CachyOS (rolling, Arch-based) | x86_64 / `7.2.9-1-cachyos` | Native Steam; Proton Experimental `experimental-11.0-20261008-x86_64` | AppID 730 bootstrap approach + GC mode: coordinator handshake, inventory sync and custom-server gameplay observed. Initial machine-specific wrapper tested; portable implementation checks tracked below. | 2026-10-15 |

This table records the tested configuration, not every machine using that distro. The initial CachyOS session connected to the EU ClassicCounter coordinator, synchronized 111 inventory items, and loaded `de_stmarc` on a custom server beyond the earlier disconnect window. Other distros remain unconfirmed. For a new entry, record distro/version, architecture, Steam packaging, Proton version, GPU/driver and an actual GC/server test.

Portable implementation validation on that host: bootstrap built with Clang/LLD; isolated Wine and Steam Linux Runtime/Proton tests confirmed the native helper, working-directory handoff and child exit status; all 14 wrapper regression tests passed; setup/doctor resolved the existing game and Proton prefix. A live Steam gameplay run of the portable entry point remains to be recorded; the original successful session used the earlier machine-specific script.

## Development and building

```bash
# Wrapper regression tests; mock Steam/Proton, no account required:
python3 -m unittest discover -s linux/tests -v
bash -n linux/wauncher-linux linux/scripts/*.sh
shellcheck linux/wauncher-linux linux/scripts/*.sh

# Build only our Windows bootstrap:
./linux/scripts/build-bootstrap.sh "$PWD/linux/build/steam.exe"
# Optional: WAUNCHER_BOOTSTRAP_TOOLCHAIN=clang (or mingw)

# Publish Wauncher with its Windows .NET runtime (requires .NET 8 SDK):
./linux/scripts/publish-wauncher.sh "$PWD/dist/wauncher"
```

Publish into an empty directory and copy the **entire published output** beside the existing game executables after closing Wauncher. The Linux workflow builds both toolchains, runs checks, and uploads a wrapper archive plus a self-contained Windows Wauncher artifact. Workflow artifacts are not automatically published releases and do not include ClassicCounter game assets.

Tests cover quoting, fresh/existing prefixes, preserved settings, prefix locking, exit status, XDG paths, malformed commands, and rejection of mismatched Steam sessions. They do not replace real Steam gameplay tests. Building Wauncher requires NuGet access; running the already built wrapper does not require the .NET SDK on Linux.

To merge upstream source updates:

```bash
git remote add upstream https://github.com/ClassicCounter/launcher.git
git fetch upstream
git merge upstream/main
```

Resolve any source/README conflicts, rebuild if needed, rerun tests and repeat a Steam/GC/server test. The original upstream README is preserved in [UPSTREAM_README.md](UPSTREAM_README.md). Upstream source and these integration files are covered by the repository's [MIT license](../LICENSE); Steam, Proton and game assets retain their own licenses.
