#!/usr/bin/env python3
"""Deploy only OrbisFox packages, verify transfer, and replace previous versions."""
import argparse
from ftplib import FTP
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAMES = (
    'OrbisFox.pkg',
    'IV0000-ORBV00001_00-ORBISFOXVIDEO000.pkg',
)
LEGACY_MAIN_PACKAGE = 'IV0000-ORBF00001_00-ORBISFOXPROBE000.pkg'


def upload_packages(ftp, files, directory='/data/pkg', resume=False):
    files = list(map(Path, files))
    if any(path.name not in PACKAGE_NAMES or not path.is_file() for path in files):
        raise ValueError('Only existing, registered OrbisFox packages may be deployed')
    ftp.cwd(directory)
    existing = {PurePosixPath(name).name for name in ftp.nlst()}
    diagnostics_requested = any(path.name == PACKAGE_NAMES[1] for path in files)
    for path in files:
        temporary = '.' + path.name + '.uploading'
        offset = 0
        if temporary in existing:
            if resume:
                ftp.voidcmd('TYPE I')
                offset = ftp.size(temporary) or 0
            if not resume or offset < 0 or offset > path.stat().st_size:
                ftp.delete(temporary)
                offset = 0
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        if offset < path.stat().st_size:
            with path.open('rb') as source:
                source.seek(offset)
                if offset:
                    print(f'Resuming {path.name} at {offset} bytes; entire result will be hash-verified', flush=True)
                    ftp.storbinary('STOR ' + temporary, source, blocksize=128 * 1024, rest=offset)
                else:
                    ftp.storbinary('STOR ' + temporary, source, blocksize=128 * 1024)
        digest = hashlib.sha256()
        ftp.retrbinary('RETR ' + temporary, digest.update, blocksize=128 * 1024)
        if digest.hexdigest() != expected:
            ftp.delete(temporary)
            raise RuntimeError(f'Transfer hash mismatch: {path.name}; old package retained')
        # Do not remove an old working file until its replacement is verified.
        # Delete before rename so GoldHEN never has to overwrite an existing file.
        superseded = {path.name}
        if path.name == PACKAGE_NAMES[0]:
            superseded.add(LEGACY_MAIN_PACKAGE)
            if not diagnostics_requested:
                superseded.add(PACKAGE_NAMES[1])
        for old in sorted(superseded & existing):
            ftp.delete(old)
            existing.remove(old)
        ftp.rename(temporary, path.name)
        existing.add(path.name)
        print(f'Uploaded {directory}/{path.name}: {path.stat().st_size} bytes, SHA256 {expected}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=2121)
    parser.add_argument('--directory', default='/data/pkg')
    parser.add_argument('--user', default='anonymous')
    parser.add_argument('--include-diagnostics', action='store_true',
                        help='Also upload the optional VideoOut diagnostic; requires make pkg-videoout')
    parser.add_argument('--gecko', action='store_true',
                        help='Upload the separately verified 0.48 native bounded popup-provider full-Gecko test package')
    parser.add_argument('--resume', action='store_true',
                        help='Resume a partial hidden upload using FTP REST, then verify the entire file')
    args = parser.parse_args()
    source = ROOT / 'dist'
    if args.gecko:
        if args.include_diagnostics:
            parser.error('--gecko cannot be combined with --include-diagnostics')
        source /= 'gecko'
        report = json.loads((source / 'build-report.json').read_text())
        required = ('native_full_gecko_linked', 'new_package_created',
                    'extracted_payload_verified', 'extracted_sfo_verified')
        if not all(report.get(field) is True for field in required):
            raise ValueError('Full-Gecko package has not passed all local deployment gates')
        if hashlib.sha256((source / PACKAGE_NAMES[0]).read_bytes()).hexdigest() != report['sha256']:
            raise ValueError('Full-Gecko package hash differs from its verified report')
    with FTP() as ftp:
        ftp.connect(args.host, args.port, timeout=30)
        ftp.login(args.user, os.environ.get('PS4_FTP_PASSWORD', 'anonymous@'))
        names = PACKAGE_NAMES if args.include_diagnostics else PACKAGE_NAMES[:1]
        upload_packages(ftp, [source / name for name in names], args.directory, resume=args.resume)


if __name__ == '__main__':
    main()
