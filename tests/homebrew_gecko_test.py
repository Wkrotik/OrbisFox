# SPDX-License-Identifier: MIT
"""Native SDK source ownership and fail-closed migration gates, not execution."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
APP = runpy.run_path(str(ROOT / 'scripts/build-gecko-app.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
VERIFY = runpy.run_path(str(ROOT / 'scripts/verify-rust-abi.py'))


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in root.rglob('*') if p.is_file()}


class HomebrewGeckoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOT / '.deps/gecko-layout'
        if not source.is_dir():
            raise unittest.SkipTest('Pinned Gecko source needed for real producer fixture')
        cls.archive = subprocess.check_output(['git', '-C', str(source), 'archive', PATCH['REVISION'],
                                               'third_party/rust/libc'])

    def fixture(self, directory):
        with tarfile.open(fileobj=io.BytesIO(self.archive)) as archive:
            archive.extractall(directory, filter='data')
        return Path(directory)

    def test_native_libc_idempotent_and_legacy_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.fixture(tmp)
            with patch('subprocess.check_output', return_value=self.archive):
                PATCH['prepare_libc'](source, native_sdk=False)
                PATCH['prepare_libc'](source)
                before = snapshot(source)
                result = PATCH['prepare_libc'](source)
                self.assertEqual(result['changed_files'], [])
                self.assertEqual(before, snapshot(source))
                PATCH['prepare_libc'](source, native_sdk=False)
                PATCH['prepare_libc'](source)
                after = snapshot(source)
                self.assertEqual({k: v[1] for k, v in before.items()}, {k: v[1] for k, v in after.items()})
            native = (source / 'third_party/rust/libc/src/unix/bsd/freebsdlike/mod.rs').read_text()
            self.assertIn('target_vendor = "scei"', native)
            self.assertIn('pub fn __error()', (source / 'third_party/rust/libc/src/unix/bsd/freebsdlike/freebsd/mod.rs').read_text())

    def test_unknown_vendor_edit_is_preserved_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self.fixture(tmp)
            edited = source / 'third_party/rust/libc/src/unix/mod.rs'
            edited.write_text(edited.read_text() + '\n// Unknown contributor edit must survive.\n')
            before = snapshot(source)
            with patch('subprocess.check_output', return_value=self.archive):
                with self.assertRaisesRegex(RuntimeError, 'non-producer libc edit'):
                    PATCH['prepare_libc'](source)
            self.assertEqual(before, snapshot(source))

    def test_rust_detection_transformation_byte_mtime_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            path = source / 'build/moz.configure/rust.configure'
            path.parent.mkdir(parents=True)
            path.write_text('def check(t):\n    try:\n            info = split_triplet(t, allow_wasi=True)\n    except ValueError:\n        pass\n')
            PATCH['patch_rust_detection'](source)
            before = snapshot(source)
            PATCH['patch_rust_detection'](source)
            self.assertEqual(before, snapshot(source))
            self.assertIn('"x86_64-orbis-freebsd9.0" if t == "x86_64-scei-ps4"', path.read_text())

    def test_actual_gecko_libc_matches_native_cxx_abi(self):
        if not (ROOT / '.deps/rust-homebrew-sysroot/lib/rustlib/x86_64-scei-ps4/lib').is_dir():
            self.skipTest('Build the native SDK Rust runtime first')
        with tempfile.TemporaryDirectory() as tmp:
            source = self.fixture(tmp)
            with patch('subprocess.check_output', return_value=self.archive):
                PATCH['prepare_libc'](source)
            rust = [str(ROOT / 'scripts/homebrew-rustc.py'),
                    '--target=' + str(ROOT / 'targets/x86_64-scei-ps4.json'),
                    '--edition=2021', '-Awarnings']
            crate, probe, cpp, joined = (source / name for name in ('libgecko_libc.rlib', 'probe.a', 'cpp.o', 'joined.o'))
            commands = [
                rust + ['--crate-name', 'libc', '--crate-type', 'rlib', '--cfg', 'freebsd11',
                        '--cfg', 'libc_const_extern_fn', str(source / 'third_party/rust/libc/src/lib.rs'), '-o', str(crate)],
                rust + ['--crate-name', 'orbisfox_gecko_abi', '--crate-type', 'staticlib',
                        '--extern', 'libc=' + str(crate), '-Cpanic=abort',
                        str(ROOT / 'rust/runtime-probe/src/lib.rs'), '-o', str(probe)],
                DRIVER['compiler_command'](['--cxx', '-std=c++20', '-I' + str(ROOT / 'include'),
                        '-c', str(ROOT / 'src/ps4/rust_runtime.cpp'), '-o', str(cpp)]),
                ['ld.lld', '-r', str(cpp), '--whole-archive', str(probe), '--no-whole-archive', '-o', str(joined)],
            ]
            for command in commands:
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                VERIFY['verify'](joined, sdk_name='native Gecko libc')
            self.assertIn('all 32 audited ABI', output.getvalue())

    def test_native_netdb_adapters_preserve_results_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'netdb-test'
            command = ['clang', '-std=c11', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                       str(ROOT / 'tests/homebrew_netdb_test.c'), '-Wl,--wrap=gethostbyname',
                       '-Wl,--wrap=getprotobyname', '-o', str(exe)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=10)

    def test_all_configured_native_nspr_units_compile_and_link_without_gc(self):
        build = ROOT / 'build/gecko-layout'
        status = build / 'config.status.json'
        if not status.is_file() or not json.loads(status.read_text()).get('defines', {}).get('MOZ_ORBIS_HOMEBREW_SDK'):
            self.skipTest('Configure Gecko with --sdk homebrew for native NSPR check')
        directory = build / 'config/external/nspr/pr'
        compiler = next(shlex.split(line.split(' = ', 1)[1])
                        for line in (build / 'config/autoconf.mk').read_text().splitlines()
                        if line.startswith('CC = '))
        flags, sources = [], []
        for line in (directory / 'backend.mk').read_text().splitlines():
            if line.startswith('COMPUTED_CFLAGS += '):
                flags.extend(shlex.split(line.split(' += ', 1)[1]))
            elif line.startswith('CSRCS += ') and '$(UNIFIED_CSRCS)' not in line:
                sources.extend(Path(name.replace('$(topsrcdir)', str(ROOT / '.deps/gecko-layout')))
                               for name in shlex.split(line.split(' += ', 1)[1]))
            elif line.startswith('UNIFIED_CSRCS := '):
                sources.extend(directory / name for name in shlex.split(line.split(' := ', 1)[1]))
        self.assertEqual(len(sources), 6, 'Review changed native NSPR translation-unit coverage')
        with tempfile.TemporaryDirectory() as tmp:
            objects = []
            for source in sources:
                output = Path(tmp) / (source.stem + '.o')
                result = subprocess.run([*compiler, *flags, '-c', str(source), '-o', str(output)],
                                        cwd=directory, env=dict(os.environ, ORBISFOX_SDK='homebrew'),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                objects.append(str(output))
            main = Path(tmp) / 'main.c'
            main.write_text('#include "prinit.h"\nint main(void) {PR_Init(PR_USER_THREAD, PR_PRIORITY_NORMAL, 0); return PR_Cleanup() == PR_SUCCESS ? 0 : 1;}\n')
            elf = Path(tmp) / 'nspr.elf'
            command = DRIVER['compiler_command'](['-D__ORBIS__', '-I' + str(build / 'dist/include/nspr'),
                        '-I' + str(ROOT / '.deps/gecko-layout/nsprpub/pr/include'), str(main),
                        *objects, '-Wl,--no-gc-sections', '-o', str(elf)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(elf)], text=True)
            for name in ('PR_Init', 'PR_GetProtoByNumber', 'PR_GetIPNodeByName', 'PR_GetAddrInfoByName'):
                self.assertIn(' ' + name + '\n', symbols)
            undefined = subprocess.check_output(['llvm-nm', '--undefined-only', str(elf)], text=True)
            self.assertNotIn(' gethostbyname2\n', undefined)
            self.assertNotIn(' getprotobynumber\n', undefined)

    def test_legacy_application_cannot_consume_native_engine(self):
        APP['require_openorbis_engine']({'defines': {}})
        with self.assertRaisesRegex(RuntimeError, 'refusing to mix'):
            APP['require_openorbis_engine']({'defines': {'MOZ_ORBIS_HOMEBREW_SDK': '1'}})
        # Native SWGL now has its own application lane. Only unmigrated Mesa
        # must fail before any producer starts; never launch an engine in tests.
        for script, expected in (('build-gecko-app.py', 'Native SDK Mesa closure is not migrated'),
                                 ('build-gecko-layout.py', 'migration is incomplete')):
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), '--mesa'],
                                    env=dict(os.environ, ORBISFOX_SDK='homebrew'), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)


if __name__ == '__main__':
    unittest.main()
