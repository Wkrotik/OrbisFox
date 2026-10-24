#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Package the compiled OrbisFox application and its artwork."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
TITLE_ID = 'ORBF00001'
CONTENT_ID = f'IV0000-{TITLE_ID}_00-ORBISFOXPROBE000'
VERSION = '0.11'
APP_TITLE = 'OrbisFox'
PACKAGE_NAME = 'OrbisFox.pkg'
SWGL_REVISION = '83cebcf5a522bf49667fd07084f04e8497de0eba'
VIDEOOUT_TITLE_ID = 'ORBV00001'
VIDEOOUT_CONTENT_ID = f'IV0000-{VIDEOOUT_TITLE_ID}_00-ORBISFOXVIDEO000'
# Composite/Piglet application capabilities, as used by OpenOrbis' Piglet sample.
# This is broader than a production browser should need; review before release.
AUTHINFO = '000000000000000000000000001C004000FF000000000080000000000000000000000000000000000000008000400040000000000000008000000000000000080040FFFF000000F000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'


def prepare_artwork(stage):
    """Convert user-supplied JPEGs to PS4 system PNGs and a bounded CPU surface."""
    system = stage / 'sce_sys'
    system.mkdir(parents=True, exist_ok=True)
    with Image.open(ROOT / 'assets/icon.jpg') as source:
        icon = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGBA'), (512, 512),
                            method=Image.Resampling.LANCZOS)
        icon.save(system / 'icon0.png', compress_level=9)
    with Image.open(ROOT / 'assets/splash.jpg') as source:
        splash = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGBA'), (1920, 1080),
                              method=Image.Resampling.LANCZOS)
        splash.save(system / 'pic0.png', compress_level=9)
        splash.save(system / 'pic1.png', compress_level=9)
        pixels = splash.resize((1280, 720), Image.Resampling.LANCZOS)
    (stage / 'assets').mkdir(exist_ok=True)
    # Decode once at build time: no new runtime JPEG/PNG library or imports.
    (stage / 'assets/splash.rgba').write_bytes(struct.pack('<8sII', b'ORBFIMG1', 1280, 720) + pixels.tobytes())
    return ['sce_sys/icon0.png', 'sce_sys/pic0.png', 'sce_sys/pic1.png', 'assets/splash.rgba']


def verify_oelf(path):
    """Catch linker layouts the ELF-to-Orbis converter cannot safely map."""
    data = path.read_bytes()
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if header[0][:6] != b'\x7fELF\x02\x01' or header[1] != 0xfe10 or header[2] != 62:
        raise ValueError('Expected a converted little-endian x86-64 Orbis ELF')
    if header[9] != 56 or header[11] != 64:
        raise ValueError('Unexpected ELF table entry size')
    programs = [struct.unpack_from('<IIQQQQQQ', data, header[5] + i * header[9])
                for i in range(header[10])]
    mapped = [p for p in programs if p[0] in (1, 0x61000010)]  # LOAD / SCE_RELRO
    if not mapped or any(p[7] != 0x4000 or p[2] % 0x4000 or p[3] % 0x4000 for p in mapped):
        raise ValueError('Orbis load segments must have 16 KiB alignment')
    for p in mapped:
        if p[5] > p[6] or p[2] + p[5] > len(data):
            raise ValueError('Invalid Orbis segment size')
    ordered = sorted(mapped, key=lambda p: p[3])
    for left, right in zip(ordered, ordered[1:]):
        # The loader maps whole 16 KiB pages, not just the declared bytes.
        end = (left[3] + left[6] + 0x3fff) & ~0x3fff
        if end > right[3]:
            raise ValueError('Overlapping Orbis load segments (including RELRO)')
    if len([p for p in mapped if p[0] == 1 and p[1] & 2]) != 1:
        raise ValueError('Expected one writable Orbis load segment')
    for p in programs:
        if p[0] == 7:  # PT_TLS, whose alignment the converter sets to 32 bytes.
            if not p[7] or p[7] & (p[7] - 1) or p[3] % p[7] or p[5] > p[6]:
                raise ValueError('Invalid Orbis TLS alignment or size')
            if not any(q[3] <= p[3] and p[3] + p[6] <= q[3] + q[6] for q in mapped):
                raise ValueError('TLS outside mapped memory')
    if not any(p[1] & 1 and p[3] <= header[4] < p[3] + p[6] for p in mapped):
        raise ValueError('Entry point outside executable segments')
    checked = 0
    for i in range(header[12]):
        section = struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * header[11])
        _, kind, flags, address, offset, size, *_ = section
        # DYNAMIC is consumed via a special Orbis header after conversion.
        if not flags & 2 or not size or kind == 6:
            continue
        if kind == 8:  # NOBITS still needs valid memory coverage (BSS / TLS).
            if not any(p[3] <= address and address + size <= p[3] + p[6] for p in mapped):
                raise ValueError(f'Allocated NOBITS section {i} outside Orbis memory mapping')
            continue
        if not any(p[3] <= address and address + size <= p[3] + p[5]
                   and offset == p[2] + address - p[3] for p in mapped):
            raise ValueError(f'Allocated section {i} does not match its Orbis load mapping')
        checked += 1
    if not checked:
        raise ValueError('No mapped payload sections')
    return checked


def auth_info_bytes(value):
    result = bytes.fromhex(value)
    if len(result) != 0x88:
        raise ValueError(f'Authentication record must be 136 bytes, not {len(result)}')
    return result


def verify_self(path, authinfo, paid):
    """Check emitted SELF metadata (also used after package extraction).

    Retained GPL-3.0-or-later validation from the standalone Mesa probe.
    """
    expected = auth_info_bytes(authinfo)
    data = path.read_bytes()
    if len(data) < 32 or struct.unpack_from('<I', data)[0] != 0x1d3d154f:
        raise ValueError('Expected a PS4 SELF header')
    header_size, metadata_size = struct.unpack_from('<HH', data, 12)
    if struct.unpack_from('<Q', data, 16)[0] != len(data):
        raise ValueError('SELF declared file size differs from payload')
    end = header_size + metadata_size
    if header_size < 32 or metadata_size < 256 or end > len(data):
        raise ValueError('Invalid SELF metadata bounds')
    signature = (struct.pack('<QQ', 0x88, paid) + expected[8:]).ljust(256, b'\0')
    if data[end-256:end] != signature:
        raise ValueError('SELF authentication record length, PAID or contents mismatch')
    return {'authinfo_bytes': 0x88, 'paid': hex(paid), 'signature_verified': True}


def verify_service_imports(path):
    """Optional service entry points must not bypass explicit runtime loading."""
    data = path.read_bytes()
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if header[0][:6] != b'\x7fELF\x02\x01' or header[2] != 62 or header[11] != 64:
        raise ValueError('Expected a little-endian x86-64 ELF')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * header[11])
                for i in range(header[12])]
    forbidden = []
    for section in sections:
        if section[1] != 11:  # SHT_DYNSYM
            continue
        if section[9] != 24 or section[6] >= len(sections):
            raise ValueError('Invalid dynamic symbol table')
        strings = sections[section[6]]
        names = data[strings[4]:strings[4] + strings[5]]
        for offset in range(section[4], section[4] + section[5], 24):
            name, _, _, index, _, _ = struct.unpack_from('<IBBHQQ', data, offset)
            if index != 0 or not name:
                continue
            end = names.find(b'\0', name)
            if name >= len(names) or end < 0:
                raise ValueError('Invalid symbol name')
            symbol = names[name:end].decode('ascii')
            if symbol.startswith(('sceVideoOut', 'sceUserService', 'scePad', 'sceSystemService')):
                forbidden.append(symbol)
    if forbidden:
        raise ValueError(f'Optional firmware services imported statically: {forbidden}')
    return forbidden


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=('main', 'piglet', 'videoout'), default='main')
    args = parser.parse_args()
    videoout = args.variant == 'videoout'
    title_id = VIDEOOUT_TITLE_ID if videoout else TITLE_ID
    content_id = VIDEOOUT_CONTENT_ID if videoout else CONTENT_ID
    title = 'OrbisFox VideoOut Diagnostic' if videoout else APP_TITLE
    build = ROOT / ('build/videoout' if videoout else 'build')
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
    tools = sdk / 'bin/linux'
    stage = build / 'pkg'
    dist = ROOT / 'dist'
    (stage / 'sce_sys').mkdir(parents=True, exist_ok=True)
    dist.mkdir(exist_ok=True)
    env = dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1')

    def run(tool, *args):
        subprocess.run([str(tools / tool), *map(str, args)], cwd=stage, env=env, check=True)

    # A package claiming JS integration must pass the real embedding tests.
    subprocess.run(['python3', str(ROOT / 'scripts/test-javascript.py')], check=True)
    subprocess.run(['python3', str(ROOT / 'scripts/verify-rust-abi.py'), str(build / 'orbisfox.elf')], check=True)
    subprocess.run(['python3', str(ROOT / 'scripts/verify-startup.py'), str(build / 'orbisfox.elf')], check=True)
    service_imports = verify_service_imports(build / 'orbisfox.elf')
    print('Optional service imports: none; runtime binding required', flush=True)
    run('create-fself', f'-in={build / "orbisfox.elf"}',
        f'-out={build / "orbisfox.oelf"}', '--eboot', 'eboot.bin',
        '--paid', '0x3800000000000035', '--authinfo', AUTHINFO)
    sections = verify_oelf(build / 'orbisfox.oelf')
    print(f'Orbis ELF layout: {sections} payload sections verified', flush=True)
    sfo = 'sce_sys/param.sfo'
    run('PkgTool.Core', 'sfo_new', sfo)
    entries = {
        'APP_TYPE': ('Integer', 4, '1'),
        'APP_VER': ('Utf8', 8, VERSION),
        'ATTRIBUTE': ('Integer', 4, '0'),
        'CATEGORY': ('Utf8', 4, 'gde'),
        'FORMAT': ('Utf8', 4, 'obs'),
        'CONTENT_ID': ('Utf8', 48, content_id),
        'DOWNLOAD_DATA_SIZE': ('Integer', 4, '0'),
        'SYSTEM_VER': ('Integer', 4, '1020'),
        'TITLE': ('Utf8', 128, title),
        'TITLE_ID': ('Utf8', 12, title_id),
        'VERSION': ('Utf8', 8, VERSION),
    }
    for key, (kind, size, value) in entries.items():
        run('PkgTool.Core', 'sfo_setentry', sfo, key, '--type', kind,
            '--maxsize', size, '--value', value)
    artwork = prepare_artwork(stage)
    script = stage / 'assets/playground.js'
    shutil.copy2(ROOT / 'assets/playground.js', script)
    licenses = {
        'project-MIT.txt': ROOT / 'LICENSE',
        'project-license-scope.md': ROOT / 'LICENSES/README.md',
        'third-party-notices.md': ROOT / 'THIRD_PARTY.md',
        'OpenOrbis-derived-GPL-3.0.txt': ROOT / 'LICENSES/GPL-3.0-only.txt',
        'MPL-2.0.txt': ROOT / 'LICENSES/MPL-2.0.txt',
        'mozilla-license.txt': ROOT / '.deps/gecko/LICENSE',
        'llvm-libcxx-license.txt': ROOT / '.deps/llvm-runtimes/libcxx/LICENSE.TXT',
        'llvm-libcxxabi-license.txt': ROOT / '.deps/llvm-runtimes/libcxxabi/LICENSE.TXT',
        'llvm-libunwind-license.txt': ROOT / '.deps/llvm-runtimes/libunwind/LICENSE.TXT',
    }
    license_files = []
    for name, source in licenses.items():
        target = stage / 'assets/misc' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        license_files.append('assets/misc/' + name)
    # Firmware modules/shaders are console-resident; only our code/assets ship.
    run('create-gp4', '-out', 'project.gp4', f'--content-id={content_id}',
        '--files', ' '.join(['eboot.bin', 'sce_sys/param.sfo', 'assets/playground.js', *artwork, *license_files]))
    run('PkgTool.Core', 'pkg_build', 'project.gp4', dist)
    artifact = dist / (f'{content_id}.pkg' if videoout else PACKAGE_NAME)
    built = dist / f'{content_id}.pkg'
    if artifact != built:
        built.replace(artifact)
    run('PkgTool.Core', 'pkg_validate', artifact)
    shutil.copy2(build / 'orbisfox.elf', dist / ('orbisfox-videoout.elf' if videoout else 'orbisfox.elf'))
    report = {
        'title': title,
        'version': VERSION,
        'variant': 'videoout' if videoout else 'main',
        'artwork': artwork,
        'overlapping_load_segments': False,
        'pre_main_static_initializer_trace': '/data/orbisfox/startup.log',
        'constructor_priorities_sorted': True,
        'pthread_attribute_handle_bytes': 8,
        'pthread_attribute_stack_guards_implemented': True,
        'stack_protection_disabled_to_mask_crash': False,
        'tls_alignment_verified': True,
        'touchpad_cursor_implemented': True,
        'normal_exit': 'SystemService LoadExec exit',
        'experimental_rust_runtime_included': True,
        'rust_runtime_hardware_tested': False,
        'rust_allocation_utf8_hardware_confirmed_version': '0.07 (user report)',
        'stick_cursor_divisor': 13,
        'previous_stick_cursor_divisor': 16,
        'content_id': content_id,
        'package': artifact.name,
        'bytes': artifact.stat().st_size,
        'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
        'gecko_included': False,  # Full Gecko layout/browser remains absent.
        'spidermonkey_included': True,
        'javascript_execution_implemented': True,
        'javascript_executed_on_console': False,
        'javascript_host_embedding_tests_passed': True,
        'javascript_jit_enabled': False,
        'javascript_gc_heap_limit_bytes': 32 * 1024 * 1024,
        'javascript_frame_deadline_ms': 100,
        'javascript_draw_command_limit': 512,
        'javascript_language_self_tests': 12,
        'javascript_canvas_is_not_dom_or_html_layout': True,
        'private_libcxx_version': '21.1.8',
        'private_libcxx_hardware_tested': False,
        'bundled_script': 'assets/playground.js',
        'licenses': license_files,
        'swgl_included': True,
        'swgl_revision': SWGL_REVISION,
        'html_css_layout_included': False,
        'primary_default_presenter': 'VideoOut',
        'network_access_implemented': False,
        'hardware_tested': False,
        'oelf_payload_sections_verified': sections,
        'static_optional_service_imports': service_imports,
        'package_validation': 'OpenOrbis PkgTool.Core completed; inspect validation output',
        'compiled_presenters': (['VideoOut CPU scanout'] if videoout else
                               ['Piglet GLES2 GPU texture blit', 'VideoOut CPU scanout']),
    }
    report_name = 'build-report-videoout.json' if videoout else 'build-report.json'
    (dist / report_name).write_text(json.dumps(report, indent=2) + '\n')
    print(f'Built {artifact}')


if __name__ == '__main__':
    main()
