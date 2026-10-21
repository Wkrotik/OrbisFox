#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rust driver using the native SDK's isolated source/ABI/runtime installation."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
TARGET = 'x86_64-scei-ps4'
args = sys.argv[1:]
if args in (['--print', 'target-list'], ['--print=target-list']):
    result = subprocess.run(['rustc', *args], check=True, capture_output=True, text=True)
    names = result.stdout.splitlines()
    print('\n'.join(sorted(set(names + [TARGET]))))
    sys.exit(0)
for i, arg in enumerate(args):
    if arg == '--target=' + TARGET:
        args[i] = '--target=' + str(ROOT / 'targets' / (TARGET + '.json'))
    elif arg == TARGET and i and args[i - 1] == '--target':
        args[i] = str(ROOT / 'targets' / (TARGET + '.json'))
    elif arg.startswith('--target=') and Path(arg.split('=', 1)[1]).stem == 'x86_64-orbis-freebsd':
        sys.exit('Old SDK Rust target passed to the native SDK driver')
    elif arg == '--target' and i + 1 < len(args) and Path(args[i + 1]).stem == 'x86_64-orbis-freebsd':
        sys.exit('Old SDK Rust target passed to the native SDK driver')
os.environ['RUSTC_BOOTSTRAP'] = '1'
os.execvp('rustc', ['rustc', '-Zunstable-options', '--sysroot',
                     str(ROOT / '.deps/rust-homebrew-sysroot'), *args])
