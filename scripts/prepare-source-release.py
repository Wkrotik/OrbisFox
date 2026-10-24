#!/usr/bin/env python3
"""Create and read-back verify an allowlisted alpha source archive; never publish."""
import ast
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = ('.gitignore', '.gitattributes', 'Makefile', 'LICENSE', 'README.md',
              'CONTRIBUTING.md', 'AGENTS.md', 'THIRD_PARTY.md')
SOURCE_DIRS = ('assets', 'docs', 'gecko', 'include', 'rust', 'scripts', 'src', 'targets', 'tests', 'LICENSES')
EXTENSIONS = {'.cpp', '.c', '.h', '.hpp', '.S', '.inc', '.idl', '.ipdl', '.ipdlh',
              '.js', '.mjs', '.css', '.html', '.xhtml', '.json', '.toml', '.lock',
              '.py', '.sh', '.rs', '.ld', '.md', '.txt', '.jpg', '.jpeg', '.png',
              '.build', '.mozbuild', '.configure', '.conf'}


def version(root):
    tree = ast.parse((root / 'scripts/package-gecko.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and all(part.isdigit() for part in value.split('.')):
                return value
    raise ValueError('Missing literal package version')


def source_files(root):
    files = []
    for name in ROOT_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symlinked source root file: ' + name)
        files.append(path)
    for name in SOURCE_DIRS:
        directory = root / name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError('Missing or symlinked source directory: ' + name)
        for path in sorted(directory.rglob('*')):
            relative = path.relative_to(root)
            if '__pycache__' in relative.parts:
                continue
            if path.is_symlink():
                raise ValueError('Symlink in public source: ' + str(relative))
            if path.is_dir():
                continue
            if not path.is_file() or path.suffix not in EXTENSIONS:
                raise ValueError('Unreviewed file type in public source: ' + str(relative))
            files.append(path)
    if len(files) > 5000 or sum(p.stat().st_size for p in files) > 50 * 1024 * 1024:
        raise ValueError('Unexpected source volume; review before publication')
    return sorted(files)


def prepare(root=ROOT):
    files = source_files(root)
    release = 'orbisfox-' + version(root) + '-alpha-source'
    output = root / 'build/releases'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (release + '.tar.gz')
    records = []
    for path in files:
        data = path.read_bytes()
        records.append({'path': path.relative_to(root).as_posix(), 'bytes': len(data),
                        'sha256': hashlib.sha256(data).hexdigest(),
                        'mode': 0o755 if path.stat().st_mode & 0o111 else 0o644})
    manifest = {'release': release, 'source_only': True, 'files': records}
    manifest_data = (json.dumps(manifest, indent=2) + '\n').encode()
    pending = archive.with_suffix(archive.suffix + '.part')
    with pending.open('wb') as stream, gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w|') as tar:
        for path, record in zip(files, records):
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Source changed during export: ' + record['path'])
            member = tarfile.TarInfo(release + '/' + record['path'])
            member.size, member.mode = len(data), record['mode']
            tar.addfile(member, io.BytesIO(data))
        member = tarfile.TarInfo(release + '/SOURCE-MANIFEST.json')
        member.size, member.mode = len(manifest_data), 0o644
        tar.addfile(member, io.BytesIO(manifest_data))
    expected = {release + '/' + record['path']: record for record in records}
    seen = set()
    with tarfile.open(pending, 'r:gz') as tar:
        for member in tar:
            if not member.isfile() or member.name in seen:
                raise ValueError('Unexpected archive member')
            seen.add(member.name)
            data = tar.extractfile(member).read()
            if member.name == release + '/SOURCE-MANIFEST.json':
                if data != manifest_data:
                    raise ValueError('Manifest changed')
            else:
                record = expected.get(member.name)
                if record is None or len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256'] or member.mode != record['mode']:
                    raise ValueError('Source archive verification failed: ' + member.name)
    if seen != set(expected) | {release + '/SOURCE-MANIFEST.json'}:
        raise ValueError('Incomplete source archive')
    pending.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(digest + '  ' + archive.name + '\n')
    report = {'archive': str(archive.relative_to(root)), 'sha256': digest,
              'bytes': archive.stat().st_size, 'files_verified': len(records),
              'source_only': True, 'published': False, 'binary_redistribution_review_complete': False}
    (output / 'source-release-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    print(json.dumps(prepare(), indent=2))
