#!/usr/bin/env python3
"""Produce OrbisFox 0.68 CPU affinity/fullscreen/website appearance candidate; preserve matched milestones."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build/gecko-app'
ENGINE = ROOT / 'build/gecko-layout'
DIST = ROOT / 'dist/gecko'
VERSION = '0.68'
# Public PS4 Param.sfo ATTRIBUTE bit5: common dialogs follow system assignment.
# Leave the stable standalone package's attributes and console settings untouched.
COMMON_DIALOG_ATTRIBUTE_SYSTEM = 0x20
spec = importlib.util.spec_from_file_location('baseline_packaging', ROOT / 'scripts/package.py')
PKG = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PKG)


def stage_resources(source, target):
    """Ship public upstream resource files, not desktop executables or DSOs."""
    # Non-omnijar Preferences::InitInitialObjects reads $gre/greprefs.js.
    # Omitting it silently leaves many dynamic prefs at constructor fallbacks,
    # including the script-security manager's JavaScript-disabled fallback.
    greprefs = source / 'greprefs.js'
    if not greprefs.is_file() or not 0 < greprefs.stat().st_size <= 2 * 1024 * 1024:
        raise ValueError('Required generated Gecko greprefs.js is missing or invalid')
    target.mkdir(parents=True, exist_ok=True)
    generated_prefs = target / 'greprefs.js'
    shutil.copyfile(greprefs, generated_prefs)
    files = [generated_prefs]
    for name in ('actors', 'chrome', 'components', 'defaults', 'modules', 'res', 'hyphenation', 'localization'):
        directory = source / name
        if not directory.is_dir():
            continue
        for item in sorted(directory.rglob('*')):
            if not item.is_file():
                continue
            relative = item.relative_to(source)
            if item.suffix.lower() in ('.so', '.dll', '.exe', '.a', '.o', '.md'):
                raise ValueError('Non-resource input in resource tree: ' + str(relative))
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, destination)
            files.append(destination)
    # Upstream packager normally aggregates these manifests. Use the same real
    # generated manifest fragments in an unpacked, single-application GRE tree.
    manifest = target / 'chrome.manifest'
    entries = ['resource gre ./', 'resource app ./', 'content orbisfox chrome/orbisfox/content/']
    entries += ['manifest ' + item.relative_to(target).as_posix()
                for item in files if item.suffix == '.manifest']
    manifest.write_text('\n'.join(entries) + '\n')
    files.append(manifest)
    return files


def complete_gp4(path, files):
    """Avoid command-line size limits and include every real resource directory."""
    tree = ET.parse(path)
    table = tree.getroot().find('files')
    directories = tree.getroot().find('rootdir')
    if table is None or directories is None:
        raise ValueError('Unexpected OpenOrbis GP4 structure')
    for child in list(table):
        table.remove(child)
    for child in list(directories):
        directories.remove(child)
    nodes = {(): directories}
    for name in files:
        parts = Path(name).parts
        if not parts or Path(name).is_absolute() or '..' in parts:
            raise ValueError('Unsafe GP4 path: ' + name)
        ET.SubElement(table, 'file', {'targ_path': name, 'orig_path': name})
        for depth in range(1, len(parts)):
            key = parts[:depth]
            if key not in nodes:
                nodes[key] = ET.SubElement(nodes[key[:-1]], 'dir', {'targ_name': key[-1]})
    ET.indent(tree, space='  ')
    tree.write(path, encoding='utf-8', xml_declaration=True)


def preserved_baseline_digest():
    path = ROOT / 'dist/OrbisFox.pkg'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    app = json.loads((BUILD / 'build-report.json').read_text())
    if (app.get('version') != VERSION or not app.get('final_engine_application_linked')
            or not app.get('baseline_unchanged') or not app.get('upstream_static_nss_closure_verified')):
        raise RuntimeError('Verified native final link required')
    native_elf = BUILD / 'orbisfox.elf'
    if (native_elf.stat().st_size != app['executable']['bytes']
            or hashlib.sha256(native_elf.read_bytes()).hexdigest() != app['executable']['sha256']):
        raise RuntimeError('Native executable differs from verified build report')
    baseline = preserved_baseline_digest()
    sdk = Path(os.environ.get('OO_PS4_TOOLCHAIN', ROOT / '.deps/OpenOrbis/PS4Toolchain')).resolve()
    tools = sdk / 'bin/linux'
    stage = BUILD / 'pkg'
    shutil.rmtree(stage, ignore_errors=True)
    (stage / 'sce_sys').mkdir(parents=True)
    DIST.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, DOTNET_SYSTEM_GLOBALIZATION_INVARIANT='1',
               OO_PS4_TOOLCHAIN=str(sdk))
    def run(tool, *args):
        subprocess.run([str(tools / tool), *map(str, args)], cwd=stage, env=env, check=True)
    # Adapter/ABI tests retain their scoped claims; they do not certify Gecko
    # rendering or turn an untested firmware package into a hardware pass.
    subprocess.run(['make', 'test'], cwd=ROOT, check=True)
    subprocess.run(['node', str(ROOT / 'tests/generated_gecko_prefs_test.js')], cwd=ROOT, check=True)
    subprocess.run(['node', str(ROOT / 'tests/network_probe_test.js')], cwd=ROOT, check=True)
    subprocess.run(['node', str(ROOT / 'tests/storage_probe_test.js')], cwd=ROOT, check=True)
    subprocess.run(['node', str(ROOT / 'tests/https_probe_test.js')], cwd=ROOT, check=True)
    subprocess.run(['node', str(ROOT / 'tests/browser_shell_test.js')], cwd=ROOT, check=True)
    subprocess.run(['node', str(ROOT / 'tests/browser_shell_ui_test.js')], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/test-native-network.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/test-initial-frame-remoteness.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/test-cxx-guards.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/test-javascript.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/test-nspr-static.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/verify-startup.py'), str(BUILD / 'orbisfox.elf')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/verify-rust-abi.py'), str(BUILD / 'orbisfox.elf')], check=True)
    PKG.verify_service_imports(BUILD / 'orbisfox.elf')
    run('create-fself', f'-in={BUILD / "orbisfox.elf"}', f'-out={BUILD / "orbisfox.oelf"}',
        '--eboot', 'eboot.bin', '--paid', '0x3800000000000035', '--authinfo', PKG.AUTHINFO)
    sections = PKG.verify_oelf(BUILD / 'orbisfox.oelf')
    sfo = 'sce_sys/param.sfo'
    run('PkgTool.Core', 'sfo_new', sfo)
    entries = {
        'APP_TYPE': ('Integer', 4, '1'), 'APP_VER': ('Utf8', 8, VERSION),
        'ATTRIBUTE': ('Integer', 4, str(COMMON_DIALOG_ATTRIBUTE_SYSTEM)), 'CATEGORY': ('Utf8', 4, 'gd'),
        'FORMAT': ('Utf8', 4, 'obs'), 'CONTENT_ID': ('Utf8', 48, PKG.CONTENT_ID),
        'DOWNLOAD_DATA_SIZE': ('Integer', 4, '0'), 'SYSTEM_VER': ('Integer', 4, '1020'),
        'TITLE': ('Utf8', 128, 'OrbisFox'), 'TITLE_ID': ('Utf8', 12, PKG.TITLE_ID),
        'VERSION': ('Utf8', 8, VERSION),
    }
    for key, (kind, size, value) in entries.items():
        run('PkgTool.Core', 'sfo_setentry', sfo, key, '--type', kind, '--maxsize', size, '--value', value)
    PKG.prepare_artwork(stage)
    resources = stage_resources(ENGINE / 'dist/bin', stage / 'gecko')
    for source, destination in (
            (ROOT / 'gecko/orbisfox/fixtures/default-prefs.js', 'gecko/defaults/pref/orbisfox.js'),
            (ROOT / 'gecko/orbisfox/fixtures/offline.html', 'assets/offline.html'),
            (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js', 'assets/gecko-startup.js'),
            (ROOT / 'gecko/orbisfox/fixtures/network-probe.js', 'assets/network-probe.js'),
            (ROOT / 'gecko/orbisfox/fixtures/storage-probe.js', 'assets/storage-probe.js'),
            (ROOT / 'gecko/orbisfox/fixtures/profile-lifecycle.js', 'assets/profile-lifecycle.js'),
            (ROOT / 'gecko/orbisfox/fixtures/https-probe.js', 'assets/https-probe.js'),
            (ROOT / 'gecko/orbisfox/fixtures/browser.xhtml', 'gecko/chrome/orbisfox/content/browser.xhtml'),
            (ROOT / 'gecko/orbisfox/fixtures/browser.css', 'gecko/chrome/orbisfox/content/browser.css'),
            (ROOT / 'gecko/orbisfox/fixtures/browser-shell-ui.js', 'gecko/chrome/orbisfox/content/browser-shell-ui.js'),
            (ROOT / 'gecko/orbisfox/fixtures/browser-shell-model.js', 'gecko/chrome/orbisfox/content/browser-shell-model.js'),
            (ROOT / 'gecko/orbisfox/fixtures/browser-shell-model.js', 'assets/browser-shell-model.js'),
            (ROOT / 'gecko/orbisfox/fixtures/browser-shell-host.js', 'assets/browser-shell-host.js'),
            (ENGINE / 'offline-assets/fonts/NotoSans-Regular.ttf', 'assets/fonts/NotoSans-Regular.ttf'),
            (ENGINE / 'offline-assets/fonts/NotoSansSymbols2-Regular.ttf', 'assets/fonts/NotoSansSymbols2-Regular.ttf'),
            (ENGINE / 'offline-assets/fonts/NotoSansMath-Regular.ttf', 'assets/fonts/NotoSansMath-Regular.ttf'),
            (ENGINE / 'offline-assets/fonts/NotoColorEmoji.ttf', 'assets/fonts/NotoColorEmoji.ttf')):
        target = stage / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    licenses = {
        'project-MIT.txt': ROOT / 'LICENSE',
        'project-license-scope.md': ROOT / 'LICENSES/README.md',
        'third-party-notices.md': ROOT / 'THIRD_PARTY.md',
        'OpenOrbis-derived-GPL-3.0.txt': ROOT / 'LICENSES/GPL-3.0-only.txt',
        'MPL-2.0.txt': ROOT / 'LICENSES/MPL-2.0.txt',
        'mozilla-license.txt': ROOT / '.deps/gecko-layout/LICENSE',
        'llvm-libcxx-license.txt': ROOT / '.deps/llvm-runtimes/libcxx/LICENSE.TXT',
        'llvm-libcxxabi-license.txt': ROOT / '.deps/llvm-runtimes/libcxxabi/LICENSE.TXT',
        'llvm-libunwind-license.txt': ROOT / '.deps/llvm-runtimes/libunwind/LICENSE.TXT',
        'stb-truetype-MIT.txt': ROOT / 'assets/licenses/stb-truetype-MIT.txt',
        'ffmpeg-LGPL-2.1.txt': ROOT / '.deps/ffmpeg-9.0.2/COPYING.LGPLv2.1',
        'noto-OFL.txt': ENGINE / 'offline-assets/licenses/noto-OFL.txt',
        'noto-emoji-OFL.txt': ENGINE / 'offline-assets/licenses/noto-emoji-OFL.txt',
    }
    # Exact public source and reproducible configuration for the added static
    # LGPL codecs accompany the binary, not proprietary SDK material.
    codec_sources = {
        'ffmpeg-9.0.2.tar.xz': ROOT / '.deps/downloads/ffmpeg-9.0.2.tar.xz',
        'ffmpeg-build-report.json': ROOT / 'build/media-codecs/native/build-report.json',
        'ffmpeg-config.h': ROOT / 'build/media-codecs/native/config.h',
        'ffmpeg-config-components.h': ROOT / 'build/media-codecs/native/config_components.h',
        'build-media-codecs.py': ROOT / 'scripts/build-media-codecs.py',
    }
    licenses.update(codec_sources)
    for name, source in licenses.items():
        target = stage / 'assets/misc' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    # create-gp4 takes a space-separated file list. Refuse ambiguous paths.
    files = sorted(item.relative_to(stage).as_posix() for item in stage.rglob('*') if item.is_file())
    if any(any(character.isspace() for character in name) for name in files):
        raise ValueError('Package path contains whitespace')
    run('create-gp4', '-out', 'project.gp4', f'--content-id={PKG.CONTENT_ID}',
        '--files', 'eboot.bin sce_sys/param.sfo')
    complete_gp4(stage / 'project.gp4', files)
    run('PkgTool.Core', 'pkg_build', 'project.gp4', DIST)
    artifact = DIST / 'OrbisFox.pkg'
    (DIST / (PKG.CONTENT_ID + '.pkg')).replace(artifact)
    run('PkgTool.Core', 'pkg_validate', artifact)
    shutil.copyfile(BUILD / 'orbisfox.elf', DIST / 'orbisfox.elf')
    unchanged = preserved_baseline_digest() == baseline
    if not unchanged:
        raise RuntimeError('Preserved 0.11 changed unexpectedly')
    report = {
        'title': 'OrbisFox', 'version': VERSION, 'package': str(artifact.relative_to(ROOT)),
        'bytes': artifact.stat().st_size, 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
        'gecko_revision': PKG.SWGL_REVISION, 'native_full_gecko_linked': True,
        'native_executable': app['executable'],
        'native_affinity_processor_count_adapter_implemented': app['processor_count_real_affinity_only_full_gecko_sdk_other_sysconf_preserved'],
        'website_color_scheme_preference_implemented': True,
        'website_fullscreen_focus_lifecycle_and_chrome_events_implemented': True,
        'cpu_count_fullscreen_color_scheme_hardware_verified': False,
        'sfo_category': 'gd',
        'chrome_home_screen_with_search_and_bookmarks': True,
        'bookmarks_profile_preferences_with_explicit_save_and_rollback': True,
        'fullscreen_chrome_hidden_options_restores_ui': True,
        'SDK_mremap_ENOSYS_shrink_copy_bounded_to_destination_capacity': True,
        'unique_native_run_log_directories_initialized_before_constructors': True,
        'SDK_mapped_free_unmap_read_only_leaf_audit_implemented': True,
        'nspr_static_linker_initialized_without_desktop_dlopen_on_host': True,
        'upstream_static_nss_crypto_closure_verified': True,
        'native_nspr_static_linker_behavior_probe_implemented': True,
        'native_filesystem_path_port_implemented': True,
        'native_path_resolver_real_filesystem_host_tests_passed': True,
        'console_filesystem_preflight_logging_implemented': True,
        'firmware_stat_record_marshalling_implemented': True,
        'native_stat_lstat_fstat_executable_binding_implemented': True,
        'stat_record_translation_sanitizer_tests_passed': True,
        'native_filesystem_metadata_firmware_probe_implemented': True,
        'unsupported_sdk_fallocate_disabled_in_shared_memory_backend': True,
        'actual_gecko_shared_memory_snapshot_probe_implemented': True,
        'native_utf8_path_conversion_avoids_incompatible_sdk_wchar': True,
        'early_single_process_default_preferences_packaged': True,
        'visible_browser_attached_context_flags_validated_without_mutation': True,
        'visible_browser_creation_stage_logging_implemented': True,
        'absent_gfx_info_feature_queries_return_real_unavailable_error': True,
        'absent_webgl_backend_disabled_explicitly': True,
        'directory_provider_declines_unrelated_keys_without_exception': True,
        'orbis_font_visibility_uses_bundled_noto_not_android_device_identity': True,
        'optional_shader_cache_driver_metadata_guarded': True,
        'optional_archive_font_scan_requires_real_reader': True,
        'archive_font_cache_invalidated_when_metadata_unavailable': True,
        'absent_adapter_telemetry_skipped_without_losing_screen_metrics': True,
        'graphics_failure_logging_preserved_without_gfx_info_service': True,
        'navigation_timer_event_loop_and_first_pump_checkpoints_implemented': True,
        'independent_content_context_activation_implemented': True,
        'navigation_progress_and_partial_fixture_reporting_implemented': True,
        'original_offline_file_document_navigation_restored': True,
        'supported_force_disable_e10s_environment_switch_implemented': True,
        'global_remote_autostart_gate_before_browser_creation_implemented': True,
        'standalone_context_windowless_process_switch_policy_implemented': True,
        'visible_native_widget_retained_and_checked': True,
        'required_generated_greprefs_packaging_repair_implemented': True,
        'missing_defaults_regression_gate_implemented': True,
        'sdk_to_firmware_clock_boundary_repair_implemented': True,
        'coherent_condition_clock_and_absolute_deadline_probe_implemented': True,
        'clock_repair_hardware_validated': False,
        'post_render_stall_fix_claimed': False,
        'native_event_wait_and_clock_diagnostics_implemented': True,
        'stick_cursor_base_speed_multiplier': 1.5,
        'stick_cursor_user_multiplier_range': [0.25, 3.0],
        'persistent_search_engine_settings': ['google', 'duckduckgo', 'bing'],
        'SDK_failed_geometric_arena_bounded_mapping_retry': True,
        'Orbis_GC_unsupported_FreeBSD_MAP_ALIGNED_path_excluded': True,
        'stick_fractional_carry_and_unchanged_touchpad': True,
        'controlled_lan_necko_http_and_native_dns_probes_implemented': True,
        'square_lan_navigation_requires_exact_http_probe_success': True,
        'native_networking_hardware_validated': False,
        'native_net_module_load_init_resolver_symbol_gate_implemented': True,
        'https_valid_builtin_chain_and_three_certificate_rejection_probes_implemented': True,
        'https_certificate_override_or_added_test_trust_roots': False,
        'https_probes_require_native_storage_profile_dns_success': True,
        'public_browsing_requires_lan_fixture_server': False,
        'standard_firefox_bootstrap_owned_sqlite_lifetime_implemented': True,
        'real_persistent_mozstorage_gate_before_networking_implemented': True,
        'full_gecko_sdk_flock_bsd_layout_and_type_marshalling_implemented': True,
        'sqlite_supported_unix_vfs_fcntl_syscall_override_implemented': True,
        'global_sdk_and_rust_fcntl_not_interposed': True,
        'raw_vs_translated_firmware_lock_gate_implemented': True,
        'file_lock_repair_hardware_validated': False,
        'sqlite_real_extended_error_logging_implemented': True,
        'cookie_storage_failure_workaround_or_security_relaxation': False,
        'https_certificate_validation_hardware_tested': False,
        'general_internet_navigation_enabled_after_runtime_safety_gates': True,
        'three_real_tabs_available': True,
        'native_window_provider_popup_bridge_implemented': True,
        'native_popup_bridge_hardware_verified': False,
        'optin_heap_guards_quarantine_trace_implemented': True,
        'heap_diagnostics_enabled_by_default': False,
        'heap_tracking_admission_limit': 196608,
        'heap_tracking_saturation_preserves_existing_guards_new_raw_SDK_fallback': True,
        'heap_trace_v2_coverage_counters': True,
        'allocator_raw_reclaim_coalesce_pretrim_startup_canaries': True,
        'allocator_eight_worker_bin_mmap_boundary_requests': [229360, 229361, 229376],
        'allocator_boundary_grow_shrink_zero_startup_canaries': True,
        'allocator_startup_watchdog_seconds': 30,
        'allocator_reclaim_canaries_firmware_verified': False,
        'allocator_read_only_endpoint_bin_audit_full_startup_then_realloc_copy_discard': True,
        'SDK_reclaim_retention_capability_gate_implemented': True,
        'SDK_reclaim_rejected_until_native_retention_verified': True,
        'SDK_reclaim_retention_gate_firmware_verified': False,
        'allocator_bin_audit_allocator_policy_unchanged': True,
        'SDK_heap_backing_prefers_game_direct_memory_with_real_flexible_fallback': True,
        'SDK_direct_map_exact_whole_release_and_explicit_zero_initialization': True,
        'SDK_direct_backing_hardware_verified': False,
        'SDK_game_direct_heap_memory_type': {'name': 'WB_ONION', 'value': 0},
        'SDK_cached_heap_performance_hardware_verified': False,
        'GC_arena_nursery_chunks_prefer_cached_game_direct_memory': True,
        'GC_direct_memory_excludes_shrinkable_buffers_files_stacks_and_JIT': True,
        'GC_direct_chunk_hardware_verified': False,
        'profile_saved_preferences_explicitly_loaded_before_browser_UI': True,
        'browser_keyboard_native_only': True,
        'settings_explicit_blocking_profile_preferences_save': True,
        'native_mouse_moves_preserve_held_primary_button': True,
        'allocator_bin_audit_hardware_verified': False,
        'website_crashes_claimed_fixed': False,
        'skia_checked_pthread_OS_semaphore_implemented': True,
        'skia_actual_native_contention_startup_gate': True,
        'glyph_lookup_prepare_consume_failfast_diagnostics': True,
        'original_null_glyph_root_cause_claimed_proven': False,
        'common_dialog_ATTRIBUTE_system_assignment': COMMON_DIALOG_ATTRIBUTE_SYSTEM,
        'independent_atomic_heartbeat_probe_implemented': True,
        'bounded_timer_pump_script_execution_stage_traces_implemented': True,
        'separate_actual_async_file_channel_probe_implemented': True,
        'async_file_loading_repair_claimed': False,
        'shared_memory_create_map_freeze_clone_firmware_verified': False,
        'path_resolver_firmware_behavior_verified': False,
        'offline_html_fixture_included': True, 'html_css_dom_layout_included': True,
        'swgl_included': True, 'videoout_frame_bridge_implemented': True,
        'font_family': 'Noto Sans', 'resource_files': len(resources),
        'oelf_payload_sections_verified': sections, 'new_package_created': True,
        'html_rendered_on_console': False, 'fixture_dom_assertions_executed_on_console': False,
        'hardware_tested': False, 'baseline_0_11_unchanged': unchanged,
        'baseline_0_11_sha256': baseline, 'network_navigation_enabled_after_runtime_safety_gates': True,
        'sandbox_enabled': False, 'jit_enabled': None, 'jit_backend_compiled': True,
        'jit_native_capability_gated': True, 'jit_firmware_verified': False,
        'native_audioout_backend_implemented': True, 'audio_playback_firmware_verified': False,
        'static_ffvpx_real_codec_binding_implemented': True,
        'video_playback_firmware_verified': False,
        'symbol_math_font_fallbacks_packaged': True,
        'color_emoji_font_packaged': True,
        'emoji_rendering_firmware_verified': False,
        'wheel_cursor_hit_testing_implemented': True,
        'pointer_elapsed_time_and_stall_reanchoring_implemented': True,
        'independent_native_controller_cursor_scanout_implemented': True,
        'native_ui_worker_latest_completed_frame_only': True,
        'native_ui_worker_ime_presentation_quiescence_implemented': True,
        'native_ui_worker_hardware_verified': False,
        'invalid_table_caller_persisted_before_original_fault': True,
        'youtube_crash_claimed_fixed': False,
        'hal_app_shell_init_shutdown_genuine_calls_verified': app['hal_app_shell_init_shutdown_genuine_calls_verified'],
        'media_wake_lock_table_hardware_verified': False,
        'separate_bookmarks_history_chrome_pages_implemented': True,
        'bounded_profile_history_and_recent_home_sites_implemented': True,
        'content_and_chrome_main_threads_isolated': False,
        'private_use_icon_font_remapping': False,
        'website_security_certified': False,
        'runtime_logs': ['/data/orbisfox/runs/<run-id>/startup-layout.log', '/data/orbisfox/runs/<run-id>/platform-layout.log', '/data/orbisfox/runs/<run-id>/heap-audit.log'],
        'runtime_capture': '/data/orbisfox/runs/<run-id>/gecko-fixture-frame.bgra',
        'scope': 'Development browser with gated HTTP/HTTPS and optional heap diagnostics; no production security or website stability certification',
    }
    (DIST / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    subprocess.run([sys.executable, ROOT / 'scripts/verify-gecko-package.py'], check=True)
    print(json.dumps(json.loads((DIST / 'build-report.json').read_text()), indent=2))
    return 0

if __name__ == '__main__':
    sys.exit(main())
