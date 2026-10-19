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

    def test_deployer_reuses_only_actual_registered_installer_names(self):
        self.assertIn('IV0000-ORBV00001_00-ORBISFOXVIDEO000.pkg', DEPLOY.REGISTERED_INSTALLERS)
        self.assertIn('IV0000-ORBF00001_00-ORBISFOXPROBE000.pkg', DEPLOY.REGISTERED_INSTALLERS)
        self.assertNotIn('unrelated.pkg', DEPLOY.REGISTERED_INSTALLERS)


if __name__ == '__main__':
    unittest.main()
