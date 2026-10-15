# ClassicCounter Wauncher Linux

An unofficial Linux integration for [ClassicCounter Wauncher](https://github.com/ClassicCounter/launcher). Launch Wauncher and ClassicCounter's game coordinator through Steam/Proton with a real AppID 730 session.

```bash
git clone https://github.com/notbemji/cc-wauncher-linux.git
cd cc-wauncher-linux
./linux/wauncher-linux setup --game-dir "/path/to/ClassicCounter"
```

Setup prints the launch-options line to paste into **Counter-Strike 2 → Properties → General**, after forcing **Proton Experimental** in Compatibility. Then use Counter-Strike 2's **Play** button to open Wauncher. On first launch, the wrapper automatically downloads, verifies and installs Windows .NET 8 Desktop Runtime into its Proton prefix if needed. GC mode is enabled automatically.

Requires x86_64 Linux, native Steam, Bash 4.4+, Python 3.8+, util-linux/coreutils, a working graphics runtime, and your existing ClassicCounter game files. Source checkouts also need MinGW-w64 GCC or Clang/LLD/LLVM to build the small Windows bootstrap. A fresh prefix needs internet for the runtime installation (about 60 MB); later launches reuse the installed runtime. Use `setup --skip-dotnet` with a self-contained Wauncher build.

Read the [Linux wrapper guide](linux/README.md) for installation, reusable prefixes, build scripts, diagnostics, Flatpak limitations and the confirmed-distro table. CachyOS is the first recorded working gameplay environment; other distributions need actual server testing before confirmation.

This is the main fork, with upstream source/history retained and integration isolated in `linux/`. No submodules are needed. The upstream Windows documentation is preserved in [linux/UPSTREAM_README.md](linux/UPSTREAM_README.md).

The wrapper changes the CS2 launch target while its Steam launch option is installed. Clear that option and restore Compatibility settings to return to regular CS2. This project does not redistribute Steam or ClassicCounter game assets.

Licensed under the [MIT license](LICENSE).
