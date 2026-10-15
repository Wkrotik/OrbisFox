#!/usr/bin/env python3
"""Build standalone SpiderMonkey and record incomplete link/port gates honestly."""
import json
import os
import shutil
import hashlib
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build/gecko-spidermonkey'


def main():
    subprocess.run([sys.executable, str(ROOT / 'scripts/configure-gecko.py')], check=True)
    # A newly introduced header overlay is not in existing compiler depfiles.
    # Recompile C/C++ objects when its ABI revision changes, including mozglue.
    overlay_revision = hashlib.sha256((ROOT / 'scripts/sdk-overlay.py').read_bytes()).hexdigest()
    overlay_marker = BUILD / '.sdk-overlay-revision'
    if not overlay_marker.exists() or overlay_marker.read_text() != overlay_revision:
        for obj in BUILD.rglob('*.o'):
            obj.unlink()
        overlay_marker.write_text(overlay_revision)
    # Cargo doesn't fingerprint a private sysroot's replaced std archives.
    # Avoid embedding stale ABI/entropy implementations after runtime patches.
    revision = (ROOT / 'build/rust/.abi-patch-revision').read_text()
    marker = BUILD / '.rust-sysroot-revision'
    if not marker.exists() or marker.read_text() != revision:
        for directory in ('x86_64-orbis-freebsd', 'release'):
            shutil.rmtree(BUILD / directory, ignore_errors=True)
        marker.write_text(revision)
    log = BUILD / 'build-output.log'
    with log.open('w') as output:
        result = subprocess.run(['make', '-j' + os.environ.get('ORBISFOX_JOBS', '6')], cwd=BUILD,
                                stdout=output, stderr=subprocess.STDOUT)
    support = BUILD / 'liborbisfox-gecko-support.a'
    response = BUILD / 'js/src/shell/js.list'
    if result.returncode == 0 and response.exists():
        objects = [(response.parent / name).resolve() for name in response.read_text().splitlines()
                   if name and not name.startswith('Unified_cpp_js_src_shell') and '/editline/' not in name]
        if not objects or any(not path.exists() for path in objects):
            raise RuntimeError('Missing SpiderMonkey embedding support objects')
        support.unlink(missing_ok=True)
        subprocess.run(['llvm-ar', 'rcs', str(support), *(str(path) for path in objects)], check=True)
    library = BUILD / 'js/src/build/libjs_static.a'
    rust = BUILD / 'x86_64-orbis-freebsd/release/libjsrust.a'
    if result.returncode == 0:
        # Grouped Make targets must all advance even when Mozilla reuses a
        # cached archive; otherwise an older jsrust timestamp rebuilds forever.
        for artifact in (library, rust, support):
            artifact.touch()
    errors = [line for line in log.read_text().splitlines() if 'error:' in line or 'fatal error:' in line]
    report = {'revision': '83cebcf5a522bf49667fd07084f04e8497de0eba',
              'result': result.returncode, 'spidermonkey_static_archive_present': library.exists(),
              'shell_link_succeeded': result.returncode == 0 and (BUILD / 'dist/bin/js').exists(),
              'jsrust_static_archive_present': rust.exists(),
              'embedding_support_archive_present': support.exists(),
              'gecko_in_package': False, 'javascript_executed_on_console': False,
              'hardware_tested': False, 'log': str(log.relative_to(ROOT)), 'errors': errors[:20]}
    (BUILD / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
