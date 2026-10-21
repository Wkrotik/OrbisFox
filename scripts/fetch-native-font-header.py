#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One pinned MIT stb font implementation; never expose old SDK C headers."""
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
REVISION = '6929bafac0b565692ed61e66032a79185ee9cf65'
SHA256 = '97233cfddd15dc96ea28d73b10599887584c38e3166b4cd3ef62934cb79b20e6'
RELATIVE = Path('stb/stb_truetype.h')
DESTINATION = ROOT / '.deps/native-font-header'
URL = f'https://raw.githubusercontent.com/OpenOrbis/OpenOrbis-PS4-Toolchain/{REVISION}/include/{RELATIVE.as_posix()}'


def source_report():
    return {'revision': REVISION, 'sha256': SHA256, 'path': RELATIVE.as_posix(),
            'url': URL, 'license': 'MIT option; assets/licenses/stb-truetype-MIT.txt',
            'scope': 'Unchanged existing native chrome font implementation only; no SDK C/POSIX/runtime files'}


def verify(destination=DESTINATION):
    destination = Path(destination)
    if destination.is_symlink():
        raise RuntimeError('Native font header root must not be a symlink')
    files = set()
    for path in destination.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Native font header input must not be a symlink')
        if path.is_file():
            files.add(path.relative_to(destination).as_posix())
    if files != {RELATIVE.as_posix(), 'source-report.json'}:
        raise RuntimeError('Native font header inventory changed')
    if hashlib.sha256((destination / RELATIVE).read_bytes()).hexdigest() != SHA256:
        raise RuntimeError('Native font header hash changed')
    if json.loads((destination / 'source-report.json').read_text()) != source_report():
        raise RuntimeError('Native font header report changed')
    return source_report()


def fetch(destination=DESTINATION, local=ROOT / '.deps/OpenOrbis/PS4Toolchain/include'):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        return verify(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(local) / RELATIVE
    data = candidate.read_bytes() if candidate.is_file() else b''
    if hashlib.sha256(data).hexdigest() != SHA256:
        with urllib.request.urlopen(URL, timeout=30) as response:
            data = response.read(512 * 1024 + 1)
    if len(data) > 512 * 1024 or hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('Pinned native font header size/hash mismatch')
    with tempfile.TemporaryDirectory(prefix='native-font-', dir=destination.parent) as tmp:
        staging = Path(tmp) / 'include'
        (staging / RELATIVE.parent).mkdir(parents=True)
        (staging / RELATIVE).write_bytes(data)
        (staging / 'source-report.json').write_text(json.dumps(source_report(), indent=2) + '\n')
        verify(staging)
        staging.rename(destination)
    return verify(destination)


if __name__ == '__main__':
    print(json.dumps(fetch(), indent=2))
