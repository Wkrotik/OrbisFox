import ast
import importlib.util
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def module(name, script):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / script)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


PATCH = module('layout_patch', 'patch-gecko-layout.py')
CONFIGURE = module('layout_configure', 'configure-gecko-layout.py')
BUILD = module('layout_build', 'build-gecko-layout.py')
ASSETS = module('layout_assets', 'fetch-layout-assets.py')


class GeckoLayoutTests(unittest.TestCase):
    def test_lane_is_isolated_from_working_application(self):
        self.assertEqual(CONFIGURE.SOURCE, ROOT / '.deps/gecko-layout')
        self.assertEqual(CONFIGURE.BUILD, ROOT / 'build/gecko-layout')
        self.assertIn('browser', CONFIGURE.DIRECTORIES)
        self.assertIn('nsprpub', CONFIGURE.DIRECTORIES)
        self.assertIn('gfx', CONFIGURE.DIRECTORIES)
        app = (ROOT / 'gecko/orbisfox/app.mozbuild').read_text()
        self.assertIn('include("/toolkit/toolkit.mozbuild")', app)
        self.assertNotIn('"/browser"', app)

    def test_patch_is_idempotent_and_rejects_source_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'toolkit/moz.configure'
            file.parent.mkdir()
            file.write_text('def toolkit_choices(target):\n    if target.os == "WINNT":\n        pass\n')
            old = 'def toolkit_choices(target):\n    if target.os == "WINNT":'
            new = ('def toolkit_choices(target):\n'
                   '    if target.vendor == "orbis":\n'
                   '        return ("cairo-orbis",)\n'
                   '    if target.os == "WINNT":')
            PATCH.replace_once(root, 'toolkit/moz.configure', old, new)
            timestamp = file.stat().st_mtime_ns
            PATCH.replace_once(root, 'toolkit/moz.configure', old, new)
            self.assertEqual(timestamp, file.stat().st_mtime_ns)
            self.assertIn('target.vendor == "orbis"', file.read_text())
            self.assertIn('target.os == "WINNT"', file.read_text())
            file.write_text('unrecognized upstream source\n')
            with self.assertRaises(RuntimeError):
                PATCH.replace_once(root, 'toolkit/moz.configure', old, new)

    def test_entire_vendor_patch_is_timestamp_stable(self):
        source = ROOT / '.deps/gecko-layout'
        if not (source / 'toolkit/moz.configure').exists():
            self.skipTest('experimental Gecko source not prepared')
        script = ROOT / 'scripts/patch-gecko-layout.py'
        # All patched file names are literal inputs, including loop members.
        names = {node.value for node in ast.walk(ast.parse(script.read_text()))
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and '\n' not in node.value and '/' in node.value
                 and not node.value.startswith('/') and (source / node.value).is_file()}
        # Static bindings use computed wrapper paths, not literal patch inputs.
        names.update({'dom/media/platforms/ffmpeg/FFmpegLibWrapper.cpp',
                      'dom/media/platforms/ffmpeg/FFmpegLibWrapper.h',
                      'dom/media/platforms/ffmpeg/OrbisStaticFFVPX.inc',
                      'media/ffvpx/libavcodec/avcodec.symbols',
                      'media/ffvpx/libavutil/avutil.symbols'})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((source / name).read_bytes())
            result = subprocess.run([sys.executable, str(script), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # OS_LIBS treats bare absolute archives as -l/path. Generated
            # compiler-driver arguments must bypass that system-name rewrite.
            codec_build = ast.parse((root / 'dom/media/platforms/ffmpeg/moz.build').read_text())
            codec_flags = [flag for node in ast.walk(codec_build)
                           if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
                           and node.target.id == 'OS_LIBS'
                           for flag in ast.literal_eval(node.value)]
            expected_archives = ['-Wl,' + str(ROOT / 'build/media-codecs/native' / ('liborbis_' + name + '.a'))
                                 for name in ('avcodec', 'swresample', 'avutil')]
            self.assertEqual(codec_flags, ['-Wl,--start-group', *expected_archives, '-Wl,--end-group'])
            first = {name: ((root / name).read_bytes(), (root / name).stat().st_mtime_ns)
                     for name in names}
            subprocess.run([sys.executable, str(script), str(root)], check=True,
                           capture_output=True, text=True)
            second = {name: ((root / name).read_bytes(), (root / name).stat().st_mtime_ns)
                      for name in names}
            self.assertEqual(first, second)

    def test_freetype_guards_migrate_duplicates_and_stay_idempotent(self):
        original = ('#ifdef MOZ_WIDGET_ANDROID\n'
                    '#elif defined(MOZ_WIDGET_ANDROID)\n'
                    '#elif defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS) || defined(MOZ_WIDGET_ORBIS)\n'
                    '#ifdef MOZ_WIDGET_GTK\n')
        expected = ('#if defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                    '#elif defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                    '#elif defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                    '#ifdef MOZ_WIDGET_GTK\n')
        self.assertEqual(PATCH.freetype_guards(original), expected)
        self.assertEqual(PATCH.freetype_guards(expected), expected)

    def test_patch_migrates_known_variant_without_duplicate_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'config'
            path.write_text('old-port\noriginal-anchor\n')
            PATCH.replace_once(root, 'config',
                               ('old-port\noriginal-anchor', 'original-anchor'),
                               'new-port\noriginal-anchor')
            self.assertEqual(path.read_text(), 'new-port\noriginal-anchor\n')
            PATCH.replace_once(root, 'config',
                               ('old-port\noriginal-anchor', 'original-anchor'),
                               'new-port\noriginal-anchor')
            self.assertEqual(path.read_text().count('new-port'), 1)

    def test_native_services_do_not_pull_in_a_desktop_backend(self):
        widget = ROOT / 'gecko/widget/orbis'
        self.assertIn('nsBaseAppShell', (widget / 'nsAppShell.h').read_text())
        events = (widget / 'nsAppShell.cpp').read_text()
        self.assertIn('while (!mPending)', events)
        self.assertIn('HeadlessScreenHelper', events)
        self.assertIn('NativeEventCallback();', events)
        self.assertNotIn('#include <gtk', events)
        services = (widget / 'components.conf').read_text()
        self.assertIn('appshell/orbis;1', services)
        self.assertIn('HeadlessClipboard', services)
        self.assertNotIn("'@mozilla.org/parent/filepicker;1'", services)

    def test_build_report_keeps_actual_diagnostics(self):
        self.assertEqual(BUILD.build_errors(
            '15 | pub enum DateError {\n'
            '159 | ) -> Result<CertificateDirectoryTable, error::Error> {\n'
            'warning: use of deprecated method `std::error::Error::description`\n'
            'error[E0463]: missing crate\n'
            '/src/file.c:15:10: fatal error: missing header\n'
            'make[3]: *** [target] Error 1\n'
            'warning: unused variable\n'), [
                'error[E0463]: missing crate',
                '/src/file.c:15:10: fatal error: missing header',
                'make[3]: *** [target] Error 1'])

    def test_orbis_wasm_signal_recovery_is_unavailable_without_disabling_baseline_jit(self):
        source = ROOT / '.deps/gecko-layout/js/src/wasm/WasmSignalHandlers.cpp'
        if not source.exists():
            self.skipTest('pinned Gecko source unavailable')
        text = source.read_text()
        self.assertEqual(text.count('#if !defined(JS_CODEGEN_NONE) && !defined(MOZ_WIDGET_ORBIS)\n'), 2)
        self.assertEqual(text.count('#if defined(JS_CODEGEN_NONE) || defined(MOZ_WIDGET_ORBIS)\n'), 4)
        self.assertIn('bool wasm::EnsureFullSignalHandlers(JSContext* cx) {\n'
                      '#if defined(JS_CODEGEN_NONE) || defined(MOZ_WIDGET_ORBIS)\n  return false;', text)
        self.assertNotIn('#define JS_CODEGEN_NONE', text)
        executable = (ROOT / '.deps/gecko-layout/js/src/jit/ProcessExecutableMemory.cpp').read_text()
        self.assertIn('orbisfox::reserve_orbis_executable_memory(bytes)', executable)

    def test_orbis_nspr_uses_sdk_stat_and_posix_calls(self):
        header = (ROOT / 'gecko/nsprpub/pr/include/md/_orbis.h').read_text()
        self.assertIn('#define _PR_STAT_HAS_ST_ATIM\n', header)
        self.assertIn('#define _PR_HAVE_GETHOSTBYNAME2\n', header)
        self.assertIn('select(nfds, r, w, e, tv)', header)
        self.assertIn('poll(fds, nfds, timeout)', header)
        self.assertNotIn('syscall(', header)
        self.assertNotIn('#define _PR_HAVE_SYSV_SEMAPHORES', header)
        self.assertNotIn('#define _PR_STAT_HAS_ST_ATIMESPEC', header)

    def test_orbis_uses_upstream_software_vsync(self):
        header = (ROOT / 'gecko/gfx/thebes/gfxOrbisPlatform.h').read_text()
        source = (ROOT / 'gecko/gfx/thebes/gfxOrbisPlatform.cpp').read_text()
        self.assertIn('CreateGlobalHardwareVsyncSource()', header)
        self.assertIn('return GetSoftwareVsyncSource();', source)

    def test_offline_assets_verify_before_write_and_keep_cache(self):
        data = b'verified asset'
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'font'
            with patch.object(ASSETS, 'urlopen', return_value=io.BytesIO(b'corrupt')):
                with self.assertRaises(RuntimeError):
                    ASSETS.checked_file(path, 'https://example.invalid/font', digest)
            self.assertFalse(path.exists())
            with patch.object(ASSETS, 'urlopen', return_value=io.BytesIO(data)):
                self.assertEqual(ASSETS.checked_file(path, 'https://example.invalid/font', digest), data)
            timestamp = path.stat().st_mtime_ns
            with patch.object(ASSETS, 'urlopen', side_effect=AssertionError('cache must be used')):
                self.assertEqual(ASSETS.checked_file(path, 'https://example.invalid/font', digest), data)
            self.assertEqual(path.stat().st_mtime_ns, timestamp)
            path.write_bytes(b'corrupt')
            with self.assertRaises(RuntimeError):
                ASSETS.checked_file(path, 'https://example.invalid/font', digest)

    def test_nspr_definitions_cross_compile_against_sdk(self):
        include = ROOT / 'build/gecko-layout/dist/include/nspr'
        if not (include / 'prcpucfg.h').exists():
            self.skipTest('experimental Gecko configure has not generated NSPR headers')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'probe.c'
            source.write_text('#include "md/_orbis.h"\n'
                              '#include <sys/stat.h>\n'
                              '#include <pthread.h>\n'
                              '#include <unicode/platform.h>\n'
                              '#include <msgpack/predef/other/endian.h>\n'
                              '_Static_assert(sizeof(PRInt64) == 8, "NSPR int64");\n'
                              '_Static_assert(sizeof(pthread_mutexattr_t) == 8, "native attr");\n'
                              '_Static_assert(FIONREAD == 0x4004667fUL, "BSD ioctl encoding");\n'
                              '_Static_assert(U_IS_BIG_ENDIAN == 0, "ICU target byte order");\n'
                              '_Static_assert(MSGPACK_ENDIAN_LITTLE_BYTE != 0, "msgpack target byte order");\n'
                              '_Static_assert(MSGPACK_ENDIAN_BIG_BYTE == 0, "msgpack not big endian");\n'
                              'long stat_time(struct stat *s) { return s->st_mtim.tv_nsec; }\n')
            subprocess.run([str(ROOT / 'scripts/orbis-cc.py'), '-std=c11', '-c',
                            '-D_PR_PTHREADS', '-DFREEBSD', '-DXP_UNIX',
                            '-I' + str(include),
                            '-I' + str(ROOT / '.deps/gecko-layout/nsprpub/pr/include'),
                            '-I' + str(ROOT / '.deps/gecko-layout/intl/icu/source/common'),
                            '-I' + str(ROOT / '.deps/gecko-layout/third_party/msgpack/include'),
                            '-I' + str(ROOT / 'gecko/nsprpub/pr/include'),
                            str(source), '-o', str(Path(directory) / 'probe.o')],
                           check=True, capture_output=True, text=True)

    def test_libevent_configuration_cross_compiles_without_bsd_kernel_claims(self):
        include = ROOT / '.deps/gecko-layout/ipc/chromium/src/third_party/libevent/orbis'
        if not (include / 'event2/event-config.h').exists():
            self.skipTest('experimental libevent port not prepared')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'probe.c'
            source.write_text('#include "event2/event-config.h"\n'
                              '#include <sys/types.h>\n#include <pthread.h>\n'
                              '#include <netinet/in.h>\n'
                              '#if defined(EVENT__HAVE_KQUEUE) || defined(EVENT__HAVE_SYSCTL) || '
                              'defined(EVENT__HAVE_ARC4RANDOM) || defined(EVENT__HAVE_GETRANDOM)\n'
                              '#error Unsupported firmware capability advertised\n#endif\n'
                              '#if !EVENT__HAVE_POLL || !EVENT__HAVE_SELECT\n'
                              '#error Portable event backends missing\n#endif\n'
                              '_Static_assert(EVENT__SIZEOF_INT == sizeof(int), "int ABI");\n'
                              '_Static_assert(EVENT__SIZEOF_LONG == sizeof(long), "long ABI");\n'
                              '_Static_assert(EVENT__SIZEOF_TIME_T == sizeof(time_t), "time ABI");\n'
                              '_Static_assert(EVENT__SIZEOF_PTHREAD_T == sizeof(pthread_t), "thread ABI");\n'
                              '_Static_assert(sizeof(((struct sockaddr_in*)0)->sin_len) == 1, "IPv4 length");\n'
                              '_Static_assert(sizeof(((struct sockaddr_in6*)0)->sin6_len) == 1, "IPv6 length");\n')
            subprocess.run([str(ROOT / 'scripts/orbis-cc.py'), '-std=c11', '-c',
                            '-I' + str(include), str(source), '-o',
                            str(Path(directory) / 'probe.o')], check=True,
                           capture_output=True, text=True)

    def test_posix_mapping_host_behavior_with_sanitizers(self):
        source = ROOT / '.deps/gecko-layout/toolkit/crashreporter/google-breakpad/src'
        if not (source / 'common/linux/memory_mapped_file.cc').exists():
            self.skipTest('experimental Breakpad source not prepared')
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'mapping-test'
            subprocess.run(['clang++', '-std=c++20', '-D__ORBIS__',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I' + str(source), str(ROOT / 'tests/gecko_mapping_test.cpp'),
                            '-o', str(executable)], check=True, capture_output=True, text=True)
            subprocess.run([str(executable)], check=True, capture_output=True, text=True,
                           timeout=10)

    def test_nss_endianness_cross_compile_and_sanitized_host_behavior(self):
        paths = ('libcrux/karamel/krml/lowstar_endianness.h',
                 'libcrux/karamel/endianness.h',
                 'verified/karamel/include/krml/lowstar_endianness.h')
        root = ROOT / '.deps/gecko-layout/security/nss/lib/freebl'
        if not all((root / name).exists() for name in paths):
            self.skipTest('experimental NSS source not prepared')
        with tempfile.TemporaryDirectory() as directory:
            for index, name in enumerate(paths):
                with self.subTest(header=name):
                    output = Path(directory) / f'endian-{index}'
                    source = ROOT / 'tests/gecko_endianness_test.c'
                    header = '-DHEADER="' + str(root / name) + '"'
                    subprocess.run([str(ROOT / 'scripts/orbis-cc.py'), '-std=c11',
                                    header, '-c', str(source), '-o', str(output) + '.o'],
                                   check=True, capture_output=True, text=True)
                    subprocess.run(['clang', '-std=c11', '-D__ORBIS__', '-D_GNU_SOURCE',
                                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                                    header, str(source), '-o', str(output)],
                                   check=True, capture_output=True, text=True)
                    subprocess.run([str(output)], check=True, capture_output=True,
                                   text=True, timeout=10)

    def test_locale_fallback_compiles_against_real_gecko_headers(self):
        build = ROOT / 'build/gecko-layout'
        if not (build / 'mozilla-config.h').exists() or not (
                ROOT / '.deps/gecko-layout/intl/locale/OSPreferences.h').exists():
            self.skipTest('experimental Gecko headers not generated')
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([str(ROOT / 'scripts/orbis-cxx.py'), '-std=c++20', '-c',
                            '-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
                            '-fno-exceptions', '-fno-rtti', '-fPIC',
                            '-fno-sized-deallocation', '-fno-aligned-new',
                            '-include', str(build / 'mozilla-config.h'),
                            '-I' + str(build / 'dist/include'),
                            '-I' + str(build / 'dist/include/nspr'),
                            '-I' + str(ROOT / '.deps/gecko-layout/intl/locale'),
                            str(ROOT / 'gecko/intl/locale/orbis/OSPreferences_orbis.cpp'),
                            '-o', str(Path(directory) / 'locale.o')],
                           check=True, capture_output=True, text=True)

    def test_copy_preserves_timestamp_for_identical_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nested/input'
            CONFIGURE.write_changed(path, b'first')
            timestamp = path.stat().st_mtime_ns
            CONFIGURE.write_changed(path, b'first')
            self.assertEqual(path.stat().st_mtime_ns, timestamp)
            CONFIGURE.write_changed(path, b'second')
            self.assertEqual(path.read_bytes(), b'second')


if __name__ == '__main__':
    unittest.main()
