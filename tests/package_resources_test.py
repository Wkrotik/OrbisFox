"""Packaging-only resource bundling: same bytes, deterministic ZIP, no deletion."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

PACKAGE = load('resource_packaging', 'package-gecko.py')
VERIFY = load('resource_verification', 'verify-gecko-package.py')


class PackageResourcesTests(unittest.TestCase):
    def tree(self, root):
        files = {'greprefs.js': b'pref("javascript.enabled", true);\n',
                 'chrome.manifest': b'resource gre ./\nmanifest chrome/example.manifest\n',
                 'chrome/example.manifest': b'content example example/\n',
                 'chrome/example/page.xhtml': b'<html/>',
                 'defaults/pref/orbisfox.js': b'pref("example", true);',
                 'modules/example.sys.mjs': b'export const example = 42;',
                 'res/data.bin': bytes(range(256))}
        for name, data in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return files

    def test_archive_preserves_all_bytes_manifests_and_generated_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'gecko'
            original = self.tree(root)
            report = PACKAGE.archive_resources(root)
            with zipfile.ZipFile(root / 'omni.ja') as archive:
                self.assertEqual(set(archive.namelist()), set(original))
                for name, data in original.items():
                    self.assertEqual(archive.read(name), data)
                    self.assertEqual(archive.getinfo(name).compress_type, zipfile.ZIP_STORED)
            self.assertEqual({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()},
                             {'omni.ja', 'greprefs.js', 'chrome.manifest'})
            self.assertEqual((root / 'greprefs.js').read_bytes(), original['greprefs.js'])
            self.assertEqual(VERIFY.verify_resource_archive(root, report), len(original))

    def test_archive_is_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = [Path(directory) / name for name in ('first', 'second')]
            for root in roots:
                self.tree(root)
                PACKAGE.archive_resources(root)
            self.assertEqual((roots[0] / 'omni.ja').read_bytes(), (roots[1] / 'omni.ja').read_bytes())

    def test_verifier_rejects_changed_archive_manifest_and_loose_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'gecko'
            self.tree(root)
            report = PACKAGE.archive_resources(root)
            changed = json.loads(json.dumps(report))
            changed['entries'][0]['sha256'] = '0' * 64
            with self.assertRaises(ValueError): VERIFY.verify_resource_archive(root, changed)
            (root / 'greprefs.js').write_text('pref("javascript.enabled", false);')
            with self.assertRaises(ValueError): VERIFY.verify_resource_archive(root, report)
            with (root / 'omni.ja').open('ab') as stream: stream.write(b'changed')
            with self.assertRaises(ValueError): VERIFY.verify_resource_archive(root, report)

    def test_verifier_rejects_extra_entries_even_with_matching_outer_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'gecko'
            self.tree(root)
            report = PACKAGE.archive_resources(root)
            path = root / 'omni.ja'
            with zipfile.ZipFile(path, 'a') as archive:
                archive.writestr('../unexpected', b'not an original input')
            report['bytes'] = path.stat().st_size
            report['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError): VERIFY.verify_resource_archive(root, report)

    def test_rejects_symlinks_and_missing_required_resources_without_deleting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'gecko'
            original = self.tree(root)
            (root / 'linked').symlink_to(root / 'greprefs.js')
            with self.assertRaises(ValueError): PACKAGE.archive_resources(root)
            self.assertTrue((root / 'modules/example.sys.mjs').exists())
            (root / 'linked').unlink()
            (root / 'chrome.manifest').unlink()
            with self.assertRaises(ValueError): PACKAGE.archive_resources(root)
            self.assertEqual((root / 'greprefs.js').read_bytes(), original['greprefs.js'])


if __name__ == '__main__':
    unittest.main()
