#!/usr/bin/env python3
"""Audit the native static-init dispatcher and produce an ELF-offset trace map."""
from pathlib import Path
import json
import struct
import sys

def verify(path):
    data = Path(path).read_bytes()
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if h[0][:6] != b'\x7fELF\x02\x01' or h[2] != 62:
        raise ValueError('Expected little-endian x86-64 ELF')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, h[6] + i*h[11]) for i in range(h[12])]
    symbols = {}; function_names = {}; relocations = {}; dynamic = {}
    for s in sections:
        if s[1] == 2:
            names_section = sections[s[6]]
            names = data[names_section[4]:names_section[4]+names_section[5]]
            for offset in range(s[4], s[4]+s[5], s[9]):
                name, info, _, index, address, _ = struct.unpack_from('<IBBHQQ', data, offset)
                label = names[name:names.find(b'\0', name)].decode()
                if index:
                    symbols[label] = address
                    if info & 15 == 2:
                        function_names[address] = label
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
    verify(sys.argv[1])
