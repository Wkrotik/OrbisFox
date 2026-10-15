#!/usr/bin/env python3
"""Read-only OrbisFox log/coredump retrieval with atomic, hash-recorded evidence.
Example: python3 scripts/fetch-console-crash.py --version 0.50 --kernel-log build/hardware-0.49/klog-netcat-live.log
No kernel-log socket is opened; reuse the existing single reader's file.
"""
import argparse
from ftplib import FTP
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
LOGS = {'platform.log', 'platform-videoout.log', 'platform-layout.log', 'startup.log',
        'startup-layout.log', 'gecko-heartbeat.log', 'gecko-first-frame.bgra',
        'gecko-fixture-frame.bgra', 'stdio-lock-probe.log','heap-audit.log'}
MARKERS = ('heap-debug', 'probe-jit', 'verbose-gecko-log', 'diagnostic-only', 'probe-sdk-semaphore')


def names(ftp, directory):
    ftp.cwd(directory)
    return sorted({PurePosixPath(item).name for item in ftp.nlst()} - {'.', '..', ''})


def retrieve(ftp, remote, destination, limit=128 * 1024 * 1024):
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.fetch-', delete=False) as stream:
            temporary = Path(stream.name)
            def receive(data):
                nonlocal count
                count += len(data)
                if count > limit:
                    raise ValueError(f'Evidence file exceeds bounded retrieval limit: {remote}')
                digest.update(data)
                stream.write(data)
            ftp.retrbinary('RETR ' + remote, receive, blocksize=128 * 1024)
        value = digest.hexdigest()
        if destination.exists():
            with destination.open('rb') as stream:
                previous = hashlib.file_digest(stream, 'sha256').hexdigest()
            if previous != value:
                raise FileExistsError(f'Refusing to overwrite different evidence: {destination}')
        else:
            temporary.replace(destination)
        return {'remote': remote, 'local': str(destination), 'bytes': count, 'sha256': value}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fetch_runs(ftp, version, out):
    records=[]
    runs=[name for name in names(ftp,'/data/orbisfox/runs') if re.fullmatch(r'run-[0-9a-f-]+',name)]
    if len(runs)>256:raise ValueError('More than256 retained runs; select a smaller collection batch')
    for run in runs:
        remote='/data/orbisfox/runs/'+run
        metadata=bytearray()
        def receive(data):
            metadata.extend(data)
            if len(metadata)>16384:raise ValueError('Run metadata exceeds16KiB')
        ftp.retrbinary('RETR '+remote+'/run-meta.json',receive)
        parsed=json.loads(metadata)
        if parsed.get('run_id')!=run:raise ValueError('Run directory/metadata mismatch: '+run)
        if parsed.get('version')!=version:continue
        for name in names(ftp,remote):
            if name in LOGS or name in {'run-meta.json','heap-diagnostics.bin'} or re.fullmatch(r'gecko-load\.log(?:[._-][A-Za-z0-9._-]+)?',name):
                record=retrieve(ftp,remote+'/'+name,out/'runs'/run/name)
                record['run_id']=run;record['native_version']=parsed['version'];records.append(record)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Explicit console address; no maintainer default')
    parser.add_argument('--port', type=int, default=2121)
    parser.add_argument('--version', required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--kernel-log', type=Path)
    parser.add_argument('--logs-only',action='store_true',help='Collect retained runs without requiring a crash dump')
    parser.add_argument('--all-dumps',action='store_true',help='Fetch every currently retained title dump, not just latest')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9]+\.[0-9]+', args.version):
        parser.error('Version must have numeric major.minor form')
    out = args.out or ROOT / f'build/hardware-{args.version}/captures/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / 'crash-fetch-report.json'
    if report_path.exists():
        parser.error('Output already has a crash report; choose a new evidence directory')
    report = {'version': args.version, 'epoch': time.time(), 'host': args.host,
              'files': [], 'errors': [], 'console_files_changed': False,
              'heap_trace_fetched': False, 'heap_trace_reason': 'Not automatically fetched: prove current-launch ownership first.'}
    try:
        if args.kernel_log:
            # Freeze the reader's current prefix, not an unbounded growing stream.
            destination = out / 'kernel-crash-snapshot.log'
            if destination.exists():
                raise FileExistsError(f'Refusing to overwrite evidence: {destination}')
            size = args.kernel_log.stat().st_size
            with args.kernel_log.open('rb') as source, destination.open('xb') as target:
                remaining = size
                while remaining:
                    block = source.read(min(128 * 1024, remaining))
                    if not block:
                        raise IOError('Kernel capture truncated during snapshot')
                    target.write(block)
                    remaining -= len(block)
            report['kernel_source'] = str(args.kernel_log)
            report['kernel_snapshot_bytes'] = size
        with FTP() as ftp:
            ftp.connect(args.host, args.port, timeout=30)
            ftp.login('anonymous', os.environ.get('PS4_FTP_PASSWORD', 'anonymous@'))
            listing = names(ftp, '/data/orbisfox')
            report['markers_current'] = {name: name in listing for name in MARKERS}
            for name in listing:
                if name in LOGS or re.fullmatch(r'gecko-load\.log(?:[._-][A-Za-z0-9._-]+)?', name):
                    report['files'].append(retrieve(ftp, '/data/orbisfox/' + name, out / 'crash-evidence' / name))
            if 'runs' in listing:
                retained=fetch_runs(ftp,args.version,out);report['files'].extend(retained)
                report['retained_run_ids']=sorted({record['run_id'] for record in retained})
                report['heap_trace_fetched']=any(record['remote'].endswith('/heap-diagnostics.bin') for record in retained)
                if report['heap_trace_fetched']:report['heap_trace_reason']='Owned unique run directory; metadata version checked, not legacy flat trace'
            dumps = [] if args.logs_only else [name for name in names(ftp, '/data/sce_coredumps')
                     if re.fullmatch(r'ORBF00001_[0-9]+', name)]
            report['available_title_dumps'] = dumps
            if not dumps and not args.logs_only:
                raise FileNotFoundError('No OrbisFox coredump directory found')
            selected=sorted(dumps,key=lambda name:int(name.rsplit('_',1)[1]))
            if not args.all_dumps:selected=selected[-1:]
            report['selected_title_dumps']=selected
            if selected:report['selected_latest_title_dump']=selected[-1]
            report['dump_version_association_requires_matching_kernel_run'] = True
            for dump in selected:
                directory='/data/sce_coredumps/'+dump
                for name in names(ftp,directory):
                    report['files'].append(retrieve(ftp,directory+'/'+name,out/'coredump'/dump/name))
    except Exception as failure:
        report['errors'].append(str(failure))
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(report_path), 'files': len(report['files']), 'errors': report['errors']}, indent=2))
    return int(bool(report['errors']))


if __name__ == '__main__':
    sys.exit(main())
