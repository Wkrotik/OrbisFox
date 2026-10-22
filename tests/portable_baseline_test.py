import ast
import importlib.util
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('portable_probe', ROOT / 'scripts/test-portable-baseline.py')
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class PortableBaselineTests(unittest.TestCase):
    def test_interpreter_only_configuration(self):
        PROBE.validate_configuration({'JS_CODEGEN_NONE': 1, 'ENABLE_PORTABLE_BASELINE_INTERP': 1,
                                      'MOZ_OPTIMIZE_FLAGS': ['-O2']})

    def test_wrong_configurations_are_not_evidence(self):
        valid = {'JS_CODEGEN_NONE': 1, 'ENABLE_PORTABLE_BASELINE_INTERP': 1,
                 'MOZ_OPTIMIZE_FLAGS': ['-O2']}
        for key, value in [('JS_CODEGEN_NONE', None), ('ENABLE_PORTABLE_BASELINE_INTERP', None),
                           ('MOZ_OPTIMIZE_FLAGS', ['-O'])]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                PROBE.validate_configuration(dict(valid, **{key: value}))

    def test_eager_does_not_replace_enable(self):
        self.assertEqual(PROBE.MODES['portable'], ['--portable-baseline', '--portable-baseline-eager'])
        self.assertEqual(PROBE.MODES['generic'], ['--no-portable-baseline'])
        self.assertIn('--disable-jit', PROBE.FLAGS)

    def test_creating_breakpoint_is_not_executing_code(self):
        self.assertFalse(PROBE.observed_portable_entry('Breakpoint 1 at 0x123\n'
                         'js::pbl::PortableBaselineInterpret<false, true>\nexited normally'))
        self.assertFalse(PROBE.observed_portable_entry('Breakpoint 1, js::Interpret()'))

    def test_native_proof_accepts_weak_functions_not_weak_data_or_imports(self):
        parse = runpy.run_path(str(ROOT / 'scripts/build-gecko-app.py'))['portable_baseline_bodies']
        name = 'js::pbl::PBIResult js::pbl::PortableBaselineInterpret<false, true>(JSContext*)'
        weak = '1: 00004ba15f0 48314 FUNC WEAK DEFAULT 1 ' + name
        local = '2: 00004ba15f0 300 FUNC LOCAL DEFAULT 1 ' + name
        data = '3: 00000b683020 2048 OBJECT WEAK DEFAULT 10 ' + name + '::addresses'
        imported = '4: 0000000000 0 FUNC GLOBAL DEFAULT UND ' + name
        empty = '5: 0000000000 0 FUNC WEAK DEFAULT 1 ' + name
        self.assertEqual(parse(f'{weak}\n{local}\n{data}\n{imported}\n{empty}'), [weak, local])

    def test_native_mode_cannot_silently_use_a_different_engine(self):
        require = runpy.run_path(str(ROOT / 'scripts/build-gecko-app.py'))['require_portable_baseline']
        defines = {'ENABLE_PORTABLE_BASELINE_INTERP': 1, 'ENABLE_PORTABLE_BASELINE_INTERP_FORCE': 1,
                   'JS_CODEGEN_NONE': 1}
        require({'defines': defines}, {'portable_baseline': True}, True)
        require({'defines': {}}, {}, False)
        for actual, report, requested in [(defines, {}, True), ({}, {}, True),
                                          (defines, {'portable_baseline': True}, False),
                                          (dict(defines, JS_CODEGEN_NONE=None), {'portable_baseline': True}, True),
                                          (dict(defines, ENABLE_PORTABLE_BASELINE_INTERP_FORCE=None),
                                           {'portable_baseline': True}, True)]:
            with self.subTest(actual=actual, report=report, requested=requested), self.assertRaises(RuntimeError):
                require({'defines': actual}, report, requested)

    def test_portable_flags_are_explicit_and_other_builds_unchanged(self):
        source = ast.parse((ROOT / 'scripts/configure-gecko-layout.py').read_text())
        main = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        start = next(i for i, node in enumerate(main.body) if isinstance(node, ast.Assign) and
                     any(isinstance(t, ast.Name) and t.id == 'command' for t in node.targets))
        construction = compile(ast.Module(body=main.body[start:start + 3], type_ignores=[]), '<configure command>', 'exec')
        for native, portable in [(False, False), (True, False), (True, True)]:
            values = {'SOURCE': ROOT / '.deps/gecko-layout', 'native_sdk': native,
                      'args': SimpleNamespace(mesa=False, portable_baseline=portable)}
            exec(construction, values)
            command = values['command']
            assert isinstance(command, list)
            self.assertEqual('--disable-jit' in command, portable)
            self.assertEqual('--enable-portable-baseline-interp' in command, portable)
            self.assertEqual('--enable-portable-baseline-interp-force' in command, portable)

    def test_legacy_rejected_before_build_or_source_preparation(self):
        for script in ['configure-gecko-layout.py', 'build-gecko-layout.py', 'build-gecko-app.py']:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), '--sdk', 'openorbis',
                                     '--portable-baseline'], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('requires --sdk homebrew', result.stderr)

    def test_marker_patch_is_bounded_and_timestamp_stable(self):
        patch = runpy.run_path(str(ROOT / 'scripts/patch-gecko-layout.py'))['patch_portable_baseline_marker']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'js/src/vm/PortableBaselineInterpret.cpp'
            file.parent.mkdir(parents=True)
            file.write_text('#include "vm/PortableBaselineInterpret.h"\nusing namespace js::jit;\n'
                            '    StackVal* restartEntryFrame, PBIResult restartCode) {\n')
            patch(root)
            before = file.read_bytes(), file.stat().st_mtime_ns
            patch(root)
            self.assertEqual((file.read_bytes(), file.stat().st_mtime_ns), before)
            self.assertEqual(file.read_text().count('sOrbisPortableBaselineEntered = true'), 1)
            self.assertIn('#ifdef MOZ_ORBIS_HOMEBREW_SDK', file.read_text())
            file.write_text('upstream source drift\n')
            with self.assertRaisesRegex(RuntimeError, 'no longer matches'):
                patch(root)

    def test_actual_core_entry(self):
        self.assertTrue(PROBE.observed_portable_entry('\nThread 1 hit Breakpoint 1, '
                        'js::pbl::PortableBaselineInterpret<false, true>()'))
        self.assertTrue(PROBE.observed_portable_entry('\nBreakpoint 2, '
                        'js::pbl::PortableBaselineInterpret<true, true>()'))


if __name__ == '__main__':
    unittest.main()
