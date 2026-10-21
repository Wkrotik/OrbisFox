# SPDX-License-Identifier: MIT
"""Native engine producer ownership/SDK gates, not engine execution proof."""
import ast
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
BUILD = runpy.run_path(str(ROOT / 'scripts/build-gecko-layout.py'))


class HomebrewEngineTest(unittest.TestCase):
    def test_native_configure_uses_o2_without_changing_legacy_flags(self):
        source = ast.parse((ROOT / 'scripts/configure-gecko-layout.py').read_text())
        main = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        position = next(index for index, node in enumerate(main.body)
                        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'command' for target in node.targets))
        construction = compile(ast.Module(body=main.body[position:position + 2], type_ignores=[]), '<actual configure command>', 'exec')
        for native in (False, True):
            values = {'SOURCE': ROOT / '.deps/gecko-layout', 'native_sdk': native, 'args': SimpleNamespace(mesa=False)}
            exec(construction, values)
            command = values['command']
            assert isinstance(command, list)
            options = [option for option in command if option.startswith('--enable-optimize')]
            self.assertEqual(options, ['--enable-optimize=-O2'] if native else [])

    def test_native_prerequisites_are_separate_and_explicit(self):
        commands = BUILD['prerequisite_commands']('homebrew', False, 3)
        self.assertEqual([Path(c[1]).name for c in commands],
                         ['fetch-homebrew-service-headers.py', 'build-homebrew-libcxx.py',
                          'build-homebrew-rust.py', 'build-media-codecs.py'])
        self.assertEqual(len(commands[0]), 2)
        self.assertTrue(all(c[2:4] == ['--jobs', '3'] for c in commands[1:]))
        self.assertEqual(commands[-1][-2:], ['--sdk', 'homebrew'])

    def test_old_sdk_gpu_is_rejected_before_any_build_or_deletion(self):
        with self.assertRaisesRegex(RuntimeError, 'Mesa dependency migration is incomplete'):
            BUILD['prerequisite_commands']('homebrew', True, 4)
        with self.assertRaisesRegex(RuntimeError, 'Unknown ORBISFOX_SDK'):
            BUILD['prerequisite_commands']('typo', False, 4)

    def test_legacy_plan_remains_default_sdk_and_gpu_optional(self):
        self.assertEqual(len(BUILD['prerequisite_commands']('openorbis', False, 4)), 1)
        commands = BUILD['prerequisite_commands']('openorbis', True, 4)
        self.assertEqual([Path(c[1]).name for c in commands], ['build-media-codecs.py', 'build-orbis-mesa.py'])
        self.assertEqual(commands[0][-2:], ['--sdk', 'openorbis'])

    def test_existing_sdk_mismatch_never_reconfigures_or_removes_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            report = build / 'configure-report.json'
            report.write_text(json.dumps({'sdk': 'homebrew'}))
            member = build / 'kept.o'
            member.write_bytes(b'thin archive input')
            before = {p.name: p.read_bytes() for p in build.iterdir()}
            BUILD['require_build_sdk']('homebrew', build)
            with self.assertRaisesRegex(RuntimeError, 'Object tree SDK mismatch'):
                BUILD['require_build_sdk']('openorbis', build)
            self.assertEqual(before, {p.name: p.read_bytes() for p in build.iterdir()})
            report.write_text('{}')
            with self.assertRaisesRegex(RuntimeError, 'Object tree SDK mismatch'):
                BUILD['require_build_sdk']('homebrew', build)
            report.unlink()
            (build / 'config.status').write_text('unknown SDK')
            with self.assertRaisesRegex(RuntimeError, 'no recorded SDK identity'):
                BUILD['require_build_sdk']('homebrew', build)

    def test_native_rust_revision_change_preserves_members_and_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            BUILD['prepare_rust_cache']('homebrew', 'first', build)
            marker = build / '.rust-sysroot-revision'
            mtime = marker.stat().st_mtime_ns
            BUILD['prepare_rust_cache']('homebrew', 'first', build)
            self.assertEqual(marker.stat().st_mtime_ns, mtime)
            target = build / 'x86_64-scei-ps4/release'
            target.mkdir(parents=True)
            member = target / 'retained.o'
            member.write_bytes(b'archive member')
            with self.assertRaisesRegex(RuntimeError, 'preserve/archive owned inputs'):
                BUILD['prepare_rust_cache']('homebrew', 'different', build)
            self.assertEqual(marker.read_text(), 'first')
            self.assertEqual(member.read_bytes(), b'archive member')


if __name__ == '__main__':
    unittest.main()
