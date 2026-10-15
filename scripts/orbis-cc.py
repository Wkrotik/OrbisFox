#!/usr/bin/env python3
"""Clang driver for Mozilla's cross-compile probes against OpenOrbis, not host libc."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
# cc-rs puts Mozilla's CXX selector inside CXXFLAGS, after its own flags.
cxx = '--cxx' in args
args = [arg for arg in args if arg != '--cxx' and arg != '--target=x86_64-orbis-freebsd']
sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
compiler = os.environ.get('ORBIS_CXX' if cxx else 'ORBIS_CC', 'clang++' if cxx else 'clang')
resource = subprocess.check_output([compiler, '-print-resource-dir'], text=True).strip()
command = [compiler, '--target=x86_64-pc-freebsd12-elf', '-nostdinc', '-D_POSIX_C_SOURCE=200809L', '-D_GNU_SOURCE', '-D_BSD_SOURCE', '-D__ORBIS__', '-mno-red-zone']
if cxx and '-nostdinc++' not in args:
    modern = ROOT / '.deps/libcxx-orbis/include/c++/v1'
    headers = Path(os.environ.get('ORBIS_CXX_HEADERS', modern if modern.exists() else sdk / 'include/c++/v1'))
    command += ['-isystem', str(headers)]
if (ROOT / '.deps/sdk-overlay/math.h').exists():
    command += ['-isystem', str(ROOT / '.deps/sdk-overlay')]
command += ['-isystem', str(sdk / 'include'), '-isystem', str(Path(resource) / 'include')]
# Mozilla also calls the driver for macro/version queries. Only attach the
# CRT/libraries to actual link invocations, never preprocessor/compiler probes.
has_input = any(not a.startswith('-') and (a.endswith(('.c', '.cc', '.cpp', '.cxx', '.s', '.S', '.o', '.a', '.so')) or a == '-') for a in args)
link = ('-o' in args or has_input) and not any(flag in args for flag in ('-E', '-c', '-S', '-M', '-MM'))
if link:
    command += ['-nostdlib', '-fuse-ld=lld', '-Wl,--gc-sections']
    modern_lib = ROOT / '.deps/libcxx-orbis/lib'
    if cxx and (modern_lib / 'libc++.a').exists():
        command += ['-L' + str(modern_lib)]
    command += ['-L' + str(sdk / 'lib')]
    if '-shared' not in args:
        command += ['-pie', str(sdk / 'lib/crt1.o')]
command += args
if link:
    command += ['-lc++', '-lc++abi']
    if cxx and (ROOT / '.deps/libcxx-orbis/lib/libunwind.a').exists():
        command += ['-lunwind']
    command += ['-lc', '-lkernel', '-lSceSysmodule']
sys.exit(subprocess.call(command))
