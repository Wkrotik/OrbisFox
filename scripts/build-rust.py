#!/usr/bin/env python3
"""Build the experimental, ABI-adapted OpenOrbis Rust standard library gate."""
import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parent.parent


def main():
    subprocess.run([sys.executable, str(ROOT / 'scripts/bootstrap-rust.py')], check=True)
    # Cargo treats vendored registry crates as immutable and can reuse a stale
    # build script after an intentional ABI patch. Invalidate on patch revision.
    revision = hashlib.sha256(b''.join((ROOT / 'scripts' / name).read_bytes() for name in
        ('patch-rust-libc.py', 'bootstrap-rust.py', 'orbis-rustc.py'))).hexdigest()
    marker = ROOT / 'build/rust/.abi-patch-revision'
    if not marker.exists() or marker.read_text() != revision:
        shutil.rmtree(ROOT / 'build/rust', ignore_errors=True)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(revision)
    source = ROOT / '.deps/rust-sysroot/lib/rustlib/src/rust/library'
    env = dict(os.environ, RUSTC=str(ROOT / 'scripts/orbis-rustc.py'), RUSTC_BOOTSTRAP='1',
               RUST_LIBC_UNSTABLE_FREEBSD_VERSION='11', CARGO_TARGET_DIR=str(ROOT / 'build/rust'))
    command = ['cargo', 'build', '-Zjson-target-spec', '-Zbuild-std=std,panic_abort', '--release',
               '--target', str(ROOT / 'targets/x86_64-orbis-freebsd.json'),
               '--manifest-path', str(ROOT / 'rust/runtime-probe/Cargo.toml'),
               '--config', 'source.crates-io.replace-with="rust-source"',
               '--config', f'source.rust-source.directory="{source / "vendor"}"']
    subprocess.run(command, env=env, check=True)
    built = ROOT / 'build/rust/x86_64-orbis-freebsd/release'
    # Link only the probe crate's objects. SpiderMonkey's jsrust owns the one
    # allocator/runtime; a second Rust staticlib would duplicate allocator hooks.
    rlib_command = command.copy()
    rlib_command[1] = 'rustc'
    rlib_command += ['--crate-type=rlib']
    subprocess.run(rlib_command, env=env, check=True)
    rlib = built / 'liborbisfox_runtime_probe.rlib'
    objects = ROOT / 'build/rust/probe-objects'
    objects.mkdir(parents=True, exist_ok=True)
    members = subprocess.check_output(['llvm-ar', 't', str(rlib)], text=True).splitlines()
    members = [name for name in members if name.endswith('.o')]
    if not members:
        raise RuntimeError('Rust probe rlib has no native objects')
    subprocess.run(['llvm-ar', 'x', str(rlib), *members], cwd=objects, check=True)
    archive = ROOT / 'build/rust/liborbisfox.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['llvm-ar', 'rcs', str(archive), *(str(objects / name) for name in members)], check=True)
    library = ROOT / '.deps/rust-sysroot/lib/rustlib/x86_64-orbis-freebsd/lib'
    library.mkdir(parents=True, exist_ok=True)
    for pattern in ('*.rlib', '*.rmeta'):
        for path in (built / 'deps').glob(pattern):
            # Only install Rust runtime crates, not application-specific crate metadata.
            if not path.name.startswith('liborbisfox_runtime_probe'):
                shutil.copy2(path, library / path.name)
    print('Rust runtime built; native behavior remains subject to console ABI/probe testing')


if __name__ == '__main__':
    main()
