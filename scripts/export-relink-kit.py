#!/usr/bin/env python3
"""Export verified, relocatable application inputs for static FFmpeg relinking.

Only enumerated native-link inputs are exported, not an SDK distribution,
firmware modules, profiles, captures, or arbitrary build-directory contents.
The audited public musl allocator object is a required application link input.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def materialize(source, destination):
    """Preserve archive order and duplicate members; remove only debug sections."""
    with source.open('rb') as stream:
        thin = source.suffix == '.a' and stream.read(8) == b'!<thin>\n'
    if thin:
        members = subprocess.check_output(['llvm-ar', 't', source], text=True).splitlines()
        paths = [(source.parent / name).resolve() for name in members]
        if not paths or any(not p.is_file() or not p.is_relative_to(ROOT) for p in paths):
            raise ValueError('Missing/out-of-project thin archive member: ' + str(source))
        response = destination.with_suffix('.members')
        response.write_text('\n'.join(shlex.quote(str(p)) for p in paths) + '\n')
        try:
            subprocess.run(['llvm-ar', 'rcsD', destination, '@' + str(response)], check=True)
        finally:
            response.unlink(missing_ok=True)
    else:
        shutil.copyfile(source, destination)
    subprocess.run(['llvm-objcopy', '--strip-debug', destination], check=True)


def same_image_and_symbols(original, rebuilt):
    """Allow only a permutation of non-loadable .symtab entries, nothing else.

    Materializing thin archives changes lld's local-symbol enumeration order.
    Code/data, headers, relocations, dynamic symbols and every symbol record
    must remain identical. This is deliberately stricter than a text-only check.
    """
    a, b = original.read_bytes(), rebuilt.read_bytes()
    if a == b:
        return True
    if len(a) != len(b) or a[:64] != b[:64] or a[:6] != b'\x7fELF\x02\x01':
        return False
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', a)
    tables = []
    for index in range(header[12]):
        section = struct.unpack_from('<IIQQQQIIQQ', a, header[6] + index * header[11])
        if section[1] == 2:
            if section[2] & 2 or section[9] != 24:
                return False
            tables.append(section)
    if len(tables) != 1:
        return False
    section = tables[0]
    start, end = section[4], section[4] + section[5]
    if end > len(a) or section[5] % 24 or a[:start] != b[:start] or a[end:] != b[end:]:
        return False
    return sorted(a[i:i+24] for i in range(start, end, 24)) == sorted(b[i:i+24] for i in range(start, end, 24))


RELINK = '''#!/usr/bin/env python3
"""Relink application with replacement LGPL archives; never install or launch."""
import argparse,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--sdk',required=True,type=Path,help='Hash-pinned public OpenOrbis PS4Toolchain directory')
p.add_argument('--codecs',type=Path,help='Replacement liborbis_{avcodec,swresample,avutil}.a directory')
p.add_argument('--output',required=True,type=Path)
a=p.parse_args();root=Path(__file__).resolve().parent
spec=json.loads((root/'link.json').read_text());sdk=a.sdk.resolve()
if not (sdk/'lib/crt1.o').is_file():p.error('Expected public SDK lib/crt1.o')
codecs=(a.codecs or root/'codecs').resolve()
for name in ('avcodec','swresample','avutil'):
 if not (codecs/('liborbis_'+name+'.a')).is_file():p.error('Missing replacement '+name)
values={'@KIT@':str(root),'@SDK@':str(sdk),'@CODECS@':str(codecs),'@OUTPUT@':str(a.output.resolve())}
def expand(s):
 for key,value in values.items():s=s.replace(key,value)
 return s
# Pass arguments directly, never through a shell or an unquoted response file.
subprocess.run([expand(s) for s in spec['command']],check=True)
# Match the native producer's final normalization after its strict link.
subprocess.run(['llvm-strip','--strip-debug',str(a.output.resolve())],check=True)
print('Relinked ELF:',a.output.resolve())
print('This does not create a package, install, launch, or certify firmware behavior.')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-log', type=Path, required=True,
                        help='Native builder stdout containing its final ld.lld command')
    parser.add_argument('--source-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    native = json.loads((ROOT / 'build/gecko-app/build-report.json').read_text())
    elf = ROOT / native['executable']['path']
    if not native.get('final_engine_application_linked') or sha(elf) != native['executable']['sha256']:
        raise ValueError('Verified native ELF required')
    for name, digest in native['runtime_source_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('Native source has changed: ' + name)
    commands = [shlex.split(line[2:]) for line in args.native_log.read_text().splitlines()
                if line.startswith('+ ld.lld ')]
    if not commands:
        raise ValueError('No native link command')
    command = commands[-1]
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
    runtime = ROOT / '.deps/libcxx-orbis/lib'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='relink-', dir=args.output.parent) as directory:
        kit = Path(directory) / 'orbisfox-relink'
        kit.mkdir()
        inventory = []

        def copy_input(source, target, *, strip=False):
            destination = kit / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            if strip:
                materialize(source, destination)
            else:
                shutil.copyfile(source, destination)
            inventory.append({'path': target, 'bytes': destination.stat().st_size, 'sha256': sha(destination)})
            return str(destination)

        inputs = shlex.split((ROOT / 'build/gecko-app/engine-inputs.rsp').read_text())
        flattened = []
        codec_names = {'liborbis_' + name + '.a' for name in ('avcodec', 'swresample', 'avutil')}
        for index, item in enumerate(inputs):
            if item in ('--start-group', '--end-group'):
                flattened.append(item)
                continue
            source = Path(item).resolve()
            if not source.is_relative_to(ROOT / 'build') or source.suffix not in ('.o', '.a'):
                raise ValueError('Unexpected application link input: ' + str(source))
            target = ('codecs/' + source.name if source.name in codec_names
                      else f'inputs/{index:04d}' + source.suffix)
            copy_input(source, target, strip=True)
            flattened.append(('@CODECS@/' + source.name) if source.name in codec_names else '@KIT@/' + target)
        # LLVM runtimes are public Apache/LLVM-exception inputs, not SDK/firmware copies.
        for name in ('libc++.a', 'libc++abi.a', 'libunwind.a'):
            copy_input(runtime / name, 'runtime/' + name, strip=True)
        copy_input(ROOT / 'scripts/ps4-gecko.ld', 'ps4-gecko.ld')
        for name in ('LICENSE', 'THIRD_PARTY.md', 'LICENSES/README.md',
                     'LICENSES/GPL-3.0-only.txt', 'LICENSES/MPL-2.0.txt',
                     'docs/RELINKING.md', 'assets/licenses/musl-COPYRIGHT.txt'):
            copy_input(ROOT / name, 'source-notices/' + name)
        for library in ('libcxx', 'libcxxabi', 'libunwind'):
            copy_input(ROOT / '.deps/llvm-runtimes' / library / 'LICENSE.TXT',
                       'source-notices/llvm-' + library + '.txt')
        copy_input(args.source_archive.resolve(), 'orbisfox-source.tar.gz')
        copy_input(ROOT / '.deps/downloads/ffmpeg-9.0.2.tar.xz', 'ffmpeg-9.0.2.tar.xz')
        copy_input(ROOT / '.deps/ffmpeg-9.0.2/COPYING.LGPLv2.1', 'COPYING.LGPLv2.1')
        for name in ('config.h', 'config_components.h', 'configuration.json', 'build-report.json', 'symbol-map.txt'):
            copy_input(ROOT / 'build/media-codecs/native' / name, 'codec-build/' + name)
        rewritten = []
        for arg in command:
            if arg == '@' + str(ROOT / 'build/gecko-app/engine-inputs.rsp'):
                rewritten.extend(flattened)
            elif arg == str(elf):
                rewritten.append('@OUTPUT@')
            elif arg == str(ROOT / 'scripts/ps4-gecko.ld'):
                rewritten.append('@KIT@/ps4-gecko.ld')
            elif arg == '-L' + str(runtime):
                rewritten.append('-L@KIT@/runtime')
            else:
                arg = arg.replace(str(sdk), '@SDK@')
                if str(ROOT) in arg:
                    raise ValueError('Unmapped local link path: ' + arg)
                rewritten.append(arg)
        spec = {'command': rewritten, 'original_elf_sha256': sha(elf),
                'source_archive_sha256': sha(args.source_archive.resolve()), 'files': inventory}
        (kit / 'link.json').write_text(json.dumps(spec, indent=2) + '\n')
        (kit / 'relink.py').write_text(RELINK)
        # Test the shipped inputs/driver before archiving, not a separate guessed command.
        trial = Path(directory) / 'relinked.elf'
        subprocess.run(['python3', kit / 'relink.py', '--sdk', sdk, '--output', trial], check=True)
        if not same_image_and_symbols(elf, trial):
            shutil.copyfile(trial, args.output.parent / 'relink-mismatch.elf')
            raise ValueError('Relink changed more than non-loadable symbol-table ordering')
        report = {key: spec[key] for key in ('original_elf_sha256', 'source_archive_sha256')}
        report.update(relinked_elf_sha256=sha(trial), byte_identical_relink_verified=sha(trial) == sha(elf),
                      execution_image_and_all_symbol_records_identical=True,
                      permitted_difference='non-loadable symtab entry ordering only',
                      input_files=len(inventory), native_execution_tested=False)
        (kit / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        with tarfile.open(args.output, 'w:gz', compresslevel=6) as packed:
            packed.add(kit, arcname='orbisfox-relink')
    report.update(archive=str(args.output), bytes=args.output.stat().st_size, sha256=sha(args.output))
    args.output.with_suffix(args.output.suffix + '.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
