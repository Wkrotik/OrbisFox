#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline, bounded allocator flight-recorder decoder. Does not execute targets."""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import struct
import subprocess

MAGIC = 0x3130544c4658424f
CAPACITY = 1048576
RECORD = struct.Struct('<7QBBHI')
OPERATIONS = ('internal', 'malloc', 'calloc', 'realloc', 'free', 'malloc_usable_size',
              'memalign', '__memalign', 'aligned_alloc', 'posix_memalign', 'valloc', '__expand_heap',
              'SDK-discard', 'SDK-unmap', 'SDK-map', 'SDK-copy', 'Mesa-dispatch', 'fault')


def checksum(data):
    result = 2166136261
    for value in data[:60]:
        result = ((result ^ value) * 16777619) & 0xffffffff
    return result


def decode(path, address=None, limit=80):
    if not 1 <= limit <= 4096:
        raise ValueError('Event limit must be 1..4096')
    path = Path(path)
    size = path.stat().st_size
    if not 64 <= size <= 64 + CAPACITY * 64:
        raise ValueError('Flight trace outside fixed size bound')
    selected = deque(maxlen=limit)
    counts = Counter()
    with path.open('rb') as stream:
        header = struct.unpack('<8Q', stream.read(64))
        magic, version, width, capacity, committed, generation, failures, attempted = header
        if (magic, version, width, capacity) != (MAGIC, 1, 64, CAPACITY):
            raise ValueError('Unknown allocator flight format')
        if attempted < committed:
            raise ValueError('Invalid flight commit sequence')
        first = max(1, committed - capacity + 1)
        valid = invalid = missing = matching = 0
        for sequence in range(first, committed + 1):
            offset = 64 + ((sequence - 1) % capacity) * width
            if offset + width > size:
                missing += 1
                continue
            stream.seek(offset)
            raw = stream.read(width)
            event = RECORD.unpack(raw)
            seq, caller, source, output, requested, extra, thread, op, phase, depth, crc = event
            if seq != sequence:
                missing += 1
                continue
            if crc != checksum(raw) or phase not in (1, 2, 3):
                invalid += 1
                continue
            valid += 1
            operation = OPERATIONS[op] if op < len(OPERATIONS) else 'unknown'
            counts[operation + ':' + str(phase)] += 1
            overlaps = (phase == 2 and op in (1, 2, 3, 6, 7, 8, 9, 10, 11, 14, 15)
                        and 0 < output < 0xffffffffffffffff and requested < 0xffffffffffffffff - output
                        and address is not None and max(0, output - 16) <= address < output + requested + 16)
            if address is not None and address not in (source, output) and not overlaps:
                continue
            matching += 1
            selected.append({'sequence': seq, 'caller': hex(caller), 'input': hex(source),
                             'output': hex(output), 'bytes': requested, 'extra': hex(extra),
                             'thread': hex(thread), 'operation': operation, 'phase': phase, 'depth': depth})
    return {'path': str(path), 'bytes': size, 'generation': generation,
            'committed_sequence': committed, 'attempted_sequence': attempted, 'io_failures': failures,
            'valid_records': valid, 'missing_or_overwritten_records': missing, 'invalid_records': invalid,
            'matching_records': matching, 'operation_counts': dict(counts), 'events': list(selected),
            'limitations': ['Bounded rolling metadata, not memory-write tracing or ownership proof.',
                           'Batches not flushed at an unrelated crash may be absent; sequence/checksum gaps are explicit.',
                           'Address range matches include requested payload plus 16-byte metadata adjacency, not usable capacity.',
                           'Only wrapped APIs and explicit checkpoints are covered; no payloads, URLs or call-stack unwinding.']}


def symbolize(report, elf, expected_sha, bias):
    elf = Path(elf)
    sha = hashlib.sha256(elf.read_bytes()).hexdigest()
    if sha != expected_sha:
        raise ValueError('ELF does not match expected crash artifact SHA-256')
    targets = sorted({int(e['caller'], 16) - bias for e in report['events'] if int(e['caller'], 16) >= bias})
    names = {}
    process = subprocess.Popen(['llvm-nm', '-nC', '--defined-only', str(elf)], stdout=subprocess.PIPE, text=True)
    previous = None
    index = 0
    try:
        for line in process.stdout:
            fields = line.split(maxsplit=2)
            if len(fields) < 3 or fields[1] not in ('t', 'T'):
                continue
            at = int(fields[0], 16)
            while index < len(targets) and targets[index] < at:
                if previous:
                    names[targets[index]] = previous[1] + '+0x%x' % (targets[index] - previous[0])
                index += 1
            previous = (at, fields[2].strip())
        while index < len(targets):
            # No next symbol establishes a terminal function's extent.
            names[targets[index]] = 'unknown (past final code symbol)'
            index += 1
    finally:
        process.stdout.close()
        if process.wait():
            raise ValueError('llvm-nm failed')
    for event in report['events']:
        event['nearest_code_symbol'] = names.get(int(event['caller'], 16) - bias, 'unknown')
    report['symbolization'] = {'elf': str(elf), 'sha256': sha, 'runtime_bias': hex(bias),
                               'scope': 'Nearest preceding actual t/T code symbol; not a stack trace or exact function extent.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--address', type=lambda x: int(x, 0))
    parser.add_argument('--limit', type=int, default=80)
    parser.add_argument('--elf', type=Path)
    parser.add_argument('--expected-elf-sha256')
    parser.add_argument('--bias', type=lambda x: int(x, 0))
    args = parser.parse_args()
    if args.elf and (not args.expected_elf_sha256 or args.bias is None):
        parser.error('--elf requires --expected-elf-sha256 and explicit --bias')
    report = decode(args.trace, args.address, args.limit)
    if args.elf:
        symbolize(report, args.elf, args.expected_elf_sha256, args.bias)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
