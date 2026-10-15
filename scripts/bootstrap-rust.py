#!/usr/bin/env python3
"""Install checksum-pinned Rust source in a private sysroot, never system-wide."""
import hashlib
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
VERSION = '1.99.0'
SHA256 = '3f1f9b7ed48f4596fc87889b7b3c61747336a55c9c22db1ab0c697e0aadb77aa'
SYSROOT = ROOT / '.deps/rust-sysroot'


def main():
    version = subprocess.check_output(['rustc', '--version'], text=True)
    if not version.startswith(f'rustc {VERSION} '):
        raise RuntimeError(f'Rust compiler must match pinned sources: {VERSION}')
    marker = SYSROOT / '.source-sha256'
    if not marker.exists():
        archive = ROOT / '.deps/rust-src.tar.xz'
        if not archive.exists():
            with urllib.request.urlopen(f'https://static.rust-lang.org/dist/rust-src-{VERSION}.tar.xz', timeout=60) as response:
                archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError('Rust source archive checksum mismatch')
        SYSROOT.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as source:
            for member in source.getmembers():
                parts = Path(member.name).parts
                if len(parts) > 2 and parts[1:3] == ('rust-src', 'lib'):
                    member.name = str(Path(*parts[2:]))
                    source.extract(member, SYSROOT, filter='data')
        marker.write_text(SHA256 + '\n')
    host = subprocess.check_output(['rustc', '-vV'], text=True).split('host: ', 1)[1].splitlines()[0]
    system = Path(subprocess.check_output(['rustc', '--print', 'sysroot'], text=True).strip())
    library = SYSROOT / 'lib/rustlib' / host
    if not library.exists():
        library.symlink_to(system / 'lib/rustlib' / host, target_is_directory=True)
    subprocess.run(['python3', str(ROOT / 'scripts/patch-rust-libc.py'),
                    str(SYSROOT / 'lib/rustlib/src/rust/library/vendor/libc-0.2.189')], check=True)
    fs = SYSROOT / 'lib/rustlib/src/rust/library/std/src/sys/fs/unix.rs'
    text = fs.read_text()
    old = 'd_ino: (*entry_ptr).d_fileno,'
    new = 'd_ino: (*entry_ptr).d_fileno as u64,'
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Unexpected Rust directory-entry inode conversion')
        fs.write_text(text.replace(old, new))
    random = SYSROOT / 'lib/rustlib/src/rust/library/std/src/sys/random/mod.rs'
    text = random.read_text()
    old = 'cfg_select! {\n    // Tier 1'
    new = 'cfg_select! {\n    target_vendor = "orbis" => {\n        mod unix_legacy;\n        pub use unix_legacy::fill_bytes;\n    }\n    // Tier 1'
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Unexpected Rust OS entropy selection')
        random.write_text(text.replace(old, new))
    print('Private Rust sysroot sources verified and ABI patch applied')


if __name__ == '__main__':
    main()
