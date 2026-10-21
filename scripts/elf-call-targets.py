#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve final x86-64 calls without trusting nearest-symbol disassembly labels.

The native SDK merges PLT thunks into .text. Follow their actual RIP-relative
GOT slots and ELF relocations, not labels such as unrelated_function+offset.
This inspects the final image; it does not execute it or certify console ABI.
"""
from pathlib import Path
import re
import struct


def call_targets(path, assembly):
    data = Path(path).read_bytes()

    def bounded(offset, size):
        if offset < 0 or size < 0 or offset + size > len(data):
            raise ValueError('Final ELF call audit range is out of bounds')
        return memoryview(data)[offset:offset + size]

    header = struct.unpack('<16sHHIQQQIHHHHHH', bounded(0, 64))
    if header[0][:6] != b'\x7fELF\x02\x01' or header[2] != 62 or header[11] != 64:
        raise ValueError('Call audit requires little-endian x86-64 ELF sections')
    sections = [struct.unpack('<IIQQQQIIQQ', bounded(header[6] + i * 64, 64))
                for i in range(header[12])]

    def code(address, size):
        for section in sections:
            if (section[2] & 4 and section[3] <= address
                    and address + size <= section[3] + section[5]):
                return bytes(bounded(section[4] + address - section[3], size))
        raise ValueError('Final ELF call target is outside executable sections')

    tables = {}
    functions = {}
    for index, section in enumerate(sections):
        if section[1] not in (2, 11):  # SYMTAB, DYNSYM
            continue
        if section[9] != 24 or section[5] % 24 or section[6] >= len(sections):
            raise ValueError('Invalid final ELF symbol table')
        strings = sections[section[6]]
        names = bytes(bounded(strings[4], strings[5]))
        table = []
        for offset in range(section[4], section[4] + section[5], 24):
            name, info, _, owner, address, _ = struct.unpack('<IBBHQQ', bounded(offset, 24))
            end = names.find(b'\0', name)
            if name >= len(names) or end < 0:
                raise ValueError('Invalid final ELF symbol name')
            label = names[name:end].decode('utf-8')
            table.append((label, owner))
            if owner and info & 15 == 2:
                functions.setdefault(address, set()).add(label)
        tables[index] = table

    imports = {}
    for section in sections:
        if section[1] != 4:  # RELA
            continue
        if section[9] != 24 or section[5] % 24 or section[6] not in tables:
            raise ValueError('Invalid final ELF relocation table')
        table = tables[section[6]]
        for address, info, _ in struct.iter_unpack('<QQq', bounded(section[4], section[5])):
            kind, symbol = info & 0xffffffff, info >> 32
            if kind not in (6, 7):  # GLOB_DAT, JUMP_SLOT
                continue
            if symbol >= len(table):
                raise ValueError('Invalid final ELF relocation symbol')
            label, owner = table[symbol]
            if owner == 0:
                imports[address] = label

    result = []
    pattern = re.compile(r'^\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}\s+)+)(?:callq?|jmpq?)\s')
    for line in assembly.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        pc = int(match[1], 16)
        instruction = bytes.fromhex(match[2])
        if code(pc, len(instruction)) != instruction:
            raise ValueError('Disassembly bytes do not match final ELF')
        target = got = None
        if instruction[:1] in (b'\xe8', b'\xe9') and len(instruction) == 5:
            target = pc + 5 + struct.unpack('<i', instruction[1:])[0]
            if target in functions:
                for name in sorted(functions[target]):
                    result.append({'instruction': hex(pc), 'target': hex(target),
                                   'symbol': name, 'imported': False})
                continue
            thunk = code(target, 6)
            if thunk[:2] == b'\xff\x25':
                got = target + 6 + struct.unpack('<i', thunk[2:])[0]
        elif instruction[:2] in (b'\xff\x15', b'\xff\x25') and len(instruction) == 6:
            got = pc + 6 + struct.unpack('<i', instruction[2:])[0]
        if got in imports:
            result.append({'instruction': hex(pc), 'target': hex(target) if target is not None else None,
                           'got': hex(got), 'symbol': imports[got], 'imported': True})
    return result
