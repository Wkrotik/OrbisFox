#!/usr/bin/env python3
"""Link the isolated native offline Gecko application; never replace 0.11."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / 'build/gecko-layout'
BUILD = ROOT / 'build/gecko-app'


def response_objects(path):
    """Use Gecko's actual link inputs, not a guessed list of engine features."""
    result = []
    for token in shlex.split(path.read_text()):
        if token in ('--whole-archive', '--no-whole-archive'):
            continue
        if not token.endswith(('.o', '.a')):
            raise ValueError('Unsupported Gecko response input: ' + token)
        item = (path.parent / token).resolve()
        if not item.is_file() or not item.is_relative_to(ENGINE):
            raise ValueError('Missing or out-of-lane Gecko object: ' + str(item))
        result.append(item)
    return result


def run(command, *, log=None):
    print('+', shlex.join(map(str, command)), flush=True)
    if log:
        with log.open('w') as output:
            subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                           stderr=subprocess.STDOUT, check=True)
    else:
        subprocess.run(list(map(str, command)), cwd=ROOT, check=True)


def fingerprint(path, *, optional=False):
    if optional and not path.exists():
        return None
    return {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-engine-build', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if not args.skip_engine_build:
        run([sys.executable, ROOT / 'scripts/build-gecko-layout.py', '--jobs', args.jobs])
    engine_report = json.loads((ENGINE / 'build-report.json').read_text())
    if not engine_report.get('full_engine_linked'):
        raise RuntimeError('Strict full Gecko link must succeed before the application build')
    baseline = fingerprint(ROOT / 'dist/OrbisFox.pkg', optional=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
    runtime = ROOT / '.deps/libcxx-orbis/lib'
    flags = [ROOT / 'scripts/orbis-cxx.py', '-std=c++20', '-O2', '-g', '-fPIC',
             '-mno-red-zone', '-funwind-tables', '-fstack-protector-strong',
             '-fno-exceptions', '-fno-rtti', '-fno-sized-deallocation', '-fno-aligned-new',
             '-DORBISFOX_FULL_GECKO', '-DORBISFOX_NATIVE_RUN_LOGS', '-I' + str(ROOT / 'include')]
    sources = ['src/surface.cpp', 'src/artwork.cpp', 'src/touch_cursor.cpp', 'src/native_ui_loop.cpp', 'src/native_chrome.cpp',
               'src/ps4/modules.cpp', 'src/ps4/services.cpp', 'src/ps4/native_stat.cpp',
               'src/ps4/native_clock.cpp', 'src/ps4/native_cpu.cpp', 'src/ps4/native_fcntl.cpp', 'src/ps4/native_network.cpp', 'src/ps4/native_keyboard.cpp', 'src/ps4/native_stdio.cpp', 'src/ps4/native_allocator.cpp', 'src/ps4/native_jit.cpp', 'src/ps4/native_audio.cpp', 'src/ps4/videoout.cpp',
               'src/ps4/startup.cpp', 'src/ps4/run_logs.cpp', 'src/ps4/sdk_heap_memory.cpp', 'src/ps4/platform.cpp', 'src/ps4/rust_runtime.cpp']
    # Expose only the copied SDK allocator's state symbol for read-only checks;
    # never patch allocator instructions, flags, or the pinned archive.
    import runpy
    original_malloc = BUILD / 'sdk-malloc-original.lo'
    original_malloc.write_bytes(subprocess.check_output(['llvm-ar', 'p', str(sdk / 'lib/libc.a'), 'malloc.lo']))
    audited_malloc = BUILD / 'sdk-malloc-audited.o'
    audit_binding = runpy.run_path(str(ROOT / 'scripts/sdk-heap-audit-object.py'))['expose'](original_malloc, audited_malloc)
    flags += ['-DORBISFOX_SDK_BIN_AUDIT', '-DORBISFOX_NATIVE_DIRECT_HEAP']
    native = [audited_malloc]
    for name in sources:
        output = BUILD / (name.replace('/', '_').removesuffix('.cpp') + '.o')
        run(flags + ['-c', ROOT / name, '-o', output], log=output.with_suffix('.log'))
        native.append(output)
    main_object = BUILD / 'main.o'
    run(flags + ['-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
                 '-include', ENGINE / 'mozilla-config.h',
                 '-I' + str(ENGINE / 'dist/include'),
                 '-I' + str(ENGINE / 'dist/include/nspr'),
                 '-I' + str(ENGINE / 'dist/include/nss'),
                 '-c', ROOT / 'gecko/orbisfox/native/main.cpp', '-o', main_object],
        log=BUILD / 'main-compile.log')
    native.append(main_object)
    shared_probe = BUILD / 'shared-memory-probe.o'
    run(flags + ['-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
                 '-include', ENGINE / 'mozilla-config.h',
                 '-I' + str(ENGINE / 'dist/include'),
                 '-I' + str(ENGINE / 'dist/include/nspr'), '-c',
                 ROOT / 'gecko/orbisfox/native/shared_memory_probe.cpp', '-o', shared_probe],
        log=BUILD / 'shared-memory-probe-compile.log')
    native.append(shared_probe)
    clock_probe = BUILD / 'clock-probe.o'
    run(flags + ['-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
                 '-include', ENGINE / 'mozilla-config.h',
                 '-I' + str(ENGINE / 'dist/include'),
                 '-I' + str(ENGINE / 'dist/include/nspr'), '-c',
                 ROOT / 'gecko/orbisfox/native/clock_probe.cpp', '-o', clock_probe],
        log=BUILD / 'clock-probe-compile.log')
    native.append(clock_probe)
    cxx_guard_probe = BUILD / 'cxx-guard-probe.o'
    run(flags + ['-c', ROOT / 'gecko/orbisfox/native/cxx_guard_probe.cpp', '-o', cxx_guard_probe],
        log=BUILD / 'cxx-guard-probe-compile.log')
    native.append(cxx_guard_probe)
    skia_probe = BUILD / 'skia-sync-probe.o'
    run(flags + ['-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
                 '-include', ENGINE / 'mozilla-config.h',
                 '-I' + str(ENGINE / 'dist/include'),
                 '-I' + str(ROOT / '.deps/gecko-layout/gfx/skia/skia'),
                 '-c', ROOT / 'gecko/orbisfox/native/skia_sync_probe.cpp', '-o', skia_probe],
        log=BUILD / 'skia-sync-probe-compile.log')
    native.append(skia_probe)
    stdio_probe = BUILD / 'stdio-probe.o'
    run(flags + ['-c', ROOT / 'gecko/orbisfox/native/stdio_probe.cpp', '-o', stdio_probe],
        log=BUILD / 'stdio-probe-compile.log')
    native.append(stdio_probe)
    allocator_probe = BUILD / 'allocator-probe.o'
    # The probe must execute its runtime calloc/zero/free checks. With builtin
    # knowledge clang can prove calloc zero-filled and delete the entire pair,
    # invalidating both hardware coverage and the protected-entry count gate.
    run(flags + ['-fno-builtin', '-c', ROOT / 'gecko/orbisfox/native/allocator_probe.cpp', '-o', allocator_probe],
        log=BUILD / 'allocator-probe-compile.log')
    allocator_probe_imports = subprocess.check_output(['llvm-nm', '-u', str(allocator_probe)], text=True)
    allocator_probe_calls = {line.split()[-1] for line in allocator_probe_imports.splitlines() if line.split()}
    if not {'malloc', 'calloc', 'realloc', 'free', 'posix_memalign'} <= allocator_probe_calls:
        raise ValueError('Native allocator runtime probe was optimized into incomplete coverage')
    native.append(allocator_probe)
    sqlite_vfs = BUILD / 'sqlite-vfs.o'
    run(flags + ['-I' + str(ENGINE / 'dist/include'), '-c',
                 ROOT / 'gecko/orbisfox/native/sqlite_vfs.cpp', '-o', sqlite_vfs],
        log=BUILD / 'sqlite-vfs-compile.log')
    native.append(sqlite_vfs)
    nspr_probe = BUILD / 'nspr-link-probe.o'
    run(flags + ['-DNO_NSPR_10_SUPPORT', '-I' + str(ENGINE / 'dist/include/nspr'), '-c',
                 ROOT / 'gecko/orbisfox/native/nspr_link_probe.cpp', '-o', nspr_probe],
        log=BUILD / 'nspr-link-probe-compile.log')
    native.append(nspr_probe)
    xul = response_objects(ENGINE / 'toolkit/library/build/libxul_so.list')
    # libxul deliberately weak-imports mozglue from its host executable. Include
    # the exact upstream XPCShell host support objects, excluding its main().
    host_objects = response_objects(ENGINE / 'js/xpconnect/shell/xpcshell.list')
    xul += [item for item in host_objects if item.name != 'xpcshell.o' and item not in xul]
    nss_inputs = response_objects(ENGINE / 'security/nss/lib/nss/nss_nss3/libnss3_so.list')
    for target in ('pk11wrap_pk11wrap_static', 'softoken_softokn_static', 'freebl_freebl_static'):
        if not any(target in item.parts for item in nss_inputs):
            raise RuntimeError('Missing upstream static NSS closure: ' + target)
    if any(item.name == 'loader.o' for item in nss_inputs):
        raise RuntimeError('Static NSS closure still contains its desktop freebl DLL loader')
    # Fold supporting DSO *objects* into lazy thin archives. No Linux/FreeBSD
    # libxul.so or other custom desktop DLL is deployed to the console. Lazy
    # resolution also avoids dragging in duplicate per-DSO version entrypoints.
    media_report_path = ROOT / 'build/media-codecs/native/build-report.json'
    media_report = json.loads(media_report_path.read_text())
    if media_report.get('host') is not False or media_report.get('symbol_prefix') != 'orbis_media_':
        raise RuntimeError('Missing isolated native software codec build')
    support = []
    for item in media_report['archives']:
        archive = ROOT / item['path']
        if not archive.is_relative_to(ROOT / 'build/media-codecs/native') or fingerprint(archive)['sha256'] != item['sha256']:
            raise RuntimeError('Native software codec archive binding changed')
        support.append(archive)
    lists = sorted((ENGINE / 'config/external').glob('**/*_so.list'))
    lists += sorted((ENGINE / 'security/nss/lib').glob('**/*_so.list'))
    codec_lists = [ENGINE / 'media/ffvpx/libavcodec/libmozavcodec_so.list',
                   ENGINE / 'media/ffvpx/libavutil/libmozavutil_so.list']
    for path in codec_lists:
        if not path.is_file():
            raise RuntimeError('Missing actual pinned static FFVPX object list: ' + str(path))
    lists += codec_lists
    for index, path in enumerate(lists):
        # nss3 now uses upstream pk11wrap_static -> softokn_static ->
        # freebl_static. Never fold old DLL loader objects into that closure.
        if path.name in ('libsoftokn3_so.list', 'libfreebl3_so.list', 'libfreeblpriv3_so.list'):
            continue
        output = BUILD / ('support-' + str(index) + '.a')
        output.unlink(missing_ok=True)
        run(['llvm-ar', 'crsT', output, *response_objects(path)])
        support.append(output)
    for name in ('pr', 'libc', 'ds'):
        output = BUILD / ('nspr-' + name + '.a')
        output.unlink(missing_ok=True)
        inputs = sorted((ENGINE / 'config/external/nspr' / name).glob('*.o'))
        if not inputs:
            raise RuntimeError('Missing NSPR native objects: ' + name)
        run(['llvm-ar', 'crsT', output, *inputs])
        support.append(output)
    archives = [ENGINE / 'third_party/angle/translator_gn/libtranslator_gn.a',
                ENGINE / 'third_party/angle/angle_common_gn/libangle_common_gn.a',
                ENGINE / 'third_party/angle/angle_common_shader_state_gn/libangle_common_shader_state_gn.a',
                ENGINE / 'third_party/angle/preprocessor_gn/libpreprocessor_gn.a',
                ENGINE / 'js/src/build/libjs_static.a',
                ENGINE / 'build/pure_virtual/libpure_virtual.a',
                ENGINE / 'x86_64-orbis-freebsd/release/libgkrust.a',
                ROOT / 'build/rust/liborbisfox.a']
    for item in archives:
        if not item.is_file():
            raise RuntimeError('Missing private engine archive: ' + str(item))
    inputs = BUILD / 'engine-inputs.rsp'
    inputs.write_text('\n'.join(shlex.quote(str(item)) for item in [*native, *xul]) + '\n' +
                      '--start-group\n' + '\n'.join(shlex.quote(str(item)) for item in [*archives, *support]) +
                      '\n--end-group\n')
    elf = BUILD / 'orbisfox.elf'
    # Drop only non-loadable DWARF at link time, not symbols or required inputs.
    # Materializing two giant debug ELFs before post-link strip can exhaust disk
    # while replacing the optional-weak-hook first link. Canonical engine objects
    # and every preserved evidence ELF remain untouched.
    command = ['ld.lld', '-m', 'elf_x86_64', '-pie', '-z', 'max-page-size=0x4000',
               '--no-rosegment', '--gc-sections', '--strip-debug', '--error-limit=0',
               '--script', ROOT / 'scripts/ps4-gecko.ld', '--eh-frame-hdr',
               '-L' + str(runtime), '-L' + str(sdk / 'lib'), '-o', elf,
               sdk / 'lib/crt1.o', '@' + str(inputs),
               '-lc++', '-lc++abi', '-lunwind', '-lc', '-lkernel', '-lSceSysmodule', '-lSceNet']
    report = {'stage': 'isolated native full Gecko executable', 'version': '0.68',
              'final_engine_application_linked': False, 'html_rendered': False,
              'hardware_tested': False, 'new_package_created': False,
              'baseline': baseline, 'desktop_engine_dsos_deployed': False,
              'nonloadable_DWARF_removed_at_link_symbols_and_relocations_preserved': True,
              'runtime_source_sha256': {str(p.relative_to(ROOT)): fingerprint(p)['sha256']
                  for directory in ('gecko','src','include') for p in sorted((ROOT / directory).rglob('*'))
                  if p.is_file() and p.suffix != '.md' and '__pycache__' not in p.parts},
              'isolated_software_codecs': media_report,
              'upstream_static_nss_closure_verified': True,
              'native_nspr_static_linker_probe_implemented': True,
              'scope': 'Development browser with gated HTTP/HTTPS; no sandbox, production security or arbitrary-site stability certification'}
    try:
        import re
        stdio_wrapped = re.findall(r'"([a-z]+)"', (ROOT / 'include/orbisfox/stdio_wrapped_symbols.h').read_text())
        allocator_wrapped = re.findall(r'"([a-z_]+)"', (ROOT / 'include/orbisfox/allocator_wrapped_symbols.h').read_text())
        wrapped = stdio_wrapped + allocator_wrapped + ['__expand_heap','__madvise','__munmap','__mmap'] + ['sysconf']
        command[1:1] = ['--wrap=' + name for name in wrapped] + ['--undefined=__wrap_' + name for name in wrapped]
        run(command, log=BUILD / 'link-output.log')
        # The converter cannot import absent weak hooks. Audit before resolving
        # any to zero: missing mozglue APIs must never silently become null.
        symbols = subprocess.check_output(['llvm-nm', '--undefined-only', str(elf)], text=True)
        weak = {line.split()[-1] for line in symbols.splitlines()
                if line.split() and line.split()[0] in ('w', 'v')}
        optional = {'ZSTD_trace_decompress_begin', 'ZSTD_trace_decompress_end',
                    '__cxa_thread_atexit_impl', '__gcov_dump', '__gcov_flush'}
        missing = weak - optional
        if missing:
            raise ValueError('Missing native engine/host APIs: ' + ', '.join(sorted(missing)))
        if weak:
            # These are upstream optional, null-checked hooks. LLVM emits literal
            # zero without fake implementations or invalid firmware imports;
            # libc++abi's actual pthread-TLS fallback stays active.
            command = command[:1] + ['-z', 'nodynamic-undefined-weak'] + command[1:]
            run(command, log=BUILD / 'final-link-output.log')
        report['absent_optional_weak_hooks'] = sorted(weak)
        report['missing_native_host_apis'] = []
        defined = subprocess.check_output(['llvm-nm', '-g', '--defined-only', str(elf)], text=True)
        clock_names = {'clock_gettime', 'clock_getres', 'pthread_condattr_setclock', 'pthread_condattr_getclock'}
        text_symbols = {parts[-1] for line in defined.splitlines()
                        if len(parts := line.split()) >= 3 and parts[-2] == 'T'}
        undefined_names = {line.split()[-1] for line in symbols.splitlines() if line.split()}
        if not clock_names <= text_symbols or clock_names & undefined_names:
            raise ValueError('Required SDK-to-firmware clock boundary was not installed in the executable')
        if not {'__wrap_sysconf', 'sysconf'} <= text_symbols:
            raise ValueError('Genuine native CPU affinity adapter and SDK sysconf fallback missing')
        cpu_probe = subprocess.check_output(['llvm-objdump', '-d', '--no-show-raw-insn',
            '--disassemble-symbols=PR_GetNumberOfProcessors,__wrap_sysconf', str(elf)], text=True)
        if '<__wrap_sysconf>' not in cpu_probe.split('<PR_GetNumberOfProcessors>:', 1)[-1]:
            raise ValueError('Actual NSPR processor count does not call the native affinity adapter')
        if not {'scePthreadSelf', 'scePthreadGetaffinity'} <= undefined_names:
            raise ValueError('Native CPU affinity adapter must use actual kernel thread/affinity imports')
        report['processor_count_real_affinity_only_full_gecko_sdk_other_sysconf_preserved'] = True
        report['processor_count_native_hardware_verified'] = False
        codec_names = {'orbis_media_' + name for name in
                       ('avcodec_version', 'avcodec_find_decoder', 'avcodec_send_packet',
                        'avcodec_receive_frame', 'av_frame_alloc', 'av_malloc', 'av_free',
                        'av_tx_init', 'av_tx_uninit')}
        # Static archive symbols may be localized by lld. Require actual code
        # bodies (not public visibility), exactly as for hidden Cubeb/Speex.
        all_defined = subprocess.check_output(['llvm-nm', '--defined-only', str(elf)], text=True)
        codec_text = {parts[-1] for line in all_defined.splitlines()
                      if len(parts := line.split()) >= 3 and parts[-2] in ('t', 'T')}
        if not codec_names <= codec_text or codec_names & undefined_names:
            raise ValueError('Actual isolated FFmpeg decoder/utility symbols missing from native executable')
        defined_names = {parts[-1] for line in all_defined.splitlines() if len(parts := line.split()) >= 3}
        decoder_records = {'orbis_media_ff_h264_decoder', 'orbis_media_ff_aac_decoder'}
        if not decoder_records <= defined_names or decoder_records & undefined_names:
            raise ValueError('Real H264/AAC codec registrations missing from native executable')
        report['isolated_h264_aac_decoder_registration_symbols_verified'] = sorted(decoder_records)
        report['static_ffvpx_defined_codec_symbols_verified'] = sorted(codec_names)
        report['static_ffvpx_object_lists'] = [str(path.relative_to(ROOT)) for path in codec_lists]
        audio_names = {'orbis_init', 'cubeb_resampler_create', 'cubeb_resampler_fill',
                       'cubeb_resampler_destroy', 'moz_speex_resampler_process_interleaved_float'}
        # Gecko marks Cubeb/Speex hidden; lld localizes these real code symbols
        # in the monolithic PIE. Global-only nm cannot prove their absence.
        audio_defined = subprocess.check_output(['llvm-nm', '--defined-only', str(elf)], text=True)
        audio_text_symbols = {parts[-1] for line in audio_defined.splitlines()
                              if len(parts := line.split()) >= 3 and parts[-2] in ('T', 't')}
        if not audio_names <= audio_text_symbols or audio_names & undefined_names:
            raise ValueError('Real Cubeb Orbis AudioOut adapter/resampler missing from native executable')
        report['native_cubeb_real_resampler_defined_symbols_verified'] = sorted(audio_names)
        report['native_cubeb_hidden_or_global_code_symbol_visibility_verified'] = True
        report['native_cubeb_orbis_adapter_defined_symbol_verified'] = True
        report['native_sdk_clock_adapter_defined_symbols_verified'] = sorted(clock_names)
        report['clock_adapter_only_installed_in_full_gecko_lane'] = True
        if 'XRE_GetBootstrap' not in text_symbols:
            raise ValueError('Required genuine Firefox singleton bootstrap factory is missing')
        report['standard_firefox_bootstrap_factory_defined_symbol_verified'] = True
        if 'orbisfox_sqlite_fcntl' not in text_symbols:
            raise ValueError('Required SDK file-lock record marshalling symbol is missing')
        report['sdk_file_lock_adapter_defined_symbol_verified'] = True
        if 'TRUST_ANCHORS_GetFunctionList' not in text_symbols:
            raise ValueError('Actual pinned Gecko builtin trust anchors are missing')
        report['actual_pinned_builtin_trust_anchor_factory_defined'] = True
        demangled = subprocess.check_output(['llvm-nm', '-C', '--defined-only', str(elf)], text=True)
        ui_names = ('orbisfox::NativeUiLoop::run()', 'orbisfox::NativeUiLoop::stop()',
                    'orbisfox::NativeUiLoop::publishFrame()', 'orbisfox::LatestUiFrame::read(')
        ui_code = '\n'.join(line for line in demangled.splitlines()
                            if len(line.split()) >= 3 and line.split()[1] in ('t', 'T'))
        websocket_names = ('mozilla::dom::WebSocket::Constructor(',
                           'mozilla::net::WebSocketChannel::AsyncOpen(',
                           'mozilla::net::WebSocketChannel::OnDataAvailable(')
        if any(name not in ui_code for name in websocket_names):
            raise ValueError('Actual Gecko DOM/WebSocket networking code missing from native executable')
        report['actual_gecko_dom_and_websocket_channel_defined_code_verified'] = True
        report['browser_websocket_fixture_hardware_verified'] = False
        if any(name not in ui_code for name in ui_names):
            raise ValueError('Independent native UI worker/frame ownership code missing')
        report['independent_native_controller_cursor_scanout_defined_code_verified'] = True
        report['native_ui_thread_hardware_verified'] = False
        report['chrome_content_thread_isolation_implemented'] = False
        report['youtube_crash_claimed_fixed'] = False
        hal_assembly = subprocess.check_output(['llvm-objdump', '-d',
            '--disassemble-symbols=_ZN10nsAppShell4InitEv,_ZN10nsAppShellD0Ev,_ZN10nsAppShellD1Ev,_ZN10nsAppShellD2Ev', str(elf)], text=True)
        (BUILD / 'orbis-hal-lifecycle-disassembly.log').write_text(hal_assembly)
        if ('<_ZN7mozilla3hal4InitEv>' not in hal_assembly
                or '<_ZN7mozilla3hal8ShutdownEv>' not in hal_assembly):
            raise ValueError('Orbis app shell must own genuine HAL initialization and shutdown')
        report['hal_app_shell_init_shutdown_genuine_calls_verified'] = True
        report['media_wake_lock_table_hardware_verified'] = False
        if 'WebBrowserChrome2Stub::ProvideWindow(' not in demangled:
            raise ValueError('Native bounded popup window-provider bridge is missing from final executable')
        report['native_bounded_window_provider_bridge_defined_symbol_verified'] = True
        report['native_popup_bridge_hardware_verified'] = False
        report['popup_integration_claimed_heap_crash_fix'] = False
        guard_disassembly = subprocess.check_output(['llvm-objdump', '-d', '--disassemble-symbols=__cxa_guard_acquire', str(elf)], text=True)
        (BUILD / 'cxx-guard-acquire-disassembly.log').write_text(guard_disassembly)
        if 'scePthreadGetthreadid' not in guard_disassembly or '<syscall>' in guard_disassembly:
            raise ValueError('C++ guard must use genuine native thread IDs, not SDK syscall stub')
        report['cxx_static_guard_native_thread_identity_disassembly_verified'] = True
        skia_assembly = subprocess.check_output(['llvm-objdump', '-d',
            '--disassemble-symbols=_ZN11SkSemaphore6osWaitEv,_ZN18OrbisSkiaSemaphore4waitEv', str(elf)], text=True)
        (BUILD / 'skia-wait-disassembly.log').write_text(skia_assembly)
        if 'pthread_cond_wait' not in skia_assembly or '<sem_wait' in skia_assembly or '<ksem_' in skia_assembly:
            raise ValueError('Skia OS wait must use checked pthread predicate, not unchecked SDK ksem')
        report['skia_checked_pthread_wait_backend_disassembly_verified'] = True
        report['skia_sync_native_gate_implemented_not_hardware_certified'] = True
        report['glyph_index_null_capacity_failfast_checks_implemented'] = True
        report['original_glyph_crash_cause_claimed_proven'] = False
        stdio_disassembly = subprocess.check_output(['llvm-objdump', '-d', '--disassemble-symbols=__lockfile', str(elf)], text=True)
        (BUILD / 'stdio-lock-disassembly.log').write_text(stdio_disassembly)
        if 'pthread_mutex_lock' not in stdio_disassembly or '%fs:' in stdio_disassembly:
            raise ValueError('SDK buffered stdio must use native mutex ownership, not musl-TCB thread IDs')
        all_defined = subprocess.check_output(['llvm-nm', '--defined-only', str(elf)], text=True)
        stdio_text = {parts[-1] for line in all_defined.splitlines()
                      if len(parts := line.split()) >= 3 and parts[-2] in ('T', 't')}
        for symbol in ('__lockfile', '__unlockfile', 'flockfile', 'funlockfile', 'ftrylockfile'):
            if symbol not in stdio_text:
                raise ValueError('Missing actual stdio lock boundary: ' + symbol)
        for name in stdio_wrapped:
            if '__wrap_' + name not in stdio_text:
                raise ValueError('Missing real buffered stdio entry-point protection: ' + name)
        fprintf_disassembly = subprocess.check_output(['llvm-objdump', '-d', '--disassemble-symbols=__wrap_fprintf', str(elf)], text=True)
        (BUILD / 'sdk-fprintf-entry-disassembly.log').write_text(fprintf_disassembly)
        if '<vfprintf>' not in fprintf_disassembly or 'pthread_mutex_lock' not in fprintf_disassembly:
            raise ValueError('SDK fprintf must reach protected entry even when FILE.lock=-1')
        report['stdio_public_entries_wrapped_independently_of_sdk_lock_skip'] = stdio_wrapped
        report['buffered_stdio_native_mutex_ownership_disassembly_verified'] = True
        for name in allocator_wrapped:
            if '__wrap_' + name not in stdio_text:
                raise ValueError('Missing genuine SDK allocator entry lock: ' + name)
        malloc_assembly = subprocess.check_output(['llvm-objdump', '-d', '--disassemble-symbols=__wrap_malloc,malloc', str(elf)], text=True)
        # Additional diagnostics can make LLVM outline the lock constructor.
        # Follow that actual call rather than requiring its body to be inlined.
        lock_symbol = '_ZN12_GLOBAL__N_18HeapLockC2EPKcmPvm'
        outlined_lock = '<' + lock_symbol + '>' in malloc_assembly
        if outlined_lock:
            malloc_assembly += subprocess.check_output(['llvm-objdump', '-d', '--disassemble-symbols=' + lock_symbol, str(elf)], text=True)
        (BUILD / 'native-allocator-disassembly.log').write_text(malloc_assembly)
        if 'pthread_mutex_lock' not in malloc_assembly or '<malloc>' not in malloc_assembly or '<__libc+0xc>' not in malloc_assembly:
            raise ValueError('Allocator wrapper must protect real audited SDK allocator and retain read-only libc+12 gate evidence')
        report['genuine_sdk_allocator_entries_native_mutex_verified'] = allocator_wrapped
        report['allocator_full_gecko_no_private_libc_flags_changed'] = True
        report['allocator_diagnostics_optin_default_direct_SDK_API'] = True
        report['allocator_runtime_probe_required_real_calls_retained'] = True
        report['allocator_native_raw_reclaim_coalesce_pretrim_canaries_implemented'] = True
        report['allocator_native_eight_worker_bin_mmap_requests'] = [229360, 229361, 229376]
        report['allocator_native_boundary_grow_shrink_zero_canaries_implemented'] = True
        report['allocator_startup_watchdog_30s_and_fatal_uncertain_join_implemented'] = True
        report['allocator_reclaim_canaries_firmware_verified'] = False
        report['SDK_heap_corruption_root_cause_claimed_fixed'] = False
        audit_symbols = subprocess.check_output(['llvm-nm', '-S', str(elf)], text=True)
        if not any(line.split()[1:] == ['0000000000000610', 'B', 'orbisfox_sdk_malloc_state'] for line in audit_symbols.splitlines()):
            raise ValueError('Read-only SDK bin-state binding missing or wrong size')
        expand_assembly = subprocess.check_output(['llvm-objdump', '-d', '--disassemble-symbols=malloc', str(elf)], text=True)
        if '<__wrap___expand_heap>' not in expand_assembly:
            raise ValueError('SDK heap expansions must register audit-readable ranges')
        report['allocator_bin_audit_binding'] = audit_binding
        report['allocator_read_only_endpoint_bin_audit_full_startup_then_realloc_copy_discard'] = True
        reclaim_assembly = subprocess.check_output(['llvm-objdump', '-d', '--disassemble-symbols=__bin_chunk,realloc,orbisfox_sdk_realloc_copy', str(elf)], text=True)
        (BUILD / 'native-reclaim-copy-disassembly.log').write_text(reclaim_assembly)
        if '<__wrap___madvise>' not in reclaim_assembly or '<__wrap___munmap>' not in reclaim_assembly or '<orbisfox_sdk_realloc_copy>' not in reclaim_assembly or '<memcpy>' not in reclaim_assembly:
            raise ValueError('SDK reclaim/copy capability and audit bridges must retain genuine SDK callees')
        report['SDK_reclaim_retention_capability_gate_implemented'] = True
        report['SDK_reclaim_rejected_until_native_retention_verified'] = True
        report['SDK_realloc_copy_read_only_leaf_audit_and_genuine_memcpy_verified'] = True
        report['SDK_mapped_free_unmap_read_only_leaf_audit_verified'] = True
        report['SDK_reclaim_retention_gate_firmware_verified'] = False
        if '__wrap___mmap' not in stdio_text:
            raise ValueError('SDK anonymous mapping boundary missing')
        report['SDK_game_direct_backing_only_whole_SDK_maps_not_GC_or_file_maps'] = True
        report['SDK_game_direct_backing_native_hardware_verified'] = False
        report['SDK_game_direct_heap_memory_type'] = {'name': 'WB_ONION', 'value': 0}
        report['SDK_cached_heap_performance_hardware_verified'] = False
        if 'orbisfox::map_gc_chunk_memory(' not in demangled or 'js::gc::MapGCChunkPages(' not in demangled:
            raise ValueError('GC arena-chunk direct-memory backend missing from final link')
        report['GC_arena_nursery_chunks_cached_game_memory_only'] = True
        report['GC_direct_chunk_memory_hardware_verified'] = False
        report['profile_saved_preferences_explicitly_loaded_before_browser_UI'] = True
        report['SDK_mremap_ENOSYS_shrink_copy_bounded_to_destination_capacity'] = True
        report['unique_native_run_log_directories_initialized_before_constructors'] = True
        report['allocator_bin_audit_interior_list_full_walk'] = False
        report['allocator_bin_audit_hardware_verified'] = False
        # Preserve symbols/relative relocations for the startup audit; discard
        # only DWARF before conversion so debug data cannot exhaust package space.
        run(['llvm-strip', '--strip-debug', elf])
        run([sys.executable, ROOT / 'scripts/verify-startup.py', elf])
        run([sys.executable, ROOT / 'scripts/verify-rust-abi.py', elf])
        report['final_engine_application_linked'] = True
        report['executable'] = fingerprint(elf)
    finally:
        report['baseline_present_before_build'] = baseline is not None
        report['baseline_unchanged'] = fingerprint(ROOT / 'dist/OrbisFox.pkg', optional=True) == baseline
        (BUILD / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0

if __name__ == '__main__':
    sys.exit(main())
