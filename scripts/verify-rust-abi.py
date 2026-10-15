#!/usr/bin/env python3
"""Compare SDK C++ and Rust ABI constants directly from the cross-linked ELF."""
from pathlib import Path
import struct
import sys


def verify(path):
    data = Path(path).read_bytes()
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    if header[0][:6] != b'\x7fELF\x02\x01' or header[2] != 62:
        raise ValueError('Expected little-endian x86-64 ELF')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * header[11])
                for i in range(header[12])]
    found = {}
    for section in sections:
        if section[1] != 2:
            continue
        names_section = sections[section[6]]
        names = data[names_section[4]:names_section[4] + names_section[5]]
        for offset in range(section[4], section[4] + section[5], section[9]):
            name, _, _, index, address, size = struct.unpack_from('<IBBHQQ', data, offset)
            label = names[name:names.find(b'\0', name)].decode('utf8')
            if label in ('ORBISFOX_CPP_ABI', 'ORBISFOX_RUST_ABI') and index:
                source = sections[index]
                start = source[4] + address - source[3]
                found[label] = data[start:start + size]
    if len(found) != 2 or any(len(v) != 256 for v in found.values()):
        raise ValueError('Both complete 32-field ABI tables must be linked')
    left = struct.unpack('<32Q', found['ORBISFOX_CPP_ABI'])
    right = struct.unpack('<32Q', found['ORBISFOX_RUST_ABI'])
    for i, (a, b) in enumerate(zip(left, right), 1):
        if a != b:
            raise ValueError(f'ABI field {i} mismatch: OpenOrbis={a}, Rust={b}')
    print('Rust/OpenOrbis: all 32 audited ABI layouts/constants match in cross-linked ELF')


if __name__ == '__main__':
    verify(sys.argv[1])
