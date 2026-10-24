import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FETCH = load('fetch-console-crash')
DEPLOY = load('deploy-console')


class FakeFTP:
    def __init__(self, content=b'evidence'):
        self.content = content
        self.requests = []
        self.directory = ''

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def connect(self, *args, **kwargs):
        pass

    def login(self, *args):
        pass

    def cwd(self, directory):
        self.directory = directory

    def nlst(self):
        if self.directory == '/data/orbisfox':
            return ['startup-layout.log', 'gecko-load.log.child-1.moz_log', 'heap-debug', 'heap-crash-trace.bin']
        if self.directory == '/data/sce_coredumps':
            return ['ORBF00001_9', 'ORBF00001_10', 'OTHER0001_99']
        return ['dump.sorbisdmp', 'report.log']

    def retrbinary(self, command, callback, blocksize):
        self.requests.append(command)
        callback(self.content[:3])
        callback(self.content[3:])


class ConsoleWorkflowTests(unittest.TestCase):
    def test_fetch_atomic_hash_and_refuse_changed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'dump'
            record = FETCH.retrieve(FakeFTP(), '/remote/dump', target)
            self.assertEqual(target.read_bytes(), b'evidence')
            self.assertEqual(record['sha256'], hashlib.sha256(b'evidence').hexdigest())
            FETCH.retrieve(FakeFTP(), '/remote/dump', target)  # Same evidence is idempotent.
            with self.assertRaises(FileExistsError):
                FETCH.retrieve(FakeFTP(b'changed'), '/remote/dump', target)
            self.assertEqual(target.read_bytes(), b'evidence')
            self.assertEqual(list(Path(directory).glob('.fetch-*')), [])

    def test_fetch_bound_leaves_no_partial_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'dump'
            with self.assertRaisesRegex(ValueError, 'bounded retrieval limit'):
                FETCH.retrieve(FakeFTP(), '/remote/dump', target, limit=4)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_fetch_latest_title_dump_freezes_kernel_and_never_stale_heap_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel = root / 'live.log'
            kernel.write_bytes(b'kernel-prefix')
            ftp = FakeFTP()
            with patch.object(FETCH, 'FTP', return_value=ftp), patch('sys.argv',
                    ['fetch', '--host', 'console.example.test', '--version', '0.50', '--out', str(root / 'out'), '--kernel-log', str(kernel)]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(FETCH.main(), 0)
            report = json.loads((root / 'out/crash-fetch-report.json').read_text())
            self.assertEqual(report['selected_latest_title_dump'], 'ORBF00001_10')
            self.assertTrue(report['dump_version_association_requires_matching_kernel_run'])
            self.assertEqual(report['errors'], [])
            self.assertEqual(len(report['files']), 4)
            self.assertTrue(report['markers_current']['heap-debug'])
            self.assertFalse(report['heap_trace_fetched'])
            self.assertFalse(report['console_files_changed'])
            self.assertTrue(all('heap-crash-trace' not in item for item in ftp.requests))
            self.assertEqual((root / 'out/kernel-crash-snapshot.log').read_bytes(), kernel.read_bytes())

    def test_fetch_report_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'crash-fetch-report.json'
            target.write_text('old evidence')
            with patch.object(FETCH, 'FTP') as ftp, patch('sys.argv', ['fetch', '--host', 'console.example.test', '--version', '0.50', '--out', directory]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    FETCH.main()
                ftp.assert_not_called()
            self.assertEqual(target.read_text(), 'old evidence')

    def test_preserve_is_independent_and_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'evidence'
            source.write_bytes(b'matched')
            DEPLOY.preserve(source, target)
            self.assertNotEqual(source.stat().st_ino, target.stat().st_ino)
            DEPLOY.preserve(source, target)
            source.write_bytes(b'new build')
            self.assertEqual(target.read_bytes(), b'matched')
            with self.assertRaises(FileExistsError):
                DEPLOY.preserve(source, target)

    def candidate_files(self, root):
        package = root / 'dist/gecko'
        native = root / 'build/gecko-app'
        package.mkdir(parents=True)
        native.mkdir(parents=True)
        (root / 'src').mkdir()
        (root / 'src/test.cpp').write_bytes(b'compiled source')
        (package / 'OrbisFox.pkg').write_bytes(b'pkg')
        (native / 'orbisfox.elf').write_bytes(b'elf')
        pkg = {'version': '0.51', 'new_package_created': True, 'extracted_payload_verified': True,
               'bytes': 3, 'sha256': hashlib.sha256(b'pkg').hexdigest()}
        app = {'version': '0.51', 'final_engine_application_linked': True, 'baseline_unchanged': True,
               'executable': {'bytes': 3, 'sha256': hashlib.sha256(b'elf').hexdigest()},
               'runtime_source_sha256': {'src/test.cpp': hashlib.sha256(b'compiled source').hexdigest()}}
        pkg['native_executable'] = dict(app['executable'])
        (package / 'build-report.json').write_text(json.dumps(pkg))
        (native / 'build-report.json').write_text(json.dumps(app))
        return pkg, app

    def native_browser_files(self, root):
        package, app = self.candidate_files(root)
        (root / 'dist/gecko').rename(root / 'dist/gecko-homebrew')
        (root / 'build/gecko-app').rename(root / 'build/gecko-app-homebrew')
        dist, build = root / 'dist/gecko-homebrew', root / 'build/gecko-app-homebrew'
        identity = DEPLOY.IDENTITY['package_identity'](sdk='homebrew')
        (dist / 'OrbisFox.pkg').rename(dist / identity['package_name'])
        app.update(sdk='homebrew', sdk_identity={'revision': 'fixture'})
        (build / 'build-report.json').write_text(json.dumps(app))
        package.update(sdk='homebrew', sdk_identity=app['sdk_identity'],
                       package_identity=identity, package='dist/gecko-homebrew/' + identity['package_name'],
                       native_full_gecko_linked=True, extracted_sfo_verified=True,
                       ffmpeg_source_and_configuration_match_linked_application=True,
                       self_authentication_metadata_verified={
                           'authinfo_bytes': 136, 'paid': '0x3800000000000035', 'signature_verified': True},
                       native_application_report_sha256=hashlib.sha256(
                           (build / 'build-report.json').read_bytes()).hexdigest())
        (dist / 'build-report.json').write_text(json.dumps(package))
        return package, app

    def test_native_browser_validation_bindings_and_packaging_preflight(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            package, app = self.native_browser_files(root)
            with patch.object(DEPLOY.runpy, 'run_path') as load:
                validate = load.return_value['validate_application']
                self.assertEqual(DEPLOY.candidate('homebrew'), ('0.51', package, app))
                validate.assert_called_once_with(app, root / 'build/gecko-app-homebrew', 'homebrew')
                report = root / 'dist/gecko-homebrew/build-report.json'
                for changes in ({'sdk': 'openorbis'}, {'extracted_sfo_verified': False},
                                {'native_application_report_sha256': '0' * 64},
                                {'self_authentication_metadata_verified': True}):
                    report.write_text(json.dumps(dict(package, **changes)))
                    with self.assertRaises(ValueError):
                        DEPLOY.candidate('homebrew')
                report.write_text(json.dumps(package))
                (root / 'dist/gecko-homebrew/OrbisFox-Homebrew.pkg').write_bytes(b'bad')
                with self.assertRaisesRegex(ValueError, 'bytes/hash changed'):
                    DEPLOY.candidate('homebrew')

    def test_native_browser_deployment_is_upload_only_and_preserves_all_installers(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            package, app = self.native_browser_files(root)
            (root / 'Makefile').write_text('fixture')
            state = {'installers': ['OrbisFox.pkg', 'OrbisFox-Mesa.pkg', 'unrelated.pkg'], 'markers': {}}
            with patch.object(DEPLOY, 'candidate', return_value=('0.51', package, app)), \
                    patch.object(DEPLOY, 'console_state', return_value=state), \
                    patch.object(DEPLOY, 'prepare_capture') as capture, \
                    patch.object(DEPLOY.subprocess, 'run') as run, \
                    patch('sys.argv', ['deploy', '--host', 'console.example.test', '--sdk', 'homebrew']), \
                    contextlib.redirect_stdout(io.StringIO()):
                run.return_value.returncode = 0
                self.assertEqual(DEPLOY.main(), 0)
                capture.assert_not_called()
                self.assertEqual(run.call_args.args[0][-2:], ['--sdk', 'homebrew'])
            report = json.loads((root / 'build/hardware-0.51-homebrew/deployment-report.json').read_text())
            self.assertTrue(report['uploaded'])
            self.assertTrue(report['unrelated_installers_preserved'])
            self.assertEqual(report['remote_path'], '/data/pkg/OrbisFox-Homebrew.pkg')
            self.assertFalse(report['installed'] or report['launched'] or report['capture']['new_reader'])
            with patch.object(DEPLOY, 'candidate') as candidate, \
                    patch('sys.argv', ['deploy', '--host', 'console.example.test', '--sdk', 'homebrew', '--capture']), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    DEPLOY.main()
                candidate.assert_not_called()

    def test_candidate_requires_matching_artifacts_and_runtime_sources(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            self.candidate_files(root)
            self.assertEqual(DEPLOY.candidate()[0], '0.51')
            (root / 'src/test.cpp').write_bytes(b'edited after build')
            with self.assertRaisesRegex(ValueError, 'Runtime source changed'):
                DEPLOY.candidate()

    def test_mesa_candidate_uses_distinct_installer_and_requires_matching_flavor(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            pkg, app = self.candidate_files(root)
            (root / 'dist/gecko/OrbisFox.pkg').rename(root / 'dist/gecko/OrbisFox-Mesa.pkg')
            pkg.update(experimental_mesa=True, package_identity=DEPLOY.IDENTITY['package_identity'](True),
                       package='dist/gecko/OrbisFox-Mesa.pkg')
            app['experimental_native_mesa'] = {'verified_dependency_fixture': True}
            (root / 'dist/gecko/build-report.json').write_text(json.dumps(pkg))
            (root / 'build/gecko-app/build-report.json').write_text(json.dumps(app))
            self.assertEqual(DEPLOY.candidate()[0], '0.51')
            app['experimental_native_mesa'] = None
            (root / 'build/gecko-app/build-report.json').write_text(json.dumps(app))
            with self.assertRaisesRegex(ValueError, 'flavor mismatch'):
                DEPLOY.candidate()

    def test_candidate_rejects_incomplete_native_build(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            pkg, app = self.candidate_files(root)
            app['final_engine_application_linked'] = False
            (root / 'build/gecko-app/build-report.json').write_text(json.dumps(app))
            with self.assertRaisesRegex(ValueError, 'verification incomplete'):
                DEPLOY.candidate()

    def test_candidate_rejects_same_version_package_from_different_elf(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            pkg, app = self.candidate_files(root)
            pkg['native_executable']['sha256'] = '0' * 64
            (root / 'dist/gecko/build-report.json').write_text(json.dumps(pkg))
            with self.assertRaisesRegex(ValueError, 'different native ELF'):
                DEPLOY.candidate()

    def test_candidate_rejects_wrong_package_hash(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            self.candidate_files(root)
            (root / 'dist/gecko/OrbisFox.pkg').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'Package bytes/hash'):
                DEPLOY.candidate()

    def test_deploy_main_archives_and_uploads_without_install_or_launch(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            self.candidate_files(root)
            (root / 'Makefile').write_text('fixture')
            before = {'installers': ['unrelated.pkg', 'OrbisFox.pkg'], 'markers': {}}
            with patch.object(DEPLOY, 'console_state', side_effect=[before, before]), patch.object(DEPLOY, 'prepare_capture', return_value={'active': False}) as capture, patch.object(DEPLOY.subprocess, 'run') as run, patch('sys.argv', ['deploy', '--host', 'console.example.test']), contextlib.redirect_stdout(io.StringIO()):
                run.return_value.returncode = 0
                self.assertEqual(DEPLOY.main(), 0)
                capture.assert_not_called()
            report = json.loads((root / 'build/hardware-0.51/deployment-report.json').read_text())
            self.assertTrue(report['uploaded'])
            self.assertTrue(report['uploader_full_remote_SHA256_verified'])
            self.assertFalse(report['installed'])
            self.assertFalse(report['launched'])
            self.assertFalse(report['console_settings_changed'])
            self.assertEqual((root / 'build/hardware-0.51/orbisfox.elf').read_bytes(), b'elf')
            self.assertEqual(run.call_args.kwargs['timeout'], 110)
            self.assertIn('--gecko', run.call_args.args[0])

    def test_same_version_redeployment_preserves_old_and_new_matched_artifacts(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            self.candidate_files(root)
            (root / 'Makefile').write_text('fixture')
            out = root / 'build/hardware-0.51'
            old = out / 'deployments/previous'
            old.mkdir(parents=True)
            for name, data in [('OrbisFox.pkg', b'previous-pkg'), ('orbisfox.elf', b'previous-elf')]:
                (out / name).write_bytes(data)
                (old / name).write_bytes(data)
            before = {'installers': ['unrelated.pkg', 'OrbisFox.pkg'], 'markers': {}}
            with patch.object(DEPLOY, 'console_state', return_value=before), patch.object(DEPLOY, 'prepare_capture') as capture, patch.object(DEPLOY.subprocess, 'run') as run, patch('sys.argv', ['deploy', '--host', 'console.example.test']), contextlib.redirect_stdout(io.StringIO()):
                run.return_value.returncode = 0
                self.assertEqual(DEPLOY.main(), 0)
                capture.assert_not_called()
            report = json.loads((out / 'deployment-report.json').read_text())
            self.assertTrue(report['uploaded'])
            for name, data in [('OrbisFox.pkg', b'pkg'), ('orbisfox.elf', b'elf')]:
                artifact = report['artifacts'][name]
                archived = Path(artifact['path'])
                self.assertTrue(archived.is_relative_to(out / 'deployments'))
                self.assertEqual(archived.read_bytes(), data)
                self.assertEqual(artifact['sha256'], hashlib.sha256(data).hexdigest())
                self.assertNotEqual(archived.stat().st_ino, (root / ('dist/gecko/' if name.endswith('.pkg') else 'build/gecko-app/') / name).stat().st_ino)
            self.assertEqual((out / 'OrbisFox.pkg').read_bytes(), b'previous-pkg')
            self.assertEqual((out / 'orbisfox.elf').read_bytes(), b'previous-elf')
            self.assertEqual((old / 'OrbisFox.pkg').read_bytes(), b'previous-pkg')
            self.assertEqual((old / 'orbisfox.elf').read_bytes(), b'previous-elf')

    def test_deploy_failure_keeps_archives_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(DEPLOY, 'ROOT', Path(directory)):
            root = Path(directory)
            self.candidate_files(root)
            (root / 'Makefile').write_text('fixture')
            with patch.object(DEPLOY, 'console_state', return_value={'installers': [], 'markers': {}}), patch.object(DEPLOY, 'prepare_capture', return_value={'active': False}), patch.object(DEPLOY.subprocess, 'run') as run, patch('sys.argv', ['deploy', '--host', 'console.example.test']), contextlib.redirect_stdout(io.StringIO()):
                run.return_value.returncode = 1
                self.assertEqual(DEPLOY.main(), 1)
            report = json.loads((root / 'build/hardware-0.51/deployment-report.json').read_text())
            self.assertFalse(report['uploaded'])
            self.assertTrue(report['errors'])
            self.assertEqual((root / 'build/hardware-0.51/OrbisFox.pkg').read_bytes(), b'pkg')

    def probe_files(self, root):
        base = root / 'build/shared-memory-probe'; base.mkdir(parents=True)
        name = DEPLOY.UPLOADER['SHARED_MEMORY_PROBE_PACKAGE']
        (base / name).write_bytes(b'probe-pkg')
        (base / 'shared-memory-probe.elf').write_bytes(b'probe-elf')
        (root / 'Makefile').write_text('fixture')
        report = {'native_linked': True,
                  'elf': {'file': 'build/shared-memory-probe/shared-memory-probe.elf',
                          'bytes': 9, 'sha256': hashlib.sha256(b'probe-elf').hexdigest()},
                  'sources': {'Makefile': hashlib.sha256(b'fixture').hexdigest()},
                  'package': {'file': 'build/shared-memory-probe/' + name,
                              'bytes': 9, 'sha256': hashlib.sha256(b'probe-pkg').hexdigest(),
                              'title_id': 'SHMP00001', 'content_id': 'IV0000-SHMP00001_00-SHMEMPROBE000001',
                              'sections_verified': 17, 'extracted_sfo_verified': True,
                              'extracted_files_verified': ['eboot.bin', 'sce_sys/param.sfo', 'sce_sys/icon0.png', 'source.tar.gz'],
                              'self': {'authinfo_bytes': 136, 'paid': '0x3800000000000035', 'signature_verified': True}}}
        (base / 'build-report.json').write_text(json.dumps(report))
        return report

    def test_probe_candidate_rejects_changed_sources_and_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); report = self.probe_files(root)
            validate = DEPLOY.UPLOADER['shared_memory_probe_candidate']
            self.assertEqual(validate(root), report)
            (root / 'Makefile').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'source changed'): validate(root)
            (root / 'Makefile').write_text('fixture')
            (root / report['elf']['file']).write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'artifact mismatch'): validate(root)

    def test_probe_deployment_is_separate_and_cannot_start_capture(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(DEPLOY, 'ROOT', Path(folder)):
            root = Path(folder); self.probe_files(root)
            state = {'installers': ['OrbisFox.pkg', 'OrbisFox-Mesa.pkg', 'unrelated.pkg'], 'markers': {}}
            with patch.object(DEPLOY, 'console_state', return_value=state), patch.object(DEPLOY, 'prepare_capture') as capture, patch.object(DEPLOY.subprocess, 'run') as run, patch('sys.argv', ['deploy', '--host', 'console.example.test', '--shared-memory-probe']), contextlib.redirect_stdout(io.StringIO()):
                run.return_value.returncode = 0
                self.assertEqual(DEPLOY.main(), 0)
                capture.assert_not_called()
                self.assertIn('--shared-memory-probe', run.call_args.args[0])
                self.assertNotIn('--gecko', run.call_args.args[0])
            report = json.loads((root / 'build/hardware-00.01-shmem/deployment-report.json').read_text())
            self.assertTrue(report['uploaded'])
            self.assertTrue(report['unrelated_installers_preserved'])
            self.assertFalse(report['installed'])
            self.assertFalse(report['launched'])
            self.assertFalse(report['capture']['new_reader'])
            self.assertEqual((root / 'build/hardware-00.01-shmem/shared-memory-probe.elf').read_bytes(), b'probe-elf')
            with patch('sys.argv', ['deploy', '--host', 'console.example.test', '--shared-memory-probe', '--capture']), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): DEPLOY.main()

    def sdk_probe_files(self, root):
        base = root / 'build/homebrew-sdk-probe/1792432504891457491'
        (base / 'pkg').mkdir(parents=True)
        name = DEPLOY.UPLOADER['HOMEBREW_SDK_PROBE_PACKAGE']
        report_path = base / 'build-report.json'
        def source(name, data=b'fixture'):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        report = {'result': 0, 'package_verified': True, 'title_id': 'OSDK00001',
                  'content_id': 'IV0000-OSDK00001_00-SDKPROBE00000001',
                  'package_path': str((base / name).relative_to(root)),
                  'package': source(str((base / name).relative_to(root)), b'sdk-pkg'),
                  'elf': source(str((base / 'runtime.elf').relative_to(root)), b'sdk-elf'),
                  'eboot': source(str((base / 'pkg/eboot.bin').relative_to(root)), b'sdk-self'),
                  'extracted_files': ['eboot.bin', 'sce_sys/param.sfo', 'sce_sys/icon0.png', 'source.tar.gz'],
                  'self': {'authinfo_bytes': 136, 'paid': '0x3800000000000035', 'signature_verified': True},
                  'oelf_layout': {'sectionless': True, 'mapped_segments': 3, 'tls_bytes': 4},
                  'application_exit': {'hook': 'catchReturnFromMain', 'service': 'sceSystemServiceLoadExec',
                                       'request': 'exit', 'general_cpp_teardown_proven': False},
                  'system_dependencies': ['libkernel.sprx', 'libSceLibcInternal.sprx', 'libSceSysmodule.sprx',
                                          'libSceNet.sprx', 'libSceSystemService.sprx'],
                  'sdk_version': 'v0.2.1', 'sdk_revision': 'pinned-revision', 'sdk_archive_sha256': 'pinned-hash'}
        for field, names in [('native_sources', ['tests/homebrew_sdk_probe.c']),
                             ('producer_sources', ['scripts/build-homebrew-sdk-probe.py', 'scripts/fetch-homebrew-sdk.py']),
                             ('package_sources', ['scripts/package.py', 'scripts/build-shared-memory-probe.py',
                                                  'docs/HOMEBREW_SDK.md', 'LICENSES/README.md'])]:
            report[field] = {name: source(name) for name in names}
        report['sdk_inventory'] = source('.deps/ps4-homebrew-sdk-v0.2.1/source-report.json')
        source('Makefile')
        report_path.write_text(json.dumps(report))
        (base.parent / 'latest-build.json').write_text(json.dumps({'report': str(report_path.relative_to(root))}))
        return report_path, report

    def test_sdk_probe_candidate_binds_sources_artifacts_and_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path, report = self.sdk_probe_files(root)
            validate = DEPLOY.UPLOADER['homebrew_sdk_probe_candidate']
            fetch = {'VERSION': 'v0.2.1', 'REVISION': 'pinned-revision', 'SHA256': 'pinned-hash',
                     'verify_sdk': lambda sdk: None}
            with patch.object(DEPLOY.runpy, 'run_path', return_value=fetch):
                self.assertEqual(validate(root), (path, report))
                (root / 'tests/homebrew_sdk_probe.c').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'changed'): validate(root)
                (root / 'tests/homebrew_sdk_probe.c').write_bytes(b'fixture')
                (root / report['package_path']).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'changed'): validate(root)

    def test_dialog_probe_requires_extra_source_and_declaration_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path, report = self.sdk_probe_files(root)
            report.update(probe_mode='dialog', app_version='00.02',
                          service_declarations={'revision': 'public-headers'})
            for field, names in (
                    ('native_sources', ['tests/homebrew_dialog_probe.h']),
                    ('producer_sources', ['scripts/fetch-homebrew-service-headers.py']),
                    ('package_sources', ['tests/homebrew_dialog_probe.h', 'scripts/fetch-homebrew-service-headers.py'])):
                for name in names:
                    source = root / name; source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(b'fixture')
                    report[field][name] = {'bytes': 7, 'sha256': hashlib.sha256(b'fixture').hexdigest()}
            validate = DEPLOY.UPLOADER['homebrew_sdk_probe_candidate']
            fetch = {'VERSION': 'v0.2.1', 'REVISION': 'pinned-revision', 'SHA256': 'pinned-hash',
                     'verify_sdk': lambda sdk: None}
            def inputs(name):
                if str(name).endswith('fetch-homebrew-service-headers.py'):
                    return {'verify': lambda: {'revision': 'public-headers'}}
                return fetch
            with patch.object(DEPLOY.runpy, 'run_path', side_effect=inputs):
                path.write_text(json.dumps(report))
                self.assertEqual(validate(root), (path, report))
                report['service_declarations'] = {'revision': 'changed'}
                path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, 'declarations changed'): validate(root)
                report['service_declarations'] = {'revision': 'public-headers'}
                saved = report['native_sources'].pop('tests/homebrew_dialog_probe.h')
                path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, 'lacks source'): validate(root)
                report['native_sources']['tests/homebrew_dialog_probe.h'] = saved
                report['app_version'] = '00.01'; path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, 'version/mode'): validate(root)
                report['probe_mode'] = 'unknown'; path.write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, 'Unknown'): validate(root)

    def test_sdk_probe_rejects_build_pointer_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.sdk_probe_files(root)
            (root / 'build/homebrew-sdk-probe/latest-build.json').write_text(json.dumps({'report': '../outside.json'}))
            with self.assertRaisesRegex(ValueError, 'build pointer'):
                DEPLOY.UPLOADER['homebrew_sdk_probe_candidate'](root)

    def test_sdk_probe_deployment_cannot_capture_or_replace_browsers(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(DEPLOY, 'ROOT', Path(folder)):
            root = Path(folder); path, report = self.sdk_probe_files(root)
            state = {'installers': ['OrbisFox.pkg', 'OrbisFox-Mesa.pkg', 'unrelated.pkg'], 'markers': {}}
            with patch.dict(DEPLOY.UPLOADER, homebrew_sdk_probe_candidate=lambda root: (path, report)), patch.object(DEPLOY, 'console_state', return_value=state), patch.object(DEPLOY, 'prepare_capture') as capture, patch.object(DEPLOY.subprocess, 'run') as run, patch('sys.argv', ['deploy', '--host', 'console.example.test', '--homebrew-sdk-probe']), contextlib.redirect_stdout(io.StringIO()):
                run.return_value.returncode = 0
                self.assertEqual(DEPLOY.main(), 0)
                capture.assert_not_called()
                self.assertIn('--homebrew-sdk-probe', run.call_args.args[0])
                self.assertNotIn('--gecko', run.call_args.args[0])
            result = json.loads((root / 'build/hardware-00.01-sdk/deployment-report.json').read_text())
            self.assertTrue(result['uploaded'])
            self.assertTrue(result['unrelated_installers_preserved'])
            self.assertFalse(result['installed'])
            self.assertFalse(result['launched'])
            self.assertFalse(result['capture']['new_reader'])
            self.assertEqual((root / 'build/hardware-00.01-sdk/sdk-probe.elf').read_bytes(), b'sdk-elf')
            for extra in ('--capture', '--shared-memory-probe'):
                with patch('sys.argv', ['deploy', '--host', 'console.example.test', '--homebrew-sdk-probe', extra]), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit): DEPLOY.main()

    def test_deployer_reuses_only_actual_registered_installer_names(self):
        self.assertIn('IV0000-ORBV00001_00-ORBISFOXVIDEO000.pkg', DEPLOY.REGISTERED_INSTALLERS)
        self.assertIn('IV0000-ORBF00001_00-ORBISFOXPROBE000.pkg', DEPLOY.REGISTERED_INSTALLERS)
        self.assertNotIn('unrelated.pkg', DEPLOY.REGISTERED_INSTALLERS)


if __name__ == '__main__':
    unittest.main()
