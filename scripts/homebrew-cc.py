#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Browser compiler entry point for the pinned native homebrew SDK, never musl."""
import os
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
LEGACY_TARGETS = {'x86_64-orbis-freebsd', 'x86_64-orbis-freebsd12.0',
                  'x86_64-pc-freebsd12-elf'}
NATIVE_TARGET = 'x86_64-scei-ps4'
# Keep Gecko's Orbis platform selection distinct from the SDK/ABI choice.
CONFIGURE_TARGET = 'x86_64-orbis-freebsd9.0'


def compiler_command(arguments, *, root=ROOT):
    root = Path(root)
    cxx = '--cxx' in arguments
    args = []
    original = iter(arguments)
    for arg in original:
        if arg == '--cxx':
            continue
        if arg in ('--target', '-target') or arg.startswith(('--target=', '-target=')):
            target = next(original, None) if '=' not in arg else arg.split('=', 1)[1]
            if target not in LEGACY_TARGETS | {NATIVE_TARGET, CONFIGURE_TARGET}:
                raise ValueError('Unsupported homebrew compiler target: ' + str(target))
            # Keep the SDK's real target: overriding it changes wchar/pthread ABI.
            continue
        if arg in ('--sysroot', '-isysroot') or arg.startswith(('--sysroot=', '-isysroot=')):
            raise ValueError('Homebrew SDK owns the sysroot; do not override it')
        args.append(arg)
    forbidden = [root / '.deps' / name for name in
                 ('sdk-overlay', 'OpenOrbis', 'libcxx-orbis', 'rust-sysroot')]
    for arg in args:
        if any(str(path) in arg or str(path.resolve()) in arg or
               path.relative_to(root).as_posix() in arg for path in forbidden):
            raise ValueError('Old-SDK input in homebrew compile/link: ' + arg)
    sdk = root / '.deps/ps4-homebrew-sdk-v0.2.1'
    runtime = root / '.deps/libcxx-homebrew'
    command = [str(sdk / ('bin/orbis-clang++' if cxx else 'bin/orbis-clang')),
               '-DORBISFOX_HOMEBREW_SDK=1', '-mno-red-zone']
    if cxx:
        # Never let a system compiler find host C++ headers or select old archives.
        command += ['-nostdlib++']
        if '-nostdinc++' not in args:
            headers = runtime / 'include/c++/v1'
            if not headers.is_dir():
                raise RuntimeError('Build the homebrew C++ runtime first (headers missing)')
            command += ['-nostdinc++', '-isystem', str(headers)]
    has_input = any(arg == '-' or (not arg.startswith('-') and
                    arg.endswith(('.c', '.cc', '.cpp', '.cxx', '.s', '.S', '.o', '.a', '.so')))
                    for arg in args)
    link = ('-o' in args or has_input) and not any(
        flag in args for flag in ('-E', '-c', '-S', '-M', '-MM', '-r', '-fsyntax-only'))
    if not link:
        # The SDK shell driver otherwise injects CRT objects for syntax-only/M
        # queries. In a forced -x language they are misparsed as source text.
        command += ['--start-no-unused-arguments', '-nostartfiles', '--end-no-unused-arguments']
    if '-nostdlib' in args and '-nodefaultlibs' not in args:
        command += ['-nodefaultlibs']
    if cxx and link and not any(flag in args for flag in ('-nostdlib', '-nodefaultlibs', '-nostdlib++')):
        libraries = runtime / 'lib'
        if not all((libraries / name).is_file() for name in ('libc++.a', 'libc++abi.a', 'libunwind.a')):
            raise RuntimeError('Build the homebrew C++ runtime first (archives missing)')
        command += ['-L' + str(libraries)]
        args += ['-lc++', '-lc++abi', '-lunwind']
    return command + args


def main():
    # Fetching is explicit; a compile must not download or replace SDK inputs.
    fetch = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-sdk.py'))
    fetch['verify_sdk']()
    return subprocess.call(compiler_command(sys.argv[1:]))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as error:
        sys.exit(str(error))
