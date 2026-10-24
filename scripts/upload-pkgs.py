#!/usr/bin/env python3
"""Deploy only OrbisFox packages, verify transfer, and replace previous versions."""
import argparse
from ftplib import FTP
import hashlib
import json
import os
import re
import runpy
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
SHARED_MEMORY_PROBE_PACKAGE = 'IV0000-SHMP00001_00-SHMEMPROBE000001.pkg'
HOMEBREW_SDK_PROBE_PACKAGE = 'IV0000-OSDK00001_00-SDKPROBE00000001.pkg'
IDENTITY = runpy.run_path(str(Path(__file__).with_name('gecko-package-identity.py')))
HOMEBREW_BROWSER_PACKAGE = IDENTITY['package_identity'](sdk='homebrew')['package_name']
PACKAGE_NAMES = (
    'OrbisFox.pkg',
    'IV0000-ORBV00001_00-ORBISFOXVIDEO000.pkg',
    'OrbisFox-Mesa.pkg',
    SHARED_MEMORY_PROBE_PACKAGE,
    HOMEBREW_SDK_PROBE_PACKAGE,
    HOMEBREW_BROWSER_PACKAGE,
)
LEGACY_MAIN_PACKAGE = 'IV0000-ORBF00001_00-ORBISFOXPROBE000.pkg'


def shared_memory_probe_candidate(root=ROOT):
    root = Path(root).resolve()
    report = json.loads((root / 'build/shared-memory-probe/build-report.json').read_text())
    package = report['package']
    if (report.get('native_linked') is not True or package.get('title_id') != 'SHMP00001'
            or package.get('content_id') != 'IV0000-SHMP00001_00-SHMEMPROBE000001'
            or package.get('extracted_sfo_verified') is not True
            or set(package.get('extracted_files_verified', [])) !=
               {'eboot.bin', 'sce_sys/param.sfo', 'sce_sys/icon0.png', 'source.tar.gz'}
            or package.get('self') != {'authinfo_bytes': 136, 'paid': '0x3800000000000035',
                                       'signature_verified': True}
            or not isinstance(package.get('sections_verified'), int) or package['sections_verified'] <= 0):
        raise ValueError('Shared-memory probe verification incomplete')
    expected = {'package': 'build/shared-memory-probe/' + SHARED_MEMORY_PROBE_PACKAGE,
                'elf': 'build/shared-memory-probe/shared-memory-probe.elf'}
    for kind, name in expected.items():
        artifact = package if kind == 'package' else report['elf']
        path = root / name
        if (artifact['file'] != name or path.is_symlink() or path.stat().st_size != artifact['bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']):
            raise ValueError('Shared-memory probe artifact mismatch: ' + kind)
    if not report.get('sources'):
        raise ValueError('Shared-memory probe lacks source fingerprints')
    for name, digest in report['sources'].items():
        path = (root / name).resolve()
        if (Path(name).is_absolute() or not path.is_relative_to(root)
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise ValueError('Shared-memory probe source changed: ' + name)
    return report


def homebrew_sdk_probe_candidate(root=ROOT):
    """Validate only the fixed standalone new-SDK probe, without downloading."""
    root = Path(root).resolve()
    base = root / 'build/homebrew-sdk-probe'
    pointer = json.loads((base / 'latest-build.json').read_text())
    name = pointer.get('report', '')
    if not re.fullmatch(r'build/homebrew-sdk-probe/[0-9]{10,24}/build-report\.json', name):
        raise ValueError('Invalid new-SDK probe build pointer')
    path = root / name
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('New-SDK probe report path escaped its build directory')
    report = json.loads(path.read_text())
    expected_package = str(path.parent.relative_to(root) / HOMEBREW_SDK_PROBE_PACKAGE)
    if (report.get('result') != 0 or report.get('package_verified') is not True or
            report.get('title_id') != 'OSDK00001' or
            report.get('content_id') != 'IV0000-OSDK00001_00-SDKPROBE00000001' or
            report.get('package_path') != expected_package or
            set(report.get('extracted_files', [])) !=
                {'eboot.bin', 'sce_sys/param.sfo', 'sce_sys/icon0.png', 'source.tar.gz'} or
            report.get('self') != {'authinfo_bytes': 136, 'paid': '0x3800000000000035',
                                   'signature_verified': True} or
            report.get('oelf_layout', {}).get('sectionless') is not True or
            report.get('oelf_layout', {}).get('mapped_segments') != 3 or
            report.get('oelf_layout', {}).get('tls_bytes') != 4 or
            report.get('application_exit') !=
                {'hook': 'catchReturnFromMain', 'service': 'sceSystemServiceLoadExec',
                 'request': 'exit', 'general_cpp_teardown_proven': False} or
            set(report.get('system_dependencies', [])) !=
                {'libkernel.sprx', 'libSceLibcInternal.sprx', 'libSceSysmodule.sprx',
                 'libSceNet.sprx', 'libSceSystemService.sprx'}):
        raise ValueError('New-SDK probe verification incomplete')
    def fingerprint(relative, expected):
        source = root / relative
        if (Path(relative).is_absolute() or source.resolve() != source or
                not source.is_relative_to(root) or source.stat().st_size != expected['bytes'] or
                hashlib.sha256(source.read_bytes()).hexdigest() != expected['sha256']):
            raise ValueError('New-SDK probe input/artifact changed: ' + relative)
    for key, relative in (('package', expected_package),
                          ('elf', str(path.parent.relative_to(root) / 'runtime.elf')),
                          ('eboot', str(path.parent.relative_to(root) / 'pkg/eboot.bin'))):
        fingerprint(relative, report[key])
    for field, required in (('native_sources', {'tests/homebrew_sdk_probe.c'}),
                            ('producer_sources', {'scripts/build-homebrew-sdk-probe.py', 'scripts/fetch-homebrew-sdk.py'}),
                            ('package_sources', {'scripts/package.py', 'scripts/build-shared-memory-probe.py',
                                                 'docs/HOMEBREW_SDK.md', 'LICENSES/README.md'})):
        sources = report.get(field, {})
        if not required.issubset(sources):
            raise ValueError('New-SDK probe lacks source fingerprints: ' + field)
        for relative, expected in sources.items():
            fingerprint(relative, expected)
    mode = report.get('probe_mode', 'runtime')
    if mode not in ('runtime', 'dialog'):
        raise ValueError('Unknown new-SDK probe mode')
    expected_version = '00.02' if mode == 'dialog' else '00.01'
    if report.get('app_version', '00.01') != expected_version:
        raise ValueError('New-SDK probe version/mode mismatch')
    if mode == 'dialog':
        for field, required in (
                ('native_sources', {'tests/homebrew_dialog_probe.h'}),
                ('producer_sources', {'scripts/fetch-homebrew-service-headers.py'}),
                ('package_sources', {'tests/homebrew_dialog_probe.h', 'scripts/fetch-homebrew-service-headers.py'})):
            if not required.issubset(report[field]):
                raise ValueError('Dialog probe lacks source fingerprints: ' + field)
        headers = runpy.run_path(str(root / 'scripts/fetch-homebrew-service-headers.py'))
        if report.get('service_declarations') != headers['verify']():
            raise ValueError('Dialog probe service declarations changed')
    fetch = runpy.run_path(str(root / 'scripts/fetch-homebrew-sdk.py'))
    if any(report.get(key) != fetch[value] for key, value in
           (('sdk_version', 'VERSION'), ('sdk_revision', 'REVISION'), ('sdk_archive_sha256', 'SHA256'))):
        raise ValueError('New-SDK probe source pin mismatch')
    sdk = root / '.deps' / ('ps4-homebrew-sdk-' + fetch['VERSION'])
    fetch['verify_sdk'](sdk)
    fingerprint(str((sdk / 'source-report.json').relative_to(root)), report['sdk_inventory'])
    return path, report


def homebrew_browser_candidate(root=ROOT):
    """Select the fixed SDK browser; never fall back to a different installer."""
    root = Path(root).resolve()
    build_dir, dist_dir = IDENTITY['package_directories']('homebrew')
    build, dist = root / build_dir, root / dist_dir
    report_path, app_path = dist / 'build-report.json', build / 'build-report.json'
    for path in (report_path, app_path):
        if path.resolve() != path:
            raise ValueError('Native browser report path escaped its output directory')
    report, app = json.loads(report_path.read_text()), json.loads(app_path.read_text())
    identity = IDENTITY['report_identity'](report)
    required = ('native_full_gecko_linked', 'new_package_created', 'extracted_payload_verified',
                'extracted_sfo_verified', 'ffmpeg_source_and_configuration_match_linked_application')
    if (report.get('sdk') != 'homebrew' or app.get('sdk') != 'homebrew' or
            identity != IDENTITY['package_identity'](sdk='homebrew') or
            not all(report.get(key) is True for key in required) or
            report.get('self_authentication_metadata_verified') != {
                'authinfo_bytes': 136, 'paid': '0x3800000000000035', 'signature_verified': True} or
            report.get('experimental_mesa', False) or app.get('experimental_native_mesa') or
            not re.fullmatch(r'[0-9]+\.[0-9]+', report.get('version', '')) or
            app.get('version') != report['version']):
        raise ValueError('Native browser verification/SDK identity incomplete')
    pkg = dist / identity['package_name']
    if (pkg.resolve() != pkg or pkg.stat().st_size != report['bytes'] or
            hashlib.sha256(pkg.read_bytes()).hexdigest() != report['sha256']):
        raise ValueError('Native browser package bytes/hash changed after verification')
    if (hashlib.sha256(app_path.read_bytes()).hexdigest() != report.get('native_application_report_sha256') or
            report.get('native_executable') != app['executable'] or
            report.get('sdk_identity') != app.get('sdk_identity')):
        raise ValueError('Native browser package/application binding changed')
    if not app.get('runtime_source_sha256'):
        raise ValueError('Native browser lacks runtime source fingerprints')
    for name in app['runtime_source_sha256']:
        if Path(name).is_absolute() or not (root / name).resolve().is_relative_to(root):
            raise ValueError('Native browser runtime source escaped repository: ' + name)
    packaging = runpy.run_path(str(root / 'scripts/package-gecko.py'))
    packaging['validate_application'](app, build, 'homebrew')
    return report['version'], report, app


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
    parser.add_argument('--sdk', choices=('openorbis', 'homebrew'), default='openorbis',
                        help='homebrew requires --gecko and selects only ORHB00001')
    parser.add_argument('--include-diagnostics', action='store_true',
                        help='Also upload the optional VideoOut diagnostic; requires make pkg-videoout')
    parser.add_argument('--homebrew-sdk-probe', action='store_true',
                        help='Upload only the separately verified OSDK00001 runtime probe')
    parser.add_argument('--shared-memory-probe', action='store_true',
                        help='Upload only the separately verified SHMP00001 diagnostic installer')
    parser.add_argument('--gecko', action='store_true',
                        help='Upload the separately verified 0.48 native bounded popup-provider full-Gecko test package')
    parser.add_argument('--resume', action='store_true',
                        help='Resume a partial hidden upload using FTP REST, then verify the entire file')
    args = parser.parse_args()
    if args.sdk == 'homebrew' and (not args.gecko or args.homebrew_sdk_probe or
                                   args.shared_memory_probe or args.include_diagnostics):
        parser.error('--sdk homebrew requires --gecko without other installer choices')
    source = ROOT / 'dist'
    if args.homebrew_sdk_probe:
        if args.shared_memory_probe or args.gecko or args.include_diagnostics:
            parser.error('--homebrew-sdk-probe cannot be combined with other installer choices')
        sdk_report_path, _ = homebrew_sdk_probe_candidate()
        source = sdk_report_path.parent
    if args.shared_memory_probe:
        if args.gecko or args.include_diagnostics:
            parser.error('--shared-memory-probe cannot be combined with other installer choices')
        shared_memory_probe_candidate()
        source = ROOT / 'build/shared-memory-probe'
    if args.gecko:
        if args.include_diagnostics:
            parser.error('--gecko cannot be combined with --include-diagnostics')
        source = ROOT / IDENTITY['package_directories'](args.sdk)[1]
        if args.sdk == 'homebrew':
            homebrew_browser_candidate()
        report = json.loads((source / 'build-report.json').read_text())
        required = ('native_full_gecko_linked', 'new_package_created',
                    'extracted_payload_verified', 'extracted_sfo_verified')
        if not all(report.get(field) is True for field in required):
            raise ValueError('Full-Gecko package has not passed all local deployment gates')
        identity = runpy.run_path(str(ROOT / 'scripts/gecko-package-identity.py'))['report_identity'](report)
        if hashlib.sha256((source / identity['package_name']).read_bytes()).hexdigest() != report['sha256']:
            raise ValueError('Full-Gecko package hash differs from its verified report')
    with FTP() as ftp:
        ftp.connect(args.host, args.port, timeout=30)
        ftp.login(args.user, os.environ.get('PS4_FTP_PASSWORD', 'anonymous@'))
        names = PACKAGE_NAMES[:2] if args.include_diagnostics else PACKAGE_NAMES[:1]
        if args.gecko:
            names = (identity['package_name'],)
        if args.shared_memory_probe:
            names = (SHARED_MEMORY_PROBE_PACKAGE,)
        if args.homebrew_sdk_probe:
            names = (HOMEBREW_SDK_PROBE_PACKAGE,)
        upload_packages(ftp, [source / name for name in names], args.directory, resume=args.resume)


if __name__ == '__main__':
    main()
