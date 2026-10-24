# SPDX-License-Identifier: MIT
"""SDK-neutral input discovery, not native linking or console execution."""
from pathlib import Path
import runpy
import shlex
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
LINK = runpy.run_path(str(ROOT / 'scripts/gecko-link-inputs.py'))


class GeckoLinkInputsTest(unittest.TestCase):
    def file(self, engine, relative):
        path = engine / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture inventory only')
        return path

    def response(self, engine, relative, items):
        path = engine / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(shlex.quote(str(item)) for item in items))
        return path

    def fixture(self, engine):
        core = self.file(engine, 'objects/core with spaces.o')
        host = self.file(engine, 'objects/host.o')
        shell = self.file(engine, 'objects/xpcshell.o')
        self.response(engine, 'toolkit/library/build/libxul_so.list', [core])
        self.response(engine, 'js/xpconnect/shell/xpcshell.list', [core, host, shell])
        nss = [self.file(engine, 'security/nss/' + name + '/unit.o') for name in LINK['NSS_STATIC_COMPONENTS']]
        response = self.response(engine, 'security/nss/lib/nss/nss_nss3/libnss3_so.list', nss)
        # Never even open desktop DLL lists: their objects are intentionally
        # absent in a static-only build. No fake-success loader objects added.
        self.response(engine, 'security/nss/lib/softoken/libsoftokn3_so.list', ['absent-desktop-loader.o'])
        for codec in ('libavcodec/libmozavcodec', 'libavutil/libmozavutil'):
            obj = self.file(engine, 'media/ffvpx/' + codec + '.o')
            self.response(engine, 'media/ffvpx/' + codec + '_so.list', [obj])
        for name in ('pr', 'libc', 'ds'):
            self.file(engine, 'config/external/nspr/' + name + '/unit.o')
        for directory in ('translator_gn', 'angle_common_gn', 'angle_common_shader_state_gn', 'preprocessor_gn'):
            self.file(engine, 'third_party/angle/' + directory + '/lib' + directory + '.a')
        for relative in ('js/src/build/libjs_static.a', 'build/pure_virtual/libpure_virtual.a',
                         'x86_64-scei-ps4/release/libgkrust.a'):
            self.file(engine, relative)
        return core, host, nss, response

    def test_both_targets_use_actual_static_nss_ffvpx_nspr_and_host_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            core, host, nss, _ = self.fixture(engine)
            native = LINK['collect_engine_inputs'](engine, 'x86_64-scei-ps4')
            self.assertEqual(native['direct'], [core, host])
            self.assertEqual(native['static_nss'], nss)
            self.assertEqual(set(native['nspr']), {'pr', 'libc', 'ds'})
            self.assertEqual(len(native['support']), 3)
            self.assertEqual([path.name for path in native['codec_responses']],
                             ['libmozavcodec_so.list', 'libmozavutil_so.list'])
            self.assertTrue(all(path in [item['response'] for item in native['support']]
                                for path in native['codec_responses']))
            self.assertFalse(any(item['response'].name in LINK['NSS_DESKTOP_LISTS'] for item in native['support']))
            # Preserve legacy support numbering, including its skipped slot.
            self.assertEqual([item['index'] for item in native['support']], [0, 2, 3])
            with self.assertRaisesRegex(ValueError, 'out-of-lane'):
                LINK['collect_engine_inputs'](engine, 'x86_64-orbis-freebsd')
            self.file(engine, 'x86_64-orbis-freebsd/release/libgkrust.a')
            old = LINK['collect_engine_inputs'](engine, 'x86_64-orbis-freebsd')
            self.assertEqual(old['direct'], native['direct'])
            self.assertEqual(old['support'], native['support'])
            self.assertEqual(old['archives'][:-1], native['archives'][:-1])
            self.assertNotEqual(old['archives'][-1], native['archives'][-1])
            for invalid in ('../other-sdk', None, {'target': 'x86_64-scei-ps4'}):
                with self.assertRaisesRegex(ValueError, 'Rust target'):
                    LINK['collect_engine_inputs'](engine, invalid)

    def test_missing_static_nss_or_desktop_loader_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            _, _, nss, response = self.fixture(engine)
            response.write_text('\n'.join(map(str, nss[:-1])))
            with self.assertRaisesRegex(RuntimeError, 'Missing upstream static NSS closure: freebl_freebl_static'):
                LINK['collect_engine_inputs'](engine, 'x86_64-scei-ps4')
            loader = self.file(engine, 'security/nss/lib/freebl/loader.o')
            response.write_text('\n'.join(map(str, [*nss, loader])))
            with self.assertRaisesRegex(RuntimeError, 'desktop freebl DLL loader'):
                LINK['collect_engine_inputs'](engine, 'x86_64-scei-ps4')

    def test_codec_and_nspr_inputs_are_mandatory_and_confined(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / 'engine'
            self.fixture(engine)
            codec = engine / 'media/ffvpx/libavutil/libmozavutil_so.list'
            saved = codec.read_bytes()
            codec.unlink()
            with self.assertRaisesRegex(RuntimeError, 'actual pinned static FFVPX'):
                LINK['collect_engine_inputs'](engine, 'x86_64-scei-ps4')
            codec.write_bytes(saved)
            nspr = engine / 'config/external/nspr/pr/unit.o'
            nspr.unlink()
            with self.assertRaisesRegex(RuntimeError, 'Missing NSPR native objects: pr'):
                LINK['collect_engine_inputs'](engine, 'x86_64-scei-ps4')
            outside = self.file(Path(tmp), 'outside.o')
            nspr.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'out-of-lane'):
                LINK['collect_engine_inputs'](engine, 'x86_64-scei-ps4')

    def test_response_flags_cross_lane_links_and_response_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = root / 'engine'
            item = self.file(engine, 'unit.o')
            outside = self.file(root, 'outside.o')
            response = self.response(engine, 'test.list', [item])
            for content in ('--allow-shlib-undefined', '../outside.o', 'desktop.so'):
                response.write_text(content)
                with self.assertRaises(ValueError):
                    LINK['response_objects'](response, engine)
            response.write_text('unit.o')
            item.unlink()
            item.symlink_to(outside)
            with self.assertRaises(ValueError):
                LINK['response_objects'](response, engine)
            response.unlink()
            response.symlink_to(self.response(root, 'outside.list', [outside]))
            with self.assertRaises(ValueError):
                LINK['response_objects'](response, engine)


if __name__ == '__main__':
    unittest.main()
