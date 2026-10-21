# SPDX-License-Identifier: MIT
"""Native Rust selects checked I/O fallbacks and honest unsupported errors."""
from pathlib import Path
import json
import runpy
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
BOOT = runpy.run_path(str(ROOT / 'scripts/bootstrap-homebrew-rust.py'))
FILES = ('std/src/sys/pipe/unix.rs', 'std/src/sys/net/connection/socket/unix.rs',
         'std/src/sys/fs/unix.rs', 'std/src/os/unix/net/ucred.rs',
         'std/src/sys/fd/unix.rs', 'std/src/os/fd/owned.rs')


def fixture(root):
    archive = ROOT / '.deps/rust-src.tar.xz'
    if not archive.exists():
        archive = (ROOT / '.deps/rust-sysroot').resolve().parent / 'rust-src.tar.xz'
    remaining = set(FILES)
    with tarfile.open(archive) as tar:
        for member in tar:
            for relative in tuple(remaining):
                if member.name.endswith('/library/' + relative):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(tar.extractfile(member).read())
                    remaining.remove(relative)
            if not remaining:
                break
    if remaining:
        raise RuntimeError('Pinned Rust source fixture missing: ' + repr(remaining))


def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


class HomebrewRustIoTest(unittest.TestCase):
    def test_pinned_source_idempotent_upstream_fd_fallbacks_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            original = {relative: (root / relative).read_text() for relative in FILES}
            BOOT['patch_native_std_io'](root)
            before = [(root.joinpath(path).read_bytes(), root.joinpath(path).stat().st_mtime_ns) for path in FILES]
            BOOT['patch_native_std_io'](root)
            self.assertEqual(before, [(root.joinpath(path).read_bytes(), root.joinpath(path).stat().st_mtime_ns) for path in FILES])
            for relative in FILES[:2]:
                text = (root / relative).read_text()
                restored = text.replace('all(target_os = "freebsd", not(target_vendor = "scei")),',
                                        'target_os = "freebsd",')
                self.assertEqual(restored, original[relative])
                self.assertIn('set_cloexec()', text)
            times = (root / FILES[2]).read_text()
            self.assertEqual(times.count('any(target_vendor = "scei", target_os = "redox"'), 2)
            self.assertIn('"setting file times not supported"', times)

    def test_peer_credentials_returns_real_unsupported_not_invented_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            BOOT['patch_native_std_io'](root)
            text = (root / FILES[3]).read_text()
            text = text[text.index('mod impl_bsd {'):]
            body = function(text, 'pub fn peer_cred(')
            # const_error! is std-private; only its constructor spelling changes
            # in this host harness. The actual native cfg branch is unchanged.
            body = body.replace('io::const_error!', 'io::Error::new')
            source = root / 'peer.rs'
            source.write_text('''use std::io;
use std::os::unix::net::UnixStream;
#[derive(Debug)]
struct UCred { uid:u32, gid:u32, pid:Option<u32> }
''' + body + '''
fn main() {
 let (socket, _other) = UnixStream::pair().unwrap();
 for _ in 0..32 {
  let error=peer_cred(&socket).unwrap_err();
  assert_eq!(error.kind(), io::ErrorKind::Unsupported);
 }
}
''')
            exe = root / 'peer'
            result = subprocess.run(['rustc', '--cfg', 'target_vendor="scei"',
                                     '-Aexplicit_builtin_cfgs_in_flags', '-Awarnings',
                                     str(source), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(exe)], check=True)

    def test_actual_native_std_archive_uses_pipe_accept_not_missing_modern_apis(self):
        report = json.loads((ROOT / 'build/rust-homebrew/build-report.json').read_text())
        self.assertEqual(report['result'], 0)
        libraries = list((ROOT / '.deps/rust-homebrew-sysroot/lib/rustlib/x86_64-scei-ps4/lib').glob('libstd-*.rlib'))
        self.assertEqual(len(libraries), 1)
        archive = libraries[0]
        members = [name for name in subprocess.check_output(['llvm-ar', 't', str(archive)], text=True).splitlines()
                   if name.endswith('.o')]
        self.assertTrue(members)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['llvm-ar', 'x', str(archive), *members], cwd=tmp, check=True)
            symbols = subprocess.check_output(['llvm-nm', '--undefined-only',
                                               *[str(Path(tmp) / name) for name in members]], text=True)
        undefined = {line.split()[-1] for line in symbols.splitlines()
                     if len(line.split()) == 2 and line.split()[0] == 'U'}
        self.assertTrue({'pipe', 'accept'} <= undefined)
        self.assertFalse({'pipe2', 'accept4', 'futimens', 'utimensat', 'getpeereid'} & undefined)


if __name__ == '__main__':
    unittest.main()
