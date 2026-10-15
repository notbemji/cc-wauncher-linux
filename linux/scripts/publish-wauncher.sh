#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_dir=$(cd -- "$script_dir/../.." && pwd -P)
if (( $# != 1 )); then
    printf 'Usage: %s /path/to/empty-output-directory\n' "$0" >&2
    exit 2
fi
command -v dotnet >/dev/null 2>&1 || { printf '.NET 8 SDK is required to publish Wauncher.\n' >&2; exit 1; }
output=$(realpath -m -- "$1")
if [[ -d "$output" ]] && [[ -n "$(ls -A -- "$output")" ]]; then
    printf 'Publish to an empty directory, then copy its contents beside csgo.exe.\n' >&2
    exit 1
fi
# Ship the Windows runtime with Wauncher so a fresh Proton prefix does not need
# a separate Windows .NET Desktop Runtime installation.
exec dotnet publish "$repo_dir/Wauncher/Wauncher.csproj" -c Release -r win-x64 \
    --self-contained true -p:PublishSingleFile=true -p:EnableWindowsTargeting=true -o "$output"
