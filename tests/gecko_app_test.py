import importlib.util
from pathlib import Path
import tempfile
import struct
import subprocess
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent

def load(name, script):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

APP = load('gecko_native_app', 'build-gecko-app.py')
PACKAGE = load('gecko_native_package', 'package-gecko.py')
VERIFY = load('gecko_native_package_verify', 'verify-gecko-package.py')

class GeckoAppTests(unittest.TestCase):
    def test_fresh_checkout_needs_no_historical_baseline(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(APP, 'ROOT', Path(directory)):
            root = Path(directory)
            missing = root / 'dist/OrbisFox.pkg'
            self.assertIsNone(APP.fingerprint(missing, optional=True))
            with self.assertRaises(FileNotFoundError):
                APP.fingerprint(missing)
            with patch.object(PACKAGE, 'ROOT', root):
                self.assertIsNone(PACKAGE.preserved_baseline_digest())
                missing.parent.mkdir()
                missing.write_bytes(b'protected old package')
                before = PACKAGE.preserved_baseline_digest()
                self.assertEqual(before, APP.fingerprint(missing)['sha256'])
                missing.write_bytes(b'changed package')
                self.assertNotEqual(PACKAGE.preserved_baseline_digest(), before)

    def test_engine_response_requires_real_in_lane_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'objects').mkdir()
            item = root / 'objects/file with space.o'
            item.write_bytes(b'object')
            response = root / 'link.rsp'
            response.write_text("--whole-archive 'objects/file with space.o' --no-whole-archive\n")
            with patch.object(APP, 'ENGINE', root):
                self.assertEqual(APP.response_objects(response), [item])
                response.write_text('--ignore-unresolved-symbols\n')
                with self.assertRaises(ValueError): APP.response_objects(response)
                response.write_text('missing.o\n')
                with self.assertRaises(ValueError): APP.response_objects(response)

    def test_response_cannot_pull_another_lane(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lane = root / 'lane'
            lane.mkdir()
            (root / 'other.o').write_bytes(b'other')
            response = lane / 'link.rsp'
            response.write_text('../other.o\n')
            with patch.object(APP, 'ENGINE', lane):
                with self.assertRaises(ValueError): APP.response_objects(response)

    def test_gp4_contains_complete_nested_resource_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'project.gp4'
            path.write_text('<psproject><files img_no="0"><file targ_path="stale"/></files>'
                            '<rootdir><dir targ_name="stale"/></rootdir></psproject>')
            files = ['eboot.bin', 'sce_sys/param.sfo', 'assets/fonts/NotoSans.ttf',
                     'gecko/modules/submodule/helper.sys.mjs']
            PACKAGE.complete_gp4(path, files)
            root = ET.parse(path).getroot()
            self.assertEqual([node.get('targ_path') for node in root.find('files')], files)
            self.assertEqual(root.find('files').get('img_no'), '0')
            self.assertIsNotNone(root.find('./rootdir/dir[@targ_name="gecko"]/dir[@targ_name="modules"]/dir[@targ_name="submodule"]'))
            self.assertIsNotNone(root.find('./rootdir/dir[@targ_name="assets"]/dir[@targ_name="fonts"]'))
            self.assertIsNone(root.find('./rootdir/dir[@targ_name="stale"]'))
            for unsafe in ('../escape', '/absolute'):
                with self.assertRaises(ValueError): PACKAGE.complete_gp4(path, [unsafe])

    def test_gre_resources_are_copied_without_desktop_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            target = Path(directory) / 'stage'
            (source / 'modules').mkdir(parents=True)
            (source / 'components').mkdir()
            (source / 'greprefs.js').write_text('pref("javascript.enabled", true);\n')
            (source / 'modules/example.sys.mjs').write_text('export const value = 42;')
            (source / 'components/example.manifest').write_text('component example\n')
            files = PACKAGE.stage_resources(source, target)
            self.assertEqual(len(files), 4)
            self.assertEqual((target / 'greprefs.js').read_bytes(), (source / 'greprefs.js').read_bytes())
            self.assertEqual((target / 'modules/example.sys.mjs').read_text(), 'export const value = 42;')
            self.assertIn('manifest components/example.manifest', (target / 'chrome.manifest').read_text())
            (source / 'modules/unexpected.so').write_bytes(b'ELF')
            with self.assertRaises(ValueError): PACKAGE.stage_resources(source, target)

    def test_packaging_rejects_missing_empty_or_oversized_generated_greprefs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            target = Path(directory) / 'stage'
            source.mkdir()
            with self.assertRaises(ValueError): PACKAGE.stage_resources(source, target)
            prefs = source / 'greprefs.js'
            prefs.write_bytes(b'')
            with self.assertRaises(ValueError): PACKAGE.stage_resources(source, target)
            with prefs.open('wb') as output: output.truncate(2 * 1024 * 1024 + 1)
            with self.assertRaises(ValueError): PACKAGE.stage_resources(source, target)
            verifier = (ROOT / 'scripts/verify-gecko-package.py').read_text()
            self.assertIn("payload / 'gecko/greprefs.js'", verifier)
            self.assertIn('digest(generated_prefs) != digest(extracted_prefs)', verifier)

    def test_default_pref_gate_and_native_event_sampling_preserve_real_status(self):
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('prefs.getBoolPref("javascript.enabled", false)', launcher)
        self.assertIn('if (!pageJavaScriptEnabled) throw new Error', launcher)
        self.assertNotIn('setBoolPref("javascript.enabled", true)', launcher)
        shell = (ROOT / 'gecko/widget/orbis/nsAppShell.cpp').read_text()
        self.assertIn('GetOrbisEventDiagnostics()', shell)
        self.assertIn('mozilla::widget::sEventStage = 2', shell)
        self.assertIn('lock.Wait()', shell)
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('clock_gettime(CLOCK_MONOTONIC, &mono)', native)
        self.assertIn('orbisfox::firmware_clock_gettime(4, &alternate)', native)
        self.assertIn('SDK monotonic1 now translates to native4', native)
        self.assertIn('clocksReady = nsprReady && probe_gecko_clocks()', native)

    def test_sfo_parser_preserves_type_bytes_and_rejects_invalid_lengths(self):
        data = (struct.pack('<4sIIII', b'\x00PSF', 0x101, 36, 48, 1) +
                struct.pack('<HHIII', 0, 0x204, 9, 128, 0) +
                b'TITLE\0' + b'\0' * 6 + b'OrbisFox\0' + b'\0' * 119)
        self.assertEqual(VERIFY.read_sfo(data), {'TITLE': (0x204, b'OrbisFox\0')})
        invalid = bytearray(data)
        struct.pack_into('<I', invalid, 24, 129)
        with self.assertRaises(ValueError): VERIFY.read_sfo(invalid)
        invalid[:4] = b'BAD!'
        with self.assertRaises(ValueError): VERIFY.read_sfo(invalid)

    def test_chrome_shell_has_separate_nonremote_content_and_no_fake_tabs(self):
        import xml.etree.ElementTree as ET
        shell = ET.parse(ROOT / 'gecko/orbisfox/fixtures/browser.xhtml').getroot()
        elements = {node.attrib.get('id'): node for node in shell.iter() if 'id' in node.attrib}
        content = elements['content']
        self.assertEqual(content.tag, '{http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul}browser')
        self.assertEqual(content.attrib['type'], 'content')
        self.assertNotIn('remote', content.attrib)
        self.assertNotIn('maychangeremoteness', content.attrib)
        self.assertNotIn('disabled', elements['new-tab'].attrib)
        self.assertEqual(sum(node.attrib.get('role') == 'tab' for node in shell.iter()), 3)
        self.assertEqual({node.attrib.get('id') for node in shell.iter() if node.attrib.get('role') == 'tab'}, {'tab', 'settings-general-tab', 'settings-controls-tab'})
        host = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-host.js').read_text()
        self.assertIn('doc.nodePrincipal.isSystemPrincipal!==true', host)
        principal = (ROOT / '.deps/gecko-layout/caps/nsIPrincipal.idl').read_text()
        self.assertIn('readonly attribute boolean isSystemPrincipal;', principal)
        self.assertIn('ssm.createNullPrincipal({})', host)
        self.assertIn('web.DOMWindow!==e.contentWindow', host)
        self.assertIn('documentID(document)!==tab.beforeLoad', host)
        self.assertIn('documentIDs=new WeakMap()', host)
        self.assertNotIn('tab.beforeLoad=tab.nav.document', host)
        self.assertIn('host.requestExit()', host)
        self.assertIn('e.hasAttribute("remote")', host)
        ui = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-ui.js').read_text()
        self.assertIn('document.addEventListener("DOMContentLoaded",initializeOrbisFoxShell,{once:true})', ui)
        for name in ('back', 'forward', 'reload', 'home', 'bookmark-button', 'menu-button', 'new-tab'):
            self.assertIsNotNone(elements[name].find('{http://www.w3.org/2000/svg}svg'))
        self.assertNotIn('$("reload").textContent', ui)
        self.assertNotIn('$("tab-dot").textContent', ui)
        self.assertNotIn('addCertificateOverride', host)

    def test_jit_memory_is_owned_wx_gated_with_interpreter_fallback(self):
        source = (ROOT / 'include/orbisfox/jit_memory_probe.h').read_text()
        self.assertIn('read|execute', source)
        self.assertIn('read|write,&rw', source)
        self.assertIn('backend.close', source)
        self.assertIn('backend.unmap', source)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('prepare_native_jit_memory()', main)
        self.assertIn('JS::DisableJitBackend()', main)
        self.assertLess(main.index('JS::DisableJitBackend()'), main.index('bootstrap->XRE_XPCShellMain'))
        build = (ROOT / 'scripts/configure-gecko-layout.py').read_text()
        self.assertNotIn('--disable-jit', build)
        native = (ROOT / 'gecko/orbisfox/OrbisExecutableMemory.cpp').read_text()
        self.assertIn('writeStub(42)', native)
        self.assertIn('writeStub(43)', native)
        self.assertIn('protection!=0&&protection!=3&&protection!=5', native)
        self.assertIn('backend.close', native)
        self.assertIn('backend.unmap', native)

    def test_skia_sync_is_real_linked_gate_with_deadline_and_error_ownership(self):
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('cxxGuardsReady && probe_gecko_skia_sync()', native)
        self.assertIn('skiaSyncReady && probe_native_allocator()', native)
        probe = (ROOT / 'gecko/orbisfox/native/skia_sync_probe.cpp').read_text()
        self.assertIn('SkAutoMutexExclusive lock(state.mutex)', probe)
        self.assertIn('OrbisSkiaSemaphore::sleeps.load()', probe)
        self.assertIn('20000000', probe)
        self.assertIn('if(rc!=0)', probe)
        self.assertIn('abort();', probe)
        self.assertIn('optional /data/orbisfox/probe-sdk-semaphore', probe)
        build = (ROOT / 'scripts/build-gecko-app.py').read_text()
        self.assertIn('skia_sync_probe.cpp', build)
        self.assertIn('test-skia-semaphore.py', (ROOT / 'Makefile').read_text())

    def test_window_provider_native_chain_and_bounded_js_routing(self):
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        source = (ROOT / 'gecko/orbisfox/window-provider.inc').read_text()
        host = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-host.js').read_text()
        self.assertIn('NS_INTERFACE_MAP_ENTRY(nsIWindowProvider)', patch)
        self.assertIn('NS_DECL_NSIWINDOWPROVIDER', patch)
        self.assertIn('public nsIWindowProvider', patch)
        self.assertIn('GetBrowserDOMWindow()', source)
        self.assertIn('NodePrincipal()->IsSystemPrincipal()', source)
        self.assertIn('chrome://orbisfox/content/browser.xhtml', source)
        self.assertIn('GetUseRemoteTabs(&remoteTabs)', source)
        self.assertIn('OPEN_NO_REFERRER', source)
        self.assertIn('NS_IF_RELEASE(*aReturn)', source)
        self.assertIn('return NS_ERROR_ABORT', source)
        self.assertNotIn('LoadURI(', source)
        self.assertIn('where===locations.OPEN_NEWTAB_BACKGROUND', host)
        self.assertIn('Finish editing before opening a popup', host)
        self.assertIn('test-orbis-window-provider.py', (ROOT / 'Makefile').read_text())

    def test_skia_glyph_invariant_failures_not_silent_filtering(self):
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('Orbis glyph lookup: digest-index=', patch)
        self.assertIn('Orbis glyph consume: null accepted-slot=', patch)
        self.assertIn('Orbis glyph prepare: source=', patch)
        self.assertIn('glyph = this->glyph(*digestPtr)', patch)
        self.assertIn('test-skia-glyph-invariants.py', (ROOT / 'Makefile').read_text())
        source = (ROOT / 'gecko/orbisfox/SkiaSemaphore.h').read_text()
        self.assertIn('while (count_ == 0)', source)
        self.assertIn('check(pthread_cond_wait', source)
        self.assertIn('SK_ABORT', source)

    def test_stdio_entry_guards_cannot_be_skipped_by_single_threaded_FILE_flag(self):
        source = (ROOT / 'src/ps4/native_stdio.cpp').read_text()
        self.assertIn('__wrap_fprintf', source)
        self.assertIn('WRAPPED(int,vfprintf', source)
        self.assertIn('WRAPPED(int,fflush', source)
        self.assertIn('LockedStream lock(stream)', source)
        self.assertNotIn('__libc.threaded =', source)
        build = (ROOT / 'scripts/build-gecko-app.py').read_text()
        self.assertIn('--wrap=', build)
        self.assertIn('stdio_public_entries_wrapped_independently_of_sdk_lock_skip', build)
        probe = (ROOT / 'gecko/orbisfox/native/stdio_probe.cpp').read_text()
        self.assertIn('entryDelta>=4096', probe)

    def test_native_stdio_locking_avoids_sdk_musl_tcb_layout_and_keeps_logging(self):
        source = (ROOT / 'src/ps4/native_stdio.cpp').read_text()
        self.assertIn('#ifdef ORBISFOX_FULL_GECKO', source)
        self.assertIn('PTHREAD_MUTEX_RECURSIVE', source)
        self.assertIn('pthread_mutex_lock(&mutex)', source)
        self.assertIn('pthread_mutex_trylock(&mutex)', source)
        self.assertNotIn('%fs:', source)
        self.assertNotIn('pthread_once(', source)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('allocatorReady && probe_native_stdio_locks()', main)
        self.assertIn('nsSocketTransport:5', main)
        self.assertNotIn('rotate:1', main)  # Runtime LogModule::SetLogFile forbids rotation.
        self.assertIn('unsetenv("MOZ_LOG_FILE")', main)
        self.assertIn('native_diagnostics_enabled()', main)

    def test_profile_notification_and_real_quota_storage_probe_precede_web_and_shutdown(self):
        source = (ROOT / 'gecko/orbisfox/fixtures/profile-lifecycle.js').read_text()
        self.assertIn('"profile-do-change"', source)
        self.assertIn('"profile-before-change-qm"', source)
        self.assertIn('wantGlobalProperties:["indexedDB"]', source)
        self.assertIn('factory.open("orbisfox-durable-probe",1)', source)
        self.assertNotIn('setBoolPref', source)
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertLess(launcher.index('directories.registerProvider(provider)'), launcher.index('startOrbisFoxProfile('))
        self.assertLess(launcher.index('profileLifecycle.close()'), launcher.index('directories.unregisterProvider(provider)'))
        subprocess.run(['node', 'tests/profile_lifecycle_test.js'], cwd=ROOT, check=True)

    def test_native_allocator_wraps_real_sdk_heap_without_private_flag_hacks(self):
        source = (ROOT / 'src/ps4/native_allocator.cpp').read_text()
        self.assertIn('PTHREAD_MUTEX_RECURSIVE', source)
        self.assertIn('HeapLock lock', source)
        self.assertIn('__real_free(pointer)', source)
        self.assertNotIn('printf(', source)
        self.assertNotIn('__libc.', source)
        build = (ROOT / 'scripts/build-gecko-app.py').read_text()
        self.assertIn('genuine_sdk_allocator_entries_native_mutex_verified', build)
        subprocess.run(['python3', 'scripts/test-native-allocator.py'], cwd=ROOT, check=True)

    def test_heap_diagnostics_optin_real_backing_no_silent_claim_of_fix(self):
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('/data/orbisfox/heap-debug', native)
        self.assertIn('sharedMemoryReady && heapDiagnosticsReady', native)
        self.assertIn('not a production fix', native)
        source = (ROOT / 'src/ps4/native_allocator.cpp').read_text()
        self.assertIn('diagnostics.enabled()&&depth==1', source)
        self.assertIn('diagnostics.enable({__real_malloc,__real_free,record,fault})', source)
        self.assertIn('uint64_t header[8]', source)
        self.assertNotIn('printf(', source)
        header = (ROOT / 'include/orbisfox/heap_diagnostics.h').read_text()
        self.assertIn('backend_.free(r.raw)', header)
        self.assertIn('write after free in quarantine', header)
        self.assertNotIn('event(10,nullptr,nullptr,size,caller);errno=ENOMEM;return nullptr;', header)
        self.assertIn('void* raw=make(size);event(11,nullptr,raw,size,caller);return raw;', header)
        self.assertIn('while(active_+count_>=admissionLimit&&count_)', header)
        self.assertIn('HeapDiagnostics<262144,512,8*1024*1024>', source)
        self.assertIn('uint64_t(diagnostics.trackingLimit())<<32', source)
        self.assertIn('saturationRequests,untrackedReturns', source)
        self.assertNotIn('Tombstone', header)
        self.assertIn('heap_diagnostics_test.cpp', (ROOT / 'Makefile').read_text())
        package = (ROOT / 'scripts/package-gecko.py').read_text()
        self.assertIn("'general_internet_navigation_enabled_after_runtime_safety_gates': True", package)
        self.assertIn("'public_browsing_requires_lan_fixture_server': False", package)
        self.assertIn("'heap_diagnostics_enabled_by_default': False", package)
        self.assertIn("'website_crashes_claimed_fixed': False", package)

    def test_native_allocator_runtime_probe_retains_calloc_and_reports_real_worker_failures(self):
        build = (ROOT / 'scripts/build-gecko-app.py').read_text()
        self.assertIn("['-fno-builtin', '-c'", build)
        self.assertIn("{'malloc', 'calloc', 'realloc', 'free', 'posix_memalign'} <= allocator_probe_calls", build)
        source = (ROOT / 'gecko/orbisfox/native/allocator_probe.cpp').read_text()
        self.assertIn('state.completed[i]==512', source)
        self.assertIn('error-mask=0x%x', source)
        self.assertIn('calls>=8*512*5', source)
        self.assertIn('probe_heap_boundary(malloc,calloc,realloc,free', source)
        harness = (ROOT / 'tests/native_allocator_test.cpp').read_text()
        self.assertIn('orbisfox::probe_heap_boundary(__wrap_malloc,__wrap_calloc', harness)
        self.assertIn('assert(bool(csize&1)==(sample==0))', harness)
        header = (ROOT / 'include/orbisfox/heap_reclaim_probe.h').read_text()
        self.assertIn('sizes[]={229360,229361,229376}', header)

    def test_sdk_heap_bin_audit_is_read_only_and_bounds_checked(self):
        source = (ROOT / 'src/ps4/native_allocator.cpp').read_text()
        self.assertIn('extern "C" unsigned char orbisfox_sdk_malloc_state[]', source)
        self.assertNotIn('const unsigned char orbisfox_sdk_malloc_state[]', source)
        self.assertIn('Failure check(const unsigned char* state) const', (ROOT / 'include/orbisfox/heap_bin_audit.h').read_text())
        self.assertIn('if(auditAllBoundaries() || reallocContext.active)auditBins(operation,site,"before")', source)
        self.assertIn('if(auditAllBoundaries() || reallocContext.active)auditBins(operation,site,"after")', source)
        self.assertIn('if(allApiAudit)return true;', source)
        self.assertIn('return mesaBoundaryAudit && orbisfox::native_diagnostics_enabled();', source)
        self.assertIn('lastGoodApi=currentApi', source)
        self.assertIn('lastGoodPhase=phase', source)
        self.assertIn('auditBins("SDK-copy",lock.site,"copy-after")', source)
        self.assertIn('auditBins("SDK-discard",lock.site,"discard-after")', source)
        self.assertIn('if(!reclaimVerified){errno=ENOTSUP;return -1;}', source)
        self.assertIn('reallocContext.output=reinterpret_cast<uintptr_t>(result)', source)
        probe = (ROOT / 'gecko/orbisfox/native/allocator_probe.cpp').read_text()
        self.assertIn('configure_native_allocator_reclaim(advice.safe())', probe)
        self.assertIn('configure_native_allocator_bin_audit(false)', probe)
        self.assertIn('heap_advice_probe_test.cpp', (ROOT / 'Makefile').read_text())
        self.assertIn('binAudit.addArena(p,*size)', source)
        self.assertIn('__wrap___expand_heap', source)
        self.assertIn('ORBISFOX SDK BIN AUDIT:', source)
        header = (ROOT / 'include/orbisfox/heap_bin_audit.h').read_text()
        self.assertIn('if(!contains(p,32))', header)
        self.assertIn('if(!contains(neighbor,32))', header)
        self.assertIn('!contains(p+size,16)', header)
        helper = (ROOT / 'scripts/sdk-heap-audit-object.py').read_text()
        self.assertIn('sections(before) != sections(after)', helper)
        self.assertIn('Expected local SDK malloc state symbol mal', helper)
        build = (ROOT / 'scripts/build-gecko-app.py').read_text()
        self.assertIn("allocator_bin_audit_hardware_verified'] = False", build)
        self.assertIn("['__expand_heap','__madvise','__munmap','__mmap']", build)
        self.assertIn('unmap-before', source)
        self.assertIn('unmap-after', source)
        self.assertIn('SDK_mapped_free_unmap_read_only_leaf_audit_verified', build)

    def test_native_allocator_reclaim_gate_is_bounded_and_not_synthetic_corruption_fix(self):
        source = (ROOT / 'gecko/orbisfox/native/allocator_probe.cpp').read_text()
        header = (ROOT / 'include/orbisfox/heap_reclaim_probe.h').read_text()
        self.assertIn('probe_heap_reclaim(malloc,calloc,realloc,free', source)
        self.assertIn('sceKernelGetProcessTime()+30000000', source)
        self.assertIn('reclaimCalls>=reclaim.calls', source)
        self.assertIn('if(joined!=0)', source)
        self.assertIn('stopWatchdog();return okay', source)
        self.assertLess(source.index('probe_heap_reclaim('), source.index('State state;Worker workers'))
        self.assertIn('blocks[24]', header)
        self.assertIn('b-a==65568', header)
        self.assertIn('adjacentGroups>0', header)
        self.assertIn('heap_reclaim_probe_test.cpp', (ROOT / 'Makefile').read_text())
        script = (ROOT / 'scripts/test-sdk-allocator.py').read_text()
        self.assertIn('reclaimAdviceCalls==0:reclaimAdviceCalls>0', script)
        self.assertIn('SDK_TEST_RECLAIM_UNSUPPORTED', script)
        self.assertIn('size%16384==0', script)

    def test_installed_sdk_allocator_object_harness_uses_actual_archive_and_explicit_shims(self):
        script = (ROOT / 'scripts/test-sdk-allocator.py').read_text()
        self.assertIn("'llvm-ar','p'", script)
        self.assertIn("'malloc.lo'", script)
        self.assertIn("'SDK_objects_not_ASan_instrumented':True", script)
        self.assertIn("'model_private_field_writes_not_native':True", script)
        self.assertIn('test-sdk-allocator.py', (ROOT / 'Makefile').read_text())
        self.assertIn("'-Wl,--wrap=sdk_'+name", script)
        self.assertIn('SDK_BRIDGE(void*,realloc', script)
        self.assertIn('SDK_TEST_HEAP_GUARDS', script)
        self.assertIn('SDK_TEST_NESTED_LINK', script)

    def test_game_heap_backing_does_not_replace_gc_or_file_mapping(self):
        source=(ROOT/'src/ps4/native_allocator.cpp').read_text()
        self.assertIn('sdk_direct_heap_ownership(address,bytes)',source)
        self.assertIn('__wrap___mmap',source)
        backing=(ROOT/'src/ps4/sdk_heap_memory.cpp').read_text()
        self.assertIn('memset(memory,0,bytes)',backing)
        self.assertIn('constexpr int32_t cpuWriteBackMemoryType=0;',backing)
        self.assertIn('bytes,page,cpuWriteBackMemoryType,&offset',backing)
        self.assertIn('sceKernelReleaseDirectMemory',backing)
        self.assertIn('ownershipFailure()',backing)
        build=(ROOT/'scripts/build-gecko-app.py').read_text()
        self.assertIn('ORBISFOX_NATIVE_DIRECT_HEAP',build)
        host=(ROOT/'gecko/orbisfox/fixtures/browser-shell-host.js').read_text()
        self.assertIn('service.savePrefFile(file)',host)
        self.assertNotIn('service.savePrefFile(null)',host)
        ui=(ROOT/'gecko/orbisfox/fixtures/browser-shell-ui.js').read_text()
        self.assertNotIn('keyValues',ui)
        self.assertNotIn('nativePreferred',ui)
        html=(ROOT/'gecko/orbisfox/fixtures/browser.xhtml').read_text()
        for removed in ['id="keyboard"','quick-fmhy','quick-wikipedia','home-ready','bookmark-empty']:
            self.assertNotIn(removed,html)
        producer=(ROOT/'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('mOrbisPrimaryDown ? MouseButtonsFlag::ePrimaryFlag : MouseButtonsFlag::eNoButtons',producer)

    def test_common_dialog_policy_follows_system_not_implicit_circle_default(self):
        self.assertEqual(PACKAGE.COMMON_DIALOG_ATTRIBUTE_SYSTEM, 0x20)
        package = (ROOT / 'scripts/package-gecko.py').read_text()
        self.assertIn("'ATTRIBUTE': ('Integer', 4, str(COMMON_DIALOG_ATTRIBUTE_SYSTEM))", package)
        verification = (ROOT / 'scripts/verify-gecko-package.py').read_text()
        self.assertIn("actual_sfo.get('ATTRIBUTE') != (0x404, struct.pack('<I', 0x20))", verification)
        ui = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-ui.js').read_text()
        self.assertNotIn('nativePreferred&&actions?.keyboardConfirm?.()!==2', ui)

    def test_native_pixel_conversion_skips_full_frame_clear_and_measures_real_phases(self):
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('if (w != width || h != height) fill_rect', native)
        self.assertIn('blit_bgra_opaque(target, bgra, w, h, stride)', native)
        self.assertIn('state.nativeUi.publishFrame()', native)
        worker = (ROOT / 'src/native_ui_loop.cpp').read_text()
        self.assertNotIn('OrbisFoxHost', worker)
        self.assertNotIn('SynthesizeNative', worker)
        self.assertIn('if(!paused&&', worker)
        self.assertIn('pthread_join(thread_,nullptr)', worker)
        self.assertIn('pending_=false;readSerial_=serial_', worker)
        self.assertIn('conversion-mean-us=', native)
        self.assertIn('scanout-wait-mean-us=', native)
        self.assertIn('/data/orbisfox/verbose-gecko-log', native)
        self.assertIn('nsSocketTransport:5', native) # Detailed diagnostic lane retained.

    def test_real_pointer_publishes_release_before_reentrant_click_dispatch(self):
        subprocess.run(['python3', 'scripts/test-pointer-reentrancy.py'], cwd=ROOT, check=True)

    def test_real_blob_font_platform_chooses_supported_freetype(self):
        subprocess.run(['python3', 'scripts/test-orbis-blob-font.py'], cwd=ROOT, check=True)

    def test_custom_keyboard_chrome_assets_and_editor_boundary(self):
        html = ET.parse(ROOT / 'gecko/orbisfox/fixtures/browser.xhtml')
        elements = {element.get('id'): element for element in html.iter() if element.get('id')}
        self.assertEqual(elements['keyboard-panel'].get('role'), 'dialog')
        self.assertEqual(elements['keyboard-panel'].get('aria-modal'), 'true')
        self.assertEqual(elements['keyboard-panel'].get('hidden'), 'hidden')
        self.assertEqual(elements['keyboard-password'].get('type'), 'password')
        self.assertEqual(elements['keyboard-draft'].get('maxlength'), '512')
        ui = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-ui.js').read_text()
        host = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-host.js').read_text()
        self.assertNotIn('actions?.openTextKeyboard', ui)
        self.assertIn("name==='forward')keyboardKey('Enter')", ui)
        self.assertIn("keyboard.multiline){keyboardKey('New line')", ui)
        self.assertIn('editor.insertText(insert)', host)
        self.assertIn('editor.deleteSelection(Ci.nsIEditor.eNone,Ci.nsIEditor.eStrip)', host)
        self.assertIn('host.sendEnter()', host)
        self.assertIn('active.nav.document!==target.rootDocument', host)
        self.assertIn('keyboardReleasePending&&host.buttons===0', host)
        self.assertIn("'browser_keyboard_default': 'custom_chrome'", (ROOT / 'scripts/package-gecko.py').read_text())
        interface = (ROOT / 'gecko/widget/orbis/nsIOrbisFoxHost.idl').read_text()
        self.assertIn('void sendEnter();', interface)

    def test_native_ime_modal_release_gate_and_application_presentation_quiescence(self):
        gate = (ROOT / 'include/orbisfox/keyboard_launch.h').read_text()
        self.assertIn('if(++released_<2)return', gate)
        self.assertIn('5000000', gate)
        host = (ROOT / 'gecko/widget/orbis/OrbisFoxHost.cpp').read_text()
        self.assertIn('mIMEQuiesced = true; *aContinue = true; return NS_OK;', host)
        self.assertLess(host.index('mIMEQuiesced = true; *aContinue'), host.index('OrbisCompositorWidget::GetLatestFrame'))

    def test_native_ime_uses_real_system_assignment_and_text_editor_mode(self):
        source = (ROOT / 'src/ps4/native_keyboard.cpp').read_text()
        self.assertIn('sceSystemServiceParamGetInt', source)
        self.assertIn('ORBIS_SYSTEM_SERVICE_PARAM_ID_ENTER_BUTTON_ASSIGN', source)
        self.assertNotIn('ParamSetInt', source)
        self.assertIn('self.addressMode_?ORBIS_TYPE_TYPE_URL:ORBIS_TYPE_DEFAULT', source)
        host = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-host.js').read_text()
        self.assertIn('sendContentCommandEvent("insertText",null,text)', host)
        self.assertIn('target.field.value!==target.draft', host)
        self.assertIn('target.tab!==active', host)
        self.assertNotIn('field.value=text', host)

    def test_native_ime_utf16_module_gate_and_input_quarantine(self):
        source = (ROOT / 'src/ps4/native_keyboard.cpp').read_text()
        self.assertIn('sizeof(char16_t)==2', source)
        self.assertIn('sizeof(OrbisImeDialogSetting)==96', source)
        self.assertIn('ORBIS_SYSMODULE_IME_DIALOG', source)
        self.assertIn('ORBIS_SYSMODULE_INTERNAL_COMMON_DIALOG', source)
        self.assertIn('if(result!=0) return false', source)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('state.keyboard.session.active() || state.keyboardInputQuarantine', main)
        self.assertIn('input.buttons == 0', main)
        self.assertLess(main.index('browser_exit_chord('), main.index('state.keyboard.session.active()'))

    def test_right_stick_scroll_is_separate_trusted_content_wheel_input(self):
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('input.rightStick.x, input.rightStick.y, inputNow', main)
        self.assertIn('const uint64_t inputNow=sceKernelGetProcessTime()', main)
        self.assertIn('state.stickX.update(input.leftStick.x,state.cursorSpeed,timing.elapsed)', main)
        self.assertIn('state.pointerClock.update(inputNow)', main)
        self.assertIn('if(timing.discontinuity){state.touch.reset()', main)
        host = (ROOT / 'gecko/orbisfox/fixtures/browser-shell-host.js').read_text()
        self.assertIn('win.windowUtils.sendWheelEvent(', host)
        self.assertIn('WHEEL_EVENT_ASYNC_ENABLED', host)
        self.assertIn('ui.canScroll()', host)
        self.assertIn('active.nav.document.nodePrincipal.isSystemPrincipal!==false', host)
        self.assertNotIn('scrollBy(', host)

    def test_actual_cxx_guard_native_identity_contention_and_recursion(self):
        subprocess.run(['python3', 'scripts/test-cxx-guards.py'], cwd=ROOT, check=True)
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('clocksReady && probe_gecko_cxx_guards()', native)
        self.assertIn('cxxGuardsReady && probe_gecko_skia_sync()', native)
        self.assertIn('skiaSyncReady && probe_native_allocator()', native)
        self.assertIn('allocatorReady && probe_native_stdio_locks()', native)
        self.assertIn('stdioReady && probe_native_file_locks()', native)

    def test_pinned_initial_frame_remoteness_and_boolean_accessor(self):
        subprocess.run(['python3', 'scripts/test-initial-frame-remoteness.py'], cwd=ROOT, check=True)

    def test_browser_shell_assets_and_regressions_are_packaged(self):
        source = (ROOT / 'scripts/package-gecko.py').read_text()
        for name in ('browser.xhtml', 'browser.css', 'browser-shell-ui.js',
                     'browser-shell-model.js', 'browser-shell-host.js', 'profile-lifecycle.js'):
            self.assertIn(name, source)
        self.assertIn('content orbisfox chrome/orbisfox/content/', source)
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('/data/orbisfox/diagnostic-only', launcher)
        self.assertIn('runOrbisFoxBrowserShell', launcher)
        for test in ('browser_shell_test.js', 'browser_shell_ui_test.js', 'browser_shell_host_test.js', 'browser_favicon_test.js'):
            subprocess.run(['node', str(ROOT / 'tests' / test)], cwd=ROOT, check=True)

    def test_independent_browser_activation_and_partial_fixture_reporting(self):
        bridge = (ROOT / 'gecko/orbisfox/create-visible-browser.inc').read_text()
        self.assertIn('SetExplicitActive(mozilla::dom::ExplicitActiveStatus::Active)', bridge)
        self.assertIn('NS_ENSURE_TRUE(context->IsActive()', bridge)
        self.assertLess(bridge.index('nsWebBrowser::Create'), bridge.index('SetExplicitActive'))
        fixture = (ROOT / 'gecko/orbisfox/fixtures/offline.html').read_text()
        self.assertIn('window.orbisfoxProgress', fixture)
        self.assertIn('update("waiting for animation frame")', fixture)
        self.assertIn('await new Promise(resolve => requestAnimationFrame(resolve))', fixture)
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('webProgress.addProgressListener', launcher)
        self.assertIn('webProgress.removeProgressListener', launcher)
        self.assertIn('browser.browsingContext.isActive', launcher)
        self.assertIn('softwareWebRender: host.softwareWebRender', launcher)

    def test_original_file_channel_navigation_and_supported_e10s_switch(self):
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('readTrustedFixture(Cc, Ci, fixtureFile)', launcher)
        self.assertIn('let uri = fileURI;', launcher)
        self.assertNotIn('data:text/html;charset=utf-8,', launcher)
        self.assertIn('fileProbeChannel.asyncOpen', launcher)
        self.assertIn('fileProbeChannel.cancel', launcher)
        self.assertIn('no completion assumed', launcher)
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('metadata worker entered', patch)
        self.assertIn('GetFileSize returned', patch)
        self.assertIn('emitted.compareExchange(count, count + 1)', patch)
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('nsStreamPump:5,nsThreadPool:5,DocumentChannel:5,nsRedirect:5', native)
        self.assertIn('copy_native_run_log_path(out,capacity,"gecko-load.log")', native)
        self.assertIn('setenv("MOZ_FORCE_DISABLE_E10S", "1", 1)', native)
        self.assertLess(native.index('setenv("MOZ_FORCE_DISABLE_E10S"'), native.index('XRE_XPCShellMain(7'))
        bridge = (ROOT / 'gecko/orbisfox/create-visible-browser.inc').read_text()
        self.assertIn('mozilla::BrowserTabsRemoteAutostart()', bridge)
        self.assertIn('NS_ENSURE_FALSE(globalRemote || XRE_IsE10sParentProcess()', bridge)
        self.assertLess(bridge.index('NS_ENSURE_FALSE(globalRemote'), bridge.index('nsWebBrowser::Create'))

    def test_e10s_policy_regression_test_preserves_supported_engine_policy(self):
        driver = (ROOT / 'scripts/test-e10s-startup-mode.py').read_text()
        test = (ROOT / 'tests/e10s_startup_mode_test.cpp').read_text()
        self.assertIn("'bool BrowserTabsRemoteAutostart()'", driver)
        self.assertIn('for official in (False, True)', driver)
        self.assertIn('MOZILLA_OFFICIAL', driver)
        self.assertIn('cached true', test)
        self.assertIn('child process stays remote', test)
        self.assertIn('kE10sForceDisabled', test)
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertNotIn('security_allow_unsafe_parent_loads', patch)
        self.assertNotIn('NS_ERROR_DOCUMENT_LOAD_LISTENER_NO_PARENT_CHANNEL', patch)

    def test_standalone_context_policy_does_not_replace_visible_native_widget(self):
        bridge = (ROOT / 'gecko/orbisfox/create-visible-browser.inc').read_text()
        self.assertIn('aChrome ? BrowsingContext::Type::Chrome : BrowsingContext::Type::Content', bridge)
        self.assertIn('BrowsingContext::CreateIndependent(contextType, true)', bridge)
        self.assertIn('NS_ENSURE_TRUE(context->Windowless()', bridge)
        self.assertIn('nsIWidget::CreateTopLevelWindow()', bridge)
        self.assertIn('nativeWidget->Show(true)', bridge)
        self.assertIn('NS_ENSURE_TRUE(nativeWidget->IsVisible()', bridge)
        self.assertNotIn('PuppetWidget::Create', bridge)
        test = (ROOT / 'scripts/test-standalone-process-switch.py').read_text()
        self.assertIn('static bool ContextCanProcessSwitch(', test)
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertNotIn('ContextCanProcessSwitch', patch)
        self.assertNotIn('CanLoadInParentProcess', patch)

    def test_post_render_stall_diagnostics_do_not_run_engine_or_input_off_thread(self):
        native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        start = native.index('void* monitor(void* opaque)')
        end = native.index('int clamp(', start)
        monitor = native[start:end]
        self.assertNotIn('sample < 120', monitor)
        self.assertIn('monitorStop.load()', monitor)
        self.assertIn('NativeRunLogPath("gecko-heartbeat.log")', monitor)
        self.assertNotIn('controller.poll', monitor)
        self.assertNotIn('request_system_exit', monitor)
        self.assertIn('pthread_join(monitorThread', native)
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('if (ticks <= 16)', launcher)
        self.assertIn('Gecko timer callback returned:', launcher)
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('Orbis DOM script:', patch)
        self.assertIn('ExecuteCompiledScript returned', patch)

    def test_load_and_event_loop_diagnostic_checkpoint_order_and_bounds(self):
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertLess(launcher.index('loadURI call entered'), launcher.index('browser.loadURI'))
        self.assertLess(launcher.index('browser.loadURI'), launcher.index('loadURI call returned'))
        self.assertLess(launcher.index('loadURI call returned'), launcher.index('timer initialization entered'))
        self.assertIn('if (ticks === 1)', launcher)
        self.assertIn('first frame pump returned', launcher)
        host = (ROOT / 'gecko/widget/orbis/OrbisFoxHost.cpp').read_text()
        self.assertIn('const bool trace = mPumpTraces < 8', host)
        self.assertIn('if (trace) ++mPumpTraces', host)
        self.assertIn('surface mapping entered', host)
        self.assertIn('native presentation returned', host)
        self.assertIn('frame mailbox returned no surface', host)
        shell = (ROOT / 'gecko/widget/orbis/nsAppShell.cpp').read_text()
        self.assertIn('traces < 8', shell)
        self.assertIn('while (!mPending)', shell)
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('if (emitted < 64)', patch)
        self.assertIn('URI loader OpenURI returned', patch)

    def test_adapter_telemetry_requires_service_and_failure_logging_has_fallback(self):
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('Keep real screen/headless metrics; no invented adapter identity', patch)
        self.assertIn('Graphics failure (no GfxInfo service)', patch)
        path = ROOT / '.deps/gecko-layout/gfx/thebes/gfxPlatform.cpp'
        if path.exists():
            text = path.read_text()
            start = text.index('void gfxPlatform::ReportTelemetry()')
            body = text[start:text.index('static bool IsFeatureSupported', start)]
            self.assertLess(body.index('if (!gfxInfo)'), body.index('gfxInfo->GetAdapterDescription'))
            self.assertGreater(body.index('if (!gfxInfo)'), body.index('gfx_display::primary_width'))

    def test_optional_font_archive_reader_checked_before_metadata_or_enumeration(self):
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('if (!reader)', patch)
        self.assertIn('!jarFile || NS_FAILED(jarFile->GetLastModifiedTime', patch)
        source = ROOT / '.deps/gecko-layout/gfx/thebes/gfxFT2FontList.cpp'
        if source.exists():
            text = source.read_text()
            start = text.index('void gfxFT2FontList::FindFontsInOmnijar(')
            body = text[start:text.index('using Device = ', start)]
            self.assertEqual(body.count('RefPtr<nsZipArchive> reader'), 1)
            self.assertLess(body.index('if (!reader)'), body.index('StartupCache::GetSingleton'))
            self.assertLess(body.index('if (!reader)'), body.index('reader->FindInit'))

    def test_orbis_font_visibility_does_not_query_android_device(self):
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('kBaseFonts_Orbis', patch)
        self.assertIn('? FontVisibility::Base : FontVisibility::User', patch)
        self.assertIn('gfxVars::SetUseWebRenderProgramBinaryDisk(false)', patch)
        source = ROOT / '.deps/gecko-layout/gfx/thebes/gfxFT2FontList.cpp'
        if source.exists():
            text = source.read_text()
            for name in ('GetVisibilityForFamily(', 'GetFilteredPlatformFontLists()'):
                start = text.index('gfxFT2FontList::' + name)
                branch = text[start:text.index('#else', start)]
                self.assertIn('#ifdef MOZ_WIDGET_ORBIS', branch)
                self.assertIn('kBaseFonts_Orbis', branch)
                self.assertNotIn('gfxInfo', branch)

    def test_optional_gfx_queries_and_directory_provider_decline(self):
        helper = (ROOT / 'gecko/widget/orbis/OrbisGfxInfo.h').read_text()
        self.assertIn('if (!aInfo) return NS_ERROR_NOT_AVAILABLE', helper)
        self.assertIn('*aStatus = nsIGfxInfo::FEATURE_STATUS_UNKNOWN', helper)
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('ORBISFOX_GFX_FEATURE_STATUS', patch)
        self.assertIn('gfxVars::SetAllowWebGL(false)', patch)
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('persistent.value = false;', launcher)
        self.assertIn('return null;', launcher)
        self.assertNotIn('throw Components.Exception("Unsupported directory"', launcher)
        platform = ROOT / '.deps/gecko-layout/gfx/thebes/gfxPlatform.cpp'
        if platform.exists():
            self.assertNotIn('gfxInfo->GetFeatureStatus(', platform.read_text())

    def test_visible_content_context_does_not_mutate_flags_after_attachment(self):
        browser = (ROOT / 'gecko/orbisfox/create-visible-browser.inc').read_text()
        self.assertIn('BrowsingContext::CreateIndependent', browser)
        self.assertNotIn('context->SetRemoteTabs(', browser)
        self.assertNotIn('context->SetRemoteSubframes(', browser)
        self.assertIn('context->GetUseRemoteTabs(&remoteTabs)', browser)
        self.assertIn('context->GetUseRemoteSubframes(&remoteSubframes)', browser)
        check = browser.index('NS_ENSURE_FALSE(remoteTabs || remoteSubframes')
        self.assertLess(browser.index('BrowsingContext::CreateIndependent'), check)
        self.assertLess(check, browser.index('nsWebBrowser::Create('))
        self.assertIn('aChrome ? BrowsingContext::Type::Chrome : BrowsingContext::Type::Content', browser)
        self.assertIn('nativeWidget->Show(true)', browser)

    def test_native_utf8_filename_conversion_and_early_prefs(self):
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('CopyOrbisNativeUtf8', patch)
        self.assertIn('mozilla::IsUtf8', patch)
        self.assertIn('JSMSG_CANT_CONVERT_TO_NARROW', patch)
        defaults = (ROOT / 'gecko/orbisfox/fixtures/default-prefs.js').read_text()
        self.assertIn('pref("network.process.enabled", false)', defaults)
        self.assertIn('pref("layers.gpu-process.enabled", false)', defaults)
        package = (ROOT / 'scripts/package-gecko.py').read_text()
        self.assertIn('gecko/defaults/pref/orbisfox.js', package)
        test = (ROOT / 'scripts/test-orbis-character-encoding.py').read_text()
        self.assertIn('CharacterEncoding.cpp', test)
        self.assertIn('-D__ORBIS__', test)
        self.assertIn('sdk-wcslen.o', test)
        self.assertNotIn('--allow-multiple-definition', test)

    def test_orbis_shared_memory_avoids_sdk_fallocate_stub(self):
        patch = (ROOT / 'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('#  undef HAVE_POSIX_FALLOCATE', patch)
        probe = (ROOT / 'gecko/orbisfox/native/shared_memory_probe.cpp').read_text()
        for operation in ('CreateFreezable(bytes)', '.Map()', '.Freeze()', '.Clone()',
                          'readonly.DataAs<uint8_t>()', 'second.DataAs<uint8_t>()'):
            self.assertIn(operation, probe)
        self.assertIn('size_t(16384)', probe)
        self.assertIn('size_t(524288)', probe)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('clocksReady = nsprReady && probe_gecko_clocks()', main)
        self.assertIn('clocksReady && probe_gecko_cxx_guards()', main)
        self.assertIn('stdioReady && probe_native_file_locks()', main)
        self.assertIn('fileLocksReady && probe_gecko_shared_memory()', main)
        self.assertIn('if (sharedMemoryReady && heapDiagnosticsReady)', main)
        source = ROOT / '.deps/gecko-layout/ipc/glue/SharedMemoryPlatform_posix.cpp'
        if source.exists():
            self.assertIn('#  undef HAVE_POSIX_FALLOCATE', source.read_text())
            self.assertIn('ftruncate(fd.get()', source.read_text())

    def test_native_net_module_gate_precedes_necko_requests_without_guessed_success(self):
        source = (ROOT / 'src/ps4/native_network.cpp').read_text()
        self.assertTrue(source.startswith('#ifdef ORBISFOX_FULL_GECKO'))
        self.assertIn('ORBIS_SYSMODULE_INTERNAL_NET', source)
        self.assertIn('module.bind("sceNetGetDnsInfo", dns)', source)
        self.assertIn('result == 0', source)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertLess(main.index('prepare_native_network()'), main.index('bootstrap->XRE_XPCShellMain'))
        probe = (ROOT / 'gecko/orbisfox/fixtures/network-probe.js').read_text()
        self.assertLess(probe.index('host.nativeNetworkReady !== true'), probe.index('io.offline = false'))

    def test_https_validation_requires_real_tls_evidence_and_exact_negative_errors(self):
        subprocess.run(['node', 'tests/https_probe_test.js'], cwd=ROOT, check=True)
        source = (ROOT / 'gecko/orbisfox/fixtures/https-probe.js').read_text()
        self.assertIn('isBuiltCertChainRootBuiltInRoot', source)
        self.assertIn('succeededCertChain.length', source)
        for error in ('SEC_ERROR_EXPIRED_CERTIFICATE', 'SSL_ERROR_BAD_CERT_DOMAIN', 'SEC_ERROR_UNKNOWN_ISSUER'):
            self.assertIn(error, source)
        self.assertNotIn('rememberValidityOverride', source)
        self.assertNotIn('addCertFromBase64', source)
        self.assertIn('redirectionLimit = 0', source)
        startup = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('network.storage.ok && network.http.ok && network.dns.ok', startup)
        self.assertIn('httpsProbes.close()', startup)
        self.assertIn('TRUST_ANCHORS_GetFunctionList', (ROOT / 'scripts/build-gecko-app.py').read_text())

    def test_native_file_lock_boundary_has_no_stable_lane_leak_or_no_lock_bypass(self):
        adapter = (ROOT / 'src/ps4/native_fcntl.cpp').read_text()
        self.assertTrue(adapter.startswith('#ifdef ORBISFOX_FULL_GECKO'))
        self.assertIn('Guarded native', adapter)
        self.assertIn('native.value.sysid != 0', adapter)
        self.assertIn('command == F_GETLK || command == F_SETLK || command == F_SETLKW', adapter)
        self.assertIn('return fcntl(fd, command, argument)', adapter)
        self.assertNotIn('extern "C" int _fcntl(', adapter)
        self.assertNotIn('extern "C" int fcntl(', adapter)
        vfs = (ROOT / 'gecko/orbisfox/native/sqlite_vfs.cpp').read_text()
        self.assertIn('xSetSystemCall(normal, "fcntl", adapter)', vfs)
        self.assertIn('exclusive->xGetSystemCall(exclusive, "fcntl") == adapter', vfs)
        self.assertIn('legacyErrno == EINVAL', adapter)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('probe_native_file_locks()', main)
        self.assertIn('SQLITE_CONFIG_LOG', main)
        self.assertLess(main.index('SQLITE_CONFIG_LOG'), main.index('GetBootstrap()'))
        self.assertIn("'orbisfox_sqlite_fcntl' not in text_symbols", (ROOT / 'scripts/build-gecko-app.py').read_text())

    def test_real_persistent_storage_gate_precedes_network_and_checks_errors(self):
        subprocess.run(['node', 'tests/storage_probe_test.js'], cwd=ROOT, check=True)
        source = (ROOT / 'gecko/orbisfox/fixtures/storage-probe.js').read_text()
        self.assertIn('openUnsharedDatabase(file)', source)
        self.assertIn('BEGIN IMMEDIATE', source)
        self.assertIn('COMMIT', source)
        self.assertIn('ROLLBACK', source)
        self.assertIn('getUTF8String(0)', source)
        self.assertNotIn('openSpecialDatabase', source)
        self.assertNotIn('cookies.sqlite', source)
        network = (ROOT / 'gecko/orbisfox/fixtures/network-probe.js').read_text()
        self.assertLess(network.index('verifyTrustedPersistentStorage('), network.index('io.offline = false'))
        self.assertIn('networking not started', network)
        self.assertIn('assets/storage-probe.js', (ROOT / 'scripts/package-gecko.py').read_text())

    def test_network_probes_keep_validation_and_bound_lifecycle(self):
        subprocess.run(['node', 'tests/network_probe_test.js'], cwd=ROOT, check=True)
        source = (ROOT / 'gecko/orbisfox/fixtures/network-probe.js').read_text()
        self.assertIn('httpChannel.redirectionLimit = 0', source)
        self.assertIn('RESOLVE_DISABLE_TRR', source)
        self.assertIn('RESOLVE_DISABLE_IPV6', source)
        self.assertIn('HTTPS NOT TESTED', source)
        launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('networkProbes.canNavigateLAN()', launcher)
        self.assertIn('window.document !== documentBeforeLoad', launcher)
        self.assertIn('window.document.documentURI === uri.spec', launcher)
        self.assertIn('globalThis.load("/app0/assets/network-probe.js")', launcher)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('state.stickX.update(input.leftStick.x,state.cursorSpeed,timing.elapsed)', main)
        self.assertIn('ORBIS_PAD_BUTTON_SQUARE', main)
        self.assertNotIn('security.enterprise_roots.enabled', source)
        self.assertNotIn('badCert', source)
        self.assertNotIn('setBoolPref', source)
        self.assertIn('assets/network-probe.js', (ROOT / 'scripts/package-gecko.py').read_text())

    def test_full_gecko_clock_boundary_and_runtime_deadline_gates(self):
        subprocess.run(['python3', 'scripts/test-native-clock.py'], cwd=ROOT, check=True)
        source = (ROOT / 'src/ps4/native_clock.cpp').read_text()
        self.assertTrue(source.startswith('#ifdef ORBISFOX_FULL_GECKO'))
        self.assertIn('constinit std::atomic<int> clockBinding{0}', source)
        self.assertIn('nativeSetConditionClock(attr, nativeId)', source)
        probe = (ROOT / 'gecko/orbisfox/native/clock_probe.cpp').read_text()
        self.assertIn('mozilla::Monitor monitor("OrbisClockDeadlineProbe")', probe)
        self.assertIn('lock.Wait(mozilla::TimeDuration::FromMilliseconds(200))', probe)
        self.assertIn('status == mozilla::CVStatus::Timeout', probe)
        builder = (ROOT / 'scripts/build-gecko-app.py').read_text()
        self.assertIn("'src/ps4/native_clock.cpp'", builder)
        self.assertIn('clock-probe-compile.log', builder)

    def test_native_cpu_uses_real_affinity_and_preserves_sdk_sysconf(self):
        sdk = ROOT / '.deps/OpenOrbis/PS4Toolchain/lib/libc.a'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            original, isolated = path / 'sdk-sysconf.o', path / 'isolated.o'
            original.write_bytes(subprocess.check_output(['llvm-ar', 'p', str(sdk), 'sysconf.lo']))
            subprocess.run(['llvm-objcopy', '--redefine-sym=sysconf=sdk_sysconf',
                            str(original), str(isolated)], check=True)
            executable = path / 'probe'
            subprocess.run(['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                            '-fno-omit-frame-pointer', '-Iinclude', 'tests/native_cpu_test.cpp',
                            'src/ps4/native_cpu.cpp', str(isolated), '-o', str(executable)], cwd=ROOT, check=True)
            subprocess.run([str(executable)], cwd=ROOT, check=True)
        builder = (ROOT / 'scripts/build-gecko-app.py').read_text()
        self.assertIn("'sysconf'", builder)
        self.assertIn('processor_count_real_affinity_only_full_gecko_sdk_other_sysconf_preserved', builder)

    def test_native_stat_record_translation(self):
        subprocess.run(['clang++', '-std=c++20', '-g', '-O1', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-Iinclude', 'tests/native_stat_test.cpp',
                        '-o', 'build/native-stat-test'], cwd=ROOT, check=True,
                       capture_output=True, text=True)
        subprocess.run([str(ROOT / 'build/native-stat-test')], cwd=ROOT, check=True,
                       capture_output=True, text=True)
        source = (ROOT / 'src/ps4/native_stat.cpp').read_text()
        for symbol in ('"stat"', '"lstat"', '"fstat"'):
            self.assertIn(symbol, source)
        self.assertIn('sceKernelQueryMemoryProtection', source)
        self.assertIn('EOVERFLOW', source)
        self.assertIn('256 - sizeof(orbisfox::FirmwareStat)', source)
        self.assertNotIn('fstatat(', source)
        self.assertNotIn('syscall(', source)

    def test_native_path_resolution_on_actual_filesystem(self):
        output = ROOT / 'build/orbis-path-test'
        subprocess.run(['clang++', '-std=c++20', '-g', '-O1', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', str(ROOT / 'tests/orbis_path_test.cpp'),
                        str(ROOT / 'gecko/orbisfox/OrbisPath.cpp'), '-o', str(output)],
                       cwd=ROOT, check=True, capture_output=True, text=True)
        result = subprocess.run([str(output)], cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertIn('32 real filesystem cycles passed', result.stdout)
        source = (ROOT / 'gecko/orbisfox/OrbisPath.cpp').read_text()
        for syscall in ('lstat(', 'readlink(', 'getcwd(', 'stat('):
            self.assertIn(syscall, source)
        self.assertNotIn('/proc/', source)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('XREShellData shellData{}', main)
        self.assertIn('bootstrap->XRE_XPCShellMain(7, argv, environ, &shellData)', main)
        self.assertIn('mozilla::GetBootstrap()', main)
        self.assertIn('sqliteResult == SQLITE_OK', main)
        self.assertLess(main.index('GetBootstrap()'), main.index('bootstrap->XRE_XPCShellMain'))
        self.assertGreater(main.index('bootstrap.reset()'), main.index('bootstrap->XRE_XPCShellMain'))
        self.assertNotIn('XRE_XPCShellMain(7, argv, environ, nullptr)', main)

    def test_orbis_nspr_does_not_claim_desktop_dynamic_loading(self):
        header = (ROOT / 'gecko/nsprpub/pr/include/md/_orbis.h').read_text()
        self.assertIn('#define _PR_ORBIS_STATIC_LINKER 1', header)
        self.assertNotIn('#define HAVE_DLL', header)
        self.assertNotIn('#define USE_DLFCN', header)
        builder = (ROOT / 'scripts/gecko-link-inputs.py').read_text()
        self.assertIn("LINK_INPUTS['collect_engine_inputs']", (ROOT / 'scripts/build-gecko-app.py').read_text())
        for target in ('pk11wrap_pk11wrap_static', 'softoken_softokn_static', 'freebl_freebl_static'):
            self.assertIn(target, builder)
        self.assertIn('Static NSS closure still contains its desktop freebl DLL loader', builder)

    def test_real_nspr_static_linker_behavior_under_sanitizers(self):
        source = ROOT / '.deps/gecko-layout/nsprpub'
        if not (source / 'configure').exists() or not (source / 'pr/src/linking/prlink.c').exists():
            self.skipTest('isolated full Gecko NSPR source has not been prepared')
        if '_PR_ORBIS_STATIC_LINKER' not in (source / 'pr/src/linking/prlink.c').read_text():
            self.skipTest('experimental static NSPR port has not been prepared')
        result = subprocess.run(['python3', str(ROOT / 'scripts/test-nspr-static.py')],
                                cwd=ROOT, check=True, capture_output=True, text=True, timeout=180)
        self.assertIn('32 cycles passed under ASan/UBSan', result.stdout)

    def test_test_package_is_separate_and_does_not_claim_hardware_success(self):
        self.assertEqual(PACKAGE.DIST, ROOT / 'dist/gecko')
        self.assertEqual(PACKAGE.VERSION, '0.68')
        script = (ROOT / 'scripts/package-gecko.py').read_text()
        self.assertIn("'hardware_tested': False", script)
        self.assertIn("'html_rendered_on_console': False", script)
        self.assertIn("'website_security_certified': False", script)

if __name__ == '__main__':
    unittest.main()
