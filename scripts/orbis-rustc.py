#!/usr/bin/env python3
"""Use a private Rust sysroot; never alter the host toolchain."""
import os
from pathlib import Path
import sys
import subprocess
ROOT = Path(__file__).resolve().parent.parent
sdk = os.environ.get('ORBISFOX_SDK', 'openorbis')
if sdk == 'homebrew':
    os.execv(sys.executable, [sys.executable, str(ROOT / 'scripts/homebrew-rustc.py'), *sys.argv[1:]])
if sdk != 'openorbis':
    sys.exit('Unknown ORBISFOX_SDK: ' + sdk)
args = sys.argv[1:]
if args in (['--print', 'target-list'], ['--print=target-list']):
    result = subprocess.run(['rustc', *args], check=True)
    print('x86_64-orbis-freebsd')
    sys.exit(result.returncode)
for i, arg in enumerate(args):
    if arg == '--target=x86_64-orbis-freebsd':
        args[i] = '--target=' + str(ROOT / 'targets/x86_64-orbis-freebsd.json')
    elif arg == 'x86_64-orbis-freebsd' and i and args[i - 1] == '--target':
        args[i] = str(ROOT / 'targets/x86_64-orbis-freebsd.json')
# Mozilla may explicitly clear this variable; the private JSON target/std
# build intentionally needs the pinned compiler's unstable target support.
os.environ['RUSTC_BOOTSTRAP'] = '1'
os.environ.setdefault('RUST_LIBC_UNSTABLE_FREEBSD_VERSION', '11')
os.execvp('rustc', ['rustc', '-Zunstable-options', '--sysroot', str(ROOT / '.deps/rust-sysroot'), *args])
