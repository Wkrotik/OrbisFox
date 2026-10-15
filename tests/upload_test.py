import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('upload', ROOT / 'scripts/upload-pkgs.py')
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)


class FakeFTP:
    def __init__(self, name, corrupt=False):
        self.files = {name: b'old', 'unrelated.pkg': b'leave alone'}
        self.events = []
        self.corrupt = corrupt

    def cwd(self, path):
        self.events.append(('cwd', path))

    def nlst(self):
        return list(self.files)

    def delete(self, name):
        self.events.append(('delete', name))
        del self.files[name]

    def voidcmd(self, command):
        self.events.append(('command', command))

    def size(self, name):
        return len(self.files[name])

    def storbinary(self, command, source, blocksize, rest=None):
        name = command.split(' ', 1)[1]
        self.files[name] = (self.files.get(name, b'')[:rest] if rest else b'') + source.read()
        self.events.append(('upload', name))

    def retrbinary(self, command, callback, blocksize):
        name = command.split(' ', 1)[1]
        self.events.append(('verify', name))
        callback(b'corrupt' if self.corrupt else self.files[name])

    def rename(self, old, new):
        self.events.append(('rename', old, new))
        if new in self.files:
            raise RuntimeError('GoldHEN overwrite rejected')
        self.files[new] = self.files.pop(old)


class UploadTests(unittest.TestCase):
    def test_replace_only_after_verification(self):
        name = upload.PACKAGE_NAMES[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_bytes(b'new native package')
            ftp = FakeFTP(name)
            upload.upload_packages(ftp, [path])
        self.assertEqual(ftp.files[name], b'new native package')
        self.assertEqual(ftp.files['unrelated.pkg'], b'leave alone')
        self.assertLess(ftp.events.index(('verify', '.' + name + '.uploading')),
                        ftp.events.index(('delete', name)))

    def test_corrupt_transfer_keeps_old_package(self):
        name = upload.PACKAGE_NAMES[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_bytes(b'new native package')
            ftp = FakeFTP(name, corrupt=True)
            with self.assertRaises(RuntimeError):
                upload.upload_packages(ftp, [path])
        self.assertEqual(ftp.files[name], b'old')
        self.assertEqual(ftp.files['unrelated.pkg'], b'leave alone')

    def test_single_app_retires_old_probes(self):
        name = upload.PACKAGE_NAMES[0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_bytes(b'new OrbisFox')
            ftp = FakeFTP(name)
            ftp.files[upload.LEGACY_MAIN_PACKAGE] = b'old probe'
            ftp.files[upload.PACKAGE_NAMES[1]] = b'old video probe'
            upload.upload_packages(ftp, [path])
        self.assertEqual(set(ftp.files), {name, 'unrelated.pkg'})
        self.assertLess(ftp.events.index(('verify', '.' + name + '.uploading')),
                        ftp.events.index(('delete', upload.LEGACY_MAIN_PACKAGE)))

    def test_resume_verifies_complete_file_before_replacement(self):
        name = upload.PACKAGE_NAMES[0]
        temporary = '.' + name + '.uploading'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_bytes(b'new native package')
            ftp = FakeFTP(name)
            ftp.files[temporary] = b'new native'
            upload.upload_packages(ftp, [path], resume=True)
        self.assertEqual(ftp.files[name], b'new native package')
        self.assertLess(ftp.events.index(('verify', temporary)), ftp.events.index(('delete', name)))
        self.assertEqual(ftp.files['unrelated.pkg'], b'leave alone')

    def test_corrupt_resume_prefix_keeps_old_package(self):
        name = upload.PACKAGE_NAMES[0]
        temporary = '.' + name + '.uploading'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_bytes(b'new native package')
            ftp = FakeFTP(name)
            ftp.files[temporary] = b'bad prefix'
            with self.assertRaises(RuntimeError): upload.upload_packages(ftp, [path], resume=True)
        self.assertEqual(ftp.files[name], b'old')
        self.assertNotIn(temporary, ftp.files)
        self.assertEqual(ftp.files['unrelated.pkg'], b'leave alone')

    def test_refuse_unrelated_package(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'other.pkg'
            path.write_bytes(b'no')
            ftp = FakeFTP('other.pkg')
            with self.assertRaises(ValueError):
                upload.upload_packages(ftp, [path])
            self.assertEqual(ftp.events, [])


if __name__ == '__main__':
    unittest.main()
