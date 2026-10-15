#!/usr/bin/env python3
"""Pinned offline Gecko fixture/font staging; never touches the working package."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
REVISION = 'ffebf8c1ee449e544955a7e813c54f9b73848eac'
BASE = 'https://raw.githubusercontent.com/notofonts/noto-fonts/' + REVISION + '/'
EMOJI_REVISION = 'e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e'
EMOJI_BASE = 'https://raw.githubusercontent.com/googlefonts/noto-emoji/' + EMOJI_REVISION + '/2D/fonts/'
EMOJI_FILES = (
    (EMOJI_BASE + 'NotoColorEmoji.ttf', 'fonts/NotoColorEmoji.ttf',
     '15671215ab769fdc7162a045d56fd7d7e477c51b04e6b3c761d914d8fdd6cc44'),
    (EMOJI_BASE + 'LICENSE', 'licenses/noto-emoji-OFL.txt',
     '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2'),
)
FILES = (
    ('hinted/ttf/NotoSans/NotoSans-Regular.ttf', 'fonts/NotoSans-Regular.ttf',
     'b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5'),
    ('hinted/ttf/NotoSansSymbols2/NotoSansSymbols2-Regular.ttf', 'fonts/NotoSansSymbols2-Regular.ttf',
     '630846d528dbe4c4981370a4d0a9475a1fd1491a129bb411f8e157cdb5de13c6'),
    ('hinted/ttf/NotoSansMath/NotoSansMath-Regular.ttf', 'fonts/NotoSansMath-Regular.ttf',
     '80b61fd613d3519197e64fff6f7e71fdc7f3e6526440ea4115b554ef7fd59af7'),
    ('LICENSE', 'licenses/noto-OFL.txt',
     '0dab92d0544f7b233403f14b84a663bdbfa746982eda629e7f4f9ffe1b036feb'),
)


def checked_file(path, url, expected):
    if path.exists():
        data = path.read_bytes()
    else:
        with urlopen(url, timeout=60) as response:
            data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError('Offline asset hash mismatch: ' + str(path))
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.downloading')
        temporary.write_bytes(data)
        temporary.replace(path)
    return data


def write_changed(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def main():
    cache = ROOT / '.deps/gecko-layout-assets'
    staging = ROOT / 'build/gecko-layout/offline-assets'
    assets = []
    for upstream, destination, expected in FILES + EMOJI_FILES:
        source = upstream if upstream.startswith('https://') else BASE + upstream
        data = checked_file(cache / destination, source, expected)
        write_changed(staging / destination, data)
        assets.append({'path': destination, 'bytes': len(data), 'sha256': expected,
                       'source': source})
    fixture = (ROOT / 'gecko/orbisfox/fixtures/offline.html').read_bytes()
    write_changed(staging / 'offline.html', fixture)
    assets.append({'path': 'offline.html', 'bytes': len(fixture),
                   'sha256': hashlib.sha256(fixture).hexdigest()})
    report = {'font_revision': REVISION, 'emoji_font_revision': EMOJI_REVISION, 'assets': assets,
              'in_working_package': False, 'html_rendered': False,
              'hardware_tested': False,
              'scope': 'Latin, symbols/math and real color-emoji fallback; not CJK or private-use icon-font coverage'}
    write_changed(staging / 'assets-report.json', (json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
