#!/usr/bin/env python3
"""Isolated host-only PBL correctness/entry probe; never changes the PS4 lane."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
BUILD = ROOT / 'build/portable-baseline-host'
REVISION = '83cebcf5a522bf49667fd07084f04e8497de0eba'
FLAGS = ['--disable-bootstrap', '--disable-jemalloc', '--disable-shared-js',
         '--disable-jit', '--enable-portable-baseline-interp', '--disable-debug',
         '--disable-debug-symbols', '--enable-optimize=-O2', '--disable-tests',
         '--without-intl-api']
MODES = {'portable': ['--portable-baseline', '--portable-baseline-eager'],
         'generic': ['--no-portable-baseline']}


def validate_configuration(substs):
    if not substs.get('JS_CODEGEN_NONE') or not substs.get('ENABLE_PORTABLE_BASELINE_INTERP'):
        raise RuntimeError('Probe must compile PBL without a native JIT backend')
    if substs.get('MOZ_OPTIMIZE_FLAGS') != ['-O2']:
        raise RuntimeError('Probe optimization flags differ from -O2')


def observed_portable_entry(text):
    return bool(re.search(r'(?:hit Breakpoint \d+|\nBreakpoint \d+,).*PortableBaselineInterpret', text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=2, choices=range(1, 5))
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    report = {'host_only': True, 'console_tested': False, 'browser_changed': False,
              'revision': REVISION, 'configure_flags': FLAGS, 'modes': {}, 'errors': []}
    # Protect the sibling baseline, including build inputs reached via symlinks.
    sandbox = ['bwrap', '--bind', '/', '/', '--dev-bind', '/dev', '/dev']
    baseline = ROOT.parent / 'orbisfox'
    if baseline.exists() and baseline.resolve() != ROOT.resolve():
        sandbox += ['--ro-bind', str(baseline), str(baseline)]
    env = dict(os.environ, CC='/usr/bin/clang', CXX='/usr/bin/clang++',
               RUSTC='/usr/bin/rustc', CARGO='/usr/bin/cargo',
               CBINDGEN=str(ROOT / '.deps/host-tools/bin/cbindgen'),
               MOZBUILD_STATE_PATH=str(ROOT / '.deps/mozbuild'))

    def logged(name, command, timeout):
        with (BUILD / name).open('w') as log:
            subprocess.run(sandbox + command, cwd=BUILD, env=env, check=True,
                           stdout=log, stderr=subprocess.STDOUT, timeout=timeout)

    try:
        actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != REVISION:
            raise RuntimeError('Source revision differs from pinned Gecko')
        if shutil.disk_usage(BUILD).free < 2 * 1024**3:
            raise RuntimeError('Isolated probe needs at least 2 GiB free; no retained inputs are deleted')
        logged('configure-output.log', [str(SOURCE / 'js/src/configure'), *FLAGS], 300)
        validate_configuration(json.loads((BUILD / 'config.status.json').read_text())['substs'])
        logged('build-output.log', ['make', '-j' + str(args.jobs)], 1800)
        shell = BUILD / 'dist/bin/js'
        report['shell_sha256'] = hashlib.sha256(shell.read_bytes()).hexdigest()
        fixture = ROOT / 'tests/portable_baseline_probe.js'
        report['fixture_sha256'] = hashlib.sha256(fixture.read_bytes()).hexdigest()
        for name, option in MODES.items():
            command = [str(shell), '--no-jit-backend', *option]
            run = subprocess.run(sandbox + command + ['-f', str(fixture)], cwd=BUILD,
                                 env=env, text=True, capture_output=True, timeout=120, check=False)
            (BUILD / (name + '-semantics.log')).write_text(run.stdout + run.stderr)
            run.check_returncode()
            result = json.loads(run.stdout.splitlines()[-1])
            if not result.get('portableProbe'):
                raise RuntimeError('Missing semantic probe result: ' + name)
            report['modes'][name] = result
            interrupt = subprocess.run(sandbox + command + ['-e', 'timeout(0.1); while (true) {}'],
                                       cwd=BUILD, env=env, text=True, capture_output=True, timeout=10, check=False)
            (BUILD / (name + '-interrupt.log')).write_text(interrupt.stdout + interrupt.stderr)
            if interrupt.returncode != 6:
                raise RuntimeError('Interrupt did not terminate with shell timeout status 6: ' + name)
            debug = subprocess.run(sandbox + ['gdb', '--nx', '--batch',
                '-iex', 'set auto-load off', '-iex', 'set debuginfod enabled off',
                '-ex', 'set pagination off',
                '-ex', 'rbreak js::pbl::PortableBaselineInterpret<',
                '-ex', 'run', '-ex', 'bt 2', '--args', *command, '-f', str(fixture)],
                cwd=BUILD, env=env, text=True, capture_output=True, timeout=120, check=False)
            text = debug.stdout + debug.stderr
            (BUILD / (name + '-entry.log')).write_text(text)
            entered = observed_portable_entry(text)
            if entered != (name == 'portable'):
                raise RuntimeError('Actual portable interpreter entry evidence mismatch: ' + name)
            if name == 'generic' and 'exited normally' not in text:
                raise RuntimeError('Generic control did not finish under the debugger')
            result['core_entry_observed'] = entered
            result['interrupt_exit_status'] = interrupt.returncode
        portable, generic = (report['modes'][mode] for mode in MODES)
        for key in ('checksum', 'asyncResult', 'overflow'):
            if portable[key] != generic[key]:
                raise RuntimeError('Interpreter result mismatch: ' + key)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report['errors'].append(str(error))
    (BUILD / 'probe-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return int(bool(report['errors']))


if __name__ == '__main__':
    sys.exit(main())
