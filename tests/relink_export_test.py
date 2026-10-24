import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('relink_export', ROOT / 'scripts/export-relink-kit.py')
assert SPEC is not None and SPEC.loader is not None
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


class RelinkExportTest(unittest.TestCase):
    def test_lane_specific_link_command_selection(self):
        log = ('+ make all\n+ ld.lld -o old.elf @old.rsp\n'
               '+ /source/.deps/sdk/bin/orbis-ld -o native.elf @native.rsp\n')
        self.assertEqual(EXPORT.link_commands(log, homebrew=False),
                         [['ld.lld', '-o', 'old.elf', '@old.rsp']])
        self.assertEqual(EXPORT.link_commands(log, homebrew=True),
                         [['/source/.deps/sdk/bin/orbis-ld', '-o', 'native.elf', '@native.rsp']])
        self.assertEqual(EXPORT.link_commands('+ echo /sdk/bin/orbis-ld nope\n', homebrew=True), [])

    def test_native_driver_verifies_sdk_and_keeps_replacement_codec_option(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / 'sdk'
            crt = sdk / 'target/lib/crt1.o'
            crt.parent.mkdir(parents=True)
            crt.write_bytes(b'pinned-crt')
            replacement = root / 'modified-codecs'
            replacement.mkdir()
            for name in ('avcodec', 'swresample', 'avutil'):
                (replacement / ('liborbis_' + name + '.a')).write_bytes(b'modified-library')
            spec = {'sdk': 'homebrew', 'sdk_files': {'target/lib/crt1.o': EXPORT.sha(crt)},
                    'command': ['@SDK@/bin/orbis-ld', '@CODECS@/liborbis_avutil.a', '-o', '@OUTPUT@', '--Map=@OUTPUT@.map']}
            (root / 'link.json').write_text(json.dumps(spec))
            argv = ['relink.py', '--sdk', str(sdk), '--codecs', str(replacement),
                    '--output', str(root / 'out.elf')]
            with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run') as run:
                exec(compile(EXPORT.RELINK, str(root / 'relink.py'), 'exec'),
                     {'__file__': str(root / 'relink.py')})
                self.assertEqual(run.call_args_list[0].args[0],
                                 [str(sdk / 'bin/orbis-ld'), str(replacement / 'liborbis_avutil.a'),
                                  '-o', str(root / 'out.elf'), '--Map=' + str(root / 'out.elf.map')])
                self.assertEqual(run.call_count, 2)
            crt.write_bytes(b'tampered-crt')
            with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run') as run:
                with self.assertRaises(SystemExit):
                    exec(compile(EXPORT.RELINK, str(root / 'relink.py'), 'exec'),
                         {'__file__': str(root / 'relink.py')})
                run.assert_not_called()
            spec['sdk_files'] = {'../escape': 'not-a-digest'}
            (root / 'link.json').write_text(json.dumps(spec))
            with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run') as run:
                with self.assertRaises(SystemExit):
                    exec(compile(EXPORT.RELINK, str(root / 'relink.py'), 'exec'),
                         {'__file__': str(root / 'relink.py')})
                run.assert_not_called()

    def test_streaming_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample'
            path.write_bytes(b'object-input')
            self.assertEqual(EXPORT.sha(path), hashlib.sha256(b'object-input').hexdigest())

    def test_only_nonloadable_symbol_order_may_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = (Path(directory) / name for name in ('original', 'rebuilt'))
            data = bytearray(240)
            struct.pack_into('<16sHHIQQQIHHHHHH', data, 0,
                             b'\x7fELF\x02\x01', 2, 62, 1, 0, 0, 64, 0, 64, 0, 0, 64, 2, 0)
            struct.pack_into('<IIQQQQIIQQ', data, 128, 0, 2, 0, 0, 192, 48, 0, 0, 8, 24)
            data[192:216] = bytes(range(24))
            data[216:240] = bytes(range(24, 48))
            a.write_bytes(data)
            b.write_bytes(data[:192] + data[216:240] + data[192:216])
            self.assertTrue(EXPORT.same_image_and_symbols(a, b))
            changed = bytearray(b.read_bytes())
            changed[200] ^= 1  # Any symbol change, not just its position, is rejected.
            b.write_bytes(changed)
            self.assertFalse(EXPORT.same_image_and_symbols(a, b))
            changed = bytearray(a.read_bytes())
            changed[100] ^= 1  # No changes to headers or other bytes are allowed.
            b.write_bytes(changed)
            self.assertFalse(EXPORT.same_image_and_symbols(a, b))
            struct.pack_into('<Q', data, 136, 2)  # An allocated symtab is not exempt.
            a.write_bytes(data)
            b.write_bytes(data[:192] + data[216:240] + data[192:216])
            self.assertFalse(EXPORT.same_image_and_symbols(a, b))

    def test_thin_archive_becomes_self_contained_and_preserves_duplicate_members(self):
        for tool in ('clang', 'llvm-ar', 'llvm-objcopy', 'llvm-nm'):
            self.assertIsNotNone(shutil.which(tool), 'Required host build tool: ' + tool)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            objects = []
            for name in ('first', 'second'):
                folder = root / name
                folder.mkdir()
                source = folder / 'same.c'
                source.write_text('int ' + name + '(void) { return 17; }\n')
                obj = folder / 'same.o'
                subprocess.run(['clang', '-g', '-c', source, '-o', obj], check=True)
                objects.append(obj)
            original = root / 'thin.a'
            subprocess.run(['llvm-ar', 'rcsT', original, *objects], check=True)
            output = root / 'regular.a'
            with patch.object(EXPORT, 'ROOT', root):
                EXPORT.materialize(original, output)
            self.assertEqual(output.read_bytes()[:8], b'!<arch>\n')
            for obj in objects:
                obj.unlink()
            defined = subprocess.check_output(['llvm-nm', '--defined-only', output], text=True)
            self.assertIn(' first', defined)
            self.assertIn(' second', defined)
            self.assertEqual(subprocess.check_output(['llvm-ar', 't', output], text=True).splitlines(),
                             ['same.o', 'same.o'])
            with patch.object(EXPORT, 'ROOT', root / 'other'):
                with self.assertRaisesRegex(ValueError, 'Missing/out-of-project'):
                    EXPORT.materialize(original, root / 'rejected.a')


if __name__ == '__main__':
    unittest.main()
