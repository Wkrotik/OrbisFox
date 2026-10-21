#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a separate runtime probe with only the pinned new SDK's native inputs.

No browser rebuild, upload, install, launch, diagnostics changes or cleanup.
--dialog selects CommonDialog/IME instead of the general runtime checks.
--package uses new SDK producers and the existing PkgTool only for independent
validation/extraction. Local packages are not public licensing sign-off.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import struct
import tarfile
import time

ROOT = Path(__file__).resolve().parent.parent
FETCH = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-sdk.py'))
TITLE = 'OSDK00001'
CONTENT = 'IV0000-OSDK00001_00-SDKPROBE00000001'
PAID = 0x3800000000000035
SOURCE = ROOT / 'tests/homebrew_sdk_probe.c'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(path):
    path = Path(path)
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def verify_converted_elf(path):
    """Validate the new converter's deliberately sectionless Orbis ELF layout.

    Do not weaken package.py's distinct OpenOrbis section-table contract.
    """
    data = Path(path).read_bytes()
    if len(data) < 64:
        raise ValueError('Truncated new-SDK Orbis ELF')
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if h[0][:6] != b'\x7fELF\x02\x01' or h[1] != 0xfe10 or h[2] != 62:
        raise ValueError('Expected new-SDK x86-64 Orbis ELF')
    if h[8] != 64 or h[9] != 56 or h[6] or h[11] or h[12] or h[13]:
        raise ValueError('Expected sectionless new-SDK ELF')
    if not 3 <= h[10] <= 32 or h[5] < 64 or h[5] + h[10] * 56 > len(data):
        raise ValueError('Invalid new-SDK program table')
    programs = [struct.unpack_from('<IIQQQQQQ', data, h[5] + i * 56) for i in range(h[10])]
    if any(p[2] + p[5] > len(data) for p in programs):
        raise ValueError('New-SDK program payload outside file')
    mapped = sorted((p for p in programs if p[0] in (1, 0x61000010)), key=lambda p: p[3])
    if not mapped or any(p[7] != 0x4000 or p[2] % 0x4000 or p[3] % 0x4000 or
                         p[5] > p[6] or (p[1] & 3) == 3 for p in mapped):
        raise ValueError('Invalid new-SDK mapping size/alignment/protection')
    for left, right in zip(mapped, mapped[1:]):
        if ((left[3] + left[6] + 0x3fff) & ~0x3fff) > right[3]:
            raise ValueError('Overlapping new-SDK mapped pages')
    if sum(bool(p[1] & 2) for p in mapped) != 1:
        raise ValueError('Expected one writable new-SDK mapping')
    if not any(p[1] & 1 and p[3] <= h[4] < p[3] + p[6] for p in mapped):
        raise ValueError('New-SDK entry outside executable mapping')
    tls = [p for p in programs if p[0] == 7]
    if len(tls) != 1:
        raise ValueError('Runtime probe requires one actual TLS segment')
    for p in tls:
        if (not p[7] or p[7] & (p[7] - 1) or p[3] % p[7] or p[5] > p[6] or
                not any(q[3] <= p[3] and p[3] + p[6] <= q[3] + q[6] and
                        p[2] == q[2] + p[3] - q[3] for q in mapped)):
            raise ValueError('Invalid new-SDK TLS mapping')
    return {'sectionless': True, 'mapped_segments': len(mapped), 'programs': len(programs),
            'tls_bytes': tls[0][6], 'entry': h[4]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', action='store_true')
    parser.add_argument('--dialog', action='store_true', help='Test native CommonDialog/IME without Gecko')
    args = parser.parse_args()
    sdk = FETCH['fetch']()
    native_sources = [SOURCE]
    producer_sources = ['scripts/build-homebrew-sdk-probe.py', 'scripts/fetch-homebrew-sdk.py']
    declarations = None
    if args.dialog:
        declarations = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))
        declarations['fetch']()
        native_sources.append(ROOT / 'tests/homebrew_dialog_probe.h')
        producer_sources.append('scripts/fetch-homebrew-service-headers.py')
    if shutil.disk_usage(ROOT).free < 256 * 1024 * 1024:
        raise RuntimeError('Insufficient free space for bounded runtime probe')
    base = ROOT / 'build/homebrew-sdk-probe'
    out = base / str(time.time_ns())
    out.mkdir(parents=True)
    commands = []
    report = {'sdk_version': FETCH['VERSION'], 'sdk_revision': FETCH['REVISION'],
              'sdk_archive_sha256': FETCH['SHA256'], 'console_tested': False,
              'title_id': TITLE, 'content_id': CONTENT,
              'probe_mode': 'dialog' if args.dialog else 'runtime',
              'app_version': '00.02' if args.dialog else '00.01',
              'native_sources': {str(path.relative_to(ROOT)): fingerprint(path) for path in native_sources},
              'producer_sources': {name: fingerprint(ROOT / name) for name in producer_sources},
              'sdk_inventory': fingerprint(sdk / 'source-report.json'),
              'package_verified': False, 'commands': commands}
    if declarations:
        report['service_declarations'] = declarations['verify']()
    def run(command, cwd=ROOT):
        command = list(map(str, command))
        commands.append(command)
        with (out / 'build.log').open('ab') as log:
            log.write(('\n$ ' + ' '.join(command) + '\n').encode()); log.flush()
            subprocess.run(command, cwd=cwd, check=True, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1'))
    try:
        compiler = sdk / 'bin/orbis-clang'
        report['compiler_version'] = subprocess.check_output([compiler, '--version'], text=True)
        elf, oelf = out / 'runtime.elf', out / 'runtime.oelf'
        stage = out / 'pkg'; (stage / 'sce_sys').mkdir(parents=True)
        dialog_flags = []
        if args.dialog:
            assert declarations is not None
            dialog_flags = ['-DORBISFOX_SDK_PROBE_DIALOG', '-I', declarations['DESTINATION'] / 'include']
        run([compiler, '-std=c11', '-DORBISFOX_SDK_PROBE_NATIVE', *dialog_flags, '-O2', '-g',
             '-mno-red-zone', '-Wall', '-Wextra', '-Werror', SOURCE,
             '-lSceSystemService', '-Wl,-Map,' + str(out / 'native-link.map'), '-o', elf])
        # Keep the native link map so every runtime owner can be inspected.
        report['native_link_map'] = fingerprint(out / 'native-link.map')
        report['elf'] = fingerprint(elf)
        run([sdk / 'bin/orbis-elf2self', '--paid', hex(PAID), '--elf', oelf,
             elf, stage / 'eboot.bin'])
        helpers = runpy.run_path(str(ROOT / 'scripts/package.py'))
        converter = runpy.run_path(str(sdk / 'bin/orbis-elf2self'))
        auth = converter['auth_info_type'](converter['AUTH_INFO']).hex()
        report['self'] = helpers['verify_self'](stage / 'eboot.bin', auth, PAID)
        report['oelf_layout'] = verify_converted_elf(oelf)
        report['eboot'] = fingerprint(stage / 'eboot.bin')
        # These are declared actual system dependencies, not fake PRLibrary handles.
        dynamic = subprocess.check_output(['llvm-readelf', '-d', elf], text=True)
        needed = [line.split('[')[1].split(']')[0] for line in dynamic.splitlines() if '(NEEDED)' in line]
        expected = {'libkernel.sprx', 'libSceLibcInternal.sprx', 'libSceSysmodule.sprx',
                    'libSceNet.sprx', 'libSceSystemService.sprx'}
        if set(needed) != expected:
            raise RuntimeError('Unexpected new-SDK runtime dependencies: ' + str(needed))
        report['system_dependencies'] = needed
        symbols = subprocess.check_output(['llvm-nm', '--defined-only', elf], text=True)
        if not any(line.split()[1:] == ['T', 'catchReturnFromMain'] for line in symbols.splitlines()):
            raise RuntimeError('Probe must own the strong SDK main-return hook')
        report['application_exit'] = {'hook': 'catchReturnFromMain',
                                      'service': 'sceSystemServiceLoadExec',
                                      'request': 'exit', 'general_cpp_teardown_proven': False}
        if args.package:
            from PIL import Image
            Image.new('RGB', (512, 512), (25, 72, 78)).save(stage / 'sce_sys/icon0.png')
            entries = {'APP_TYPE': 1, 'ATTRIBUTE': 0, 'DOWNLOAD_DATA_SIZE': 0, 'SYSTEM_VER': 1020}
            strings = {'APP_VER': (8, report['app_version']), 'VERSION': (8, report['app_version']),
                       'CATEGORY': (4, 'gd'), 'FORMAT': (4, 'obs'), 'CONTENT_ID': (48, CONTENT),
                       'TITLE_ID': (12, TITLE),
                       'TITLE': (128, 'OrbisFox SDK Dialog Probe' if args.dialog else 'OrbisFox SDK Probe')}
            command = [sdk / 'bin/orbis-mksfo']
            for name, value in entries.items(): command += ['-i', f'{name}={value}']
            for name, (size, value) in strings.items(): command += ['-s', str(size), f'{name}={value}']
            run([*command, 'sce_sys/param.sfo'], stage)
            # Owned probe sources plus exact upstream pin, never SDK binaries/private evidence.
            names = ['tests/homebrew_sdk_probe.c', 'scripts/fetch-homebrew-sdk.py',
                     'scripts/build-homebrew-sdk-probe.py', 'scripts/package.py',
                     'scripts/build-shared-memory-probe.py', 'docs/HOMEBREW_SDK.md',
                     'LICENSE', 'LICENSES/README.md', 'LICENSES/GPL-3.0-only.txt']
            if args.dialog:
                names += ['tests/homebrew_dialog_probe.h', 'scripts/fetch-homebrew-service-headers.py']
            report['package_sources'] = {name: fingerprint(ROOT / name) for name in names}
            with tarfile.open(stage / 'source.tar.gz', 'w:gz') as archive:
                for name in names:
                    source = ROOT / name
                    if source.is_symlink() or not source.is_file(): raise RuntimeError('Invalid probe source')
                    archive.add(source, arcname='sdk-probe/' + name, recursive=False)
            files = ['eboot.bin', 'sce_sys/param.sfo', 'sce_sys/icon0.png', 'source.tar.gz']
            run([sdk / 'bin/orbis-mkgp4', '-c', CONTENT, '-o', 'probe.gp4', *files], stage)
            pkg = out / (CONTENT + '.pkg')
            run([sdk / 'bin/orbis-mkpkg', '-o', pkg, 'probe.gp4'], stage)
            validator = ROOT / '.deps/OpenOrbis/PS4Toolchain/bin/linux/PkgTool.Core'
            if not validator.is_file(): raise RuntimeError('Independent PkgTool validator is required')
            run([validator, 'pkg_validate', pkg])
            extract = out / 'extracted'
            run([validator, 'pkg_extract', '--passcode', '0' * 32, pkg, extract])
            payload = extract / 'uroot'
            listing = subprocess.check_output([validator, 'pkg_listentries', pkg], text=True,
                       env=dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1'))
            found = set()
            for line in listing.splitlines():
                fields = line.split()
                if len(fields) >= 5 and fields[-1] in ('PARAM_SFO', 'ICON0_PNG'):
                    name = 'param.sfo' if fields[-1] == 'PARAM_SFO' else 'icon0.png'
                    (payload / 'sce_sys').mkdir(exist_ok=True)
                    run([validator, 'pkg_extractentry', '--passcode', '0' * 32, pkg,
                         fields[3], payload / 'sce_sys' / name])
                    found.add(name)
            if found != {'param.sfo', 'icon0.png'}: raise RuntimeError('Missing extracted system metadata')
            read_sfo = runpy.run_path(str(ROOT / 'scripts/build-shared-memory-probe.py'))['read_sfo']
            expected = read_sfo(stage / 'sce_sys/param.sfo')
            actual = read_sfo(payload / 'sce_sys/param.sfo')
            if any(actual.get(k) != v for k, v in expected.items()) or (
                    set(actual) - set(expected) - {'PUBTOOLINFO', 'PUBTOOLVER'}):
                raise RuntimeError('Extracted package metadata changed')
            for name in files:
                if name != 'sce_sys/param.sfo' and sha(payload / name) != sha(stage / name):
                    raise RuntimeError('Extracted probe payload changed: ' + name)
            helpers['verify_self'](payload / 'eboot.bin', auth, PAID)
            report.update(package_verified=True, package=fingerprint(pkg), package_path=str(pkg.relative_to(ROOT)),
                          extracted_files=files)
        report['result'] = 0
    except Exception as error:
        report.update(result=1, error=str(error))
        raise
    finally:
        path = out / 'build-report.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        (base / 'latest-build.json').write_text(json.dumps({'report': str(path.relative_to(ROOT))}, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
    main()
