import hashlib
import io
import json
import runpy
import stat
import struct
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FETCH = ROOT / 'scripts/fetch-homebrew-sdk.py'


class HomebrewSdkTest(unittest.TestCase):
    def fixture(self, directory, members):
        archive = Path(directory) / 'sdk.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            for name, value in members:
                z.writestr(name, value)
        return archive

    def test_corresponding_source_is_bounded_pinned_and_atomic(self):
        module = runpy.run_path(str(FETCH))
        data = b'pinned public corresponding source'
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'source.tar.gz'
            namespace = module['fetch_source'].__globals__
            with mock.patch.dict(namespace, SOURCE_ARCHIVE=archive, SOURCE_BYTES=len(data),
                                 SOURCE_SHA256=hashlib.sha256(data).hexdigest()):
                with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(data)):
                    self.assertEqual(module['fetch_source'](), archive)
                with mock.patch('urllib.request.urlopen') as fetch:
                    module['fetch_source']()
                    fetch.assert_not_called()
                archive.write_bytes(b'tampered')
                with self.assertRaisesRegex(RuntimeError, 'size/SHA-256'):
                    module['fetch_source']()
                archive.unlink()
                with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(data + b'extra')):
                    with self.assertRaisesRegex(RuntimeError, 'size/SHA-256'):
                        module['fetch_source']()
                self.assertFalse(archive.exists())
                target = Path(tmp) / 'elsewhere'
                target.write_bytes(data)
                archive.symlink_to(target)
                with self.assertRaisesRegex(RuntimeError, 'symlink'):
                    module['fetch_source']()

    def test_extract_and_preserve_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = zipfile.ZipInfo('ps4-homebrew-sdk/bin/compiler')
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            archive = self.fixture(tmp, [(info, b'compiler'), ('ps4-homebrew-sdk/include/header.h', b'header')])
            out = Path(tmp) / 'sdk'
            inventory = runpy.run_path(str(FETCH))['extract_archive'](archive, out)
            self.assertEqual(len(inventory), 2)
            self.assertEqual((out / 'include/header.h').read_bytes(), b'header')
            self.assertTrue((out / 'bin/compiler').stat().st_mode & stat.S_IXUSR)
            with self.assertRaisesRegex(RuntimeError, 'must be empty'):
                runpy.run_path(str(FETCH))['extract_archive'](archive, out)

    def test_reject_traversal_and_symlinks_before_writing(self):
        link = zipfile.ZipInfo('ps4-homebrew-sdk/link')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for bad in ('ps4-homebrew-sdk/../../escape', '/absolute', 'other/header', link):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                archive = self.fixture(tmp, [('ps4-homebrew-sdk/good', b'good'), (bad, b'bad')])
                out = Path(tmp) / 'out'
                with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                    runpy.run_path(str(FETCH))['extract_archive'](archive, out)
                self.assertFalse(out.exists())

    def test_inventory_is_bound_to_archive_not_editable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = runpy.run_path(str(FETCH))
            archive = self.fixture(tmp, [('ps4-homebrew-sdk/header.h', b'original')])
            out = Path(tmp) / 'sdk'
            files = module['extract_archive'](archive, out)
            report = {'version': module['VERSION'], 'revision': module['REVISION'],
                      'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': files}
            manifest = out / 'source-report.json'
            manifest.write_text(json.dumps(report))
            namespace = module['verify_sdk'].__globals__
            with mock.patch.dict(namespace, ARCHIVE=archive, SHA256=report['archive_sha256'],
                                 ARCHIVE_BYTES=archive.stat().st_size):
                module['verify_sdk'](out)
                (out / 'extra.h').write_bytes(b'extra')
                with self.assertRaisesRegex(RuntimeError, 'inventory changed'):
                    module['verify_sdk'](out)
                (out / 'extra.h').unlink()
                (out / 'header.h').write_bytes(b'modified')
                report['files']['header.h'] = hashlib.sha256(b'modified').hexdigest()
                manifest.write_text(json.dumps(report))
                with self.assertRaisesRegex(RuntimeError, 'report inventory changed'):
                    module['verify_sdk'](out)

    def test_sectionless_converter_contract_and_rejections(self):
        verify = runpy.run_path(str(ROOT / 'scripts/build-homebrew-sdk-probe.py'))['verify_converted_elf']
        programs = [(1, 5, 0x4000, 0, 0, 0x4000, 0x4000, 0x4000),
                    (0x61000010, 4, 0x8000, 0x4000, 0x4000, 0x4000, 0x4000, 0x4000),
                    (1, 6, 0xc000, 0x8000, 0x8000, 0x40, 0x80, 0x4000),
                    (7, 4, 0xc020, 0x8020, 0x8020, 4, 4, 32)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probe.oelf'
            def write(rows, entry=0x20):
                data = bytearray(0xc040)
                struct.pack_into('<16sHHIQQQIHHHHHH', data, 0, b'\x7fELF\x02\x01',
                                 0xfe10, 62, 1, entry, 64, 0, 0, 64, 56, len(rows), 0, 0, 0)
                for i, row in enumerate(rows): struct.pack_into('<IIQQQQQQ', data, 64 + i * 56, *row)
                path.write_bytes(data)
            write(programs)
            self.assertEqual(verify(path)['tls_bytes'], 4)
            cases = [(0, 1, 7), (1, 3, 0), (2, 5, 0x100), (3, 3, 0x18020), (0, 2, 0x5000)]
            for index, field, value in cases:
                with self.subTest(index=index, field=field):
                    rows = [list(row) for row in programs]; rows[index][field] = value
                    write(rows)
                    with self.assertRaises(ValueError): verify(path)
            write(programs, entry=0x18000)
            with self.assertRaises(ValueError): verify(path)

    def test_main_return_uses_app_service_and_rejects_returned_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / 'exit.c'
            harness.write_text('''#include <assert.h>
#include <setjmp.h>
#define ORBISFOX_SDK_PROBE_EXIT_TEST
#define main sdk_runtime_test_main
#include "''' + str(ROOT / 'tests/homebrew_sdk_probe.c') + '''"
#undef main
static jmp_buf terminated;
static int reject_exit;
int32_t sceSystemServiceLoadExec(const char *request, const char **args) {
  assert(strcmp(request, "exit") == 0 && args == NULL);
  if (reject_exit == 1) return -7;
  if (reject_exit == 2) return 0; // Accepted, but deliberately never terminates.
  longjmp(terminated, 1); // Model successful nonreturning service termination.
}
int main(int argc, char **argv) {
  reject_exit = argc > 1 ? (strcmp(argv[1], "timeout") == 0 ? 2 : 1) : 0;
  int result = sdk_runtime_test_main(0, NULL);
  assert(result == 0);
  if (setjmp(terminated) == 0) catchReturnFromMain(result);
  return 0;
}
''')
            binary = Path(tmp) / 'exit'
            subprocess.run(['clang', '-std=c11', '-D_GNU_SOURCE', '-O1', '-g', '-pthread',
                            '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            harness, '-o', binary], check=True)
            for mode in (None, 'reject', 'timeout'):
                with self.subTest(returned_service=mode):
                    import resource
                    def no_core(): resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                    result = subprocess.run([binary, *([mode] if mode else [])], capture_output=True,
                                            text=True, timeout=45, preexec_fn=no_core)
                    self.assertEqual(result.returncode == 0, mode is None, result.stderr)
                    path = Path(result.stdout.strip().split('log=', 1)[1])
                    try:
                        text = path.read_text()
                        self.assertIn('RESULT PASS checks=52 failures=0', text)
                        self.assertIn('APP_EXIT request status=0 flush=0', text)
                        self.assertEqual('FAIL APP_EXIT did not terminate' in text, mode is not None)
                        if mode:
                            code = 'fffffff9' if mode == 'reject' else '00000000'
                            self.assertIn('FAIL APP_EXIT did not terminate rc=0x' + code, text)
                    finally:
                        if path.name == 'runtime.log' and path.parent.name.startswith('orbisfox-sdk-probe-'):
                            path.unlink(); path.parent.rmdir()

    def test_host_probe_real_apis_with_sanitizers(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'probe'
            subprocess.run(['clang', '-std=c11', '-D_GNU_SOURCE', '-O1', '-g', '-pthread',
                            '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            str(ROOT / 'tests/homebrew_sdk_probe.c'), '-o', str(binary)], check=True)
            result = subprocess.run([binary], capture_output=True, text=True, timeout=45, check=True)
            path = Path(result.stdout.strip().split('log=', 1)[1])
            try:
                self.assertTrue(path.parent.name.startswith('orbisfox-sdk-probe-'))
                self.assertEqual(path.name, 'runtime.log')
                text = path.read_text()
                self.assertIn('RESULT PASS checks=52 failures=0', text)
                self.assertIn('PASS condition-genuine-timeout', text)
                self.assertIn('PASS CRT-constructor-before-main', text)
                self.assertIn('PASS recursive-lock/once/compiler-TLS/key-destructors/concurrent-heap', text)
                self.assertNotIn('PROT_EXEC', (ROOT / 'tests/homebrew_sdk_probe.c').read_text())
            finally:
                if path.name == 'runtime.log' and path.parent.name.startswith('orbisfox-sdk-probe-'):
                    path.unlink()
                    path.parent.rmdir()


if __name__ == '__main__':
    unittest.main()
