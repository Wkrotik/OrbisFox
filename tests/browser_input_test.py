import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class BrowserInputTests(unittest.TestCase):
    def test_real_trusted_middle_link_frontend(self):
        subprocess.run(['node', 'tests/browser_middle_link_test.js'], cwd=ROOT, check=True)

    def test_diagnostic_cleanup_is_app_scoped_and_non_recursive(self):
        subprocess.run(['node', 'tests/browser_log_cleaner_test.js'], cwd=ROOT, check=True)

    def test_scroll_admission_is_modal_not_shortcut_mask(self):
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        host = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-host.js').read_text()
        worker = (ROOT / 'src/native_ui_loop.cpp').read_text()
        producer = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('input.chromeModal?ScrollDelta{}:input.wheel', native)
        self.assertIn('input_.chromeModal=chromeModal', worker)
        self.assertNotIn('scrollUnavailable', host)
        self.assertIn('will retry', host)
        self.assertIn('unchanged since the stable', producer)
        self.assertIn('return MakeUnique<ScrollbarDrawingGTK>();', producer)

    def test_wasm_and_jit_cannot_be_enabled_by_preference_alone(self):
        startup = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        producer = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('"javascript.options.wasm": false', startup)
        self.assertIn('if(!jitReady){JS::DisableJitBackend()', native)
        self.assertLess(native.index('JS::DisableJitBackend()'), native.index('XRE_XPCShellMain'))
        self.assertIn('defined(JS_CODEGEN_NONE) || defined(MOZ_WIDGET_ORBIS)', producer)

    def test_settings_visual_does_not_depend_on_native_range_paint(self):
        css = (ROOT / 'gecko/orbisfox/fixtures/browser.css').read_text()
        xhtml = (ROOT / 'gecko/orbisfox/fixtures/browser.xhtml').read_text()
        self.assertIn('.range-fill', css)
        self.assertIn('.range-knob', css)
        self.assertIn('cursor-speed-shell', xhtml)
        self.assertIn('default-zoom-shell', xhtml)
        self.assertIn('style-src chrome:', xhtml)
        ui = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-ui.js').read_text()
        self.assertIn("style.setProperty('--fill'", ui)
        self.assertNotIn("attribute($(id+'-shell'),'style'", ui)

if __name__ == '__main__':
    unittest.main()
