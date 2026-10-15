#!/usr/bin/env python3
"""Generate private SDK header fixes; never mutate the pinned OpenOrbis SDK."""
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent


def write_changed(path, content):
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def generate():
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain'))
    overlay = ROOT / '.deps/sdk-overlay'
    overlay.mkdir(parents=True, exist_ok=True)
    math = (sdk / 'include/math.h').read_text()
    # SDK's legacy C++ predicates conflict with libc++ 21's own overloads.
    # Keep the old behavior for libc++ 11 and the app's existing build.
    for name in ('_fpclassify', '_isless'):
        old = f'#ifdef __cplusplus\n\n#define {name}'
        if math.count(old) != 1:
            raise RuntimeError('Unexpected OpenOrbis math header')
        math = math.replace(old, f'#if defined(__cplusplus) && (!defined(_LIBCPP_VERSION) || _LIBCPP_VERSION < 210000)\n\n#define {name}')
    write_changed(overlay / 'math.h', math)
    signal = (sdk / 'include/signal.h').read_text()
    old = '#define sa_sigaction __sa_handler.sa_sigaction'
    if signal.count(old) != 1:
        raise RuntimeError('Unexpected OpenOrbis signal header')
    write_changed(overlay / 'signal.h', signal.replace(old, '#define sa_sigaction __sa_handler.__sa_sigaction'))
    # Console klog (0.10): pthread_mutexattr_* wrote an eight-byte firmware
    # handle into the SDK's four-byte musl declaration, corrupting the stack
    # canary in Mozilla's MutexImpl constructor. Attribute handles need pointer
    # sized/aligned storage. Retain the SDK's larger object/thread-attr storage.
    types = (sdk / 'include/bits/alltypes.h').read_text()
    for name in ('mutexattr', 'condattr', 'barrierattr'):
        old = f'typedef struct {{ unsigned __attr; }} pthread_{name}_t;'
        if types.count(old) != 1:
            raise RuntimeError('Unexpected SDK pthread attribute declaration: ' + name)
        types = types.replace(old, f'typedef struct {{ unsigned long __attr; }} pthread_{name}_t;')
    old = 'typedef struct { unsigned __attr[2]; } pthread_rwlockattr_t;'
    if types.count(old) != 1:
        raise RuntimeError('Unexpected SDK rwlock attribute declaration')
    types = types.replace(old, 'typedef struct { unsigned long __attr; } pthread_rwlockattr_t;')
    (overlay / 'bits').mkdir(exist_ok=True)
    write_changed(overlay / 'bits/alltypes.h', types)


if __name__ == '__main__':
    generate()
