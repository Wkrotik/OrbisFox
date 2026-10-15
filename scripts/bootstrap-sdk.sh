#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
archive=.deps/toolchain.zip
url=https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain/releases/download/v0.5.3/toolchain-llvm-18.2.zip
sha=5006bb8629a40093b712fac971456fa4d5ad3fafaadb16d11c10b8a93b8b496f
mkdir -p .deps
if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 3 "$url" -o "$archive.part"
    mv "$archive.part" "$archive"
fi
printf '%s  %s\n' "$sha" "$archive" | sha256sum --check --status
if [[ ! -f .deps/OpenOrbis/PS4Toolchain/lib/crt1.o ]]; then
    unzip -q -o "$archive" -d .deps
    tar -xzf .deps/toolchain-llvm-18.tar.gz -C .deps
fi
printf 'OpenOrbis v0.5.3 ready: %s/.deps/OpenOrbis/PS4Toolchain\n' "$PWD"
