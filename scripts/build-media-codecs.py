#!/usr/bin/env python3
"""Reproducible, isolated LGPL software decoders; no network or hardware backend.

All defined codec symbols are namespaced before linking, so Gecko's bundled
FFVPX and this matching-major upstream implementation cannot share internal state.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '9.0.2'
SHA256 = '8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e'
PREFIX = 'orbis_media_'
DECODERS = 'h264,aac,vp8,vp9,mp3,flac,opus,vorbis,pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_alaw,pcm_mulaw'
LIBRARIES = ('avcodec', 'swresample', 'avutil')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, cwd, log):
    with log.open('ab') as stream:
        subprocess.run([str(x) for x in command], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def source():
    archive = ROOT / f'.deps/downloads/ffmpeg-{VERSION}.tar.xz'
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix('.download')
        with urllib.request.urlopen(f'https://ffmpeg.org/releases/{archive.name}', timeout=120) as response:
            with temporary.open('wb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
        if sha(temporary) != SHA256:
            temporary.unlink()
            raise ValueError('FFmpeg archive hash mismatch')
        temporary.replace(archive)
    if sha(archive) != SHA256:
        raise ValueError('FFmpeg archive hash mismatch')
    destination = ROOT / f'.deps/ffmpeg-{VERSION}'
    if not destination.exists():
        with tarfile.open(archive) as packed:
            packed.extractall(ROOT / '.deps', filter='data')
    # Verify the extracted source too; a modified dependency is not silently used.
    with tarfile.open(archive) as packed:
        for entry in packed:
            if entry.isfile():
                path = ROOT / '.deps' / entry.name
                if not path.is_file() or path.is_symlink() or path.read_bytes() != packed.extractfile(entry).read():
                    raise ValueError('Modified FFmpeg source: ' + entry.name)
    return destination


def symbols(archives):
    result = set()
    for archive in archives:
        text = subprocess.check_output(['llvm-nm', '--defined-only', '--extern-only', archive], text=True)
        for line in text.splitlines():
            fields = line.split()
            if len(fields) == 3 and len(fields[-2]) == 1:
                result.add(fields[-1])
    return result


def build(host=False, jobs=4):
    if not (ROOT / '.deps/host-tools/bin/nasm').is_file():
        subprocess.run([sys.executable, str(ROOT / 'scripts/bootstrap-nasm.py')], check=True)
    src = source()
    out = ROOT / 'build/media-codecs' / ('host' if host else 'native')
    out.mkdir(parents=True, exist_ok=True)
    log = out / 'build.log'
    command = [src / 'configure', '--disable-all', '--disable-autodetect',
               '--disable-network', '--disable-programs', '--disable-doc', '--disable-shared',
               '--enable-static', '--enable-pic', '--disable-gpl', '--disable-nonfree',
               '--disable-version3', '--enable-avcodec', '--enable-avutil', '--enable-swresample',
               '--enable-pthreads', '--enable-decoder=' + DECODERS,
               '--enable-parser=h264,aac,vp8,vp9', '--ar=llvm-ar', '--ranlib=llvm-ranlib',
               '--nm=llvm-nm', '--x86asmexe=' + str(ROOT / '.deps/host-tools/bin/nasm')]
    cflags = '-ffunction-sections -fdata-sections'
    if host:
        command += ['--cc=clang']
    else:
        command += ['--enable-cross-compile', '--target-os=freebsd', '--arch=x86_64',
                    '--cc=' + str(ROOT / 'scripts/orbis-cc.py')]
        cflags += ' -D__ORBIS__ -D_GNU_SOURCE -D_BSD_SOURCE -mno-red-zone'
    command += ['--extra-cflags=' + cflags]
    stamp = out / 'configuration.json'
    identity = {'command': [str(x) for x in command], 'source_sha256': SHA256,
                'builder_sha256': sha(Path(__file__)),
                'compiler_wrapper_sha256': sha(ROOT / 'scripts/orbis-cc.py')}
    if not stamp.exists() or json.loads(stamp.read_text()) != identity:
        run(command, out, log)
        if not host:
            # SDK libc advertises sysctl but provides no sys/sysctl.h. Use the
            # existing real sysconf/CPUID path, not a fake sysctl implementation.
            config = out / 'config.h'
            text = config.read_text()
            for flag in ('HAVE_SYSCTL', 'HAVE_SYSCTLBYNAME'):
                text = text.replace(f'#define {flag} 1', f'#define {flag} 0')
            config.write_text(text)
        stamp.write_text(json.dumps(identity, indent=2) + '\n')
    config = (out / 'config.h').read_text()
    components = (out / 'config_components.h').read_text()
    for flag in ('CONFIG_GPL', 'CONFIG_NONFREE', 'CONFIG_VERSION3', 'CONFIG_NETWORK'):
        if f'#define {flag} 0' not in config:
            raise ValueError('Unexpected codec license/network configuration: ' + flag)
    for decoder in DECODERS.split(','):
        if f'#define CONFIG_{decoder.upper()}_DECODER 1' not in components:
            raise ValueError('Missing real decoder: ' + decoder)
    targets = [f'lib{name}/lib{name}.a' for name in LIBRARIES]
    run(['make', '-j' + str(jobs), *targets], out, log)
    archives = [out / name for name in targets]
    names = symbols(archives)
    required = {'ff_h264_decoder', 'ff_aac_decoder', 'avcodec_find_decoder', 'avcodec_send_packet',
                'avcodec_receive_frame', 'av_tx_init', 'av_tx_uninit'}
    if not required <= names:
        raise ValueError('Actual codec object definitions missing: ' + str(required - names))
    mapping = out / 'symbol-map.txt'
    mapping.write_text(''.join(f'{name} {PREFIX}{name}\n' for name in sorted(names)))
    prefixed = []
    for archive in archives:
        output = out / ('liborbis_' + archive.name[3:])
        run(['llvm-objcopy', '--redefine-syms=' + str(mapping), archive, output], out, log)
        prefixed.append(output)
    after = symbols(prefixed)
    if any(name in after for name in names) or not {PREFIX + name for name in names} <= after:
        raise ValueError('Incomplete codec namespace isolation')
    report = {'stage': 'real isolated software codecs', 'version': VERSION, 'host': host,
              'source_url': f'https://ffmpeg.org/releases/ffmpeg-{VERSION}.tar.xz',
              'source_sha256': SHA256, 'license': 'LGPL-2.1-or-later', 'gpl': False,
              'network': False, 'hardware_decoding': False, 'console_tested': False,
              'decoders': DECODERS.split(','), 'symbol_prefix': PREFIX,
              'config_sha256': sha(out / 'config.h'), 'components_sha256': sha(out / 'config_components.h'),
              'archives': [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p)} for p in prefixed]}
    (out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', action='store_true', help='Build host decode-test variant, not a firmware proof')
    parser.add_argument('--jobs', type=int, default=4, choices=range(1, 33))
    args = parser.parse_args()
    build(args.host, args.jobs)
