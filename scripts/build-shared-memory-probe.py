#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a local standalone shm diagnostic with the browser's public SDK path.

No network, upload, install, launch or diagnostics-marker operations. Native
linking/package extraction and host execution are not console execution proof.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/shared-memory-probe'
TITLE = 'SHMP00001'
CONTENT = 'IV0000-SHMP00001_00-SHMEMPROBE000001'
SOURCES = ['tests/shared_memory_repro_main.cpp', 'src/ps4/modules.cpp',
           'src/ps4/services.cpp', 'src/ps4/native_stat.cpp']

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def run(command, cwd=ROOT):
    with (OUT / 'build.log').open('ab') as f:
        f.write(('\n$ ' + ' '.join(map(str, command)) + '\n').encode()); f.flush()
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=f,
                       stderr=subprocess.STDOUT, check=True,
                       env=dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1'))

def read_sfo(path):
    data = Path(path).read_bytes()
    magic, version, keys, values, count = struct.unpack_from('<5I', data)
    if magic != 0x46535000 or version != 0x101 or not (20 + count * 16 <= keys <= values <= len(data)):
        raise ValueError('Invalid SFO header')
    metadata = {}
    for i in range(count):
        key, kind, size, capacity, offset = struct.unpack_from('<HHIII', data, 20 + i * 16)
        if not (keys <= keys + key < values) or size > capacity or values + offset + capacity > len(data):
            raise ValueError('Invalid SFO entry bounds')
        name = data[keys + key:data.index(0, keys + key, values)].decode()
        if name in metadata: raise ValueError('Duplicate SFO key')
        value = data[values + offset:values + offset + size]
        metadata[name] = kind, value
    return metadata

def package(elf, sdk):
    spec = importlib.util.spec_from_file_location('probe_package_helpers', ROOT / 'scripts/package.py')
    helpers = importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
    stage = OUT / 'pkg'; (stage / 'sce_sys').mkdir(parents=True, exist_ok=True)
    tools = sdk / 'bin/linux'
    def tool(name, *args): run([tools / name, *args], stage)
    helpers.auth_info_bytes(helpers.AUTHINFO)
    tool('create-fself', '-in=' + str(elf), '-out=' + str(OUT / 'probe.oelf'),
         '--eboot', 'eboot.bin', '--paid', '0x3800000000000035', '--authinfo', helpers.AUTHINFO)
    sections = helpers.verify_oelf(OUT / 'probe.oelf')
    signature = helpers.verify_self(stage / 'eboot.bin', helpers.AUTHINFO, 0x3800000000000035)
    tool('PkgTool.Core', 'sfo_new', 'sce_sys/param.sfo')
    entries = {'APP_TYPE': ('Integer', 4, '1'), 'APP_VER': ('Utf8', 8, '00.01'),
               'ATTRIBUTE': ('Integer', 4, '0'), 'CATEGORY': ('Utf8', 4, 'gd'),
               'FORMAT': ('Utf8', 4, 'obs'), 'CONTENT_ID': ('Utf8', 48, CONTENT),
               'DOWNLOAD_DATA_SIZE': ('Integer', 4, '0'), 'SYSTEM_VER': ('Integer', 4, '1020'),
               'TITLE': ('Utf8', 128, 'Shared Memory Probe'),
               'TITLE_ID': ('Utf8', 12, TITLE), 'VERSION': ('Utf8', 8, '00.01')}
    for key, (kind, size, value) in entries.items():
        tool('PkgTool.Core', 'sfo_setentry', 'sce_sys/param.sfo', key,
             '--type', kind, '--maxsize', size, '--value', value)
    from PIL import Image
    Image.new('RGB', (512, 512), (35, 68, 85)).save(stage / 'sce_sys/icon0.png')
    # Exact owned source + relevant integration/third-party notices, never SDK
    # archives, machine paths, profiles, credentials, captures or Git metadata.
    source = [*map(lambda p: ROOT / p, SOURCES), Path(__file__),
              ROOT / 'scripts/package.py', ROOT / 'scripts/orbis-cc.py',
              ROOT / 'scripts/orbis-cxx.py', ROOT / 'scripts/ps4-gecko.ld',
              ROOT / 'LICENSE', ROOT / 'LICENSES/README.md',
              ROOT / 'LICENSES/GPL-3.0-only.txt']
    source += list((ROOT / 'include/orbisfox').glob('*.h'))
    import tarfile
    with tarfile.open(stage / 'source.tar.gz', 'w:gz') as archive:
        for path in sorted(set(source)):
            if path.is_symlink() or not path.is_file(): raise ValueError('Invalid source input: ' + str(path))
            archive.add(path, arcname='shared-memory-probe/' + path.relative_to(ROOT).as_posix(), recursive=False)
    files = ['eboot.bin', 'sce_sys/param.sfo', 'sce_sys/icon0.png', 'source.tar.gz']
    tool('create-gp4', '-out', 'probe.gp4', '--content-id=' + CONTENT, '--files', ' '.join(files))
    tree = ET.parse(stage / 'probe.gp4'); root = tree.getroot()
    old = root.find('rootdir')
    if old is not None: root.remove(old)
    dirs = ET.SubElement(root, 'rootdir'); ET.SubElement(dirs, 'dir', {'targ_name': 'sce_sys'})
    tree.write(stage / 'probe.gp4', encoding='utf-8', xml_declaration=True)
    tool('PkgTool.Core', 'pkg_build', 'probe.gp4', OUT)
    pkg = OUT / (CONTENT + '.pkg')
    tool('PkgTool.Core', 'pkg_validate', pkg)
    # Unique extraction directory; never delete prior artifacts or evidence.
    import tempfile
    extracted = Path(tempfile.mkdtemp(prefix='extracted-', dir=OUT))
    tool('PkgTool.Core', 'pkg_extract', '--passcode', '0' * 32, pkg, extracted)
    payload = extracted / 'uroot'
    listing = subprocess.check_output([str(tools / 'PkgTool.Core'), 'pkg_listentries', str(pkg)],
                                     text=True, env=dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1'))
    found = set()
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[-1] in ('PARAM_SFO', 'ICON0_PNG'):
            name = 'param.sfo' if fields[-1] == 'PARAM_SFO' else 'icon0.png'
            (payload / 'sce_sys').mkdir(exist_ok=True)
            tool('PkgTool.Core', 'pkg_extractentry', '--passcode', '0' * 32, pkg,
                 fields[3], payload / 'sce_sys' / name)
            found.add(name)
    if found != {'param.sfo', 'icon0.png'}: raise ValueError('Missing extracted system entries')
    for name in files:
        if name != 'sce_sys/param.sfo' and sha(payload / name) != sha(stage / name):
            raise ValueError('Extracted mismatch: ' + name)
    expected = read_sfo(stage / 'sce_sys/param.sfo')
    metadata = read_sfo(payload / 'sce_sys/param.sfo')
    # PkgTool adds its own PUBTOOLINFO/PUBTOOLVER fields and changes layout.
    # Require every original value/type intact, not a byte-identical SFO blob.
    for key, value in expected.items():
        if metadata.get(key) != value: raise ValueError('Extracted SFO mismatch: ' + key)
    if set(metadata) - set(expected) - {'PUBTOOLINFO', 'PUBTOOLVER'}:
        raise ValueError('Unexpected extracted SFO metadata')
    for key, value in {'TITLE_ID': TITLE, 'CONTENT_ID': CONTENT, 'APP_VER': '00.01', 'CATEGORY': 'gd'}.items():
        if metadata.get(key) != (0x204, value.encode() + b'\0'):
            raise ValueError('Extracted SFO identity mismatch: ' + key)
    helpers.verify_self(payload / 'eboot.bin', helpers.AUTHINFO, 0x3800000000000035)
    return {'file': str(pkg.relative_to(ROOT)), 'bytes': pkg.stat().st_size,
            'sha256': sha(pkg), 'sections_verified': sections, 'self': signature,
            'title_id': TITLE, 'content_id': CONTENT, 'extracted_files_verified': files,
            'extracted_sfo_verified': True}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', action='store_true')
    args = parser.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
    # The converter also consumes this variable; keep its input SDK identical.
    os.environ['OO_PS4_TOOLCHAIN'] = str(sdk)
    objects = []
    flags = ['-std=c++20', '-O2', '-g', '-fPIC', '-mno-red-zone', '-funwind-tables',
             '-fno-exceptions', '-fno-rtti', '-ffunction-sections', '-fdata-sections',
             '-Wall', '-Wextra', '-Werror', '-I' + str(ROOT / 'include')]
    for source in SOURCES:
        obj = OUT / (source.replace('/', '_') + '.o'); objects.append(obj)
        run([ROOT / 'scripts/orbis-cxx.py', *flags, '-c', ROOT / source, '-o', obj])
    elf = OUT / 'shared-memory-probe.elf'; runtime = ROOT / '.deps/libcxx-orbis/lib'
    run(['ld.lld', '-m', 'elf_x86_64', '-pie', '-z', 'max-page-size=0x4000', '--no-rosegment',
         '--gc-sections', '--strip-debug', '--script', ROOT / 'scripts/ps4-gecko.ld', '--eh-frame-hdr',
         '-Map=' + str(OUT / 'link.map'), '-L' + str(runtime), '-L' + str(sdk / 'lib'),
         '-o', elf, sdk / 'lib/crt1.o', *objects, '-lc++', '-lc++abi', '-lunwind', '-lc', '-lkernel', '-lSceSysmodule'])
    definitions = subprocess.check_output(['llvm-nm', '--defined-only', elf], text=True)
    for name in ('shared_memory_probe_startup', 'main', 'fstat'):
        if not any(line.split()[-2:] == ['T', name] or line.split()[-2:] == ['t', name]
                   for line in definitions.splitlines()): raise ValueError('Missing code body: ' + name)
    spec = importlib.util.spec_from_file_location('probe_package_helpers', ROOT / 'scripts/package.py')
    helpers = importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
    helpers.verify_service_imports(elf)
    report = {'native_linked': True, 'console_tested': False, 'uploaded': False,
              'diagnostics_flags_changed': False, 'browser_profiles_accessed': False,
              'elf': {'file': str(elf.relative_to(ROOT)), 'bytes': elf.stat().st_size, 'sha256': sha(elf)},
              'sources': {p: sha(ROOT / p) for p in SOURCES +
                          ['include/orbisfox/shared_memory_repro.h', 'scripts/build-shared-memory-probe.py',
                           'scripts/orbis-cxx.py', 'scripts/orbis-cc.py', 'scripts/ps4-gecko.ld',
                           'scripts/package.py']},
              'sdk_libc_sha256': sha(sdk / 'lib/libc.a'),
              'native_runtime_sha256': {name: sha(sdk / 'lib' / name) for name in
                                       ('crt1.o', 'libkernel.so', 'libSceSysmodule.so')},
              'private_cxx_sha256': {name: sha(runtime / name) for name in
                                     ('libc++.a', 'libc++abi.a', 'libunwind.a')},
              'limitations': ['Raw POSIX reproduction, not the Gecko IPC serialization/transport layer',
                              '16 MiB backing-pressure bound does not reproduce an exhausted browser process',
                              'Browser allocator wrappers and GPU rendering are not part of this small probe']}
    if args.package: report['package'] = package(elf, sdk)
    (OUT / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
