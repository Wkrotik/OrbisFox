# SPDX-License-Identifier: MIT
"""Real native codec link/identity checks, not native decode or playback."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
MEDIA = runpy.run_path(str(ROOT / 'scripts/build-media-codecs.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))


class HomebrewMediaTest(unittest.TestCase):
    def test_sdk_output_ownership_and_fail_closed_selection(self):
        old, old_id, old_env = MEDIA['build_identity'](sdk='openorbis')
        self.assertEqual(old, ROOT / 'build/media-codecs/native')
        self.assertEqual(old_id['sdk'], 'openorbis')
        self.assertEqual(old_env['ORBISFOX_SDK'], 'openorbis')
        host, host_id, _ = MEDIA['build_identity'](host=True, sdk='homebrew')
        self.assertEqual(host, ROOT / 'build/media-codecs/host')
        self.assertEqual(host_id['sdk'], 'host')
        with self.assertRaisesRegex(ValueError, 'Unknown ORBISFOX_SDK'):
            MEDIA['build_identity'](sdk='typo')

    def test_actual_native_codec_complete_link_and_sdk_binding(self):
        path = ROOT / 'build/media-codecs/native-homebrew/build-report.json'
        if not path.is_file():
            self.skipTest('Build media codecs with --sdk homebrew first')
        report = json.loads(path.read_text())
        directory, identity, env = MEDIA['build_identity'](sdk='homebrew')
        self.assertEqual(report['sdk_identity'], identity['sdk_identity'])
        self.assertEqual(report['native_driver_sha256'], identity['native_driver_sha256'])
        self.assertEqual(report['build_identity']['builder_sha256'], MEDIA['sha'](ROOT / 'scripts/build-media-codecs.py'))
        self.assertFalse(report['gpl'])
        self.assertFalse(report['network'])
        archives = []
        for item in report['archives']:
            archive = ROOT / item['path']
            self.assertEqual(archive.parent, directory)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), item['sha256'])
            archives.append(str(archive))
        with tempfile.TemporaryDirectory() as tmp:
            main, elf = Path(tmp) / 'main.c', Path(tmp) / 'codecs.elf'
            main.write_text('''#define avcodec_find_decoder orbis_media_avcodec_find_decoder
#define avcodec_alloc_context3 orbis_media_avcodec_alloc_context3
#define avcodec_free_context orbis_media_avcodec_free_context
#include <libavcodec/avcodec.h>
int main(void) {
  const AVCodec* decoder = avcodec_find_decoder(AV_CODEC_ID_H264);
  AVCodecContext* context = avcodec_alloc_context3(decoder);
  if (!decoder || !context) return 1;
  avcodec_free_context(&context);
  return 0;
}
''')
            command = DRIVER['compiler_command'](['-I' + str(directory),
                        '-I' + str(ROOT / '.deps/ffmpeg-9.0.2'), str(main),
                        '-Wl,--whole-archive', *archives, '-Wl,--no-whole-archive',
                        '-Wl,--no-gc-sections', '-o', str(elf)])
            result = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(elf)], text=True)
            for name in ('orbis_media_ff_h264_decoder', 'orbis_media_ff_aac_decoder',
                         'orbis_media_av_tx_init', 'orbis_media_avcodec_receive_frame'):
                self.assertIn(' ' + name + '\n', symbols)
            self.assertNotIn(' orbisfox_sdk_malloc_state\n', symbols)


if __name__ == '__main__':
    unittest.main()
