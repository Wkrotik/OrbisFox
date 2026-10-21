#!/usr/bin/env python3
"""Audit the native static-init dispatcher and produce an ELF-offset trace map."""
from pathlib import Path
import json
import struct

def verify(path, sdk='openorbis'):
    if sdk not in ('openorbis', 'homebrew'):
        raise ValueError('Unknown startup SDK: ' + str(sdk))
    data = Path(path).read_bytes()
    if len(data) < 64:
        raise ValueError('Truncated ELF header')
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if h[0][:6] != b'\x7fELF\x02\x01' or h[2] != 62:
        raise ValueError('Expected little-endian x86-64 ELF')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, h[6] + i*h[11]) for i in range(h[12])]
    symbols = {}; function_names = {}; relocations = {}; dynamic = {}
    code_functions = set()
    for s in sections:
        if s[1] == 2:
            names_section = sections[s[6]]
            names = data[names_section[4]:names_section[4]+names_section[5]]
            for offset in range(s[4], s[4]+s[5], s[9]):
                name, info, _, index, address, size = struct.unpack_from('<IBBHQQ', data, offset)
                label = names[name:names.find(b'\0', name)].decode()
                if index:
                    symbols[label] = address
                    if info & 15 == 2:
                        function_names[address] = label
                        if index < len(sections):
                            owner = sections[index]
                            if (owner[1] == 1 and owner[2] & 4 and size > 0
                                    and owner[3] <= address
                                    and address + size <= owner[3] + owner[5]):
                                code_functions.add(address)
        elif s[1] == 4:
            for offset in range(s[4], s[4]+s[5], s[9]):
                address, info, addend = struct.unpack_from('<QQq', data, offset)
                if info & 0xffffffff == 8:  # R_X86_64_RELATIVE
                    relocations[address] = addend
        elif s[1] == 6:
            for offset in range(s[4], s[4]+s[5], 16):
                tag, value = struct.unpack_from('<QQ', data, offset)
                dynamic[tag] = value
    dispatcher = symbols['orbisfox_startup_dispatch']
    if sdk == 'homebrew':
        if h[1] != 3 or h[4] != symbols.get('_start') or h[4] not in code_functions:
            raise ValueError('Native SDK startup requires a real PIE CRT entry')
        if '__orbisfox_initializers_start' in symbols or '__orbisfox_initializers_end' in symbols:
            raise ValueError('Legacy initializer dispatcher mixed with native SDK CRT')

        def array(kind, begin, end, tag, size_tag, *, allow_empty=False):
            start, stop = symbols[begin], symbols[end]
            if stop < start or (stop == start and not allow_empty) or (stop - start) % 8:
                raise ValueError('Invalid native SDK constructor/finalizer bounds')
            # The SDK linker collects old-style .ctors/.dtors inputs into
            # PROGBITS arrays; real dynamic tags and CRT bounds still agree.
            matching = [s for s in sections if s[1] in (kind, 1) and s[3] == start
                        and s[5] == stop - start and s[2] & 2]
            if len(matching) != 1:
                raise ValueError('Native SDK array does not match its allocated section')
            if dynamic.get(tag) != start or dynamic.get(size_tag) != stop - start:
                raise ValueError('Native SDK dynamic array bounds do not match CRT symbols')
            section = matching[0]
            entries = []
            for address in range(start, stop, 8):
                raw = struct.unpack_from('<Q', data, section[4] + address - start)[0]
                target = relocations.get(address)
                if raw not in (0, target) or target not in code_functions:
                    raise ValueError('Native SDK array entry lacks a real relocated code body')
                entries.append({'elf_offset': hex(target), 'symbol': function_names[target]})
            return entries

        preinit = array(16, '__preinit_array_start', '__preinit_array_end', 32, 33)
        if len(preinit) != 1 or int(preinit[0]['elf_offset'], 16) != dispatcher:
            raise ValueError('Native SDK preinit must contain only the logging dispatcher')
        initializers = array(14, '__init_array_start', '__init_array_end', 25, 27)
        finalizers = array(15, '__fini_array_start', '__fini_array_end', 26, 28,
                           allow_empty=True)
        if any(int(entry['elf_offset'], 16) == dispatcher for entry in initializers + finalizers):
            raise ValueError('Native SDK logging dispatcher would execute more than once')
        report = {'sdk': sdk, 'startup_model': 'native SDK preinit and constructor arrays',
                  'dispatcher': hex(dispatcher), 'crt_entry': hex(h[4]),
                  'preinitializers': preinit, 'initializers': initializers,
                  'finalizers': finalizers, 'console_startup_verified': False,
                  'console_cpp_shutdown_verified': False}
        Path(path).with_suffix('.startup-map.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f'Native SDK startup arrays: {len(initializers)} constructors; preinit dispatcher occurs once')
        return report
    if dynamic.get(27) != 8 or relocations.get(dynamic.get(25)) != dispatcher:
        raise ValueError('DT_INIT_ARRAY must contain exactly the startup dispatcher')
    start, end = (symbols[name] for name in ('__orbisfox_initializers_start', '__orbisfox_initializers_end'))
    if end <= start or (end-start) % 8:
        raise ValueError('Invalid upstream constructor table')
    initializers = []
    for address in range(start, end, 8):
        target = relocations.get(address)
        if target not in function_names or target == dispatcher:
            raise ValueError('Unrelocated, non-function, or recursive constructor')
        initializers.append({'elf_offset': hex(target), 'symbol': function_names[target]})
    # LLVM's init_priority(100) entry must precede ordinary upstream entries.
    if any(i['symbol'] == '_GLOBAL__I_000100' for i in initializers) and initializers[0]['symbol'] != '_GLOBAL__I_000100':
        raise ValueError('C++ runtime init_priority(100) not respected')
    report = {'dispatcher': hex(dispatcher), 'initializers': initializers,
              'console_startup_verified': False}
    Path(path).with_suffix('.startup-map.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Startup dispatcher: {len(initializers)} relocated constructors; runtime priority respected')
    return report

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('--sdk', choices=('openorbis', 'homebrew'), default='openorbis')
    args = parser.parse_args()
    verify(args.elf, sdk=args.sdk)
