"""Pinned font data covers actual 0.58 missing codepoints; not native raster proof."""
import hashlib
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / 'build/gecko-layout/offline-assets/fonts/NotoColorEmoji.ttf'
LICENSE = ROOT / 'build/gecko-layout/offline-assets/licenses/noto-emoji-OFL.txt'
MISSING_058 = (0x1f383, 0x1f4d1, 0x2795, 0x1f680, 0x1f50e, 0x1f516,
               0x1f91d, 0x1f4ac, 0x1f4be, 0x1f4d6, 0x1f3a8, 0x1f4a1)


class EmojiFontTest(unittest.TestCase):
    def setUp(self):
        if not FONT.exists() or not LICENSE.exists():
            self.skipTest('stage pinned assets with scripts/fetch-layout-assets.py')

    def test_pinned_font_and_license(self):
        self.assertEqual(hashlib.sha256(FONT.read_bytes()).hexdigest(),
                         '15671215ab769fdc7162a045d56fd7d7e477c51b04e6b3c761d914d8fdd6cc44')
        self.assertEqual(hashlib.sha256(LICENSE.read_bytes()).hexdigest(),
                         '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2')
        self.assertIn('SIL OPEN FONT LICENSE', LICENSE.read_text())

    def test_actual_cmap_covers_recorded_missing_emoji(self):
        data = FONT.read_bytes()
        self.assertEqual(data[:4], b'\0\x01\0\0')
        tables = {}
        for index in range(struct.unpack_from('>H', data, 4)[0]):
            tag, _, offset, length = struct.unpack_from('>4sIII', data, 12 + index * 16)
            self.assertLessEqual(offset + length, len(data))
            tables[tag] = (offset, length)
        self.assertTrue({b'CBDT', b'CBLC', b'cmap'} <= tables.keys())
        offset, length = tables[b'cmap']
        cmap = data[offset:offset + length]
        groups = []
        for index in range(struct.unpack_from('>H', cmap, 2)[0]):
            _, _, sub = struct.unpack_from('>HHI', cmap, 4 + index * 8)
            if struct.unpack_from('>H', cmap, sub)[0] != 12:
                continue
            count = struct.unpack_from('>I', cmap, sub + 12)[0]
            self.assertLessEqual(sub + 16 + count * 12, len(cmap))
            groups += [struct.unpack_from('>III', cmap, sub + 16 + i * 12) for i in range(count)]
        self.assertTrue(groups)
        for cp in MISSING_058:
            self.assertTrue(any(start <= cp <= end and glyph + cp - start != 0
                                for start, end, glyph in groups), f'U+{cp:04X}')


if __name__ == '__main__':
    unittest.main()
