import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('source_release', ROOT / 'scripts/prepare-source-release.py')
EXPORT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EXPORT)


class SourceReleaseTests(unittest.TestCase):
    def fixture(self, root):
        for name in EXPORT.ROOT_FILES:
            (root / name).write_text('public source\n')
        for name in EXPORT.SOURCE_DIRS:
            (root / name).mkdir()
            (root / name / 'README.md').write_text(name + '\n')
        (root / 'scripts/package-gecko.py').write_text("VERSION = '0.68'\n")
        (root / 'src/main.cpp').write_text('int main() {}\n')
        (root / 'src/native.S').write_text('// SPDX-License-Identifier: MIT\n.text\n')
        (root / 'rust/lib.rs').write_text('pub fn main() {}\n')
        executable = root / 'scripts/tool.sh'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        for name in ('.deps', '.pi', '.git', 'build', 'dist'):
            (root / name).mkdir()
            (root / name / 'private.key').write_text('MUST NOT EXPORT')
        (root / '.env').write_text('MUST NOT EXPORT')

    def test_source_only_reproducible_archive_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            first = EXPORT.prepare(root)
            second = EXPORT.prepare(root)
            self.assertEqual(first, second)
            archive = root / first['archive']
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), first['sha256'])
            self.assertFalse(first['published'])
            self.assertFalse(first['binary_redistribution_review_complete'])
            with tarfile.open(archive) as tar:
                members = tar.getmembers()
                self.assertTrue(all(m.isfile() and m.mtime == 0 and m.uid == m.gid == 0 for m in members))
                manifest = json.load(tar.extractfile(next(m for m in members if m.name.endswith('/SOURCE-MANIFEST.json'))))
                paths = {entry['path'] for entry in manifest['files']}
                self.assertIn('src/main.cpp', paths)
                self.assertIn('src/native.S', paths)
                self.assertIn('rust/lib.rs', paths)
                self.assertEqual(len(paths), first['files_verified'])
                self.assertFalse(any(p.startswith(('.deps/', '.pi/', '.git/', 'build/', 'dist/')) for p in paths))
                self.assertNotIn('.env', paths)
                self.assertEqual(next(m for m in members if m.name.endswith('/scripts/tool.sh')).mode, 0o755)
                for entry in manifest['files']:
                    data = tar.extractfile('orbisfox-0.68-alpha-source/' + entry['path']).read()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])

    def test_rejects_source_symlink_and_unreviewed_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            link = root / 'scripts/leak.py'
            link.symlink_to(root / '.env')
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                EXPORT.prepare(root)
            link.unlink()
            (root / 'assets/unreviewed.pkg').write_bytes(b'private binary')
            with self.assertRaisesRegex(ValueError, 'Unreviewed file type'):
                EXPORT.prepare(root)

    def test_rejects_symlinked_source_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / 'LICENSE').unlink()
            (root / 'LICENSE').symlink_to(root / '.env')
            with self.assertRaisesRegex(ValueError, 'symlinked source root'):
                EXPORT.prepare(root)

    def test_project_license_and_component_exceptions(self):
        license_text = (ROOT / 'LICENSE').read_text()
        self.assertTrue(license_text.startswith('MIT License\n'))
        self.assertIn('The above copyright notice and this permission notice shall be included', license_text)
        self.assertIn('license = "MIT"', (ROOT / 'rust/runtime-probe/Cargo.toml').read_text())
        self.assertIn('LICENSES/README.md', (ROOT / 'LICENSE').read_text())
        self.assertIn('SPDX-License-Identifier: GPL-3.0-only', (ROOT / 'scripts/ps4.ld').read_text())
        self.assertIn('SPDX-License-Identifier: MPL-2.0', (ROOT / 'scripts/patch-gecko-layout.py').read_text())
        self.assertIn('project-license-scope.md', (ROOT / 'scripts/package-gecko.py').read_text())
        for script in ('package-gecko.py', 'package.py'):
            source = (ROOT / 'scripts' / script).read_text()
            self.assertIn("'project-MIT.txt': ROOT / 'LICENSE'", source)
            self.assertNotIn('project-0BSD.txt', source)
            self.assertNotIn('project-gpl-3.0.txt', source)
            self.assertIn("'OpenOrbis-derived-GPL-3.0.txt': ROOT / 'LICENSES/GPL-3.0-only.txt'", source)
            self.assertIn("'MPL-2.0.txt': ROOT / 'LICENSES/MPL-2.0.txt'", source)
        self.assertIn('SPDX-License-Identifier: GPL-3.0-or-later', (ROOT / 'scripts/package.py').read_text())
        for name in ('LICENSE', 'README.md', 'CONTRIBUTING.md', 'AGENTS.md', 'THIRD_PARTY.md',
                     'LICENSES/README.md', 'docs/RELEASING.md'):
            self.assertNotIn('0BSD', (ROOT / name).read_text(), name)

    def test_public_docs_links_and_license_scopes(self):
        for removed in ('CONTRIBUTORS.md', 'agents.md', 'SESSION_HANDOFF.md'):
            self.assertNotIn(removed, EXPORT.ROOT_FILES)
        for name in EXPORT.ROOT_FILES:
            self.assertTrue((ROOT / name).is_file(), name)
        for path in [ROOT / name for name in EXPORT.ROOT_FILES if name.endswith('.md')] + list((ROOT / 'docs').glob('*.md')):
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' not in link and not link.startswith('#'):
                    self.assertTrue((path.parent / link.split('#', 1)[0]).exists(), str(path) + ': ' + link)

    def test_console_tools_require_an_explicit_destination(self):
        for script in ('deploy-console.py', 'fetch-console-crash.py', 'watch-console-crashes.py'):
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('--host', result.stderr)

    def test_gitignore_excludes_artifacts_but_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            shutil.copyfile(ROOT / '.gitignore', root / '.gitignore')
            for name in ('build/private.log', 'dist/OrbisFox.pkg', '.deps/gecko/file.cpp', '.pi/config.json',
                         '.env', 'core.sorbisdmp', 'prefs.js'):
                result = subprocess.run(['git', 'check-ignore', '-q', name], cwd=root)
                self.assertEqual(result.returncode, 0, name)
            for name in ('src/ps4/native_cpu.cpp', 'gecko/orbisfox/moz.build', 'LICENSES/MPL-2.0.txt',
                         'tests/source_release_test.py', 'AGENTS.md', '.gitignore'):
                result = subprocess.run(['git', 'check-ignore', '-q', name], cwd=root)
                self.assertEqual(result.returncode, 1, name)

    def test_clean_and_upload_require_explicit_operator_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / 'Makefile', root / 'Makefile')
            (root / 'build').mkdir()
            (root / 'dist').mkdir()
            for target in ('clean', 'upload'):
                result = subprocess.run(['make', target], cwd=root, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((root / 'build').is_dir())
                self.assertTrue((root / 'dist').is_dir())
            source = (root / 'Makefile').read_text()
            self.assertIn('all: pkg-gecko', source)
            self.assertIn('gecko-app-build: gecko-build', source)


if __name__ == '__main__':
    unittest.main()
