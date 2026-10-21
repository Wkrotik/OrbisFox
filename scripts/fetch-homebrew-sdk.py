#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch a pinned public ps4-homebrew-dev SDK without changing OpenOrbis."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = 'v0.2.1'
REVISION = 'ecc8347aa20d7b3423405a5e94d7ab119485160d'
SHA256 = 'fc021d7e6d53dcd1c73c87af4e0897012c62ffa5276289c0c3d898d71be80310'
ARCHIVE_BYTES = 4471594
URL = f'https://github.com/ps4-homebrew-dev/sdk/releases/download/{VERSION}/ps4-homebrew-sdk.zip'
ARCHIVE = ROOT / '.deps/downloads' / f'ps4-homebrew-sdk-{VERSION}.zip'
SDK = ROOT / '.deps' / f'ps4-homebrew-sdk-{VERSION}'
MAX_EXPANDED = 32 * 1024 * 1024


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_archive(path):
    if Path(path).is_symlink() or Path(path).stat().st_size != ARCHIVE_BYTES or digest(path) != SHA256:
        raise RuntimeError('Pinned homebrew SDK archive size/SHA-256 mismatch')


def extract_archive(archive, destination):
    """Validate the complete inventory before extracting into an owned empty path."""
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError('SDK extraction destination must be empty')
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 4096 or sum(i.file_size for i in entries) > MAX_EXPANDED:
            raise RuntimeError('SDK archive exceeds extraction budget')
        seen = set()
        inventory = []
        for entry in entries:
            p = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (p.is_absolute() or '..' in p.parts or '\\' in entry.filename or
                    not p.parts or p.parts[0] != 'ps4-homebrew-sdk' or
                    entry.filename in seen or stat.S_ISLNK(mode) or
                    (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise RuntimeError('Unsafe SDK archive member: ' + entry.filename)
            seen.add(entry.filename)
            relative = Path(*p.parts[1:])
            if not entry.is_dir() and (len(p.parts) < 2 or entry.file_size > 16 * 1024 * 1024):
                raise RuntimeError('Invalid SDK archive member: ' + entry.filename)
            inventory.append((entry, relative, mode))
        files = {}
        for entry, relative, mode in inventory:
            target = destination / relative
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                data = z.read(entry)  # Includes ZIP CRC verification.
                target.write_bytes(data)
                target.chmod(0o755 if mode & 0o111 else 0o644)
                files[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    return files


def verify_sdk(path=SDK):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('SDK root must not be a symlink')
    report = json.loads((path / 'source-report.json').read_text())
    if (report.get('archive_sha256') != SHA256 or report.get('revision') != REVISION or
            report.get('version') != VERSION):
        raise RuntimeError('SDK source report does not match pin')
    validate_archive(ARCHIVE)
    with zipfile.ZipFile(ARCHIVE) as z:
        expected_files = {str(PurePosixPath(i.filename).relative_to('ps4-homebrew-sdk')):
                          hashlib.sha256(z.read(i)).hexdigest()
                          for i in z.infolist() if not i.is_dir()}
    if report.get('files') != expected_files:
        raise RuntimeError('SDK source report inventory changed')
    actual = set()
    for item in path.rglob('*'):
        if item.is_symlink():
            raise RuntimeError('SDK input must not be a symlink')
        if item.is_file() and item.name != 'source-report.json':
            actual.add(item.relative_to(path).as_posix())
    if actual != set(expected_files):
        raise RuntimeError('SDK input inventory changed')
    for name, expected in report['files'].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Invalid SDK source report path')
        source = path / name
        if source.is_symlink() or digest(source) != expected:
            raise RuntimeError('SDK input changed: ' + name)
    return report


def fetch():
    if SDK.exists():
        verify_sdk()
        return SDK
    SDK.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        if shutil.disk_usage(SDK.parent).free < 128 * 1024 * 1024:
            raise RuntimeError('Insufficient free space for bounded SDK extraction')
        with tempfile.TemporaryDirectory(prefix='sdk-download-', dir=ARCHIVE.parent) as tmp:
            pending = Path(tmp) / 'sdk.zip'
            request = urllib.request.Request(URL, headers={'User-Agent': 'OrbisFox-SDK-evaluation'})
            with urllib.request.urlopen(request, timeout=60) as response, pending.open('wb') as out:
                total = 0
                while chunk := response.read(128 * 1024):
                    total += len(chunk)
                    if total > ARCHIVE_BYTES:
                        raise RuntimeError('SDK download exceeds pinned size')
                    out.write(chunk)
            validate_archive(pending)
            pending.replace(ARCHIVE)
    validate_archive(ARCHIVE)
    if shutil.disk_usage(SDK.parent).free < 128 * 1024 * 1024:
        raise RuntimeError('Insufficient free space for bounded SDK extraction')
    with tempfile.TemporaryDirectory(prefix='sdk-extract-', dir=SDK.parent) as tmp:
        pending = Path(tmp) / 'sdk'
        files = extract_archive(ARCHIVE, pending)
        report = {'version': VERSION, 'revision': REVISION, 'archive_url': URL,
                  'archive_sha256': SHA256, 'files': files}
        (pending / 'source-report.json').write_text(json.dumps(report, indent=2) + '\n')
        pending.rename(SDK)
    verify_sdk()
    return SDK


if __name__ == '__main__':
    print(fetch())
