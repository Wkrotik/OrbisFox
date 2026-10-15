#!/usr/bin/env python3
"""Decode a bounded OrbisFox development heap trace, optionally with matching ELF."""
import argparse
import json
from pathlib import Path
import struct
import subprocess

MAGIC = 0x504145484658424F
HEADER = struct.Struct('<8Q')
EVENT = struct.Struct('<8Q')
OPERATIONS = {1: 'allocation pending', 2: 'allocation returned', 3: 'free requested',
              5: 'quarantine evicted', 6: 'replacement allocation rolled back', 7: 'untracked raw free', 8: 'untracked raw realloc',
              9: 'diagnostic fault', 10: 'tracking capacity exhausted (ENOMEM)',
              11: 'untracked allocation returned (raw SDK; no guards)'}


def decode(data, base=0x400000):
    if len(data) < HEADER.size:
        raise ValueError('Truncated heap trace header')
    magic, version, size, slots, latest, occupancy, saturated, untracked = HEADER.unpack_from(data)
    if version not in (1, 2) or (magic, size, slots) != (MAGIC, EVENT.size, 4096):
        raise ValueError('Unknown heap trace format')
    records, missing = [], []
    for sequence in range(max(1, latest-slots+1), latest+1):
        at = HEADER.size + ((sequence-1) % slots)*size
        if at+size > len(data):
            missing.append(sequence)
            continue
        values = EVENT.unpack_from(data, at)
        if values[0] != sequence:
            missing.append(sequence)
            continue
        seq, op, pointer, raw, count, caller, allocated, freed = values
        operation = ('tracking saturation; new request falls back to raw SDK without guards'
                     if version == 2 and op == 10 else OPERATIONS.get(op, f'unknown {op}'))
        if version == 2 and op == 11 and pointer == 0:
            operation = 'raw SDK allocation returned null (not synthetic tracking failure)'
        record = dict(sequence=seq, operation=operation,
                      pointer=hex(pointer), backing=hex(raw), size=count)
        for key, address in [('caller', caller), ('allocated_at', allocated), ('freed_at', freed)]:
            record[key] = hex(address)
            # Application ELF base is explicit; resident addresses must not be
            # symbolized with this ELF. Known application addresses stay below
            # the resident module region at 0x800000000.
            record[key+'_ELF'] = hex(address-base) if base <= address < 0x800000000 else None
        records.append(record)
    fault = data[HEADER.size+slots*size:][:768].split(b'\0', 1)[0].decode('utf-8', errors='replace').strip()
    coverage = (dict(tracked_live_and_quarantined_at_latest_callback=occupancy & 0xffffffff,
                     tracking_admission_limit=occupancy >> 32, saturation_requests=saturated,
                     successful_untracked_fallback_allocations=untracked,
                     coverage_degraded=bool(saturated)) if version == 2 else None)
    return dict(version=version, latest_sequence=latest, missing_sequences=missing,
                coverage=coverage,
                events=records, fault=fault or None,
                limitations='Opt-in development trace, not every allocation or access; only requested-size guards and bounded quarantine. A clean trace is not proof of no memory corruption.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--elf', type=Path, help='Exact ELF matching this console run')
    parser.add_argument('--base', type=lambda value: int(value, 0), default=0x400000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = decode(args.trace.read_bytes(), args.base)
    if args.elf:
        addresses = sorted({event[key] for event in result['events']
                            for key in ('caller_ELF', 'allocated_at_ELF', 'freed_at_ELF') if event[key]})
        symbols = {}
        for start in range(0, len(addresses), 128):
            batch = addresses[start:start+128]
            output = subprocess.check_output(['llvm-addr2line', '-f', '-C', '-e', str(args.elf), *batch], text=True).splitlines()
            if len(output) != 2*len(batch):
                raise ValueError('Unexpected llvm-addr2line output')
            symbols.update({address: dict(function=output[2*i], location=output[2*i+1]) for i, address in enumerate(batch)})
        result['application_symbols'] = symbols
    text = json.dumps(result, indent=2)+'\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
