#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Public PS4 service declarations only: never import old libc, CRT or libraries."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
REVISION = '6929bafac0b565692ed61e66032a79185ee9cf65'
DESTINATION = ROOT / '.deps/homebrew-service-headers'
BASE_URL = f'https://raw.githubusercontent.com/OpenOrbis/OpenOrbis-PS4-Toolchain/{REVISION}/'
# Git blob identities from the pinned public commit; preserve bytes/notices.
FILES = {
    'include/orbis/AudioOut.h': '74cd43abcfefa81c7ca6ba67e6dee677f2c9bb97',
    'include/orbis/CommonDialog.h': '8a15388b3d864cd60df825471e4da657fe80a7eb',
    'include/orbis/ImeDialog.h': '7e2f08e5c18474bfa4f512f0c3939accfbaf48ad',
    'include/orbis/Pad.h': 'e60e21ed4a1901576a13d78b11ec3ef0292a99fe',
    'include/orbis/Sysmodule.h': 'e8f953223d2b3fb34766d9f51fb9237bfcc22ede',
    'include/orbis/SystemService.h': '0963447c8ec61db6ea722b7423751f7e92c6e097',
    'include/orbis/UserService.h': '1feb469d3631825012a4b6b10dbf8dbd914fc0c6',
    'include/orbis/VideoOut.h': '911e34a684cff862ecc609f5cc75f65d6dff3c45',
    'include/orbis/_types/audio_out.h': 'ea4b2c499fbe1f473d9b674547a13f9b15a69196',
    'include/orbis/_types/common_dialog.h': 'd239b1cccc701511718c87c0beebc589de9ac784',
    'include/orbis/_types/errors.h': 'bc6d757f079880fc399bbff54bb70e59bd353b6f',
    'include/orbis/_types/ime_dialog.h': 'eececba7e822c0ae75200f0110c70c566c6a9b99',
    'include/orbis/_types/kernel.h': 'abd324e8c9988a6d9bac7db313659bd8bce5b98b',
    'include/orbis/_types/pad.h': '196d6d1a6c225772b865ab87fedd8ed7401e58cd',
    'include/orbis/_types/pthread.h': 'fb9fcb8e0b8fb620b857934eb6806131480a694a',
    'include/orbis/_types/rtc.h': '5530eca81e87a8c390464a6a583415cf1f583fb3',
    'include/orbis/_types/sys_service.h': '67fe94375f96b7a5064a16b520771ab836612b2f',
    'include/orbis/_types/sysmodule.h': '333c8ea257311661a44e72c23e4ea30911f553b2',
    'include/orbis/_types/user.h': 'fbf3bb49c03dde75e18b776c9f95f4742a9294b2',
    'include/orbis/_types/video.h': '591af8d46a83686bd515cc333d340f70d93ce804',
    'include/orbis/libkernel.h': 'aff1f9d5bde1d414681c1a1c69f7ee979c9274ea',
    'LICENSE': 'f288702d2fa16d3cdf0035b15a9fcbc552cd88e7',
}


def blob_id(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def verify(destination=DESTINATION):
    destination = Path(destination)
    if destination.is_symlink():
        raise RuntimeError('Service header root must not be a symlink')
    actual = set()
    for path in destination.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Service header input must not be a symlink')
        if path.is_file():
            actual.add(path.relative_to(destination).as_posix())
    if actual != set(FILES) | {'source-report.json'}:
        raise RuntimeError('Service declarations inventory changed; libc/runtime files are not permitted')
    hashes = {}
    for name, expected in FILES.items():
        data = (destination / name).read_bytes()
        if blob_id(data) != expected:
            raise RuntimeError('Pinned service declaration changed: ' + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
    report = json.loads((destination / 'source-report.json').read_text())
    if report != source_report(hashes):
        raise RuntimeError('Service declaration report changed')
    return report


def source_report(hashes):
    return {'revision': REVISION, 'git_blobs': FILES, 'sha256': hashes,
            'scope': 'Public service declarations only; no legacy libc/CRT/runtime/libraries',
            'license': 'Retain upstream GPL-v3 LICENSE and file notices; no MIT relicensing',
            'native_console_execution_proven': False}


def fetch(destination=DESTINATION, local=ROOT / '.deps/OpenOrbis/PS4Toolchain'):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        return verify(destination)  # Never overwrite an unknown/changed tree.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='service-headers-', dir=destination.parent) as tmp:
        staging = Path(tmp) / 'headers'
        staging.mkdir()
        hashes = {}
        for name, expected in FILES.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts:
                raise RuntimeError('Unsafe service declaration path')
            candidate = Path(local) / name
            data = candidate.read_bytes() if candidate.is_file() else b''
            if blob_id(data) != expected:
                with urllib.request.urlopen(BASE_URL + name, timeout=30) as response:
                    data = response.read(256 * 1024 + 1)
            if len(data) > 256 * 1024 or blob_id(data) != expected:
                raise RuntimeError('Pinned public service header size/blob mismatch: ' + name)
            output = staging / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (staging / 'source-report.json').write_text(json.dumps(source_report(hashes), indent=2) + '\n')
        verify(staging)
        staging.rename(destination)
    return verify(destination)


if __name__ == '__main__':
    print(json.dumps(fetch(), indent=2))
