#!/usr/bin/env python3
"""Expose read-only state and route realloc-copy through an audit delegate.
Only symbol references in a private SDK malloc.lo copy change. The pinned
archive and every allocator instruction/data byte stay unchanged; copy still
uses the genuine SDK memcpy implementation.
"""
from pathlib import Path
import hashlib
import struct
import subprocess


def sections(data):
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected little-endian ELF64 SDK allocator object')
    offset = struct.unpack_from('<Q', data, 40)[0]
    stride, count, names = struct.unpack_from('<HHH', data, 58)
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * stride) for i in range(count)]
    strings = headers[names]
    names_data = data[strings[4]:strings[4] + strings[5]]
    result = {}
    for header in headers:
        name = names_data[header[0]:].split(b'\0', 1)[0].decode()
        if header[2] & 2:  # Every SHF_ALLOC section, including zero-filled BSS size.
            result[name] = (header[1], header[2], header[5], header[8],
                            b'' if header[1] == 8 else data[header[4]:header[4] + header[5]])
    return result


def expose(original, output):
    before = Path(original).read_bytes()
    expected = 'd98f00ff8d2f732bfa568940c31c1627ce1eb35354e86ed17034fe4cf1e930f5'
    if hashlib.sha256(before).hexdigest() != expected:
        raise ValueError('Unpinned SDK allocator object; read-only bin audit refused')
    if sections(before).get('.bss.mal', (None, None, None))[2] != 1552:
        raise ValueError('Unexpected SDK malloc bin-state layout; audit binding refused')
    symbols = subprocess.check_output(['llvm-nm', '-S', str(original)], text=True)
    if not any(line.split()[2:] == ['b', 'mal'] for line in symbols.splitlines() if len(line.split()) == 4):
        raise ValueError('Expected local SDK malloc state symbol mal')
    subprocess.run(['llvm-objcopy', '--globalize-symbol=mal',
                    '--redefine-sym=mal=orbisfox_sdk_malloc_state',
                    '--redefine-sym=memcpy=orbisfox_sdk_realloc_copy', str(original), str(output)], check=True)
    after = Path(output).read_bytes()
    if sections(before) != sections(after):
        raise ValueError('Read-only audit exposure changed allocated SDK object section bytes')
    symbols = subprocess.check_output(['llvm-nm', '-S', str(output)], text=True)
    if not any(line.split()[2:] == ['B', 'orbisfox_sdk_malloc_state'] for line in symbols.splitlines() if len(line.split()) == 4):
        raise ValueError('SDK malloc audit symbol not exposed')
    return {'original_sha256': hashlib.sha256(before).hexdigest(),
            'audit_object_sha256': hashlib.sha256(after).hexdigest(),
            'state_bytes': 1552, 'pinned_original_verified': True, 'allocated_sections_unchanged': True,
            'pinned_archive_changed': False, 'allocator_policy_changed': False,
            'SDK_realloc_copy_reference_routed_to_audit_and_genuine_SDK_memcpy': True}
