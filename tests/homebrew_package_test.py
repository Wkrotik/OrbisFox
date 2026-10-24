# SPDX-License-Identifier: MIT
"""Real SDK packaging/extraction fixtures, never console or browser execution."""
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = runpy.run_path(str(ROOT / 'scripts/gecko-package-identity.py'))
PACKAGE = runpy.run_path(str(ROOT / 'scripts/package-gecko.py'))
VERIFY = runpy.run_path(str(ROOT / 'scripts/verify-gecko-package.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HomebrewPackageTest(unittest.TestCase):
    def test_three_identities_outputs_and_cross_lane_rejection(self):
        normal = IDENTITY['package_identity']()
        mesa = IDENTITY['package_identity'](True)
        native = IDENTITY['package_identity'](sdk='homebrew')
        for key in ('title_id', 'content_id', 'profile', 'package_name'):
            self.assertEqual(len({normal[key], mesa[key], native[key]}), 3)
        self.assertEqual(IDENTITY['package_directories']('homebrew'),
                         ('build/gecko-app-homebrew', 'dist/gecko-homebrew'))
        for args in ((True, 'homebrew'), (False, 'unknown')):
            with self.assertRaises(ValueError):
                IDENTITY['package_identity'](*args)
        for report in (
                {'sdk': 'homebrew', 'package_identity': normal},
                {'sdk': 'homebrew', 'experimental_mesa': True},
                {'sdk': 'homebrew', 'package': 'dist/gecko/' + native['package_name']}):
            with self.assertRaises(ValueError):
                IDENTITY['report_identity'](report)
        self.assertEqual(IDENTITY['report_identity']({'sdk': 'homebrew', 'package_identity': native}), native)
        # Native Mesa must fail before an input read or any staging/output write.
        with self.assertRaisesRegex(ValueError, 'Mesa packaging is not implemented'):
            PACKAGE['main'](['--sdk', 'homebrew', '--mesa'])

    def test_real_native_sdk_payload_round_trip_and_binding_rejections(self):
        native = PACKAGE['native_sdk_inputs']()  # Actual pinned inventory and converter auth.
        sdk = native['path']
        identity = IDENTITY['package_identity'](sdk='homebrew')
        env = dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1')
        tool = ROOT / '.deps/OpenOrbis/PS4Toolchain/bin/linux/PkgTool.Core'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = root / 'build/gecko-app-homebrew'
            stage = build / 'pkg'
            dist = root / 'dist/gecko-homebrew'
            (stage / 'sce_sys').mkdir(parents=True)
            dist.mkdir(parents=True)
            source = root / 'fixture.cpp'
            source.write_text('thread_local int state = 7; int main() { return ++state; }\n')
            elf = build / 'orbisfox.elf'
            result = subprocess.run(DRIVER['compiler_command']([
                '--cxx', '-std=c++20', str(source), '-o', str(elf)]), capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            app = {'version': '0.69', 'sdk': 'homebrew', 'sdk_identity': native['identity'],
                   'legacy_allocator_stdio_mapping_interposition_excluded': True,
                   'final_engine_application_linked': True, 'baseline_unchanged': True,
                   'upstream_static_nss_closure_verified': True,
                   'runtime_source_sha256': {'fixture.cpp': sha(source)},
                   'executable': {'path': 'build/gecko-app-homebrew/orbisfox.elf',
                                  'bytes': elf.stat().st_size, 'sha256': sha(elf)}}
            codec = root / 'build/media-codecs/native-homebrew'
            codec.mkdir(parents=True)
            (codec / 'config.h').write_text('/* fixture config */\n')
            (codec / 'config_components.h').write_text('/* fixture components */\n')
            archive_source = root / '.deps/downloads/ffmpeg-9.0.2.tar.xz'
            archive_source.parent.mkdir(parents=True)
            archive_source.write_bytes(b'fixture archive bytes')
            scripts = root / 'scripts'
            scripts.mkdir()
            (scripts / 'build-media-codecs.py').write_text('# fixture codec producer\n')
            captured = {'config_sha256': sha(codec / 'config.h'),
                        'components_sha256': sha(codec / 'config_components.h'),
                        'source_sha256': sha(archive_source),
                        'build_identity': {'builder_sha256': sha(scripts / 'build-media-codecs.py')}}
            app['isolated_software_codecs'] = captured
            (codec / 'build-report.json').write_text(json.dumps(captured))
            app_path = build / 'build-report.json'
            app_path.write_text(json.dumps(app))
            validate = PACKAGE['validate_application']
            with patch.dict(validate.__globals__, {'ROOT': root, 'native_sdk_inputs': lambda: native}):
                self.assertEqual(validate(app, build, 'homebrew'), native)
                with self.assertRaisesRegex(RuntimeError, 'Package SDK'):
                    validate(app, build, 'openorbis')
                source.write_text(source.read_text() + '// changed\n')
                with self.assertRaisesRegex(RuntimeError, 'source changed'):
                    validate(app, build, 'homebrew')
                source.write_text('thread_local int state = 7; int main() { return ++state; }\n')
                wrong = dict(app, sdk_identity={})
                with self.assertRaisesRegex(RuntimeError, 'identity/runtime'):
                    validate(wrong, build, 'homebrew')
                for name in ('config.h', 'config_components.h', 'build-report.json'):
                    path = codec / name
                    original = path.read_bytes()
                    path.write_bytes(original + (b' ' if name.endswith('.json') else b'changed'))
                    if name.endswith('.json'):
                        altered = dict(captured, config_sha256='0' * 64)
                        path.write_text(json.dumps(altered))
                    with self.assertRaisesRegex(RuntimeError, 'Native codec materials'):
                        validate(app, build, 'homebrew')
                    path.write_bytes(original)

            def run(*args, cwd=stage):
                result = subprocess.run([str(x) for x in args], cwd=cwd, env=env,
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            run(sdk / 'bin/orbis-elf2self', '--paid', '0x3800000000000035',
                '--elf', build / 'orbisfox.oelf', elf, stage / 'eboot.bin')
            converted = runpy.run_path(str(ROOT / 'scripts/build-homebrew-sdk-probe.py'))[
                'verify_converted_elf'](build / 'orbisfox.oelf')
            self.assertTrue(converted['sectionless'])
            self.assertGreater(converted['tls_bytes'], 0)
            PACKAGE['PKG'].verify_self(stage / 'eboot.bin', native['authinfo'], 0x3800000000000035)
            entries = {'TITLE': (128, identity['title']), 'TITLE_ID': (12, identity['title_id']),
                       'CONTENT_ID': (48, identity['content_id']), 'CATEGORY': (4, 'gd'),
                       'FORMAT': (4, 'obs'), 'APP_VER': (8, '0.69'), 'VERSION': (8, '0.69')}
            command = [sdk / 'bin/orbis-mksfo', '-i', 'APP_TYPE=1', '-i', 'ATTRIBUTE=32',
                       '-i', 'SYSTEM_VER=1020', '-i', 'DOWNLOAD_DATA_SIZE=0']
            for name, (size, value) in entries.items():
                command += ['-s', str(size), name + '=' + value]
            run(*command, 'sce_sys/param.sfo')
            from PIL import Image
            Image.new('RGB', (512, 512), (30, 75, 85)).save(stage / 'sce_sys/icon0.png')
            generated = root / 'build/gecko-layout/dist/bin/greprefs.js'
            generated.parent.mkdir(parents=True)
            generated.write_text('pref("javascript.enabled", true);\n')
            resources = stage / 'gecko'
            (resources / 'defaults/pref').mkdir(parents=True)
            shutil.copyfile(generated, resources / 'greprefs.js')
            (resources / 'chrome.manifest').write_text('resource gre ./\n')
            (resources / 'defaults/pref/orbisfox.js').write_text('pref("browser.tabs.remote.autostart", false);\n')
            archive = PACKAGE['archive_resources'](resources)
            files = sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file())
            run(sdk / 'bin/orbis-mkgp4', '-c', identity['content_id'], '-o', 'project.gp4',
                'eboot.bin', 'sce_sys/param.sfo')
            PACKAGE['complete_gp4'](stage / 'project.gp4', files)
            artifact = dist / identity['package_name']
            run(sdk / 'bin/orbis-mkpkg', '-o', artifact, 'project.gp4')
            run(tool, 'pkg_validate', artifact)
            expected = {'sdk': 'homebrew', 'sdk_identity': native['identity'],
                        'self_authinfo': native['authinfo'], 'package_identity': identity,
                        'experimental_mesa': False, 'package': 'dist/gecko-homebrew/' + artifact.name,
                        'sha256': sha(artifact), 'native_executable': app['executable'],
                        'native_application_report_sha256': sha(app_path),
                        'gecko_resource_format': 'omni', 'gecko_resource_archive': archive}
            report = dist / 'build-report.json'
            report.write_text(json.dumps(expected))
            for name in ('package.py', 'gecko-package-identity.py'):
                shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
            real_run_path = runpy.run_path

            def load(path, *args, **kwargs):
                if Path(path).name == 'package-gecko.py':
                    return PACKAGE
                return real_run_path(path, *args, **kwargs)

            main = VERIFY['main']
            with patch.dict(main.__globals__, {'ROOT': root}), \
                    patch.dict(validate.__globals__, {'ROOT': root, 'native_sdk_inputs': lambda: native}), \
                    patch.object(runpy, 'run_path', side_effect=load), \
                    patch.dict(os.environ, {'OO_PS4_TOOLCHAIN': str(tool.parent.parent.parent)}):
                self.assertEqual(main(['--sdk', 'homebrew']), 0)
                proof = json.loads(report.read_text())
                self.assertTrue(proof['extracted_payload_verified'])
                self.assertEqual(proof['extracted_resource_archive_entries_verified'], 3)
                self.assertFalse((root / 'build/gecko-app').exists())
                self.assertFalse((root / 'dist/gecko').exists())
                proof['self_authinfo'] = '00' * 136
                report.write_text(json.dumps(proof))
                with self.assertRaisesRegex(ValueError, 'authentication/executable binding'):
                    main(['--sdk', 'homebrew'])
                report.write_text(json.dumps(expected))
                original = (stage / 'eboot.bin').read_bytes()
                (stage / 'eboot.bin').write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'payload mismatch: eboot.bin'):
                    main(['--sdk', 'homebrew'])


if __name__ == '__main__':
    unittest.main()
