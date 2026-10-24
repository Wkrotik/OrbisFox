# SPDX-License-Identifier: MIT
"""Parser doubles only: exercise final-ELF proof rejection, not hardware support."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('mesa_native_app_builder', ROOT / 'scripts/build-gecko-app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class MesaLinkProofTests(unittest.TestCase):
    def setUp(self):
        self.sdk = Path('/fixture/sdk')
        self.names = ['eglGetProcAddress', 'eglInitialize', 'eglCreatePbufferSurface',
                      'radv_CreateInstance', '_mesa_GetString', 'orbis_sysconf',
                      'orbis_mesa_native_ready', 'orbis_mesa_gpu_ready',
                      'regcomp', 'regexec', 'mbtowc', 'mbrtowc', 'wcslen']
        self.defined = '\n'.join(f'{0x1000+i*0x100:016x} t {name}' for i, name in enumerate(self.names))
        self.demangled = '\n'.join('0000000000008000 t ' + name for name in (
            'mozilla::wr::RenderCompositorOrbis::Create()',
            'mozilla::wr::RenderCompositorOrbis::BeginFrame()',
            'mozilla::wr::RenderCompositorOrbis::EndFrame()',
            'mozilla::widget::OrbisCompositorWidget::PublishGpuFrame()',
            'mozilla::widget::OrbisFoxHost::GetNativeGpuReady()',
            'orbisfox::prepare_native_mesa()', 'orbisfox::probe_native_mesa_gpu()',
            'mozilla::wr::RenderCompositorSWGL::Create()'))
        self.mapping = '\n'.join(
            f'{0x1000+self.names.index(name)*0x100:x} 0 30 1 {self.sdk}/lib/libc.a({name}.lo):(.text.{name})'
            for name in self.names[-5:])
        self.dynamic = '1: 0000 0 FUNC GLOBAL DEFAULT UND write\n'

    def check(self):
        return app.verify_mesa_final_link(self.defined, self.demangled, self.mapping, self.dynamic, self.sdk)

    def test_localized_actual_bodies_pass_without_hardware_claim(self):
        result = self.check()
        self.assertFalse(result['console_tested'])
        self.assertFalse(result['browser_gpu_frames_observed'])
        self.assertEqual(len(result['sdk_regex_and_wide_selected_owners']), 5)

    def test_unresolved_or_data_name_is_not_an_implementation(self):
        for kind in ('U', 'D'):
            with self.subTest(kind=kind):
                original = self.defined
                self.defined = self.defined.replace('t eglInitialize', kind + ' eglInitialize')
                with self.assertRaisesRegex(RuntimeError, 'actual implementation bodies'):
                    self.check()
                self.defined = original

    def test_selected_sdk_section_must_match_actual_symbol_address(self):
        address = 0x1000 + self.names.index('mbtowc') * 0x100
        self.mapping = self.mapping.replace(f'{address:x} 0 30', f'{address+16:x} 0 30')
        with self.assertRaisesRegex(RuntimeError, 'ABI owner.*mbtowc'):
            self.check()

    def test_no_software_fallback_is_rejected(self):
        self.demangled = self.demangled.replace('RenderCompositorSWGL::Create', 'Unrelated::Create')
        with self.assertRaisesRegex(RuntimeError, 'software fallback'):
            self.check()

    def test_forbidden_runtime_interposition_is_rejected(self):
        for archive in ('liborbis-compat.a', 'configure-sysconf.a'):
            with self.subTest(archive=archive):
                original = self.mapping
                self.mapping += '\n' + archive
                with self.assertRaisesRegex(RuntimeError, 'Forbidden Mesa runtime'):
                    self.check()
                self.mapping = original

    def test_startup_gpu_service_import_is_rejected(self):
        for name in ('sceVideoOutOpen', 'sceGnmSubmitCommandBuffers'):
            with self.subTest(name=name):
                self.dynamic = '1: 0000 0 FUNC GLOBAL DEFAULT UND ' + name
                with self.assertRaisesRegex(RuntimeError, 'startup GPU service imports'):
                    self.check()


if __name__ == '__main__':
    unittest.main()
