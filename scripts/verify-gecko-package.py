#!/usr/bin/env python3
"""Extract and audit the isolated offline Gecko package; no console claims."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build/gecko-app'


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def read_sfo(data):
    magic, version, keys, values, count = struct.unpack_from('<4sIIII', data)
    if magic != b'\x00PSF' or version != 0x101:
        raise ValueError('Unexpected SFO header')
    result = {}
    for index in range(count):
        key, kind, length, maximum, offset = struct.unpack_from('<HHIII', data, 20 + index * 16)
        end = data.index(0, keys + key)
        name = data[keys + key:end].decode('utf-8')
        begin = values + offset
        if name in result or length > maximum or begin + maximum > len(data):
            raise ValueError('Invalid SFO entry: ' + name)
        result[name] = (kind, data[begin:begin + length])
    return result


def main():
    stage = BUILD / 'pkg'
    package = ROOT / 'dist/gecko/OrbisFox.pkg'
    expected = json.loads((ROOT / 'dist/gecko/build-report.json').read_text())
    if digest(package) != expected['sha256']:
        raise ValueError('Package differs from its build report')
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
    tool = sdk / 'bin/linux/PkgTool.Core'
    env = dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1')
    extracted = BUILD / 'extracted'
    if extracted.exists(): shutil.rmtree(extracted)
    with (BUILD / 'extraction.log').open('w') as log:
        subprocess.run([str(tool), 'pkg_extract', '--passcode', '0' * 32,
                        str(package), str(extracted)], env=env, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    entries = subprocess.check_output([str(tool), 'pkg_listentries', str(package)], env=env, text=True)
    (BUILD / 'package-entries.log').write_text(entries)
    metadata = {'PARAM_SFO': 'param.sfo', 'ICON0_PNG': 'icon0.png',
                'PIC0_PNG': 'pic0.png', 'PIC1_PNG': 'pic1.png'}
    payload = extracted / 'uroot'
    for line in entries.splitlines():
        fields = line.split()
        if not fields or fields[-1] not in metadata: continue
        target = payload / 'sce_sys' / metadata[fields[-1]]
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(tool), 'pkg_extractentry', '--passcode', '0' * 32,
                        str(package), fields[3], str(target)], env=env, check=True)
    verified = []
    for source in sorted(stage.rglob('*')):
        if not source.is_file(): continue
        name = source.relative_to(stage).as_posix()
        if name in ('project.gp4', 'sce_sys/param.sfo'): continue
        target = payload / name
        if not target.is_file() or digest(source) != digest(target):
            raise ValueError('Extracted payload mismatch: ' + name)
        verified.append({'path': name, 'bytes': target.stat().st_size, 'sha256': digest(target)})
    generated_prefs = ROOT / 'build/gecko-layout/dist/bin/greprefs.js'
    extracted_prefs = payload / 'gecko/greprefs.js'
    if not extracted_prefs.is_file() or digest(generated_prefs) != digest(extracted_prefs):
        raise ValueError('Required generated Gecko preferences missing or differ from engine output')
    staged_sfo = read_sfo((stage / 'sce_sys/param.sfo').read_bytes())
    actual_sfo = read_sfo((payload / 'sce_sys/param.sfo').read_bytes())
    for name, value in staged_sfo.items():
        if actual_sfo.get(name) != value:
            raise ValueError('Extracted SFO mismatch: ' + name)
    if set(actual_sfo) - set(staged_sfo) != {'PUBTOOLINFO', 'PUBTOOLVER'}:
        raise ValueError('Unexpected generated SFO metadata')
    required = {'TITLE': b'OrbisFox\0', 'TITLE_ID': b'ORBF00001\0',
                'APP_VER': b'0.68\0', 'VERSION': b'0.68\0', 'CATEGORY': b'gd\0',
                'CONTENT_ID': b'IV0000-ORBF00001_00-ORBISFOXPROBE000\0'}
    for name, value in required.items():
        if actual_sfo.get(name) != (0x204, value):
            raise ValueError('Unexpected package identity/version: ' + name)
    if actual_sfo.get('ATTRIBUTE') != (0x404, struct.pack('<I', 0x20)):
        raise ValueError('Common dialog must follow real system enter-button assignment')
    report = {'common_dialog_enter_button_assignment_system_verified': True, 'package_sha256': digest(package), 'verified_payload_files': len(verified),
              'all_non_generated_staged_files_match_extracted_package': True,
              'generated_sfo_identity_version_and_source_fields_verified': True,
              'generated_sfo_additional_keys': ['PUBTOOLINFO', 'PUBTOOLVER'],
              'html_rendered_on_console': False, 'hardware_tested': False, 'files': verified}
    (BUILD / 'extracted-payload-report.json').write_text(json.dumps(report, indent=2) + '\n')
    expected['extracted_payload_verified'] = True
    expected['extracted_payload_files_verified'] = len(verified)
    expected['extracted_sfo_verified'] = True
    expected['extracted_generated_greprefs_matches_engine_output'] = True
    expected['generated_greprefs_sha256'] = digest(generated_prefs)
    (ROOT / 'dist/gecko/build-report.json').write_text(json.dumps(expected, indent=2) + '\n')
    print(f'Extracted package: {len(verified)} files hash-verified; SFO identity/version verified.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
