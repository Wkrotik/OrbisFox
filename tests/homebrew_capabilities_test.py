# SPDX-License-Identifier: MIT
"""SDK capability selection preserves real upstream fallbacks and entropy."""
from pathlib import Path
import ast
import hashlib
import io
import json
import runpy
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
FILES = ('ipc/chromium/src/base/process_util_posix.cc',
         'third_party/rust/getrandom/src/backends.rs',
         'third_party/rust/getrandom/.cargo-checksum.json',
         'netwerk/dns/PlatformDNSUnix.cpp', 'third_party/abseil-cpp/moz.build',
         'third_party/abseil-cpp/absl/time/internal/cctz/src/time_zone_format.cc',
         'third_party/abseil-cpp/absl/time/internal/cctz/time_zone_gn/moz.build',
         'third_party/rust/socket2/src/socket.rs',
         'third_party/rust/socket2/src/sys/unix.rs',
         'third_party/rust/socket2/.cargo-checksum.json', 'Cargo.toml', 'Cargo.lock')


def fixture(root):
    for relative in FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subprocess.check_output(['git', '-C', str(SOURCE), 'show',
                                                 PATCH['REVISION'] + ':' + relative]))


class HomebrewCapabilitiesTest(unittest.TestCase):
    def test_atomic_source_checksum_drift_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            dns = root / FILES[3]
            original = dns.read_text()
            dns.write_text(original.replace('HTTPSAliasTarget& aAlias) {', 'HTTPSAliasTarget& ownedAlias) {'))
            before = [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES]
            with self.assertRaisesRegex(RuntimeError, 'platform capability drift'):
                PATCH['patch_native_platform_capabilities'](root)
            self.assertEqual(before, [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES])
            dns.write_text(original)
            PATCH['patch_native_platform_capabilities'](root)
            before = [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES]
            PATCH['patch_native_platform_capabilities'](root)
            self.assertEqual(before, [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES])
            backend = root / FILES[1]
            checksum = json.loads(root.joinpath(FILES[2]).read_text())
            self.assertEqual(checksum['files']['src/backends.rs'], hashlib.sha256(backend.read_bytes()).hexdigest())
            self.assertIn('all(target_os = "freebsd", target_vendor = "scei")', backend.read_text())
            self.assertIn('return NS_ERROR_NOT_AVAILABLE;', dns.read_text())
            process = root.joinpath(FILES[0]).read_text()
            self.assertIn('#if !defined(__OpenBSD__) && !defined(MOZ_ORBIS_HOMEBREW_SDK)', process)
            self.assertIn('#ifdef HAVE_WAITID\n', process)
            self.assertIn('const int result = waitpid(handle, &status, maybe_wnohang);', process)
            checksum['files']['src/backends.rs'] = '0' * 64
            root.joinpath(FILES[2]).write_text(json.dumps(checksum))
            before = [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES]
            with self.assertRaisesRegex(RuntimeError, 'getrandom source/checksum drift'):
                PATCH['patch_native_platform_capabilities'](root)
            self.assertEqual(before, [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES])

    def test_socket_clone_migrates_previous_checksum_and_rejects_unknown_edits(self):
        from homebrew_rust_io_test import function
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            path = root / 'third_party/rust/socket2/src/sys/unix.rs'
            checksum = root / 'third_party/rust/socket2/.cargo-checksum.json'
            signature = 'pub(crate) fn try_clone('
            original = function(path.read_text(), signature)
            PATCH['patch_native_platform_capabilities'](root)
            wanted = path.read_bytes()
            previous = path.read_text().replace(function(path.read_text(), signature), original)
            path.write_text(previous)
            data = json.loads(checksum.read_text())
            data['files']['src/sys/unix.rs'] = hashlib.sha256(path.read_bytes()).hexdigest()
            checksum.write_text(json.dumps(data))
            PATCH['patch_native_platform_capabilities'](root)
            self.assertEqual(path.read_bytes(), wanted)
            path.write_text(path.read_text().replace(signature, 'pub(crate) fn owned_try_clone(', 1))
            before = [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES]
            with self.assertRaisesRegex(RuntimeError, 'clone capability drift'):
                PATCH['patch_native_platform_capabilities'](root)
            self.assertEqual(before, [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES])
            path.write_bytes(wanted)
            data = json.loads(checksum.read_text())
            data['files']['src/sys/unix.rs'] = '0' * 64
            checksum.write_text(json.dumps(data))
            before = [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES]
            with self.assertRaisesRegex(RuntimeError, 'socket2 source/checksum drift'):
                PATCH['patch_native_platform_capabilities'](root)
            self.assertEqual(before, [(root.joinpath(p).read_bytes(), root.joinpath(p).stat().st_mtime_ns) for p in FILES])

    def test_native_socket2_archive_uses_checked_accept_and_cloexec_not_accept4(self):
        dependencies = ROOT / 'build/gecko-layout/x86_64-scei-ps4/release/deps'
        libraries = list(dependencies.glob('liblibc-*.rlib'))
        self.assertEqual(len(libraries), 1, 'Build the native engine Rust dependencies first')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            archive = subprocess.check_output(['git', '-C', str(SOURCE), 'archive',
                PATCH['REVISION'], 'third_party/rust/socket2'])
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(root, filter='data')
            for patched in (False, True):
                if patched:
                    # Also migrate the previous parent-only CCTZ definition.
                    parent = root / FILES[4]
                    parent.write_text(parent.read_text() + '\n# Native SDK: use CCTZ\'s genuine portable parser, not absent strptime.\nif CONFIG["MOZ_ORBIS_HOMEBREW_SDK"]:\n    DEFINES["HAS_STRPTIME"] = 0\n')
                    PATCH['patch_native_platform_capabilities'](root)
                output = root / ('patched' if patched else 'original')
                output.mkdir()
                command = [sys.executable, str(ROOT / 'scripts/homebrew-rustc.py'),
                    '--crate-name', 'socket2', '--crate-type', 'rlib', '--edition=2021',
                    '--target=x86_64-scei-ps4', '--cfg', 'feature="all"',
                    '--extern', 'libc=' + str(libraries[0]), '-L', 'dependency=' + str(dependencies),
                    '-C', 'panic=abort', '-C', 'opt-level=1', '--out-dir', str(output),
                    str(root / 'third_party/rust/socket2/src/lib.rs')]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                imports = subprocess.check_output(['llvm-nm', '--undefined-only',
                    str(output / 'libsocket2.rlib')], text=True, stderr=subprocess.DEVNULL)
                self.assertEqual(' U accept4\n' in imports, not patched)
                if patched:
                    self.assertIn(' U accept\n', imports)
                    self.assertIn(' U fcntl\n', imports)
                    self.assertIn(' U close\n', imports)
                    checksum = json.loads(root.joinpath(FILES[9]).read_text())
                    for relative in ('src/socket.rs', 'src/sys/unix.rs'):
                        self.assertEqual(checksum['files'][relative], hashlib.sha256(
                            (root / 'third_party/rust/socket2' / relative).read_bytes()).hexdigest())
                    self.assertNotIn('HAS_STRPTIME', parent.read_text())
                    manifest = tomllib.loads(root.joinpath('Cargo.toml').read_text())
                    self.assertEqual(manifest['patch']['crates-io']['socket2'],
                                     {'path': 'third_party/rust/socket2'})
                    before = tomllib.loads(subprocess.check_output(['git', '-C', str(SOURCE),
                        'show', PATCH['REVISION'] + ':Cargo.lock'], text=True))
                    after = tomllib.loads(root.joinpath('Cargo.lock').read_text())
                    expected = [dict(package) for package in before['package']]
                    selected = [package for package in expected if package['name'] == 'socket2']
                    self.assertEqual(len(selected), 1)
                    del selected[0]['source']
                    del selected[0]['checksum']
                    self.assertEqual(after['package'], expected)
                    socket = root.joinpath(FILES[7]).read_text()
                    self.assertIn('socket._set_cloexec(true)?;', socket)
                    self.assertIn('let socket = set_common_accept_flags(socket)?;', socket)

    def test_native_wait_fallback_compiles_actual_status_handler_and_repairs_old_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            process = root / FILES[0]
            original = process.read_text()
            # Reproduce the failed build's earlier, incomplete adaptation.
            broken = original.replace('#ifdef HAVE_WAITID\n',
                                      '#if defined(HAVE_WAITID) && !defined(MOZ_ORBIS_HOMEBREW_SDK)\n')
            process.write_text(broken)
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_platform_capabilities'](root)
                text = process.read_text()
                capability = text[text.index('// We could configure-test'):text.index('\n#ifdef DEBUG')]
                body = 'ProcessStatus WaitForProcess(' + text.split('ProcessStatus WaitForProcess(', 1)[1].split('\nvoid FreeEnvVarsArray', 1)[0]
                unit = root / 'wait.cpp'
                for native in (False, True):
                    prefix = '#define MOZ_ORBIS_HOMEBREW_SDK 1\n' if native else ''
                    unit.write_text(prefix + WAIT_HEADERS + capability + '\n' + body)
                    obj = root / 'wait.o'
                    result = subprocess.run(DRIVER['compiler_command']([
                        '--cxx', '-std=c++20', '-c', str(unit), '-o', str(obj)]),
                        capture_output=True, text=True)
                    if native and not patched:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("undeclared identifier 'handleStatus'", result.stderr)
                        continue
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', '-u', str(obj)], text=True)
                    self.assertEqual(' U waitpid\n' in symbols, native)
                    self.assertEqual(' U waitid\n' in symbols, not native)
            before = process.read_bytes(), process.stat().st_mtime_ns
            PATCH['patch_native_platform_capabilities'](root)
            self.assertEqual(before, (process.read_bytes(), process.stat().st_mtime_ns))

    def test_native_cctz_compiles_actual_portable_parser_without_strptime_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            PATCH['patch_native_platform_capabilities'](root)
            source = root / FILES[5]
            for portable in (False, True):
                obj = root / 'time.o'
                # Read the actual owning GN leaf, not the ineffective parent
                # DEFINES scope or a hard-coded test-only compiler option.
                self.assertNotIn('HAS_STRPTIME', root.joinpath(FILES[4]).read_text())
                tree = ast.parse(root.joinpath(FILES[6]).read_text())
                namespace = {'CONFIG': {'MOZ_ORBIS_HOMEBREW_SDK': portable}, 'DEFINES': {}}
                exec(compile(ast.Module(body=[tree.body[-1]], type_ignores=[]), '<CCTZ leaf>', 'exec'), namespace)
                flags = ['-D' + name + '=' + str(value) for name, value in namespace['DEFINES'].items()]
                self.assertEqual(flags, ['-DHAS_STRPTIME=0'] if portable else [])
                result = subprocess.run(DRIVER['compiler_command']([
                    '--cxx', '-std=c++20', '-I' + str(SOURCE / 'third_party/abseil-cpp'),
                    *flags,
                    '-c', str(source), '-o', str(obj)]), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                symbols = subprocess.check_output(['llvm-nm', '-u', str(obj)], text=True)
                self.assertEqual(' U strptime\n' in symbols, not portable)


WAIT_HEADERS = r'''
#include <cerrno>
#include <signal.h>
#include <sys/wait.h>
#include <optional>
namespace mozilla {
template<class T> using Maybe = std::optional<T>;
inline auto Nothing() { return std::nullopt; }
}
using ProcessHandle = pid_t;
enum class ProcessStatus { Running, Error, Exited, Killed };
enum class BlockingWait { No, Yes };
struct Sink { template<class T> Sink& operator<<(const T&) { return *this; } };
#define LOG_AND_ASSERT Sink{}
#define CHROMIUM_LOG(level) Sink{}
#define DCHECK(value) ((void)(value))
#define HANDLE_EINTR(expression) (expression)
'''

if __name__ == '__main__':
    unittest.main()
