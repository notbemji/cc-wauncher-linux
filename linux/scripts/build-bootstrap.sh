#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if (( $# != 1 )); then
    printf 'Usage: %s /absolute/path/to/steam.exe\n' "$0" >&2
    exit 2
fi
output=$1
[[ "$output" == /* && "${output##*/}" == steam.exe ]] || { printf 'Output must be an absolute path ending in steam.exe\n' >&2; exit 2; }
mkdir -p -- "$(dirname -- "$output")"
build_dir=$(mktemp -d)
trap 'rm -rf -- "$build_dir"' EXIT
source_file="$script_dir/../native/steam-bootstrap.c"
toolchain=${WAUNCHER_BOOTSTRAP_TOOLCHAIN:-auto}
[[ "$toolchain" == auto || "$toolchain" == mingw || "$toolchain" == clang ]] || { printf 'Unknown bootstrap toolchain: %s\n' "$toolchain" >&2; exit 2; }
if [[ "$toolchain" != clang ]] && command -v x86_64-w64-mingw32-gcc >/dev/null 2>&1; then
    x86_64-w64-mingw32-gcc -Os -Wall -Wextra -Werror -fno-builtin -fno-stack-protector \
        -nostdlib "$source_file" -Wl,--entry,mainCRTStartup -Wl,--subsystem,console \
        -Wl,--no-insert-timestamp -lkernel32 -o "$build_dir/steam.exe"
elif [[ "$toolchain" != mingw ]] && command -v clang >/dev/null 2>&1 && command -v lld-link >/dev/null 2>&1 && command -v llvm-dlltool >/dev/null 2>&1; then
    llvm-dlltool -m i386:x86-64 -d "$script_dir/../native/kernel32.def" -l "$build_dir/kernel32.lib"
    clang --target=x86_64-pc-windows-msvc -Os -Wall -Wextra -Werror -ffreestanding \
        -fno-builtin -fno-stack-protector -c "$source_file" -o "$build_dir/bootstrap.obj"
    lld-link /entry:mainCRTStartup /subsystem:console /nodefaultlib /machine:x64 \
        /timestamp:0 "/out:$build_dir/steam.exe" "$build_dir/bootstrap.obj" "$build_dir/kernel32.lib"
else
    printf 'Install the MinGW-w64 x86_64 C compiler, or Clang + LLD + llvm-dlltool. See linux/README.md.\n' >&2
    exit 1
fi
install -m 0644 -- "$build_dir/steam.exe" "$output"
printf 'Built %s\n' "$output"
