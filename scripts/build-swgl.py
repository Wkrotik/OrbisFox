#!/usr/bin/env python3
"""Generate Firefox SWGL shaders on the host; compile its C++ runtime for PS4."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/firefox-wr'
BUILD = ROOT / 'build/swgl'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-only', action='store_true')
    args = parser.parse_args()
    if not (SOURCE / 'swgl/src/gl.cc').exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts/fetch-swgl.py')], check=True)
    shutil.copy2(ROOT / 'scripts/swgl-Cargo.lock', SOURCE / 'Cargo.lock')
    subprocess.run(['cargo', 'build', '--locked', '--manifest-path', str(SOURCE / 'Cargo.toml'), '-p', 'swgl'], check=True)
    candidates = list((SOURCE / 'target/debug/build').glob('swgl-*/out/load_shader.h'))
    if not candidates:
        raise RuntimeError('No generated SWGL shaders')
    generated = max(candidates, key=lambda p: p.stat().st_mtime).parent
    BUILD.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated / 'libgl_cc.a', BUILD / 'libswgl-host.a')
    if args.host_only:
        return
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
    compiler = os.environ.get('SWGL_CXX', 'clang++')
    resource = subprocess.check_output([compiler, '-print-resource-dir'], text=True).strip()
    command = [compiler, '--target=x86_64-pc-freebsd12-elf', '-nostdinc',
               '-isystem', os.environ.get('ORBIS_CXX_HEADERS', str(sdk / 'include/c++/v1')),
               '-isystem', str(ROOT / '.deps/sdk-overlay'), '-isystem', str(sdk / 'include'),
               '-isystem', str(Path(resource) / 'include'),
               '-I' + str(SOURCE / 'swgl/src'), '-I' + str(SOURCE / 'webrender/res'), '-I' + str(generated),
               '-std=c++20', '-O2', '-DNDEBUG', '-D__ORBIS__', '-D_GNU_SOURCE', '-D_POSIX_C_SOURCE=200809L', '-fPIC', '-mno-red-zone',
               '-fno-exceptions', '-fno-rtti', '-fno-math-errno', '-ffast-math',
               '-mrecip=none', '-fno-finite-math-only', '-c', str(SOURCE / 'swgl/src/gl.cc'),
               '-o', str(BUILD / 'gl.o')]
    subprocess.run(command, check=True)
    subprocess.run(['llvm-ar', 'rcs', str(BUILD / 'libswgl.a'), str(BUILD / 'gl.o')], check=True)
    print('Compiled real Firefox SWGL + generated WebRender shaders for PS4')


if __name__ == '__main__':
    main()
