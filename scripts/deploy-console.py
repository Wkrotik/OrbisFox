#!/usr/bin/env python3
"""Preserve and upload the verified current Gecko candidate; never install/launch.
Example: python3 scripts/deploy-console.py
Uses upload-pkgs.py's hidden upload + full remote SHA-256 check. Records existing
capture ownership; --capture opts into a bounded reader. Default stops only
verified owned readers and never opens a diagnostics connection. The local frozen fixture is verified too. An idle reader is not
claimed fresh and does not prevent a package upload. Use fetch-console-crash.py
for crash evidence retrieval; do not relaunch before collecting that evidence.
"""
import argparse
from ftplib import FTP
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import time
import signal
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
MARKERS = ('heap-debug', 'probe-jit', 'verbose-gecko-log', 'diagnostic-only', 'probe-sdk-semaphore')
UPLOADER = runpy.run_path(str(Path(__file__).with_name('upload-pkgs.py')))
REGISTERED_INSTALLERS = {*UPLOADER['PACKAGE_NAMES'], UPLOADER['LEGACY_MAIN_PACKAGE'], '.OrbisFox.pkg.uploading'}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def preserve(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(source) != sha256(destination):
            raise FileExistsError(f'Refusing to replace matched evidence: {destination}')
        return
    shutil.copy2(source, destination)  # Independent copies, not links to mutable outputs.
    if sha256(source) != sha256(destination):
        raise IOError(f'Preserved evidence hash mismatch: {destination}')


def candidate():
    package = json.loads((ROOT / 'dist/gecko/build-report.json').read_text())
    native = json.loads((ROOT / 'build/gecko-app/build-report.json').read_text())
    version = package['version']
    if not re.fullmatch(r'[0-9]+\.[0-9]+', version) or native['version'] != version:
        raise ValueError('Package/native versions do not match')
    if not (package.get('new_package_created') and package.get('extracted_payload_verified')
            and native.get('final_engine_application_linked') and native.get('baseline_unchanged')):
        raise ValueError('Candidate verification incomplete; refusing upload')
    pkg = ROOT / 'dist/gecko/OrbisFox.pkg'
    elf = ROOT / 'build/gecko-app/orbisfox.elf'
    if pkg.stat().st_size != package['bytes'] or sha256(pkg) != package['sha256']:
        raise ValueError('Package bytes/hash do not match verification report')
    if elf.stat().st_size != native['executable']['bytes'] or sha256(elf) != native['executable']['sha256']:
        raise ValueError('ELF bytes/hash do not match native build report')
    packaged_elf = package.get('native_executable', {})
    if any(packaged_elf.get(key) != native['executable'][key] for key in ('bytes', 'sha256')):
        raise ValueError('Package was built from a different native ELF; repackage before upload')
    hashes = native.get('runtime_source_sha256')
    if not hashes:
        raise ValueError('Candidate lacks runtime source fingerprints; rebuild before deployment')
    for name, expected in hashes.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha256(path) != expected:
            raise ValueError(f'Runtime source changed after native build: {name}')
    return version, package, native


def console_state(host, port):
    with FTP() as ftp:
        ftp.connect(host, port, timeout=30)
        ftp.login('anonymous', os.environ.get('PS4_FTP_PASSWORD', 'anonymous@'))
        ftp.cwd('/data/pkg')
        installers = sorted(Path(name).name for name in ftp.nlst())
        ftp.cwd('/data/orbisfox')
        names = {Path(name).name for name in ftp.nlst()}
        return {'installers': installers, 'markers': {name: name in names for name in MARKERS}}


def existing_capture(host):
    sockets = subprocess.check_output(['ss', '-tnp'], text=True)
    now = time.time()
    for path in sorted((ROOT / 'build').glob('hardware-*/capture-reference.json'),
                       key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            record = json.loads(path.read_text())
            if record['console'] != host or now >= record['started_epoch'] + record['lifetime_seconds']:
                continue
            pid = record['reader_child_pid']
            command = (Path('/proc') / str(pid) / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
            if f'nc {host} {record["kernel_port"]}' not in command:
                continue
            lines = [line for line in sockets.splitlines() if f'{host}:{record["kernel_port"]}' in line and 'ESTAB' in line]
            if len(lines) != 1 or f'pid={pid},' not in lines[0]:
                continue
            capture = Path(record['path'])
            if not capture.is_absolute():
                capture = ROOT / capture
            record.update(path=str(capture), active=True, new_reader=False, identity_and_socket_verified=True,
                          prelaunch_byte_boundary=capture.stat().st_size, last_checked_epoch=now,
                          fresh_bytes_verified=False,
                          note='Single existing reader reused; startup bytes must prove next launch/version. No new reader opened.')
            return record
        except (OSError, ValueError, KeyError):
            continue
    return {'active': False, 'console': host, 'fresh_bytes_verified': False,
            'note': 'No owned live reader verified; package upload allowed, capture readiness not claimed.'}


def prepare_capture(host, version, out, collect_logs=False):
    """Verify fixture; capture only when explicitly requested by the operator."""
    record = existing_capture(host)
    remaining = record.get('started_epoch', 0) + record.get('lifetime_seconds', 0) - time.time()
    if record.get('active') and (not collect_logs or remaining < 900):
        # Stop only exact owned processes; never act on a stale PID alone.
        pid = record['wrapper_pid']
        command = (Path('/proc') / str(pid) / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
        if 'timeout --signal=TERM 7200 nc ' + host + ' 3232' not in command:
            raise RuntimeError('Cannot safely renew unverified kernel wrapper')
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not any(host + ':3232' in line and 'ESTAB' in line for line in subprocess.check_output(['ss', '-tnp'], text=True).splitlines()):
                break
            time.sleep(0.1)
        record.update(active=False, new_reader=False, note='Owned kernel reader stopped: capture disabled or renewal required.')
        server_pid = record.get('fixture_server_pid')
        try:
            command = (Path('/proc') / str(server_pid) / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
            if 'scripts/serve-network-fixture.py --seconds 7200' in command and (Path('/proc') / str(server_pid) / 'cwd').resolve() == ROOT.resolve():
                os.kill(server_pid, signal.SIGTERM)
                for _ in range(20):
                    if not (Path('/proc') / str(server_pid) / 'cmdline').exists():break
                    time.sleep(0.1)
        except FileNotFoundError:
            pass
    if collect_logs and not record.get('active'):
        sockets = subprocess.check_output(['ss', '-tnp'], text=True)
        if any(host + ':3232' in line and 'ESTAB' in line for line in sockets.splitlines()):
            raise RuntimeError('Kernel reader ownership unknown; refusing overlapping capture')
        stamp = str(time.time_ns())
        path, error = out / ('klog-' + stamp + '.log'), out / ('klog-' + stamp + '.stderr')
        with path.open('xb') as stream, error.open('xb') as failures:
            reader = subprocess.Popen(['timeout', '--signal=TERM', '7200', 'nc', host, '3232'],
                                      cwd=ROOT, stdout=stream, stderr=failures, start_new_session=True)
        record = {'path': str(path), 'stderr': str(error), 'wrapper_pid': reader.pid,
                  'started_epoch': time.time(), 'lifetime_seconds': 7200,
                  'console': host, 'kernel_port': 3232, 'active': False, 'new_reader': True}
        for _ in range(20):
            try:
                children = (Path('/proc') / str(reader.pid) / 'task' / str(reader.pid) / 'children').read_text().split()
                sockets = subprocess.check_output(['ss', '-tnp'], text=True)
                if len(children) == 1 and any(host + ':3232' in line and 'ESTAB' in line and 'pid=' + children[0] + ',' in line for line in sockets.splitlines()):
                    record.update(reader_child_pid=int(children[0]), active=True, identity_and_socket_verified=True)
                    break
            except FileNotFoundError:
                break
            time.sleep(0.1)
        # Persist even failed readiness: later attempts can identify the process.
        (out / 'capture-reference.json').write_text(json.dumps(record, indent=2) + '\n')
        if not record['active']:
            raise RuntimeError('New kernel reader did not establish a verified connection')
    fixture = runpy.run_path(str(ROOT / 'scripts/serve-network-fixture.py'))
    bind_host, port, token = fixture['configuration']()
    listening = subprocess.check_output(['ss', '-ltnp'], text=True)
    if not any(':' + str(port) + ' ' in line for line in listening.splitlines()):
        path = out / ('fixture-' + str(time.time_ns()) + '.log')
        with path.open('xb') as stream:
            server = subprocess.Popen([sys.executable, '-u', 'scripts/serve-network-fixture.py', '--seconds', '7200'],
                                      cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        record['fixture_server_pid'] = server.pid
        for _ in range(20):
            if any(':' + str(port) + ' ' in line for line in subprocess.check_output(['ss', '-ltnp'], text=True).splitlines()):break
            time.sleep(0.1)
    origin = f'http://{bind_host}:{port}'
    with urllib.request.urlopen(origin + '/orbisfox/offline.html', timeout=5) as response:
        if response.read() != (ROOT / 'gecko/orbisfox/fixtures/offline.html').read_bytes():
            raise ValueError('Fixture server does not serve the current frozen fixture')
    with urllib.request.urlopen(origin + '/orbisfox/probe/' + token, timeout=5) as response:
        if response.read() != ('OrbisFox native Necko probe ' + token + '\n').encode('ascii'):
            raise ValueError('Fixture probe token/bytes differ from current source')
    size=Path(record['path']).stat().st_size if record.get('active') else 0
    record.update(owner_version=version, launch_pending=True, fixture_server_bytes_verified=True,
                  diagnostics_requested=collect_logs, prelaunch_byte_boundary=size,
                  fresh_bytes_verified=bool(record.get('active') and record.get('new_reader') and size),
                  received_bytes=size, last_checked_epoch=time.time())
    (out / 'capture-reference.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Explicit console address; no maintainer default')
    parser.add_argument('--port', type=int, default=2121)
    parser.add_argument('--deadline', type=int, default=110)
    parser.add_argument('--capture', action='store_true', help='Explicit opt-in kernel diagnostics; off by default')
    args = parser.parse_args()
    if not 1 <= args.deadline <= 110:
        parser.error('Upload deadline must be 1..110 seconds')
    version, package, native = candidate()
    out = ROOT / f'build/hardware-{version}'
    attempt = out / 'deployments' / str(time.time_ns())
    attempt.mkdir(parents=True)
    report = {'version': version, 'host': args.host, 'port': args.port,
              'uploaded': False, 'installed': False, 'launched': False,
              'console_settings_changed': False, 'sha256': package['sha256'], 'bytes': package['bytes'], 'errors': []}
    try:
        for source, name in [(ROOT / 'dist/gecko/OrbisFox.pkg', 'OrbisFox.pkg'),
                             (ROOT / 'build/gecko-app/orbisfox.elf', 'orbisfox.elf')]:
            preserve(source, out / name)
        for source, name in [(ROOT / 'dist/gecko/build-report.json', 'package-report.json'),
                             (ROOT / 'build/gecko-app/build-report.json', 'native-build-report.json')]:
            preserve(source, attempt / name)
        manifest = []
        for directory in ('gecko', 'src', 'include', 'scripts', 'tests'):
            for source in sorted((ROOT / directory).rglob('*')):
                if not source.is_file() or '__pycache__' in source.parts:
                    continue
                name = source.relative_to(ROOT)
                preserve(source, attempt / 'sources' / name)
                manifest.append({'path': str(name), 'sha256': sha256(source)})
        for name in ('Makefile',):
            preserve(ROOT / name, attempt / 'sources' / name)
            manifest.append({'path': name, 'sha256': sha256(ROOT / name)})
        (attempt / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        before = console_state(args.host, args.port)
        capture = prepare_capture(args.host, version, out, collect_logs=args.capture)
        with (attempt / 'upload.log').open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/upload-pkgs.py'),
                                     '--host', args.host, '--port', str(args.port), '--gecko'],
                                    cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=args.deadline)
        if result.returncode:
            raise RuntimeError(f'Uploader failed: exit {result.returncode}; see {attempt / "upload.log"}')
        report['uploaded'] = True
        report['uploader_full_remote_SHA256_verified'] = True
        after = console_state(args.host, args.port)
        unrelated = set(before['installers']) - REGISTERED_INSTALLERS
        if not unrelated.issubset(after['installers']) or before['markers'] != after['markers']:
            raise RuntimeError('Unrelated installers or diagnostic markers changed during deployment')
        report.update(unrelated_installers_preserved=True, markers_verified=after['markers'])
        if capture.get('active'):
            size = Path(capture['path']).stat().st_size
            capture['fresh_bytes_since_preflight'] = size - capture['prelaunch_byte_boundary']
            capture['fresh_bytes_verified'] = capture['fresh_bytes_verified'] or size > capture['prelaunch_byte_boundary']
            capture['prelaunch_byte_boundary'] = size
            capture['owner_version'] = version
            capture['launch_pending'] = True
        (out / 'capture-reference.json').write_text(json.dumps(capture, indent=2) + '\n')
        report['capture'] = capture
    except Exception as failure:
        report['errors'].append(str(failure))
    (attempt / 'deployment-report.json').write_text(json.dumps(report, indent=2) + '\n')
    # Keep every attempt report; this is only a current summary pointer/copy.
    (out / 'deployment-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(attempt / 'deployment-report.json'),
                      'uploaded': report['uploaded'], 'errors': report['errors']}, indent=2))
    return int(bool(report['errors']))


if __name__ == '__main__':
    sys.exit(main())
