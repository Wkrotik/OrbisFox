import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('package', ROOT / 'scripts/package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def test_ids(self):
        for title, content in ((package.TITLE_ID, package.CONTENT_ID),
                               (package.VIDEOOUT_TITLE_ID, package.VIDEOOUT_CONTENT_ID)):
            self.assertRegex(title, r'^[A-Z]{4}[0-9]{5}$')
            self.assertEqual(len(content), 36)
            self.assertEqual(content[7:16], title)
        self.assertNotEqual(package.CONTENT_ID, package.VIDEOOUT_CONTENT_ID)

    def test_version(self):
        self.assertEqual(package.VERSION, '0.11')
        self.assertEqual(package.APP_TITLE, 'OrbisFox')
        self.assertEqual(package.PACKAGE_NAME, 'OrbisFox.pkg')
        self.assertIn(f'OrbisFox {package.VERSION} engine bring-up',
                      (ROOT / 'src/ps4/platform.cpp').read_text())
        self.assertIn(f'VERSION {package.VERSION}',
                      (ROOT / 'src/ui.cpp').read_text())

    def test_optional_service_import_guard(self):
        def elf(symbol):
            names = b'\0' + symbol.encode('ascii') + b'\0'
            data = bytearray(280 + len(names))
            struct.pack_into('<16sHHIQQQIHHHHHH', data, 0,
                             b'\x7fELF\x02\x01' + bytes(10), 3, 62, 1,
                             0, 0, 64, 0, 64, 56, 0, 64, 3, 0)
            struct.pack_into('<IIQQQQIIQQ', data, 128, 0, 11, 0, 0, 256, 24, 2, 0, 8, 24)
            struct.pack_into('<IIQQQQIIQQ', data, 192, 0, 3, 0, 0, 280, len(names), 0, 0, 1, 0)
            struct.pack_into('<IBBHQQ', data, 256, 1, 0x12, 0, 0, 0, 0)
            data[280:] = names
            return data
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.elf'
            for name in ('sceUserServiceInitialize', 'sceVideoOutOpen', 'scePadInit',
                         'sceSystemServiceHideSplashScreen'):
                path.write_bytes(elf(name))
                with self.assertRaises(ValueError):
                    package.verify_service_imports(path)
            path.write_bytes(elf('sceKernelDlsym'))
            self.assertEqual(package.verify_service_imports(path), [])

    def test_options_uses_application_manager(self):
        main = (ROOT / 'src/ps4/main.cpp').read_text()
        options = main.split('if (pressed & ORBIS_PAD_BUTTON_OPTIONS)', 1)[1].split('if (pressed & ORBIS_PAD_BUTTON_CROSS)', 1)[0]
        self.assertIn('request_system_exit()', options)
        self.assertNotIn('break;', options)
        self.assertIn('load_exec("exit", nullptr)', (ROOT / 'src/ps4/services.cpp').read_text())

    def test_authinfo(self):
        self.assertEqual(len(bytes.fromhex(package.AUTHINFO)), 136)

    @staticmethod
    def example_oelf():
        data = bytearray(0x8100)
        struct.pack_into('<16sHHIQQQIHHHHHH', data, 0,
                         b'\x7fELF\x02\x01' + bytes(10), 0xfe10, 62, 1,
                         0x20, 64, 232, 0, 64, 56, 3, 64, 2, 0)
        struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0x4000, 0, 0, 0x100, 0x100, 0x4000)
        struct.pack_into('<IIQQQQQQ', data, 120, 1, 6, 0x8000, 0x4000, 0x4000, 0x100, 0x100, 0x4000)
        struct.pack_into('<IIQQQQIIQQ', data, 296, 0, 1, 6, 0x20, 0x4020, 4, 0, 0, 4, 0)
        return data

    def check_oelf(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.oelf'
            path.write_bytes(data)
            return package.verify_oelf(path)

    def test_oelf_mapping_guard(self):
        data = self.example_oelf()
        self.assertEqual(self.check_oelf(data), 1)
        struct.pack_into('<Q', data, 296 + 24, 0x4030)
        with self.assertRaises(ValueError):
            self.check_oelf(data)

    def test_oelf_reject_duplicate_loads(self):
        data = self.example_oelf()
        # Exact regression from 0.04: two writable LOADs at the same address.
        struct.pack_into('<IIQQQQQQ', data, 176, 1, 6, 0x8000, 0x4000, 0x4000, 0x100, 0x100, 0x4000)
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            self.check_oelf(data)

    def test_oelf_reject_page_overlap(self):
        data = self.example_oelf()
        struct.pack_into('<Q', data, 64 + 40, 0x4001)
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            self.check_oelf(data)

    def test_oelf_tls_alignment(self):
        data = self.example_oelf()
        struct.pack_into('<IIQQQQQQ', data, 176, 7, 4, 0x4040, 0x40, 0x40, 0, 8, 0x20)
        self.assertEqual(self.check_oelf(data), 1)
        struct.pack_into('<Q', data, 176 + 16, 0x48)
        with self.assertRaisesRegex(ValueError, 'TLS alignment'):
            self.check_oelf(data)

    def test_oelf_bss_coverage(self):
        data = self.example_oelf()
        struct.pack_into('<IIQQQQIIQQ', data, 296, 0, 8, 3, 0x4100, 0x8100, 4, 0, 0, 4, 0)
        with self.assertRaisesRegex(ValueError, 'NOBITS'):
            self.check_oelf(data)

    def test_user_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            files = package.prepare_artwork(stage)
            self.assertEqual(len(files), 4)
            for name, size in (('icon0.png', (512, 512)), ('pic0.png', (1920, 1080)),
                               ('pic1.png', (1920, 1080))):
                with Image.open(stage / 'sce_sys' / name) as image:
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.mode, 'RGBA')
                    self.assertEqual(image.getextrema()[3], (255, 255))
            with Image.open(ROOT / 'assets/icon.jpg') as original, Image.open(stage / 'sce_sys/icon0.png') as icon:
                self.assertEqual(icon.convert('RGB').tobytes(), original.convert('RGB').tobytes())
            raw = (stage / 'assets/splash.rgba').read_bytes()
            self.assertEqual(struct.unpack_from('<8sII', raw), (b'ORBFIMG1', 1280, 720))
            self.assertEqual(len(raw), 16 + 1280 * 720 * 4)


if __name__ == '__main__':
    unittest.main()
