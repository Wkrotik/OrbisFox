#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Vendor-gated full Gecko configuration changes for the native Orbis port."""
from pathlib import Path
import re
import sys


def replace_once(root, name, old, new):
    path = root / name
    text = path.read_text()
    if new in text:
        return
    candidates = (old,) if isinstance(old, str) else old
    for candidate in candidates:
        if text.count(candidate) == 1:
            path.write_text(text.replace(candidate, new, 1))
            return
    raise RuntimeError('Pinned Gecko layout patch no longer matches: ' + name)


def freetype_guards(text):
    """Select portable FreeType paths once, migrating older duplicated guards."""
    text = text.replace('#ifdef MOZ_WIDGET_ANDROID',
                        '#if defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS)')
    return re.sub(r'^#elif defined\(MOZ_WIDGET_ANDROID\)(?: \|\| defined\(MOZ_WIDGET_ORBIS\))*$',
                  '#elif defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS)',
                  text, flags=re.MULTILINE)


def patch_portable_baseline_marker(root):
    name = 'js/src/vm/PortableBaselineInterpret.cpp'
    replace_once(root, name, '#include "vm/PortableBaselineInterpret.h"',
                 '#include "vm/PortableBaselineInterpret.h"\n'
                 '#ifdef MOZ_ORBIS_HOMEBREW_SDK\n#include "mozilla/Atomics.h"\n#endif')
    replace_once(root, name, 'using namespace js::jit;\n',
                 'using namespace js::jit;\n\n#ifdef MOZ_ORBIS_HOMEBREW_SDK\n'
                 '#include "../../../orbisfox/OrbisPortableBaseline.inc"\n#endif\n')
    replace_once(root, name,
                 '    StackVal* restartEntryFrame, PBIResult restartCode) {\n',
                 '    StackVal* restartEntryFrame, PBIResult restartCode) {\n'
                 '#ifdef MOZ_ORBIS_HOMEBREW_SDK\n'
                 '  if (!sOrbisPortableBaselineEntered) sOrbisPortableBaselineEntered = true;\n'
                 '#endif\n')


def patch_native_link_gate_debug(root):
    # The build already strips this validation DSO; avoid its multi-GB temporary.
    replace_once(root, 'toolkit/library/build/moz.build', 'Libxul("xul-real")\n',
                 'Libxul("xul-real")\n\n'
                 'if CONFIG["MOZ_ORBIS_HOMEBREW_SDK"]:\n'
                 '    LDFLAGS += ["-Wl,--strip-debug"]\n')


def patch_native_worker_shutdown(root):
    name = 'dom/workers/RuntimeService.cpp'
    replace_once(root, name, '#include "nsISupportsPriority.h"',
                 '#include "nsISupportsPriority.h"\n'
                 '#ifdef MOZ_ORBIS_HOMEBREW_SDK\n#include "nsIThreadShutdown.h"\n#endif')
    old = ('  if (thread->ShutdownRequired()) {\n'
           '    MOZ_ALWAYS_SUCCEEDS(thread->Shutdown());\n'
           '  }\n\n  return NS_OK;\n}\n\n}  // namespace workerinternals')
    new = ('  if (thread->ShutdownRequired()) {\n'
           '#ifdef MOZ_ORBIS_HOMEBREW_SDK\n'
           '    // Keep the normal ACK/join and exit barrier without a nested main loop.\n'
           '    nsCOMPtr<nsIThreadShutdown> shutdown;\n'
           '    MOZ_ALWAYS_SUCCEEDS(thread->BeginShutdown(getter_AddRefs(shutdown)));\n'
           '#else\n'
           '    MOZ_ALWAYS_SUCCEEDS(thread->Shutdown());\n'
           '#endif\n'
           '  }\n\n  return NS_OK;\n}\n\n}  // namespace workerinternals')
    replace_once(root, name, old, new)


def patch_native_ipc_primitives(root):
    replace_once(root, 'ipc/chromium/src/chrome/common/process_watcher_posix_sigchld.cc',
                 '#if !defined(XP_DARWIN)\n'
                 '// Linux, {Free,Net,Open}BSD, and Solaris; but not macOS, yet.\n'
                 '#  define HAVE_PIPE2 1',
                 '#if !defined(XP_DARWIN) && !defined(ORBISFOX_HOMEBREW_SDK)\n'
                 '// Native BSD 9 uses the checked pipe/fcntl fallback below.\n'
                 '// Linux, {Free,Net,Open}BSD, and Solaris; but not macOS, yet.\n'
                 '#  define HAVE_PIPE2 1')
    replace_once(root, 'ipc/glue/ProcessUtils_bsd.cpp',
                 ('#if !defined(XP_NETBSD) && !defined(__ORBIS__)\n#  include <pthread_np.h>',
                  '#if !defined(XP_NETBSD)\n#  include <pthread_np.h>'),
                 '#if !defined(XP_NETBSD) && (!defined(__ORBIS__) || defined(ORBISFOX_HOMEBREW_SDK))\n'
                 '#  include <pthread_np.h>')


def patch_native_libevent_rng_names(root):
    # Keep the existing embedded entropy/error path. Native BSD headers also
    # declare arc4random APIs, so the embedded static helpers need private names.
    name = 'ipc/chromium/src/third_party/libevent/evutil_rand.c'
    anchor = '#else /* !EVENT__HAVE_ARC4RANDOM { */\n\n'
    replace_once(root, name, anchor,
                 anchor + '#ifdef ORBISFOX_HOMEBREW_SDK\n'
                 '#include <stdlib.h>\n'
                 '#define arc4random_addrandom orbis_libevent_arc4random_addrandom\n'
                 '#define arc4random_buf orbis_libevent_arc4random_buf\n'
                 '#endif\n\n')
    tail = ('void\nevutil_free_secure_rng_globals_(void)\n{\n'
            '    evutil_free_secure_rng_globals_locks();\n}\n')
    replace_once(root, name, tail,
                 tail + '\n#if defined(ORBISFOX_HOMEBREW_SDK) && !defined(EVENT__HAVE_ARC4RANDOM)\n'
                 '/* Do not leak names into the following unified-build units. */\n'
                 '#undef arc4random_addrandom\n#undef arc4random_buf\n#endif\n')


def patch_orbis_webrender_freetype(root):
    # This module consumes cairo-ft.h on Orbis too. Declare its FreeType
    # dependency locally instead of depending on SDK-global font includes.
    replace_once(root, 'gfx/webrender_bindings/moz.build',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] in ("android", "gtk"):\n'
                 '    CXXFLAGS += CONFIG["CAIRO_FT_CFLAGS"]',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] in ("android", "gtk", "orbis"):\n'
                 '    CXXFLAGS += CONFIG["CAIRO_FT_CFLAGS"]')


def static_ffvpx_bindings(root):
    """Resolve real pinned codec functions, without invented PRLibrary handles."""
    base=root/'dom/media/platforms/ffmpeg'
    header=(base/'FFmpegLibWrapper.h').read_text()
    header=re.sub(r'#(?:ifdef MOZ_WIDGET_GTK|ifdef MOZ_WIDGET_ANDROID|if defined\(MOZ_WIDGET_ANDROID\)).*?#endif','',header,flags=re.S)
    fields=set(re.findall(r'\(\*([a-z][a-z0-9_]+)\)',header))|set(re.findall(r'decltype\([^\n]+\)\*\s+(\w+)',header))
    exported=set()
    for stem in ('avcodec','avutil'):
        lines=(root/f'media/ffvpx/lib{stem}/{stem}.symbols').read_text().splitlines()
        exported.update(line for line in lines if re.fullmatch(r'[a-z][a-z0-9_]+',line))
    names=sorted(fields&exported)
    if len(names)!=64 or 'avcodec_version' not in names:
        raise RuntimeError('Pinned static FFVPX symbol schema changed')
    text='// Typed Gecko ABI bindings to the isolated upstream software codec archive.\n#include <type_traits>\n#include <string.h>\n'
    for name in names:
        text+=f'using OrbisType_{name}=std::remove_pointer_t<decltype(mozilla::FFmpegLibWrapper::{name})>;\nextern "C" OrbisType_{name} orbis_media_{name};\n'
    text+='static void* OrbisFFVPXSymbol(const char* name){\n'
    for name in names:
        text+=f' if(!strcmp(name,"{name}"))return reinterpret_cast<void*>(&orbis_media_{name});\n'
    text+=' return nullptr;\n}\n'
    path=base/'OrbisStaticFFVPX.inc'
    if not path.exists() or path.read_text()!=text:path.write_text(text)


def register_cubeb_source(root):
    replace_once(root, 'media/libcubeb/src/cubeb.c', '#if defined(USE_PULSE)\nint\npulse_init',
                 '#if defined(USE_ORBIS)\nint orbis_init(cubeb ** context, char const * context_name);\n#endif\n'
                 '#if defined(USE_PULSE)\nint\npulse_init')
    replace_once(root, 'media/libcubeb/src/cubeb.c', '    if (!strcmp(backend_name, "pulse")) {',
                 '    if (!strcmp(backend_name, "orbis")) {\n#if defined(USE_ORBIS)\n'
                 '      init_oneshot = orbis_init;\n#endif\n'
                 '    } else if (!strcmp(backend_name, "pulse")) {')
    replace_once(root, 'media/libcubeb/src/cubeb.c', '      init_oneshot,\n',
                 '      init_oneshot,\n#if defined(USE_ORBIS)\n      orbis_init,\n#endif\n')


def patch_orbis_widget_mesa(root):
    """Preserve hardware policy for the validated native headless mailbox."""
    # This port deliberately uses headless widgets for its native mailbox. The
    # generic widget selector otherwise forces SWGL even when gfxConfig permits
    # hardware, so only a validated Orbis backend may consult the global choice.
    replace_once(root, 'widget/nsIWidget.cpp', '#include "nsIWidget.h"',
                 '#include "nsIWidget.h"\n#ifdef MOZ_ORBIS_MESA\n'
                 '#include "mozilla/widget/OrbisGfxInfo.h"\n'
                 '#include "mozilla/widget/OrbisResourceDiagnostics.h"\n#endif')
    replace_once(root, 'widget/nsIWidget.cpp',
                 '    if (!IsHeadlessWidget() &&\n'
                 '        (supportsAcceleration ||',
                 '    bool headlessNeedsSoftware = IsHeadlessWidget();\n'
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '    const bool nativeGpuReady = mozilla::widget::IsOrbisMesaGpuReady();\n'
                 '    headlessNeedsSoftware = headlessNeedsSoftware && !nativeGpuReady;\n'
                 '#endif\n'
                 '    if (!headlessNeedsSoftware &&\n'
                 '        (supportsAcceleration ||')
    replace_once(root, 'widget/nsIWidget.cpp',
                 '    bool enableAPZ = UseAPZ();',
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '    mozilla::widget::RecordOrbisCompositorSelection(\n'
                 '        IsHeadlessWidget(), supportsAcceleration, nativeGpuReady,\n'
                 '        gfx::gfxVars::UseSoftwareWebRender(), enableSWWR);\n'
                 '#endif\n'
                 '    bool enableAPZ = UseAPZ();')


def patch_orbis_mesa(root):
    """Opt-in static EGL + real offscreen WebRender, never a fake PRLibrary."""
    # Permit this platform only after an owned GPU test. Preserve safe mode,
    # explicit disables, blocklist decisions and runtime software fallback.
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp', '#include "gfxConfig.h"',
                 '#include "gfxConfig.h"\n#ifdef MOZ_ORBIS_MESA\n'
                 '#include "mozilla/widget/OrbisResourceDiagnostics.h"\n#endif')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 '  gfxVars::SetUseSoftwareWebRender(!hasHardware);',
                 '  gfxVars::SetUseSoftwareWebRender(!hasHardware);\n'
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '  mozilla::widget::RecordOrbisGraphicsConfig(\n'
                 '      gfxConfig::IsEnabled(Feature::HW_COMPOSITING), hasHardware,\n'
                 '      static_cast<uint32_t>(gfxConfig::GetFeature(Feature::HW_COMPOSITING).GetValue()),\n'
                 '      static_cast<uint32_t>(gfxConfig::GetFeature(Feature::WEBRENDER).GetValue()));\n'
                 '#endif')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 '  if (feature.SetDefault(AccelerateLayersByDefault(), FeatureStatus::Blocked,',
                 '  bool nativeGpuReady = false;\n'
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '  nativeGpuReady = mozilla::widget::IsOrbisMesaGpuReady();\n'
                 '#endif\n'
                 '  if (feature.SetDefault(AccelerateLayersByDefault() || nativeGpuReady, FeatureStatus::Blocked,')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 '  if (IsHeadless()) {\n    feature.ForceDisable(FeatureStatus::Blocked,\n'
                 '                         "Acceleration blocked by headless mode",',
                 '  if (IsHeadless() && !nativeGpuReady) {\n'
                 '    feature.ForceDisable(FeatureStatus::Blocked,\n'
                 '                         "Acceleration blocked by headless mode",')
    replace_once(root, 'gfx/config/gfxConfigManager.cpp',
                 '  MOZ_ASSERT(aFeatureState);\n\n  nsCString blockId;',
                 '  MOZ_ASSERT(aFeatureState);\n\n'
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '  // No invented desktop gfxInfo: this native backend has its own\n'
                 '  // actual GLES3 shader/readback capability gate. Never mask a\n'
                 '  // present gfxInfo blocklist or qualify unrelated features.\n'
                 '  if (!mGfxInfo && aFeature == nsIGfxInfo::FEATURE_WEBRENDER &&\n'
                 '      mozilla::widget::IsOrbisMesaGpuReady()) {\n'
                 '    return;\n'
                 '  }\n'
                 '#endif\n\n  nsCString blockId;')
    mesa_response = str(Path(__file__).resolve().parent.parent / 'build/orbis-mesa/link-inputs.rsp')
    replace_once(root, 'gfx/gl/moz.build', 'FINAL_LIBRARY = "xul"',
                 'if CONFIG["MOZ_ORBIS_MESA"]:\n'
                 '    OS_LIBS += ' + repr(['-Wl,@' + mesa_response]) + '\n\n'
                 'FINAL_LIBRARY = "xul"')
    replace_once(root, 'gfx/gl/GLLibraryEGL.cpp', '#include "GLLibraryEGL.h"',
                 '#include "GLLibraryEGL.h"\n'
                 '#ifdef MOZ_ORBIS_MESA\n'
                 'extern "C" PRFuncPtr eglGetProcAddress(const char*);\n'
                 'extern "C" bool orbis_mesa_gpu_ready() __attribute__((weak));\n'
                 '#endif')
    replace_once(root, 'gfx/gl/GLLibraryEGL.cpp',
                 '  mozilla::ScopedGfxFeatureReporter reporter("EGL");\n\n#ifdef XP_WIN',
                 '  mozilla::ScopedGfxFeatureReporter reporter("EGL");\n\n'
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '  // Real statically linked Mesa; no DSO handle or fake load success.\n'
                 '  // Absent/failed native binding is an honest unavailable backend.\n'
                 '  if (!orbis_mesa_gpu_ready || !orbis_mesa_gpu_ready()) {\n'
                 '    return false;\n'
                 '  }\n'
                 '#elif defined(XP_WIN)')
    replace_once(root, 'gfx/gl/GLLibraryEGL.cpp',
                 '  if (!mEGLLibrary || !mGLLibrary) {',
                 '#ifndef MOZ_ORBIS_MESA\n  if (!mEGLLibrary || !mGLLibrary) {')
    replace_once(root, 'gfx/gl/GLLibraryEGL.cpp',
                 '#define SYMBOL(X)', '#endif  // !MOZ_ORBIS_MESA\n\n#define SYMBOL(X)')
    replace_once(root, 'gfx/gl/GLLibraryEGL.cpp',
                 '    const SymbolLoader libLoader(*mEGLLibrary);',
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '    const SymbolLoader libLoader(&eglGetProcAddress);\n'
                 '#else\n    const SymbolLoader libLoader(*mEGLLibrary);\n#endif')
    replace_once(root, 'gfx/gl/GLLibraryEGL.cpp',
                 '  {\n    const char internalFuncName[] =',
                 '#ifndef MOZ_ORBIS_MESA\n  {\n    const char internalFuncName[] =')
    replace_once(root, 'gfx/gl/GLLibraryEGL.cpp',
                 '  // -\n\n  InitLibExtensions();',
                 '#endif  // !MOZ_ORBIS_MESA\n\n  // -\n\n  InitLibExtensions();')
    replace_once(root, 'gfx/gl/GLContextProviderEGL.cpp',
                 '    auto dummySize = mozilla::gfx::IntSize{16, 16};',
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '    // Pbuffer only: no Vulkan swapchain or second VideoOut owner.\n'
                 '    auto dummySize = mozilla::gfx::IntSize{1280, 720};\n'
                 '#else\n    auto dummySize = mozilla::gfx::IntSize{16, 16};\n#endif')
    replace_once(root, 'gfx/gl/GLContextProviderEGL.cpp',
                 '#if defined(MOZ_WIDGET_ANDROID)\n  preferGles = true;\n'
                 '#else\n  preferGles = StaticPrefs::gfx_egl_prefer_gles_enabled_AtStartup();\n'
                 '#endif  // defined(MOZ_WIDGET_ANDROID)\n'
                 '  RefPtr<GLContextEGL> gl = WithUseGles(preferGles);',
                 '#if defined(MOZ_WIDGET_ANDROID) || defined(MOZ_ORBIS_MESA)\n'
                 '  preferGles = true;\n'
                 '#else\n  preferGles = StaticPrefs::gfx_egl_prefer_gles_enabled_AtStartup();\n'
                 '#endif\n  RefPtr<GLContextEGL> gl = WithUseGles(preferGles);')
    replace_once(root, 'gfx/webrender_bindings/RenderThread.cpp',
                 '#ifdef XP_WIN\n  if (gfx::gfxVars::UseWebRenderANGLE()) {',
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '  gl = gl::GLContextProviderEGL::CreateHeadless(\n'
                 '      {gl::CreateContextFlags::FORBID_SOFTWARE |\n'
                 '       gl::CreateContextFlags::PREFER_ES3}, &aError);\n'
                 '#elif defined(XP_WIN)\n  if (gfx::gfxVars::UseWebRenderANGLE()) {')
    replace_once(root, 'gfx/webrender_bindings/RenderCompositor.cpp',
                 '#include "RenderCompositor.h"',
                 '#include "RenderCompositor.h"\n#ifdef MOZ_ORBIS_MESA\n'
                 '#include "RenderCompositorOrbis.h"\n#endif')
    replace_once(root, 'gfx/webrender_bindings/RenderCompositor.cpp',
                 '  if (aWidget->AsDelegate() &&',
                 '#ifdef MOZ_ORBIS_MESA\n'
                 '  if (!aWidget->GetCompositorOptions().UseSoftwareWebRender()) {\n'
                 '    return RenderCompositorOrbis::Create(aWidget, aError);\n'
                 '  }\n#endif\n  if (aWidget->AsDelegate() &&')
    replace_once(root, 'gfx/webrender_bindings/moz.build',
                 'include("/ipc/chromium/chromium-config.mozbuild")',
                 'if CONFIG["MOZ_ORBIS_MESA"]:\n'
                 '    EXPORTS.mozilla.webrender += ["RenderCompositorOrbis.h"]\n'
                 '    SOURCES += ["RenderCompositorOrbis.cpp"]\n\n'
                 'include("/ipc/chromium/chromium-config.mozbuild")')
    patch_orbis_widget_mesa(root)


def patch_orbis_shared_memory_diagnostics(root):
    """Failure-only, bounded existing-module logging; never retry/change mmap."""
    replace_once(root, 'ipc/glue/SharedMemoryPlatform_posix.cpp',
                 '  if (mem == MAP_FAILED) {\n'
                 '    MOZ_LOG_FMT(gSharedMemoryLog, LogLevel::Warning, "call to mmap failed: {}",\n'
                 '                strerror(errno));\n'
                 '    return Nothing();\n'
                 '  }',
                 '''  if (mem == MAP_FAILED) {
#ifdef __ORBIS__
    const int mapError = errno;
    // Off unless the operator enabled the existing SharedMemory log module.
    // Bound records globally, not per thread; never dump mapped/content bytes.
    static mozilla::Atomic<uint32_t, mozilla::Relaxed> failures(0);
    uint32_t ticket = 32;
    if (MOZ_LOG_TEST(gSharedMemoryLog, LogLevel::Warning)) {
      // Saturate, rather than wrapping and restarting logging in a long run.
      for (ticket = failures; ticket < 32; ticket = failures) {
        if (failures.compareExchange(ticket, ticket + 1)) break;
      }
    }
    if (ticket < 32) {
      struct stat st = {};
      const int fd = aHandle.mHandle.get();
      errno = 0;
      const int statResult = fstat(fd, &st);
      const int statError = statResult == 0 ? 0 : errno;
      errno = 0;
      const int fdFlags = fcntl(fd, F_GETFL);
      const int flagsError = fdFlags >= 0 ? 0 : errno;
      const long pageSize = sysconf(_SC_PAGESIZE);
      MOZ_LOG_FMT(gSharedMemoryLog, LogLevel::Warning,
                  "Orbis shm mmap failure errno={} addr={:p} size={} offset={} "
                  "prot={} flags={} fd={} fstat={} stat_errno={} file_size={} "
                  "fd_flags={} flags_errno={} page_size={}",
                  mapError, aFixedAddress, aSize, aOffset,
                  PROT_READ | (aReadOnly ? 0 : PROT_WRITE), MAP_SHARED,
                  fd, statResult, statError,
                  statResult == 0 ? static_cast<int64_t>(st.st_size) : int64_t(-1),
                  fdFlags, flagsError, pageSize);
    }
    errno = mapError;
#endif
    MOZ_LOG_FMT(gSharedMemoryLog, LogLevel::Warning, "call to mmap failed: {}",
                strerror(errno));
#ifdef __ORBIS__
    errno = mapError;
#endif
    return Nothing();
  }''')


def patch_orbis_resource_accounting(root):
    """Count real shared views; no allocation routing, retries or fake releases."""
    path = 'ipc/glue/SharedMemoryPlatform_posix.cpp'
    replace_once(root, path, 'namespace mozilla::ipc::shared_memory {',
                 '#ifdef __ORBIS__\n'
                 '#include "../../widget/orbis/OrbisResourceDiagnostics.h"\n#endif\n\n'
                 'namespace mozilla::ipc::shared_memory {')
    replace_once(root, path,
                 '  if (mem == MAP_FAILED) {\n#ifdef __ORBIS__\n    const int mapError = errno;',
                 '#ifdef __ORBIS__\n'
                 '  mozilla::widget::RecordOrbisSharedMap(aSize, mem != MAP_FAILED);\n'
                 '#endif\n  if (mem == MAP_FAILED) {\n#ifdef __ORBIS__\n    const int mapError = errno;')
    replace_once(root, path,
                 '    DebugOnly<bool> munmap_succeeded = munmap(mem, aSize) == 0;\n',
                 '#ifdef __ORBIS__\n'
                 '    const bool munmap_succeeded = munmap(mem, aSize) == 0;\n'
                 '    mozilla::widget::RecordOrbisSharedUnmap(aSize, munmap_succeeded);\n'
                 '#else\n'
                 '    DebugOnly<bool> munmap_succeeded = munmap(mem, aSize) == 0;\n'
                 '#endif\n')
    replace_once(root, path,
                 'void Platform::Unmap(void* aMemory, size_t aSize) { munmap(aMemory, aSize); }',
                 'void Platform::Unmap(void* aMemory, size_t aSize) {\n'
                 '  const int result = munmap(aMemory, aSize);\n'
                 '#ifdef __ORBIS__\n'
                 '  mozilla::widget::RecordOrbisSharedUnmap(aSize, result == 0);\n'
                 '  // Failed releases stay in the live counter; never guess ownership.\n'
                 '  if (result != 0) {\n'
                 '    MOZ_LOG_FMT(gSharedMemoryLog, LogLevel::Warning,\n'
                 '                "Orbis shm munmap failed size={} errno={}", aSize, errno);\n'
                 '  }\n#else\n  (void)result;\n#endif\n}')


def main():
    root = Path(sys.argv[1]).resolve()
    patch_orbis_mesa(root)
    patch_orbis_shared_memory_diagnostics(root)
    patch_orbis_resource_accounting(root)
    replace_once(root, 'xpcom/ds/PLDHashTable.cpp', '#include "PLDHashTable.h"\n',
                 '#include "PLDHashTable.h"\n#ifdef MOZ_WIDGET_ORBIS\n'
                 '#include "../../orbisfox/OrbisTableFault.h"\n#endif\n')
    replace_once(root, 'xpcom/ds/moz.build', 'XPIDL_MODULE = "xpcom_ds"\n',
                 'XPIDL_MODULE = "xpcom_ds"\n\n'
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += ["/orbisfox/OrbisTableFault.cpp"]\n')
    for signature, operation in (
        ('mozilla::Maybe<PLDHashTable::EntryHandle> PLDHashTable::MakeEntryHandle(\n'
         '    const void* aKey, const mozilla::fallible_t&) {\n', 'fallible-entry'),
        ('PLDHashTable::EntryHandle PLDHashTable::MakeEntryHandle(const void* aKey) {\n', 'entry')):
        replace_once(root, 'xpcom/ds/PLDHashTable.cpp', signature,
                     signature + '#ifdef MOZ_WIDGET_ORBIS\n'
                     '  // Keep the invalid receiver observable despite C++ nonnull-this assumptions.\n'
                     '  uintptr_t observed = reinterpret_cast<uintptr_t>(this);\n'
                     '  asm volatile("" : "+r"(observed));\n'
                     '  if (observed < 4096) orbisfox::record_table_fault("' + operation + '", observed, aKey, __builtin_return_address(0));\n'
                     '#endif\n')
    replace_once(root, 'xpcom/threads/nsThread.cpp', '#include "nsThread.h"\n',
                 '#include "nsThread.h"\n#ifdef MOZ_WIDGET_ORBIS\n'
                 '#include "mozilla/widget/OrbisTaskDiagnostics.h"\n#endif\n')
    replace_once(root, 'xpcom/threads/nsThread.cpp',
                 '      if (!usingTaskController) {\n'
                 '        AUTO_PROFILE_FOLLOWING_RUNNABLE(event);\n'
                 '        event->Run();\n'
                 '      } else {\n'
                 '        // Avoid generating "Runnable" profiler markers for the\n'
                 '        // "TaskController::ExecutePendingMTTasks" runnables created\n'
                 '        // by TaskController, which already adds "Runnable" markers\n'
                 '        // when executing tasks.\n'
                 '        event->Run();\n'
                 '      }\n',
                 '      {\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '        mozilla::widget::OrbisMainTaskSpan taskSpan(event);\n'
                 '#endif\n'
                 '        if (!usingTaskController) {\n'
                 '          AUTO_PROFILE_FOLLOWING_RUNNABLE(event);\n'
                 '          event->Run();\n'
                 '        } else {\n'
                 '          // TaskController supplies its own profiler markers.\n'
                 '          event->Run();\n'
                 '        }\n'
                 '      }\n')
    replace_once(root, 'xpcom/threads/TaskController.cpp', '#include "TaskController.h"\n',
                 '#include "TaskController.h"\n#ifdef MOZ_WIDGET_ORBIS\n'
                 '#include "mozilla/widget/OrbisTaskDiagnostics.h"\n#endif\n')
    replace_once(root, 'xpcom/threads/TaskController.cpp',
                 '  virtual TaskResult Run() override {\n    mRunnable->Run();',
                 '  virtual TaskResult Run() override {\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '    mozilla::widget::OrbisMainTaskSpan taskSpan(mRunnable, true);\n'
                 '#endif\n'
                 '    mRunnable->Run();')
    replace_once(root, 'gfx/thebes/moz.build', 'FINAL_LIBRARY = "xul"\n',
                 'FINAL_LIBRARY = "xul"\n'
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += ["/orbisfox/OrbisGlyphDiagnostics.cpp"]\n'
                 '    EXPORTS.mozilla.orbisfox += ["/orbisfox/OrbisGlyphDiagnostics.h"]\n')
    replace_once(root, 'gfx/thebes/gfxFont.cpp', '#include "gfxFont.h"\n',
                 '#include "gfxFont.h"\n#ifdef MOZ_WIDGET_ORBIS\n'
                 '#include "mozilla/orbisfox/OrbisGlyphDiagnostics.h"\n#endif\n')
    replace_once(root, 'gfx/thebes/gfxFont.cpp',
                 '    gfxFontMissingGlyphs::DrawMissingGlyph(\n',
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '    orbisfox::record_missing_glyph(aDetails->mGlyphID);\n'
                 '#endif\n'
                 '    gfxFontMissingGlyphs::DrawMissingGlyph(\n')
    # tx.h may be included by WebAudio before the wrapper in unified builds.
    # Put real C ABI linkage at its declaration source, not only one caller.
    replace_once(root, 'media/ffvpx/libavutil/tx.h',
                 '#include <stddef.h>\n',
                 '#include <stddef.h>\n#if defined(__cplusplus) && defined(MOZ_WIDGET_ORBIS)\nextern "C" {\n#endif\n')
    replace_once(root, 'media/ffvpx/libavutil/tx.h',
                 '#endif /* AVUTIL_TX_H */',
                 '#if defined(__cplusplus) && defined(MOZ_WIDGET_ORBIS)\n}\n#endif\n\n#endif /* AVUTIL_TX_H */')
    static_ffvpx_bindings(root)
    wrapper='dom/media/platforms/ffmpeg/FFmpegLibWrapper'
    replace_once(root, wrapper+'.h', '#include "ffvpx/tx.h"\n',
                 '#ifdef MOZ_WIDGET_ORBIS\nextern "C" {\n#include "ffvpx/tx.h"\n}\n'
                 '#else\n#include "ffvpx/tx.h"\n#endif\n')
    replace_once(root, wrapper+'.h', '  LinkResult Link();\n',
                 '  LinkResult Link();\n  void* FindFunction(PRLibrary* library, const char* name);\n  bool mStaticFFVPX = false;\n')
    replace_once(root, wrapper+'.cpp', '#include "FFmpegLibWrapper.h"\n',
                 '#include "FFmpegLibWrapper.h"\n#ifdef MOZ_WIDGET_ORBIS\n#include "OrbisStaticFFVPX.inc"\n#endif\n')
    replace_once(root, wrapper+'.cpp', 'FFmpegLibWrapper::LinkResult FFmpegLibWrapper::Link() {\n',
                 'void* FFmpegLibWrapper::FindFunction(PRLibrary* library, const char* name) {\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n  if (mStaticFFVPX) return OrbisFFVPXSymbol(name);\n#endif\n'
                 '  return PR_FindSymbol(library, name);\n}\n\n'
                 'FFmpegLibWrapper::LinkResult FFmpegLibWrapper::Link() {\n')
    replace_once(root, wrapper+'.cpp', '  if (!mAVCodecLib || !mAVUtilLib) {',
                 '  if (!mStaticFFVPX && (!mAVCodecLib || !mAVUtilLib)) {')
    replace_once(root, wrapper+'.cpp', 'PR_FindSymbol(mAVCodecLib, "avcodec_version")',
                 'FindFunction(mAVCodecLib, "avcodec_version")')
    replace_once(root, wrapper+'.cpp', 'if (!((func) = (decltype(func))PR_FindSymbol(',
                 'if (!((func) = (decltype(func))FindFunction(')
    runtime='dom/media/platforms/ffmpeg/ffvpx/FFVPXRuntimeLinker.cpp'
    replace_once(root, runtime, 'static PRLibrary* MozAVLink(nsIFile* aFile) {',
                 '#ifndef MOZ_WIDGET_ORBIS\nstatic PRLibrary* MozAVLink(nsIFile* aFile) {')
    replace_once(root, runtime, '  return lib;\n}\n\n/* static */\nvoid FFVPXRuntimeLinker::PrefCallbackLogLevel',
                 '  return lib;\n}\n#endif\n\n/* static */\nvoid FFVPXRuntimeLinker::PrefCallbackLogLevel')
    replace_once(root, runtime, '#ifdef XP_WIN\n  PathString path =',
                 '#ifdef MOZ_WIDGET_ORBIS\n  sFFVPXLib.mStaticFFVPX = true;\n'
                 '#else\n#ifdef XP_WIN\n  PathString path =')
    replace_once(root, runtime, '  FFmpegLibWrapper::LinkResult res = sFFVPXLib.Link();',
                 '#endif // MOZ_WIDGET_ORBIS: statically linked real codec symbols\n'
                 '  FFmpegLibWrapper::LinkResult res = sFFVPXLib.Link();')
    codec_dir = Path(__file__).resolve().parents[1] / 'build/media-codecs/native'
    # mozbuild prepends -l to bare OS_LIBS, including absolute paths. Pass
    # archive paths through the compiler's linker-option syntax instead.
    archive_paths = [str(codec_dir / ('liborbis_' + name + '.a'))
                     for name in ('avcodec', 'swresample', 'avutil')]
    codec_libraries = ['-Wl,--start-group'] + ['-Wl,' + path for path in archive_paths] + ['-Wl,--end-group']
    previous_libraries = ['-Wl,--start-group'] + archive_paths + ['-Wl,--end-group']
    previous_codec_build = ('if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                            '    USE_LIBS += ["mozavcodec", "mozavutil"]\n'
                            '    OS_LIBS += ' + repr(previous_libraries) + '\n\nEXPORTS += [\n')
    legacy_codec_build = 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n    USE_LIBS += ["mozavcodec", "mozavutil"]\n\nEXPORTS += [\n'
    old_codec_build = ('if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                       '    USE_LIBS += ["mozavcodec", "mozavutil"]\n'
                       '    OS_LIBS += ' + repr(codec_libraries) + '\n\nEXPORTS += [\n')
    native_libraries = [entry.replace('/media-codecs/native/', '/media-codecs/native-homebrew/')
                        for entry in codec_libraries]
    replace_once(root, 'dom/media/platforms/ffmpeg/moz.build',
                 (old_codec_build, previous_codec_build, legacy_codec_build, 'EXPORTS += [\n'),
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    USE_LIBS += ["mozavcodec", "mozavutil"]\n'
                 '    if CONFIG["MOZ_ORBIS_HOMEBREW_SDK"]:\n'
                 '        OS_LIBS += ' + repr(native_libraries) + '\n'
                 '    else:\n'
                 '        OS_LIBS += ' + repr(codec_libraries) + '\n\nEXPORTS += [\n')
    register_cubeb_source(root)
    replace_once(root, 'media/libcubeb/src/moz.build', "Library('cubeb')\n",
                 "Library('cubeb')\n\n"
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += ["/orbisfox/cubeb_orbis.cpp"]\n'
                 '    LOCAL_INCLUDES += ["/media/libcubeb/src"]\n'
                 '    EXPORTS.mozilla.orbisfox += ["/orbisfox/OrbisAudioBackend.h"]\n'
                 '    DEFINES["USE_ORBIS"] = True\n')
    replace_once(root, 'media/libcubeb/src/moz.build',
                 '    DEFINES["USE_ORBIS"] = True\n',
                 '    DEFINES["USE_ORBIS"] = True\n    USE_LIBS += ["speex"]\n')
    replace_once(root, 'media/libcubeb/src/moz.build',
                 'if (\n    CONFIG["MOZ_PULSEAUDIO"]\n',
                 'if (\n    CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis"\n    or CONFIG["MOZ_PULSEAUDIO"]\n')
    # Baseline/RegExp JIT do not require Wasm trap recovery. Orbis has no
    # verified signal-context ABI or Wasm fault-handler backend: report that
    # capability unavailable, as the upstream no-codegen path already does.
    wasmSignals = root / 'js/src/wasm/WasmSignalHandlers.cpp'
    wasmText = wasmSignals.read_text()
    wasmUpdated = wasmText.replace('#if !defined(JS_CODEGEN_NONE)\n',
                                  '#if !defined(JS_CODEGEN_NONE) && !defined(MOZ_WIDGET_ORBIS)\n')
    wasmUpdated = wasmUpdated.replace('#ifndef JS_CODEGEN_NONE\n',
                                     '#if !defined(JS_CODEGEN_NONE) && !defined(MOZ_WIDGET_ORBIS)\n')
    wasmUpdated = wasmUpdated.replace('#ifdef JS_CODEGEN_NONE\n',
                                     '#if defined(JS_CODEGEN_NONE) || defined(MOZ_WIDGET_ORBIS)\n')
    if wasmUpdated.count('#if !defined(JS_CODEGEN_NONE) && !defined(MOZ_WIDGET_ORBIS)\n') != 2 or wasmUpdated.count('#if defined(JS_CODEGEN_NONE) || defined(MOZ_WIDGET_ORBIS)\n') != 4:
        raise RuntimeError('Pinned Wasm signal capability guards no longer match')
    if wasmUpdated != wasmText:
        wasmSignals.write_text(wasmUpdated)
    jitMemoryInclude='#include "mozilla/orbisfox/OrbisExecutableMemory.h"\n'
    replace_once(root, 'js/src/jit/ProcessExecutableMemory.cpp',
                 '#include "jit/ProcessExecutableMemory.h"\n',
                 '#include "jit/ProcessExecutableMemory.h"\n#ifdef MOZ_WIDGET_ORBIS\n'+jitMemoryInclude+'#endif\n')
    replace_once(root, 'js/src/jit/ProcessExecutableMemory.h',
                 '#if JS_BITS_PER_WORD == 32\n',
                 '#if defined(MOZ_WIDGET_ORBIS)\n'
                 'static const size_t MaxCodeBytesPerProcess = 64 * 1024 * 1024;\n'
                 '#elif JS_BITS_PER_WORD == 32\n')
    replace_once(root, 'js/src/jit/ProcessExecutableMemory.cpp',
                 '}\n#elif defined(__wasi__)\n#  if defined(JS_CODEGEN_WASM32)\n',
                 '}\n#elif defined(MOZ_WIDGET_ORBIS)\n'
                 'static unsigned ProtectionSettingToFlags(ProtectionSetting setting) {\n'
                 '  MOZ_RELEASE_ASSERT(JitOptions.writeProtectCode);\n'
                 '  return setting == ProtectionSetting::Executable ? 5 : 3;\n'
                 '}\n'
                 'static void* ReserveProcessExecutableMemory(size_t bytes) {\n'
                 '  return orbisfox::reserve_orbis_executable_memory(bytes);\n'
                 '}\n'
                 'static void DeallocateProcessExecutableMemory(void* address, size_t bytes) {\n'
                 '  orbisfox::release_orbis_executable_memory(address, bytes);\n'
                 '}\n'
                 'static bool CommitPages(void* address, size_t bytes, ProtectionSetting protection) {\n'
                 '  return orbisfox::protect_orbis_executable_memory(address, bytes, ProtectionSettingToFlags(protection));\n'
                 '}\n'
                 'static void DecommitPages(void* address, size_t bytes) {\n'
                 '  MOZ_RELEASE_ASSERT(orbisfox::protect_orbis_executable_memory(address, bytes, 0));\n'
                 '}\n'
                 '#elif defined(__wasi__)\n#  if defined(JS_CODEGEN_WASM32)\n')
    replace_once(root, 'js/src/jit/ProcessExecutableMemory.cpp',
                 '#  ifdef XP_WIN\n  DWORD flags = ProtectionSettingToFlags(protection);',
                 '#  if defined(MOZ_WIDGET_ORBIS)\n'
                 '  if (!orbisfox::protect_orbis_executable_memory(pageStart, size, ProtectionSettingToFlags(protection))) return false;\n'
                 '#  elif defined(XP_WIN)\n  DWORD flags = ProtectionSettingToFlags(protection);')
    # Only GC arena/nursery chunks move to CPU-cached game direct memory.
    # Leave shrinkable buffers, file reservations, stacks and JIT maps alone.
    replace_once(root, 'js/src/moz.build',
                 ('include("js-cxxflags.mozbuild")\n\n'
                  'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                  '    SOURCES += ["/orbisfox/OrbisGCChunkMemory.cpp", "/orbisfox/OrbisExecutableMemory.cpp"]\n'
                  '    EXPORTS.mozilla.orbisfox += ["/orbisfox/OrbisGCChunkMemory.h", "/orbisfox/OrbisExecutableMemory.h"]\n',
                  'include("js-cxxflags.mozbuild")\n\n'
                  'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                  '    SOURCES += ["/orbisfox/OrbisGCChunkMemory.cpp"]\n'
                  '    EXPORTS.mozilla.orbisfox += ["/orbisfox/OrbisGCChunkMemory.h"]\n',
                  'include("js-cxxflags.mozbuild")\n'),
                 'include("js-cxxflags.mozbuild")\n\n'
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += ["/orbisfox/OrbisExecutableMemory.cpp", "/orbisfox/OrbisGCChunkMemory.cpp"]\n'
                 '    EXPORTS.mozilla.orbisfox += ["/orbisfox/OrbisExecutableMemory.h", "/orbisfox/OrbisGCChunkMemory.h"]\n')
    replace_once(root, 'js/src/gc/Memory.h',
                 '// Allocate or deallocate pages from the system with the given alignment.\n',
                 '// Allocate or deallocate pages from the system with the given alignment.\n'
                 'void* MapGCChunkPages(size_t length, size_t alignment, StallAndRetry retry);\n')
    replace_once(root, 'js/src/gc/Memory.cpp', '#include "gc/Memory.h"\n',
                 '#include "gc/Memory.h"\n#ifdef MOZ_WIDGET_ORBIS\n'
                 '#include "mozilla/orbisfox/OrbisGCChunkMemory.h"\n#endif\n')
    replace_once(root, 'js/src/gc/Memory.cpp',
                 '    decommitEnabled = pageSize == PageSize && !disableDecommitRequested;\n',
                 '    decommitEnabled = pageSize == PageSize && !disableDecommitRequested;\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '    // Direct GC chunks support whole release, not partial decommit.\n'
                 '    decommitEnabled = false;\n#endif\n')
    replace_once(root, 'js/src/gc/Memory.cpp',
                 'void* MapAlignedPages(size_t length, size_t alignment,\n',
                 'void* MapGCChunkPages(size_t length, size_t alignment, StallAndRetry retry) {\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  if (void* region = orbisfox::map_gc_chunk_memory(length, alignment)) {\n'
                 '    MOZ_RELEASE_ASSERT(!IsInvalidRegion(region, length));\n'
                 '    RecordMemoryAlloc(length);\n'
                 '    return region;\n'
                 '  }\n#endif\n'
                 '  return MapAlignedPages(length, alignment, retry);\n'
                 '}\n\n'
                 'void* MapAlignedPages(size_t length, size_t alignment,\n')
    replace_once(root, 'js/src/gc/Allocator.cpp',
                 '  void* chunk = MapAlignedPages(ChunkSize, ChunkSize, stallAndRetry);',
                 '  void* chunk = MapGCChunkPages(ChunkSize, ChunkSize, stallAndRetry);')
    replace_once(root, 'js/src/gc/Memory.cpp',
                 '  MOZ_MAKE_MEM_UNDEFINED(region, length);\n\n  UnmapInternal(region, length);',
                 '  MOZ_MAKE_MEM_UNDEFINED(region, length);\n\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  if (orbisfox::unmap_gc_chunk_memory(region, length)) {\n'
                 '    RecordMemoryFree(length);\n'
                 '    return;\n'
                 '  }\n#endif\n'
                 '  UnmapInternal(region, length);')
    # Orbis mmap does not support FreeBSD's MAP_ALIGNED flag. That fast path
    # also tests raw MAP_FAILED as if it were nullptr and later unmaps -1.
    # Use the existing normalized generic mapping/alignment path on Orbis.
    replace_once(root, 'js/src/gc/Memory.cpp',
                 '#  if defined(__FreeBSD__)\n      int flags = MAP_PRIVATE | MAP_ANON |',
                 '#  if defined(__FreeBSD__) && !defined(MOZ_WIDGET_ORBIS)\n      int flags = MAP_PRIVATE | MAP_ANON |')
    # The embedding container, not an AppWindow, must expose the native window
    # provider chain used by ordinary content target=_blank/window.open calls.
    replace_once(root, 'xpfe/appshell/nsAppShellService.cpp',
                 '#include "nsAppShellService.h"',
                 '#include "nsAppShellService.h"\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n#include "nsIWindowProvider.h"\n#endif')
    replace_once(root, 'xpfe/appshell/nsAppShellService.cpp',
                 '                                    public nsIInterfaceRequestor,\n'
                 '                                    public nsSupportsWeakReference {',
                 '                                    public nsIInterfaceRequestor,\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '                                    public nsIWindowProvider,\n'
                 '#endif\n'
                 '                                    public nsSupportsWeakReference {')
    replace_once(root, 'xpfe/appshell/nsAppShellService.cpp',
                 '  NS_DECL_NSIWEBBROWSERCHROME\n  NS_DECL_NSIINTERFACEREQUESTOR\n};',
                 '  NS_DECL_NSIWEBBROWSERCHROME\n  NS_DECL_NSIINTERFACEREQUESTOR\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n  NS_DECL_NSIWINDOWPROVIDER\n#endif\n};')
    replace_once(root, 'xpfe/appshell/nsAppShellService.cpp',
                 '  NS_INTERFACE_MAP_ENTRY(nsIWebBrowserChrome)\n',
                 '  NS_INTERFACE_MAP_ENTRY(nsIWebBrowserChrome)\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n  NS_INTERFACE_MAP_ENTRY(nsIWindowProvider)\n#endif\n')
    # Orbis ksem compatibility is not assumed. Retain Skia's genuine counter
    # and lazy creation while using checked native pthread wait/notify below.
    replace_once(root, 'gfx/skia/skia/src/base/SkSemaphore.cpp',
                 '#if defined(SK_BUILD_FOR_MAC) || defined(SK_BUILD_FOR_IOS)',
                 '#if defined(MOZ_WIDGET_ORBIS)\n'
                 '#include "../../../../../orbisfox/SkiaSemaphore.h"\n'
                 'struct SkSemaphore::OSSemaphore : OrbisSkiaSemaphore {};\n'
                 '#elif defined(SK_BUILD_FOR_MAC) || defined(SK_BUILD_FOR_IOS)')
    replace_once(root, 'gfx/skia/skia/src/core/SkStrike.cpp',
                 '    return fGlyphForIndex[digest.index()];',
                 '#if defined(MOZ_WIDGET_ORBIS)\n'
                 '    if (digest.index() >= fGlyphForIndex.size()) {\n'
                 '        SK_ABORT("Orbis glyph lookup: digest-index=%zu vector-size=%zu",\n'
                 '                 size_t(digest.index()), size_t(fGlyphForIndex.size()));\n'
                 '    }\n'
                 '    if (fGlyphForIndex[digest.index()] == nullptr) {\n'
                 '        SK_ABORT("Orbis glyph lookup: null pointer index=%zu vector-size=%zu",\n'
                 '                 size_t(digest.index()), size_t(fGlyphForIndex.size()));\n'
                 '    }\n'
                 '#endif\n'
                 '    return fGlyphForIndex[digest.index()];')
    replace_once(root, 'gfx/skia/skia/src/core/SkStrike.cpp',
                 '        glyph = fGlyphForIndex[digestPtr->index()];',
                 '        glyph = this->glyph(*digestPtr);')
    replace_once(root, 'gfx/skia/skia/src/core/SkGlyphRunPainter.cpp',
                 'prepare_for_direct_mask_drawing(SkStrike* strike,\n'
                 '                                const SkMatrix& creationMatrix,\n'
                 '                                SkZip<const SkGlyphID, const SkPoint> source,\n'
                 '                                SkZip<const SkGlyph*, SkPoint> acceptedBuffer,\n'
                 '                                SkZip<SkGlyphID, SkPoint> rejectedBuffer) {\n'
                 '    const SkIPoint mask = strike->roundingSpec().ignorePositionFieldMask;',
                 'prepare_for_direct_mask_drawing(SkStrike* strike,\n'
                 '                                const SkMatrix& creationMatrix,\n'
                 '                                SkZip<const SkGlyphID, const SkPoint> source,\n'
                 '                                SkZip<const SkGlyph*, SkPoint> acceptedBuffer,\n'
                 '                                SkZip<SkGlyphID, SkPoint> rejectedBuffer) {\n'
                 '#if defined(MOZ_WIDGET_ORBIS)\n'
                 '    if (acceptedBuffer.size() < source.size() || rejectedBuffer.size() < source.size()) {\n'
                 '        SK_ABORT("Orbis glyph prepare: source=%zu accepted-capacity=%zu rejected-capacity=%zu",\n'
                 '                 source.size(), acceptedBuffer.size(), rejectedBuffer.size());\n'
                 '    }\n'
                 '#endif\n'
                 '    const SkIPoint mask = strike->roundingSpec().ignorePositionFieldMask;')
    replace_once(root, 'gfx/skia/skia/src/core/SkDraw_text.cpp',
                 'void Draw::paintMasks(SkZip<const SkGlyph*, SkPoint> accepted, const SkPaint& paint) const {',
                 'void Draw::paintMasks(SkZip<const SkGlyph*, SkPoint> accepted, const SkPaint& paint) const {\n'
                 '#if defined(MOZ_WIDGET_ORBIS)\n'
                 '    size_t slot = 0;\n'
                 '    for (auto [glyph, pos] : accepted) {\n'
                 '        if (glyph == nullptr) {\n'
                 '            SK_ABORT("Orbis glyph consume: null accepted-slot=%zu count=%zu position=(%g,%g)",\n'
                 '                     slot, accepted.size(), double(pos.x()), double(pos.y()));\n'
                 '        }\n'
                 '        ++slot;\n'
                 '    }\n'
                 '#endif')
    replace_once(root, 'toolkit/moz.configure',
                 'def toolkit_choices(target):\n    if target.os == "WINNT":',
                 'def toolkit_choices(target):\n'
                 '    if target.vendor == "orbis":\n'
                 '        return ("cairo-orbis",)\n'
                 '    if target.os == "WINNT":')
    replace_once(root, 'toolkit/moz.configure',
                 'def tree_freetype(target):\n    if target.os == "Android":',
                 'def tree_freetype(target):\n'
                 '    if target.os == "Android" or target.vendor == "orbis":')
    replace_once(root, 'widget/moz.build',
                 'if toolkit in ("android", "cocoa", "gtk", "uikit", "windows"):',
                 'if toolkit in ("android", "cocoa", "gtk", "uikit", "windows", "orbis"):')
    replace_once(root, 'widget/headless/moz.build',
                 'if widget_dir == "gtk":', 'if widget_dir in ("gtk", "orbis"):')
    replace_once(root, 'widget/headless/HeadlessLookAndFeel.h',
                 '#include "nsLookAndFeel.h"\n',
                 '#ifndef MOZ_WIDGET_ORBIS\n#include "nsLookAndFeel.h"\n#endif\n')
    replace_once(root, 'widget/headless/HeadlessLookAndFeelGTK.cpp',
                 '#include "nsStyleConsts.h"\n',
                 '#include "nsStyleConsts.h"\n#ifdef MOZ_WIDGET_ORBIS\n#include "gfxFont.h"\n#endif\n')
    replace_once(root, 'widget/headless/HeadlessLookAndFeel.h',
                 '#if defined(MOZ_WIDGET_GTK)',
                 '#if defined(MOZ_WIDGET_GTK) || defined(MOZ_WIDGET_ORBIS)')
    replace_once(root, 'widget/headless/HeadlessWidget.h',
                 '#if defined(MOZ_WIDGET_GTK)',
                 '#if defined(MOZ_WIDGET_GTK) || defined(MOZ_WIDGET_ORBIS)')
    # Range inputs inspect buttons on down/move, not merely event.mButton.
    replace_once(root, 'widget/headless/HeadlessWidget.h',
                 ('  bool mDestroyed;\n#ifdef MOZ_WIDGET_ORBIS\n  bool mOrbisPrimaryDown = false;\n#endif\n', '  bool mDestroyed;\n'),
                 '  bool mDestroyed;\n#ifdef MOZ_WIDGET_ORBIS\n  bool mOrbisPrimaryDown = false, mOrbisMiddleDown = false;\n#endif\n')
    replace_once(root, 'widget/headless/HeadlessWidget.cpp',
                 ('  event.mRefPoint = aPoint - WidgetToScreenOffset();\n#ifdef MOZ_WIDGET_ORBIS\n'
                  '  if ((msg == eMouseDown || msg == eMouseUp) && aButton == MouseButton::ePrimary) {\n'
                  '    mOrbisPrimaryDown = msg == eMouseDown;\n  }\n'
                  '  event.mButtons = mOrbisPrimaryDown ? MouseButtonsFlag::ePrimaryFlag : MouseButtonsFlag::eNoButtons;\n'
                  '#endif\n  if (msg == eMouseDown || msg == eMouseUp) {',
                  '  event.mRefPoint = aPoint - WidgetToScreenOffset();\n  if (msg == eMouseDown || msg == eMouseUp) {'),
                 '  event.mRefPoint = aPoint - WidgetToScreenOffset();\n#ifdef MOZ_WIDGET_ORBIS\n'
                 '  if ((msg == eMouseDown || msg == eMouseUp) && aButton == MouseButton::ePrimary) {\n'
                 '    mOrbisPrimaryDown = msg == eMouseDown;\n  }\n'
                 '  if ((msg == eMouseDown || msg == eMouseUp) && aButton == MouseButton::eMiddle) {\n'
                 '    mOrbisMiddleDown = msg == eMouseDown;\n  }\n'
                 '  event.mButtons = mOrbisPrimaryDown ? MouseButtonsFlag::ePrimaryFlag : MouseButtonsFlag::eNoButtons;\n'
                 '  if (mOrbisMiddleDown) event.mButtons |= MouseButtonsFlag::eMiddleFlag;\n'
                 '#endif\n  if (msg == eMouseDown || msg == eMouseUp) {')
    old_font_block = ('elif CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                      '    EXPORTS += ["gfxOrbisPlatform.h", "gfxFT2FontBase.h", "gfxFT2Fonts.h"]\n'
                      '    SOURCES += ["gfxOrbisPlatform.cpp", "gfxFT2FontBase.cpp",\n'
                      '                "gfxFT2FontList.cpp", "gfxFT2Fonts.cpp", "gfxFT2Utils.cpp"]\n'
                      '    SOURCE_HEADERS += ["gfxFT2FontList.h", "gfxFT2Utils.h"]\n')
    anchor = 'elif CONFIG["MOZ_WIDGET_TOOLKIT"] in ("cocoa", "uikit"):'
    replace_once(root, 'gfx/thebes/moz.build', (old_font_block + anchor, anchor),
                 'elif CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    EXPORTS += ["gfxFT2FontBase.h", "gfxFT2Fonts.h", "gfxOrbisPlatform.h"]\n'
                 '    SOURCES += ["gfxFT2FontBase.cpp", "gfxFT2FontList.cpp",\n'
                 '                "gfxFT2Fonts.cpp", "gfxFT2Utils.cpp", "gfxOrbisPlatform.cpp"]\n'
                 '    SOURCE_HEADERS += ["gfxFT2FontList.h", "gfxFT2Utils.h"]\n' + anchor)
    for name in ('gfx/thebes/moz.build', 'gfx/2d/moz.build'):
        path = root / name
        old = 'CONFIG["MOZ_WIDGET_TOOLKIT"] in ("android", "gtk")'
        new = 'CONFIG["MOZ_WIDGET_TOOLKIT"] in ("android", "gtk", "orbis")'
        text = path.read_text()
        if old in text:
            path.write_text(text.replace(old, new))
    path = root / 'gfx/skia/moz.build'
    text = path.read_text()
    old = "CONFIG['MOZ_WIDGET_TOOLKIT'] in ('gtk', 'android')"
    if old in text:
        path.write_text(text.replace(old, "CONFIG['MOZ_WIDGET_TOOLKIT'] in ('gtk', 'android', 'orbis')"))
    replace_once(root, 'gfx/skia/moz.build',
                 "if CONFIG['MOZ_WIDGET_TOOLKIT'] == 'gtk':\n    UNIFIED_SOURCES += [",
                 "if CONFIG['MOZ_WIDGET_TOOLKIT'] in ('gtk', 'orbis'):\n    UNIFIED_SOURCES += [")
    replace_once(root, 'gfx/thebes/moz.build',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] in ("android"):',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] in ("android", "orbis"):')
    replace_once(root, 'gfx/2d/moz.build',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "android":',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] in ("android", "orbis"):')
    replace_once(root, 'gfx/2d/2D.h',
                 '#if defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_GTK)\n',
                 '#if defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_GTK) || defined(MOZ_WIDGET_ORBIS)\n')
    replace_once(root, 'modules/libpref/init/StaticPrefList.yaml',
                 '#if defined(MOZ_WIDGET_GTK) || defined(MOZ_WIDGET_ANDROID)\n'
                 '  # -1 = disabled (no preblend, original behavior)',
                 '#if defined(MOZ_WIDGET_GTK) || defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                 '  # -1 = disabled (no preblend, original behavior)')
    # Native Orbis paths are UTF-8. SDK C wide functions operate on uint16_t,
    # while Gecko/private libc++ wchar_t is uint32_t: never pass one to the other.
    path_encoding = 'js/src/vm/CharacterEncoding.cpp'
    anchor = 'JS_PUBLIC_API JS::UniqueChars JS::EncodeNarrowToUtf8(JSContext* cx,'
    helper = ('#ifdef __ORBIS__\n'
              'static JS::UniqueChars CopyOrbisNativeUtf8(JSContext* cx, const char* chars) {\n'
              '  size_t len = strlen(chars);\n'
              '  if (!mozilla::IsUtf8(mozilla::Span(chars, len))) {\n'
              '    JS_ReportErrorNumberASCII(cx, GetErrorMessage, nullptr,\n'
              '                              JSMSG_CANT_CONVERT_TO_NARROW);\n'
              '    return nullptr;\n'
              '  }\n'
              '  auto bytes = mozilla::CheckedInt<size_t>(len) + 1;\n'
              '  if (!bytes.isValid()) { JS_ReportAllocationOverflow(cx); return nullptr; }\n'
              '  auto utf8 = cx->make_pod_array<char>(bytes.value());\n'
              '  if (utf8) memcpy(utf8.get(), chars, bytes.value());\n'
              '  return utf8;\n'
              '}\n#endif\n\n')
    replace_once(root, path_encoding, anchor, helper + anchor)
    for comment in ('  // Convert the narrow multibyte character string to a wide string and then\n',
                    '  // Convert the UTF-8 string to a wide string via EncodeUtf8ToWide() and\n'):
        replace_once(root, path_encoding, comment,
                     '#ifdef __ORBIS__\n  return CopyOrbisNativeUtf8(cx, chars);\n#endif\n' + comment)
    # Orbis does not enable MOZ_PDF_PRINTING: do not compile Cairo's disabled
    # PDF output backend. This does not replace Gecko's HTML/CSS renderer.
    replace_once(root, 'gfx/cairo/cairo/src/moz.build',
                 "if CONFIG['MOZ_WIDGET_TOOLKIT'] not in ('cocoa', 'uikit'):",
                 "if CONFIG['MOZ_WIDGET_TOOLKIT'] not in ('cocoa', 'uikit', 'orbis'):")
    patch_orbis_webrender_freetype(root)
    patch_native_libevent_rng_names(root)
    for name in ('gfx/2d/2D.h', 'gfx/2d/Factory.cpp',
                 'gfx/2d/UnscaledFontFreeType.h', 'gfx/2d/UnscaledFontFreeType.cpp',
                 'gfx/2d/NativeFontResourceFreeType.h', 'gfx/2d/NativeFontResourceFreeType.cpp'):
        path = root / name
        text = path.read_text()
        updated = freetype_guards(text)
        if updated != text:
            path.write_text(updated)
    replace_once(root, 'dom/ipc/PContent.ipdl',
                 '#if defined(ANDROID)\n// Used on Android to pass the list of fonts on the device',
                 '#if defined(ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                 '// FreeType font-list serialization for Android and Orbis.\n'
                 '// Used on Android to pass the list of fonts on the device')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 '#elif defined(ANDROID)\n#  include "gfxAndroidPlatform.h"',
                 '#elif defined(MOZ_WIDGET_ORBIS)\n#  include "gfxOrbisPlatform.h"\n'
                 '#elif defined(ANDROID)\n#  include "gfxAndroidPlatform.h"')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 '#elif defined(ANDROID)\n    sHasVariationFontSupport = gfxAndroidPlatform::CheckVariationFontSupport();',
                 '#elif defined(MOZ_WIDGET_ORBIS)\n'
                 '    sHasVariationFontSupport = gfxOrbisPlatform::CheckVariationFontSupport();\n'
                 '#elif defined(ANDROID)\n    sHasVariationFontSupport = gfxAndroidPlatform::CheckVariationFontSupport();')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 '#elif defined(ANDROID)\n  gPlatform = new gfxAndroidPlatform;',
                 '#elif defined(MOZ_WIDGET_ORBIS)\n  gPlatform = new gfxOrbisPlatform;\n'
                 '#elif defined(ANDROID)\n  gPlatform = new gfxAndroidPlatform;')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '#include <android/log.h>\n#include <dirent.h>\n\n#include "gfxAndroidPlatform.h"',
                 '#include <dirent.h>\n'
                 '#ifdef MOZ_WIDGET_ANDROID\n'
                 '#  include <android/log.h>\n#  include "gfxAndroidPlatform.h"\n#endif')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '#define ALOG(args...) __android_log_print(ANDROID_LOG_INFO, "Gecko", ##args)',
                 '#ifdef MOZ_WIDGET_ANDROID\n'
                 '#  define ALOG(args...) __android_log_print(ANDROID_LOG_INFO, "Gecko", ##args)\n'
                 '#else\n#  define ALOG(...) ((void)0)\n#endif')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '  FontFamily ff;\n#if defined(MOZ_WIDGET_ANDROID)',
                 '  FontFamily ff;\n#if defined(MOZ_WIDGET_ORBIS)\n'
                 '  ff = FindFamily(aFontVisibilityProvider, "Noto Sans"_ns);\n'
                 '#elif defined(MOZ_WIDGET_ANDROID)')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '  if (!useSystemFontAPI)\n#endif\n  {',
                 '  if (!useSystemFontAPI)\n'
                 '#elif defined(MOZ_WIDGET_ORBIS)\n'
                 '  const nsAutoCString androidFontsRoot("/app0/assets/fonts");\n'
                 '#endif\n  {')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 ('#ifdef MOZ_WIDGET_ORBIS\n'
                  '// Actual packaged fallback families; no private-use icon remapping.\n'
                  'static const char* kBaseFonts_Orbis[] = {"Noto Sans", "Noto Sans Symbols2", "Noto Sans Math"};\n'
                  '#endif\n'
                  'using Device = nsIGfxInfo::FontVisibilityDeviceDetermination;',
                  '#ifdef MOZ_WIDGET_ORBIS\n'
                  '// The actual baseline font packaged under /app0/assets/fonts.\n'
                  'static const char* kBaseFonts_Orbis[] = {"Noto Sans"};\n'
                  '#endif\n'
                  'using Device = nsIGfxInfo::FontVisibilityDeviceDetermination;',
                  'using Device = nsIGfxInfo::FontVisibilityDeviceDetermination;'),
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '// Actual packaged fallback families; no private-use icon remapping.\n'
                 'static const char* kBaseFonts_Orbis[] = {"Noto Sans", "Noto Sans Symbols2", "Noto Sans Math", "Noto Color Emoji"};\n'
                 '#endif\n'
                 'using Device = nsIGfxInfo::FontVisibilityDeviceDetermination;')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 'FontVisibility gfxFT2FontList::GetVisibilityForFamily(\n'
                 '    const nsACString& aName) const {\n',
                 'FontVisibility gfxFT2FontList::GetVisibilityForFamily(\n'
                 '    const nsACString& aName) const {\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  return FamilyInList(aName, kBaseFonts_Orbis, std::size(kBaseFonts_Orbis))\n'
                 '             ? FontVisibility::Base : FontVisibility::User;\n'
                 '#else\n')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '  return FontVisibility::User;\n}\n',
                 '  return FontVisibility::User;\n#endif\n}\n')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 'gfxFT2FontList::GetFilteredPlatformFontLists() {\n',
                 'gfxFT2FontList::GetFilteredPlatformFontLists() {\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  nsTArray<std::pair<const char**, uint32_t>> fontLists;\n'
                 '  fontLists.AppendElement(std::make_pair(kBaseFonts_Orbis,\n'
                 '                                         std::size(kBaseFonts_Orbis)));\n'
                 '  return fontLists;\n'
                 '#else\n')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '  return fontLists;\n}\n', '  return fontLists;\n#endif\n}\n')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 'void gfxFT2FontList::FindFontsInOmnijar(FontNameCache* aCache) {\n'
                 '  bool jarChanged = false;',
                 'void gfxFT2FontList::FindFontsInOmnijar(FontNameCache* aCache) {\n'
                 '  RefPtr<nsZipArchive> reader = Omnijar::GetReader(Omnijar::Type::GRE);\n'
                 '  if (!reader) {\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '    printf_stderr("Orbis fonts: no optional GRE font archive; packaged font-directory scan retained\\n");\n'
                 '#endif\n'
                 '    return;\n'
                 '  }\n'
                 '  bool jarChanged = false;')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '    jarFile->GetLastModifiedTime(&mJarModifiedTime);\n'
                 '    if (mJarModifiedTime > LittleEndian::readInt64(cachedModifiedTimeBuf)) {',
                 '    if (!jarFile || NS_FAILED(jarFile->GetLastModifiedTime(&mJarModifiedTime)) ||\n'
                 '        mJarModifiedTime > LittleEndian::readInt64(cachedModifiedTimeBuf)) {')
    replace_once(root, 'gfx/thebes/gfxFT2FontList.cpp',
                 '      "res/fonts/*.ttf$",\n  };\n'
                 '  RefPtr<nsZipArchive> reader = Omnijar::GetReader(Omnijar::Type::GRE);\n',
                 '      "res/fonts/*.ttf$",\n  };\n'
                 '  // reader was verified before consulting optional archive metadata.\n')
    # The optional hardware ML inference process is not part of offline Gecko
    # layout. Do not build its desktop backend or register its IPC implementation.
    for name in ('config/external/moz.build', 'toolkit/components/ml/moz.build',
                 'dom/media/webspeech/moz.build'):
        replace_once(root, name,
                     'if CONFIG["MOZ_WIDGET_TOOLKIT"] != "android":',
                     'if CONFIG["MOZ_WIDGET_TOOLKIT"] not in ("android", "orbis"):')
    for name in ('dom/webidl/moz.build', 'dom/chrome-webidl/moz.build',
                 'dom/events/moz.build'):
        path = root / name
        text = path.read_text()
        old = 'CONFIG["MOZ_WIDGET_TOOLKIT"] != "android"'
        if old in text:
            path.write_text(text.replace(old, 'CONFIG["MOZ_WIDGET_TOOLKIT"] not in ("android", "orbis")'))
    replace_once(root, 'third_party/abseil-cpp/absl/base/internal/sysinfo.cc',
                 '#if defined(__APPLE__) || defined(__FreeBSD__)\n#include <sys/sysctl.h>',
                 '#if defined(__APPLE__) || (defined(__FreeBSD__) && !defined(__ORBIS__))\n#include <sys/sysctl.h>')
    replace_once(root, 'third_party/abseil-cpp/absl/base/internal/sysinfo.cc',
                 '#ifdef __FreeBSD__\n#include <pthread_np.h>',
                 '#ifdef __ORBIS__\n#include <orbis/libkernel.h>\n'
                 '#elif defined(__FreeBSD__)\n#include <pthread_np.h>')
    replace_once(root, 'third_party/abseil-cpp/absl/base/internal/sysinfo.cc',
                 '#ifdef CLOCK_MONOTONIC_RAW',
                 '#if defined(CLOCK_MONOTONIC_RAW) && !defined(__ORBIS__)')
    replace_once(root, 'third_party/abseil-cpp/absl/base/internal/sysinfo.cc',
                 '#elif defined(__FreeBSD__)\n\npid_t GetTID()',
                 '#elif defined(__ORBIS__)\n\n'
                 'pid_t GetTID() { return static_cast<pid_t>(scePthreadGetthreadid()); }\n\n'
                 '#elif defined(__FreeBSD__)\n\npid_t GetTID()')
    replace_once(root, 'third_party/abseil-cpp/absl/base/internal/raw_logging.cc',
                 '#if (defined(__linux__) || defined(__FreeBSD__)) && !defined(__ANDROID__)',
                 '#if (defined(__linux__) || defined(__FreeBSD__)) && !defined(__ANDROID__) && !defined(__ORBIS__)')
    replace_once(root, 'third_party/abseil-cpp/absl/debugging/internal/vdso_support.h',
                 '#ifdef ABSL_HAVE_ELF_MEM_IMAGE\n',
                 '#if defined(ABSL_HAVE_ELF_MEM_IMAGE) && !defined(__ORBIS__)\n')
    # FreeBSD CLOCK_MONOTONIC includes suspend; Linux CLOCK_BOOTTIME is
    # rejected by the real Orbis SDK->firmware clock boundary. Keep failure
    # propagation and the AudioSessionManager uptime assertion intact.
    replace_once(root, 'mozglue/misc/Now.cpp',
                 '#  ifndef CLOCK_BOOTTIME\n  return Nothing();',
                 '#  if defined(__ORBIS__)\n'
                 '  struct timespec ts = {0};\n'
                 '  if (clock_gettime(CLOCK_MONOTONIC, &ts)) return Nothing();\n'
                 '  return Some(TimespecToMilliseconds(ts));\n'
                 '#  elif !defined(CLOCK_BOOTTIME)\n  return Nothing();')
    # No native location provider: fail service creation honestly instead of
    # publishing a null provider that later crashes in UpdateAccuracy.
    replace_once(root, 'toolkit/components/geolocation/GeolocationService.cpp',
                 '  return NS_OK;\n}\n\nGeolocationService::~GeolocationService()',
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  if (!mProvider) {\n'
                 '    obs->RemoveObserver(this, "xpcom-shutdown");\n'
                 '    return NS_ERROR_NOT_AVAILABLE;\n'
                 '  }\n#endif\n'
                 '  return NS_OK;\n}\n\nGeolocationService::~GeolocationService()')
    replace_once(root, 'third_party/msgpack/include/msgpack/predef/other/endian.h',
                 '#           if MSGPACK_OS_BSD\n',
                 '#           if MSGPACK_OS_BSD && !defined(__ORBIS__)\n')
    replace_once(root, 'xpcom/build/BinaryPath.h',
                 '#if defined(__FreeBSD__) || defined(__DragonFly__) || \\\n    defined(__FreeBSD_kernel__) || defined(__NetBSD__) || defined(__OpenBSD__)',
                 '#if !defined(__ORBIS__) && (defined(__FreeBSD__) || defined(__DragonFly__) || \\\n    defined(__FreeBSD_kernel__) || defined(__NetBSD__) || defined(__OpenBSD__))')
    replace_once(root, 'xpcom/build/BinaryPath.h',
                 '#elif defined(__FreeBSD__) || defined(__DragonFly__) || \\\n    defined(__FreeBSD_kernel__) || defined(__NetBSD__)',
                 '#elif defined(__ORBIS__)\n'
                 '  static nsresult Get(char aResult[MAXPATHLEN]) {\n'
                 '    constexpr char path[] = "/app0/eboot.bin";\n'
                 '    static_assert(sizeof(path) <= MAXPATHLEN);\n'
                 '    memcpy(aResult, path, sizeof(path));\n'
                 '    return NS_OK;\n  }\n\n'
                 '#elif defined(__FreeBSD__) || defined(__DragonFly__) || \\\n    defined(__FreeBSD_kernel__) || defined(__NetBSD__)')
    replace_once(root, 'toolkit/xre/nsXREDirProvider.cpp',
                 '#elif defined(XP_UNIX)\n  const char* homeDir = PR_GetEnv("HOME");',
                 '#elif defined(MOZ_WIDGET_ORBIS)\n'
                 '  MOZ_TRY(NS_NewNativeLocalFile(\n'
                 '      nsDependentCString(aLocal ? "/data/orbisfox/cache" : "/data/orbisfox"),\n'
                 '      getter_AddRefs(localDir)));\n'
                 '#elif defined(XP_UNIX)\n  const char* homeDir = PR_GetEnv("HOME");')
    replace_once(root, 'toolkit/crashreporter/google-breakpad/src/common/linux/elfutils.cc',
                 '#if defined(__FreeBSD__)\n#  define ElfW(type) Elf_##type',
                 '#if defined(__FreeBSD__) && !defined(__ORBIS__)\n#  define ElfW(type) Elf_##type')
    replace_once(root, 'toolkit/crashreporter/google-breakpad/src/common/linux/memory_mapped_file.cc',
                 '#include "third_party/lss/linux_syscall_support.h"\n',
                 '#ifdef __ORBIS__\n#include <sys/stat.h>\n#else\n'
                 '#include "third_party/lss/linux_syscall_support.h"\n#endif\n')
    replace_once(root, 'toolkit/crashreporter/google-breakpad/src/common/linux/memory_mapped_file.cc',
                 'namespace google_breakpad {\n',
                 'namespace google_breakpad {\n\n#ifdef __ORBIS__\n'
                 '// Bound POSIX functions, never guessed Linux/FreeBSD syscall numbers.\n'
                 'static int sys_open(const char* path, int flags, mode_t mode) {\n'
                 '  return open(path, flags, mode);\n}\n'
                 'static int sys_close(int fd) { return close(fd); }\n'
                 'static int sys_munmap(void* address, size_t size) { return munmap(address, size); }\n'
                 '#endif\n')
    replace_once(root, 'toolkit/crashreporter/google-breakpad/src/common/linux/memory_mapped_file.cc',
                 '#if defined(__x86_64__) || defined(__aarch64__) || \\\n',
                 '#ifdef __ORBIS__\n'
                 '  struct stat st;\n'
                 '  if (fstat(fd, &st) == -1 || st.st_size < 0) {\n'
                 '#elif defined(__x86_64__) || defined(__aarch64__) || \\\n')
    replace_once(root, 'toolkit/crashreporter/google-breakpad/src/common/linux/memory_mapped_file.cc',
                 '  void* data = sys_mmap(NULL, file_len, PROT_READ, MAP_PRIVATE, fd, offset);',
                 '#ifdef __ORBIS__\n'
                 '  void* data = mmap(NULL, file_len - offset, PROT_READ, MAP_PRIVATE, fd, offset);\n'
                 '#else\n'
                 '  void* data = sys_mmap(NULL, file_len, PROT_READ, MAP_PRIVATE, fd, offset);\n'
                 '#endif')
    # Required Orbis software scrollbar backend, unchanged since the stable
    # 0.56 baseline. Right-stick scrolling is admitted independently of chrome
    # shortcut masks; do not replace this backend with a styling experiment.
    replace_once(root, 'widget/Theme.cpp',
                 '#elif MOZ_WIDGET_GTK\n  return MakeUnique<ScrollbarDrawingGTK>();',
                 '#elif defined(MOZ_WIDGET_ORBIS)\n'
                 '  // Portable software scrollbar style, without GTK native services.\n'
                 '  return MakeUnique<ScrollbarDrawingGTK>();\n'
                 '#elif MOZ_WIDGET_GTK\n  return MakeUnique<ScrollbarDrawingGTK>();')
    replace_once(root, 'xpcom/base/nsDebugImpl.cpp',
                 '#if defined(XP_MACOSX) || defined(__DragonFly__) || defined(__FreeBSD__) || \\\n    defined(__NetBSD__) || defined(__OpenBSD__)',
                 '#if !defined(__ORBIS__) && (defined(XP_MACOSX) || defined(__DragonFly__) || defined(__FreeBSD__) || \\\n    defined(__NetBSD__) || defined(__OpenBSD__))')
    replace_once(root, 'xpcom/base/nsDebugImpl.cpp',
                 '#if defined(__DragonFly__) || defined(__FreeBSD__)\n#  include <sys/user.h>',
                 '#if !defined(__ORBIS__) && (defined(__DragonFly__) || defined(__FreeBSD__))\n#  include <sys/user.h>')
    replace_once(root, 'xpcom/base/nsDebugImpl.cpp',
                 '#elif defined(XP_MACOSX) || defined(__DragonFly__) || defined(__FreeBSD__) || \\\n    defined(__NetBSD__) || defined(__OpenBSD__)',
                 '#elif defined(__ORBIS__)\n  return NS_ERROR_NOT_IMPLEMENTED;\n'
                 '#elif defined(XP_MACOSX) || defined(__DragonFly__) || defined(__FreeBSD__) || \\\n    defined(__NetBSD__) || defined(__OpenBSD__)')
    replace_once(root, 'xpcom/base/nsMemoryReporterManager.cpp',
                 '#elif defined(__DragonFly__) || defined(__FreeBSD__) || defined(__NetBSD__) || \\\n    defined(__OpenBSD__) || defined(__FreeBSD_kernel__)',
                 '#elif defined(__ORBIS__)\n'
                 '// No validated process-memory reporting API; leave reporters unavailable.\n'
                 '#elif defined(__DragonFly__) || defined(__FreeBSD__) || defined(__NetBSD__) || \\\n    defined(__OpenBSD__) || defined(__FreeBSD_kernel__)')
    for name in ('security/nss/lib/freebl/libcrux/karamel/krml/lowstar_endianness.h',
                 'security/nss/lib/freebl/libcrux/karamel/endianness.h',
                 'security/nss/lib/freebl/verified/karamel/include/krml/lowstar_endianness.h'):
        replace_once(root, name,
                     '#if defined(__linux__) || defined(__CYGWIN__) ||',
                     '#if defined(__ORBIS__) || defined(__linux__) || defined(__CYGWIN__) ||')
    replace_once(root, 'mozglue/misc/moz.build',
                 'if CONFIG["TARGET_CPU"].startswith("x86"):',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += ["DemangleSymbol_orbis.cpp"]\n\n'
                 'if CONFIG["TARGET_CPU"].startswith("x86"):')
    # Desktop DSOs can each export Clear; the PS4 static executable cannot.
    # Rename the SoundTouch C ABI symbol through its declaration, so both its
    # definition and every native RLBox function-pointer call use the same name.
    replace_once(root, 'media/libsoundtouch/src/RLBoxSoundTouchFactory.h',
                 'void Clear(soundtouch::SoundTouch* mTimeStretcher);',
                 '#if defined(__ORBIS__)\n'
                 'void Clear(soundtouch::SoundTouch* mTimeStretcher) __asm__("OrbisSoundTouchClear");\n'
                 '#else\nvoid Clear(soundtouch::SoundTouch* mTimeStretcher);\n#endif')
    replace_once(root, 'services/settings/dumps/gen_last_modified.py',
                 '        "browser",\n        "mobile/android",',
                 '        "browser",\n        "orbisfox",\n        "mobile/android",')
    replace_once(root, 'services/settings/dumps/gen_last_modified.py',
                 '    if buildconfig.substs["MOZ_BUILD_APP"] == "browser":',
                 '    if buildconfig.substs["MOZ_BUILD_APP"] in ("browser", "orbisfox"):')
    replace_once(root, 'xpfe/appshell/nsAppShellService.cpp',
                 ('#ifdef MOZ_WIDGET_ORBIS\n'
                  '#include "../../orbisfox/window-provider.inc"\n'
                  '#include "../../orbisfox/create-visible-browser.inc"\n#endif\n\n'
                  '#ifdef MOZ_WIDGET_ORBIS\n'
                  '#include "../../orbisfox/create-visible-browser.inc"\n#endif\n\n'
                  '/*\n * Just do the window-making part of CreateTopLevelWindow\n */',
                  '#ifdef MOZ_WIDGET_ORBIS\n'
                  '#include "../../orbisfox/create-visible-browser.inc"\n#endif\n\n'
                  '/*\n * Just do the window-making part of CreateTopLevelWindow\n */',
                  '/*\n * Just do the window-making part of CreateTopLevelWindow\n */'),
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '#include "../../orbisfox/window-provider.inc"\n'
                 '#include "../../orbisfox/create-visible-browser.inc"\n'
                 '#endif\n\n/*\n * Just do the window-making part of CreateTopLevelWindow\n */')
    replace_once(root, 'toolkit/components/processtools/moz.build',
                 'if toolkit == "gtk" or toolkit == "android":',
                 'if toolkit == "orbis":\n    SOURCES += ["ProcInfo_orbis.cpp"]\n'
                 'elif toolkit == "gtk" or toolkit == "android":')
    replace_once(root, 'uriloader/exthandler/moz.build',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "gtk":\n    UNIFIED_SOURCES += [',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += ["unix/nsMIMEInfoOrbis.cpp"]\n'
                 'elif CONFIG["MOZ_WIDGET_TOOLKIT"] == "gtk":\n    UNIFIED_SOURCES += [')
    replace_once(root, 'third_party/angle/angle_common_gn/moz.build',
                 'if CONFIG["OS_TARGET"] == "Linux":',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += [\n'
                 '        "/third_party/angle/src/common/system_utils_orbis.cpp",\n'
                 '        "/third_party/angle/src/common/system_utils_posix.cpp",\n'
                 '    ]\n\n'
                 'if CONFIG["OS_TARGET"] == "Linux":')
    replace_once(root, 'third_party/angle/src/common/system_utils_posix.cpp',
                 '    return std::string("/tmp");',
                 '#if defined(__ORBIS__)\n    return std::string("/data/orbisfox/cache");\n'
                 '#else\n    return std::string("/tmp");\n#endif')
    replace_once(root, 'third_party/angle/src/common/system_utils_posix.cpp',
                 '#ifdef ANGLE_PLATFORM_FUCHSIA\n    static zx_handle_t me = zx_process_self();',
                 '#if defined(__ORBIS__)\n    timespec value{};\n'
                 '    if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &value) != 0) return 0;\n'
                 '    return value.tv_sec + value.tv_nsec * 1e-9;\n'
                 '#elif defined(ANGLE_PLATFORM_FUCHSIA)\n    static zx_handle_t me = zx_process_self();')
    replace_once(root, 'third_party/angle/src/common/system_utils_posix.cpp',
                 '    gPosixPageFaultHandler = new PosixPageFaultHandler(callback);\n    return gPosixPageFaultHandler;',
                 '#if defined(__ORBIS__)\n    return nullptr; // No ANGLE fault-handler capability on this port.\n'
                 '#else\n    gPosixPageFaultHandler = new PosixPageFaultHandler(callback);\n'
                 '    return gPosixPageFaultHandler;\n#endif')
    # Extend the pinned upstream condition before using it as an insertion
    # anchor; already-prepared trees hid this fresh-checkout ordering requirement.
    replace_once(root, 'widget/moz.build',
                 'if toolkit in {"gtk", "cocoa", "windows", "android", "uikit"}:',
                 'if toolkit in {"gtk", "cocoa", "windows", "android", "uikit", "orbis"}:')
    replace_once(root, 'widget/moz.build',
                 '    "nsPaper.cpp",\n    "nsPaperMargin.cpp",\n',
                 '    # Native paper objects require a supported printer backend.\n')
    replace_once(root, 'widget/moz.build',
                 '    "nsPrinterBase.cpp",\n    "nsPrinterListBase.cpp",\n',
                 '    # Native printer objects are selected below by capability.\n')
    replace_once(root, 'widget/moz.build',
                 'if toolkit in {"gtk", "cocoa", "windows", "android", "uikit", "orbis"}:',
                 'if toolkit != "orbis":\n'
                 '    UNIFIED_SOURCES += [\n        "nsPaper.cpp",\n        "nsPaperMargin.cpp",\n'
                 '        "nsPrinterBase.cpp",\n        "nsPrinterListBase.cpp",\n    ]\n\n'
                 'if toolkit in {"gtk", "cocoa", "windows", "android", "uikit", "orbis"}:')
    replace_once(root, 'build/moz.configure/flags.configure',
                 '            if target.os in ("DragonFly", "FreeBSD", "NetBSD", "OpenBSD"):',
                 '            if target.vendor != "orbis" and target.os in ("DragonFly", "FreeBSD", "NetBSD", "OpenBSD"):')
    replace_once(root, 'widget/moz.build',
                 'if toolkit in ("gtk", "windows", "cocoa", "uikit", "android"):',
                 'if toolkit in ("gtk", "windows", "cocoa", "uikit", "android", "orbis"):')
    replace_once(root, 'widget/Theme.cpp',
                 '#ifdef ANDROID\nalready_AddRefed<Theme> do_CreateNativeThemeDoNotUseDirectly() {\n  // Android doesn\'t have a native theme.',
                 '#if defined(ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                 'already_AddRefed<Theme> do_CreateNativeThemeDoNotUseDirectly() {\n'
                 '  // These toolkits use the genuine shared non-native theme.')
    # OpenOrbis realpath uses __procfdname/readlink (Linux /proc/fd). Resolve
    # through genuine lstat/readlink/getcwd instead, including symlink errors.
    replace_once(root, 'xpcom/io/moz.build', 'if CONFIG["OS_ARCH"] == "WINNT":',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":\n'
                 '    SOURCES += ["/orbisfox/OrbisPath.cpp"]\n'
                 '    EXPORTS.mozilla.orbisfox += ["/orbisfox/OrbisPath.h"]\n\n'
                 'if CONFIG["OS_ARCH"] == "WINNT":')
    for file in ('toolkit/profile/nsToolkitProfileService.cpp', 'xpcom/io/nsLocalFileUnix.cpp'):
        replace_once(root, file, '#include "nsIFile.h"',
                     '#include "nsIFile.h"\n#if defined(__ORBIS__)\n'
                     '#include "mozilla/orbisfox/OrbisPath.h"\n#endif')
    replace_once(root, 'xpcom/io/nsLocalFileUnix.cpp',
                 '  resolved_path_ptr = realpath(mPath.get(), resolved_path);',
                 '#if defined(__ORBIS__)\n'
                 '  resolved_path_ptr = mozilla::orbisfox::ResolveNativePath(mPath.get(), resolved_path);\n'
                 '#else\n  resolved_path_ptr = realpath(mPath.get(), resolved_path);\n#endif')
    replace_once(root, 'toolkit/profile/nsToolkitProfileService.cpp',
                 '#elif defined(XP_UNIX)\n  char fullPath[MAXPATHLEN];\n\n  if (!realpath(aPath, fullPath)) return NS_ERROR_FAILURE;',
                 '#elif defined(__ORBIS__)\n'
                 '  if (!aPath || aPath[0] != \'/\' || !aResult) return NS_ERROR_INVALID_ARG;\n'
                 '  *aResult = nullptr;\n'
                 '  char fullPath[PATH_MAX];\n'
                 '  if (!mozilla::orbisfox::ResolveNativePath(aPath, fullPath)) return NS_ERROR_FAILURE;\n'
                 '  return NS_NewNativeLocalFile(nsDependentCString(fullPath), aResult);\n'
                 '#elif defined(XP_UNIX)\n  char fullPath[MAXPATHLEN];\n\n  if (!realpath(aPath, fullPath)) return NS_ERROR_FAILURE;')
    replace_once(root, 'intl/locale/moz.build',
                 'if toolkit == "windows":\n    DIRS += ["windows"]',
                 'if toolkit == "orbis":\n    DIRS += ["orbis"]\n'
                 'elif toolkit == "windows":\n    DIRS += ["windows"]')
    replace_once(root, 'widget/nsIWidget.cpp',
                 '#ifdef ANDROID\nalready_AddRefed<nsIBidiKeyboard> nsIWidget::CreateBidiKeyboardInner() {',
                 '#if defined(ANDROID) || defined(MOZ_WIDGET_ORBIS)\nalready_AddRefed<nsIBidiKeyboard> nsIWidget::CreateBidiKeyboardInner() {')
    replace_once(root, 'security/moz.build',
                 'gyp_vars["disable_tests"] = 1\n',
                 'gyp_vars["disable_tests"] = 1\n'
                 'gyp_vars["orbisfox_offline"] = int(CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis")\n')
    # Select the genuine upstream static softoken and freebl implementations.
    replace_once(root, 'security/nss/lib/nss/nss.gyp',
                 "    'module': 'nss'",
                 "    'module': 'nss',\n    'orbisfox_offline%': 0")
    replace_once(root, 'security/nss/lib/nss/nss.gyp',
                 "        '<(DEPTH)/lib/libpkix/libpkix.gyp:libpkix',\n      ],\n    },\n    {\n      'target_name': 'nss3',",
                 "        '<(DEPTH)/lib/libpkix/libpkix.gyp:libpkix',\n      ],\n"
                 "      'conditions': [\n        [ 'orbisfox_offline==1', {\n"
                 "          'dependencies!': ['<(DEPTH)/lib/pk11wrap/pk11wrap.gyp:pk11wrap'],\n"
                 "          'dependencies': ['<(DEPTH)/lib/pk11wrap/pk11wrap.gyp:pk11wrap_static'],\n"
                 "        }],\n      ],\n    },\n    {\n      'target_name': 'nss3',")
    replace_once(root, 'security/nss/nss.gyp',
                 "{\n  'includes': [",
                 "{\n  'variables': {'orbisfox_offline%': 0},\n  'includes': [")
    replace_once(root, 'security/nss/nss.gyp',
                 "          'target_name': 'nss_cmds',\n          'type': 'none',\n          'dependencies': [\n            'cmd/certutil/certutil.gyp:certutil',\n            'cmd/pk12util/pk12util.gyp:pk12util',\n          ],\n          'conditions': [",
                 "          'target_name': 'nss_cmds',\n          'type': 'none',\n          'dependencies': [\n            'cmd/certutil/certutil.gyp:certutil',\n            'cmd/pk12util/pk12util.gyp:pk12util',\n          ],\n          'conditions': [\n"
                 "            [ 'orbisfox_offline==1', {\n"
                 "              'dependencies!': [\n"
                 "                'cmd/certutil/certutil.gyp:certutil',\n"
                 "                'cmd/pk12util/pk12util.gyp:pk12util',\n"
                 "              ],\n            }],")
    replace_once(root, 'toolkit/components/telemetry/moz.build',
                 'DIRS = [\n    "pingsender",\n]',
                 'if CONFIG["MOZ_WIDGET_TOOLKIT"] != "orbis":\n'
                 '    DIRS = [\n        "pingsender",\n    ]')
    replace_once(root, 'layout/style/nsMediaFeatures.cpp',
                 '#elif defined(XP_IOS)\n    case StylePlatform::Ios:\n      return true;\n#else',
                 '#elif defined(XP_IOS)\n    case StylePlatform::Ios:\n      return true;\n'
                 '#elif defined(MOZ_WIDGET_ORBIS)\n'
                 '    // No existing StylePlatform value identifies Orbis.\n'
                 '#else')
    replace_once(root, 'netwerk/base/nsNetUtil.cpp',
                 '#ifndef XP_IOS\n#  include "nsIconURI.h"',
                 '#if !defined(XP_IOS) && !defined(MOZ_WIDGET_ORBIS)\n#  include "nsIconURI.h"')
    replace_once(root, 'netwerk/base/nsNetUtil.cpp',
                 '#ifndef XP_IOS\n  if (scheme.EqualsLiteral("moz-icon")) {',
                 '#if !defined(XP_IOS) && !defined(MOZ_WIDGET_ORBIS)\n  if (scheme.EqualsLiteral("moz-icon")) {')
    replace_once(root, 'intl/icu/source/common/unicode/platform.h',
                 '#   if defined(__FreeBSD__)\n#       include <sys/endian.h>',
                 '#   if defined(__FreeBSD__) && !defined(__ORBIS__)\n#       include <sys/endian.h>')
    replace_once(root, 'nsprpub/pr/src/misc/prsystem.c',
                 '#if defined(FREEBSD) || defined(NETBSD) || defined(OPENBSD) || \\\n    defined(DRAGONFLY) || defined(DARWIN)',
                 '#if !defined(__ORBIS__) && (defined(FREEBSD) || defined(NETBSD) || defined(OPENBSD) || \\\n    defined(DRAGONFLY) || defined(DARWIN))')
    replace_once(root, 'nsprpub/pr/src/linking/prlink.c',
                 '#include <string.h>\n',
                 '#include <string.h>\n\n'
                 '#ifdef _PR_ORBIS_STATIC_LINKER\n'
                 '/* Only actual PR_LoadStaticLibrary tables are supported. */\n'
                 '#undef HAVE_DLL\n#undef USE_DLFCN\n#endif\n')
    replace_once(root, 'nsprpub/pr/src/linking/prlink.c',
                 '#ifdef USE_DLFCN\n    error = dlerror();',
                 '#ifdef _PR_ORBIS_STATIC_LINKER\n'
                 '    error = "Orbis supports only registered static libraries and symbols";\n'
                 '#elif defined(USE_DLFCN)\n    error = dlerror();')
    replace_once(root, 'nsprpub/pr/src/linking/prlink.c',
                 '    if (result != NULL) {\n        goto unlock;\n    }\n\n    lm = PR_NEWZAP(PRLibrary);',
                 '    if (result != NULL) {\n        goto unlock;\n    }\n\n'
                 '#ifdef _PR_ORBIS_STATIC_LINKER\n'
                 '    /* Unknown DLLs must fail, never fabricate an empty loaded library. */\n'
                 '    PR_SetError(PR_LOAD_LIBRARY_ERROR, 0);\n'
                 '    DLLErrorInternal(0);\n'
                 '    PR_ExitMonitor(pr_linker_lock);\n'
                 '    return NULL;\n#endif\n\n'
                 '    lm = PR_NEWZAP(PRLibrary);')
    replace_once(root, 'nsprpub/pr/src/misc/prsystem.c',
                 '#if defined(LINUX) || defined(SOLARIS)\n',
                 '#if defined(LINUX) || defined(SOLARIS) || defined(__ORBIS__)\n')
    replace_once(root, 'nsprpub/pr/src/pthreads/ptthread.c',
                 ('#if defined(OPENBSD) || defined(FREEBSD) || defined(DRAGONFLY)\n#include <pthread_np.h>',
                  '#if !defined(__ORBIS__) && (defined(OPENBSD) || defined(FREEBSD) || defined(DRAGONFLY))\n#include <pthread_np.h>'),
                 '#if (!defined(__ORBIS__) || defined(ORBISFOX_HOMEBREW_SDK)) && (defined(OPENBSD) || defined(FREEBSD) || defined(DRAGONFLY))\n#include <pthread_np.h>')
    # The native BSD netdb.h declares the five-argument public _r APIs. NSPR's
    # existing locked, one-argument fallback must have private names instead;
    # do not claim the system exports the public reentrant implementations.
    replace_once(root, 'nsprpub/pr/src/misc/prnetdb.c',
                 '#if defined(ANDROID)\n/* Android\'s Bionic libc system includes prototypes',
                 '#if defined(ANDROID) || defined(ORBISFOX_HOMEBREW_SDK)\n'
                 '/* The native SDK also declares public _r names: keep this locked fallback private. */\n'
                 '/* Android\'s Bionic libc system includes prototypes')
    replace_once(root, 'nsprpub/pr/src/misc/prnetdb.c', '#include <string.h>\n',
                 '#include <string.h>\n#ifdef ORBISFOX_HOMEBREW_SDK\n'
                 '#include "../../../../orbisfox/OrbisNsprNetdb.h"\n#endif\n')
    replace_once(root, 'nsprpub/pr/src/misc/prnetdb.c',
                 '#define GETHOSTBYNAME2(name, af) gethostbyname2(name, af)',
                 '#ifdef ORBISFOX_HOMEBREW_SDK\n'
                 '#define GETHOSTBYNAME2(name, af) OrbisNsprGetHostByName2(name, af)\n'
                 '#else\n#define GETHOSTBYNAME2(name, af) gethostbyname2(name, af)\n#endif')
    replace_once(root, 'nsprpub/pr/src/misc/prnetdb.c',
                 '    return getprotobynumber(number);',
                 '#ifdef ORBISFOX_HOMEBREW_SDK\n'
                 '    return OrbisNsprGetProtoByNumber(number);\n'
                 '#else\n    return getprotobynumber(number);\n#endif')
    # Use upstream's no-native-sampling fallback. Orbis ucontext/register and
    # cross-thread suspension ABIs have not been validated for the profiler.
    for arch in ('__x86_64__', '__aarch64__'):
        replace_once(root, 'mozglue/baseprofiler/public/ProfilerPlatformMacros.h',
                     '#elif defined(__FreeBSD__) && defined(' + arch + ')',
                     '#elif defined(__FreeBSD__) && defined(' + arch + ') && !defined(__ORBIS__)')
    replace_once(root, 'tools/profiler/core/ProfilerUtils.cpp',
                 '#  elif defined(XP_FREEBSD)\n',
                 '#  elif defined(__ORBIS__)\n\n'
                 '#    include <orbis/libkernel.h>\n'
                 'ProfilerThreadId profiler_current_thread_id() {\n'
                 '  return ProfilerThreadId::FromNativeId(\n'
                 '      static_cast<ProfilerThreadId::NativeType>(scePthreadGetthreadid()));\n'
                 '}\n\n'
                 '#  elif defined(XP_FREEBSD)\n')
    replace_once(root, 'tools/profiler/moz.build',
                 'elif CONFIG["OS_TARGET"] == "FreeBSD" and CONFIG["TARGET_CPU"] in ("aarch64", "x86_64"):',
                 'elif CONFIG["OS_TARGET"] == "FreeBSD" and CONFIG["TARGET_CPU"] in ("aarch64", "x86_64") and CONFIG["MOZ_WIDGET_TOOLKIT"] != "orbis":')
    replace_once(root, 'mozglue/baseprofiler/moz.build',
                 'CONFIG["OS_TARGET"] == "FreeBSD"\n',
                 'CONFIG["OS_TARGET"] == "FreeBSD"\n'
                 '            and CONFIG["MOZ_WIDGET_TOOLKIT"] != "orbis"\n')
    replace_once(root, 'ipc/chromium/src/base/message_loop.cc',
                 '#  if defined(XP_DARWIN)\n    pump_ = base::MessagePumpMac::Create();',
                 '#  if defined(MOZ_WIDGET_ORBIS)\n'
                 '    pump_ = new base::MessagePumpDefault();\n'
                 '#  elif defined(XP_DARWIN)\n    pump_ = base::MessagePumpMac::Create();')
    path = root / 'ipc/chromium/src/base/dir_reader_posix.h'
    text = path.read_text()
    updated = text.replace('!defined(__GLIBC__)', '!defined(__GLIBC__) && !defined(__ORBIS__)')
    # Avoid repeated suffixes when preparing an already-patched checkout.
    updated = re.sub(r'(?: && !defined\(__ORBIS__\)){2,}',
                     ' && !defined(__ORBIS__)', updated)
    if updated != text:
        path.write_text(updated)
    replace_once(root, 'ipc/glue/SetProcessTitle.cpp',
                 '#elif defined(__FreeBSD__) || defined(__NetBSD__) || defined(__OpenBSD__) || \\\n    defined(__DragonFly__)',
                 '#elif !defined(__ORBIS__) && (defined(__FreeBSD__) || defined(__NetBSD__) || defined(__OpenBSD__) || \\\n    defined(__DragonFly__))')
    patch_native_ipc_primitives(root)
    patch_native_worker_shutdown(root)
    patch_native_link_gate_debug(root)
    patch_portable_baseline_marker(root)
    replace_once(root, 'ipc/glue/SharedMemoryPlatform_posix.cpp',
                 '#include "SharedMemoryPlatform.h"\n',
                 '#include "SharedMemoryPlatform.h"\n\n#ifdef __ORBIS__\n'
                 '// SDK declarations do not establish memfd/Capsicum/fallocate support.\n'
                 '// posix_fallocate is an ENOSYS stub; use genuine ftruncate fallback.\n'
                 '#  undef HAVE_MEMFD_CREATE\n#  undef HAVE_POSIX_FALLOCATE\n#endif\n')
    replace_once(root, 'ipc/glue/SharedMemoryPlatform_posix.cpp',
                 '#ifdef __FreeBSD__\n#  include <sys/capsicum.h>',
                 '#if defined(__FreeBSD__) && !defined(__ORBIS__)\n#  include <sys/capsicum.h>')
    replace_once(root, 'ipc/glue/GeckoChildProcessHost.cpp',
                 '#  elif defined(MOZ_WIDGET_GTK)\nclass LinuxProcessLauncher',
                 '#  elif defined(MOZ_WIDGET_ORBIS)\n'
                 'class OrbisProcessLauncher : public BaseProcessLauncher {\n'
                 ' public:\n'
                 '  using BaseProcessLauncher::BaseProcessLauncher;\n'
                 ' protected:\n'
                 '  Result<Ok, LaunchError> DoSetup() override {\n'
                 '    return Err(LaunchError("Orbis subprocess launch is unavailable"));\n'
                 '  }\n'
                 '  RefPtr<ProcessLaunchPromise> DoLaunch() override {\n'
                 '    return ProcessLaunchPromise::CreateAndReject(\n'
                 '        LaunchError("Orbis subprocess launch is unavailable"), __func__);\n'
                 '  }\n'
                 '};\n'
                 'typedef OrbisProcessLauncher ProcessLauncher;\n'
                 '#  elif defined(MOZ_WIDGET_GTK)\nclass LinuxProcessLauncher')
    replace_once(root, 'ipc/chromium/src/third_party/libeventcommon.mozbuild',
                 "if CONFIG['TARGET_KERNEL'] == 'Darwin':",
                 "if CONFIG['MOZ_WIDGET_TOOLKIT'] == 'orbis':\n"
                 "    libevent_include_suffix = 'orbis'\n"
                 "elif CONFIG['TARGET_KERNEL'] == 'Darwin':")
    replace_once(root, 'ipc/chromium/src/third_party/moz.build',
                 'if CONFIG["TARGET_KERNEL"] in ("Darwin", "DragonFly", "FreeBSD", "NetBSD", "OpenBSD"):',
                 'if CONFIG["TARGET_KERNEL"] in ("Darwin", "DragonFly", "FreeBSD", "NetBSD", "OpenBSD") and CONFIG["MOZ_WIDGET_TOOLKIT"] != "orbis":')
    replace_once(root, 'ipc/chromium/src/base/platform_thread.h',
                 '#  if defined(XP_LINUX) || defined(XP_OPENBSD) || defined(XP_SOLARIS) || \\\n      defined(__GLIBC__)',
                 '#  if defined(__ORBIS__) || defined(XP_LINUX) || defined(XP_OPENBSD) || defined(XP_SOLARIS) || \\\n      defined(__GLIBC__)')
    replace_once(root, 'ipc/chromium/src/base/platform_thread_posix.cc',
                 '!defined(__GLIBC__)\n#  include <pthread_np.h>',
                 '!defined(__GLIBC__) && !defined(__ORBIS__)\n#  include <pthread_np.h>')
    replace_once(root, 'ipc/chromium/src/base/platform_thread_posix.cc',
                 '#include <sched.h>\n',
                 '#include <sched.h>\n#ifdef __ORBIS__\n#  include <orbis/libkernel.h>\n#endif\n')
    replace_once(root, 'ipc/chromium/src/base/platform_thread_posix.cc',
                 '#elif defined(XP_FREEBSD)\n  return pthread_getthreadid_np();',
                 '#elif defined(__ORBIS__)\n  return scePthreadGetthreadid();\n'
                 '#elif defined(XP_FREEBSD)\n  return pthread_getthreadid_np();')
    # Shared callers must tolerate an unregistered GPU-information contract.
    # Preserve the static component path on every non-Orbis target.
    optional_gfx = ('#ifdef MOZ_WIDGET_ORBIS\n'
                    '#  include "mozilla/widget/OrbisGfxInfo.h"\n'
                    '#  define ORBISFOX_GFXINFO_SERVICE() mozilla::widget::GetOptionalGfxInfo()\n'
                    '#else\n'
                    '#  define ORBISFOX_GFXINFO_SERVICE() mozilla::components::GfxInfo::Service()\n'
                    '#endif\n')
    for name in ('dom/ipc/ContentParent.cpp', 'gfx/thebes/gfxFT2FontList.cpp',
                 'gfx/thebes/gfxPlatform.cpp', 'gfx/thebes/gfxUtils.cpp',
                 'gfx/config/gfxConfigManager.cpp', 'gfx/src/DriverCrashGuard.cpp',
                 'gfx/ipc/GPUChild.cpp', 'gfx/ipc/GPUParent.cpp',
                 'gfx/webrender_bindings/RenderThread.cpp',
                 'toolkit/components/resistfingerprinting/nsUserCharacteristics.cpp'):
        path = root / name
        text = path.read_text()
        if optional_gfx in text:
            continue
        updated, count = re.subn(r'(?<![\w:])(?:mozilla::)?components::GfxInfo::Service\(\)',
                                 'ORBISFOX_GFXINFO_SERVICE()', text)
        if not count:
            raise RuntimeError('Pinned optional GfxInfo patch no longer matches: ' + name)
        position = updated.index('#include ')
        updated = updated[:position] + optional_gfx + updated[position:]
        path.write_text(updated)
    replace_once(root, 'layout/base/nsLayoutUtils.cpp',
                 '#elif defined(MOZ_WIDGET_ANDROID)\n  // Keep consistency with nsLookAndFeel::NativeGetFont.',
                 '#elif defined(MOZ_WIDGET_ORBIS)\n'
                 '  // Match the bundled offline font; no platform font enumeration.\n'
                 '  aName = u"Noto Sans"_ns;\n  aStyle.size = 15;\n'
                 '#elif defined(MOZ_WIDGET_ANDROID)\n  // Keep consistency with nsLookAndFeel::NativeGetFont.')
    replace_once(root, 'gfx/config/gfxConfigManager.cpp',
                 '  if (!NS_SUCCEEDED(mGfxInfo->GetFeatureStatus(aFeature, blockId, &status))) {',
                 '  if (!mGfxInfo || !NS_SUCCEEDED(mGfxInfo->GetFeatureStatus(aFeature, blockId, &status))) {')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp', '#include "gfxPlatform.h"\n',
                 '#include "gfxPlatform.h"\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '#  define ORBISFOX_GFX_FEATURE_STATUS(info, ...) mozilla::widget::GetOptionalGfxFeatureStatus(info, __VA_ARGS__)\n'
                 '#else\n'
                 '#  define ORBISFOX_GFX_FEATURE_STATUS(info, ...) (info)->GetFeatureStatus(__VA_ARGS__)\n'
                 '#endif\n')
    path = root / 'gfx/thebes/gfxPlatform.cpp'
    text = path.read_text()
    updated = text.replace('gfxInfo->GetFeatureStatus(', 'ORBISFOX_GFX_FEATURE_STATUS(gfxInfo, ')
    if updated != text:
        path.write_text(updated)
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 'void gfxPlatform::InitWebGLConfig() {\n'
                 '  if (!XRE_IsParentProcess()) return;\n\n'
                 '  const nsCOMPtr<nsIGfxInfo> gfxInfo = ORBISFOX_GFXINFO_SERVICE();\n',
                 'void gfxPlatform::InitWebGLConfig() {\n'
                 '  if (!XRE_IsParentProcess()) return;\n\n'
                 '  const nsCOMPtr<nsIGfxInfo> gfxInfo = ORBISFOX_GFXINFO_SERVICE();\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  if (!gfxInfo) {\n'
                 '    gfxConfig::GetFeature(Feature::WEBGL).DisableByDefault(\n'
                 '        FeatureStatus::BlockedNoGfxInfo, "No Orbis GPU information/backend",\n'
                 '        "FEATURE_FAILURE_ORBIS_NO_GFX_INFO"_ns);\n'
                 '    gfxVars::SetAllowWebGL(false);\n'
                 '    gfxVars::SetAllowWebgl2(false);\n'
                 '    gfxVars::SetWebglUseHardware(false);\n'
                 '    gfxVars::SetSupportsThreadsafeGL(false);\n'
                 '    gfxVars::SetUseCanvasRenderThread(false);\n'
                 '    return;\n'
                 '  }\n'
                 '#endif\n')
    replace_once(root, 'gfx/thebes/gfxUtils.cpp',
                 '  nsCOMPtr<nsIGfxInfo> gfxInfo = ORBISFOX_GFXINFO_SERVICE();\n\n'
                 '  // Get current values',
                 '  nsCOMPtr<nsIGfxInfo> gfxInfo = ORBISFOX_GFXINFO_SERVICE();\n'
                 '  if (!gfxInfo) {\n'
                 '    // No driver identity to validate native GPU shader binaries.\n'
                 '    gfxVars::SetUseWebRenderProgramBinaryDisk(false);\n'
                 '    return;\n'
                 '  }\n\n'
                 '  // Get current values')
    replace_once(root, 'gfx/thebes/gfxUtils.cpp',
                 '    if (mGfxInfo) {\n'
                 '      mNSResult = mGfxInfo->GetFeatureStatus(mFeature, mFailureId, mStatus);\n'
                 '    }\n',
                 '    if (mGfxInfo) {\n'
                 '      mNSResult = mGfxInfo->GetFeatureStatus(mFeature, mFailureId, mStatus);\n'
                 '    } else {\n'
                 '      mNSResult = NS_ERROR_NOT_AVAILABLE;\n'
                 '    }\n')
    replace_once(root, 'gfx/thebes/gfxPlatform.cpp',
                 '  nsString adapterDesc;\n  gfxInfo->GetAdapterDescription(adapterDesc);',
                 '  if (!gfxInfo) {\n'
                 '    // Keep real screen/headless metrics; no invented adapter identity.\n'
                 '    mozilla::glean::gfx_status::headless.Set(IsHeadless());\n'
                 '    return;\n'
                 '  }\n'
                 '  nsString adapterDesc;\n  gfxInfo->GetAdapterDescription(adapterDesc);')
    replace_once(root, 'gfx/thebes/gfxFailure.h',
                 '#include "nsString.h"', '#include "nsString.h"\n#include "nsDebug.h"')
    replace_once(root, 'gfx/thebes/gfxFailure.h',
                 '  gfxInfo->LogFailure(failure);',
                 '  if (gfxInfo) {\n'
                 '    gfxInfo->LogFailure(failure);\n'
                 '  } else {\n'
                 '    printf_stderr("Graphics failure (no GfxInfo service): %s\\n", failure.get());\n'
                 '  }')
    # Diagnostic-only load checkpoints: preserve navigation behavior/results.
    replace_once(root, 'docshell/base/nsDocShell.cpp', '#include "nsDocShell.h"\n',
                 '#include "nsDocShell.h"\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 'static void OrbisTraceLoad(const char* stage, nsresult result = NS_OK) {\n'
                 '  static uint32_t emitted = 0;\n'
                 '  if (emitted < 64) {\n'
                 '    ++emitted;\n'
                 '    printf_stderr("Orbis load: %s result=0x%08x\\n", stage, unsigned(result));\n'
                 '  }\n'
                 '}\n'
                 '#else\n'
                 '#  define OrbisTraceLoad(...) ((void)0)\n'
                 '#endif\n')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '                              JSContext* aCx) {\n  // generate dictionary for aLoadURIOptions and forward call',
                 '                              JSContext* aCx) {\n'
                 '  OrbisTraceLoad("LoadURIFromScript entered");\n'
                 '  // generate dictionary for aLoadURIOptions and forward call')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '  return LoadURI(aURI, loadURIOptions);\n',
                 '  OrbisTraceLoad("LoadURIFromScript dictionary converted");\n'
                 '  nsresult result = LoadURI(aURI, loadURIOptions);\n'
                 '  OrbisTraceLoad("LoadURIFromScript returned", result);\n'
                 '  return result;\n')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '                             const LoadURIOptions& aLoadURIOptions) {\n',
                 '                             const LoadURIOptions& aLoadURIOptions) {\n'
                 '  OrbisTraceLoad("LoadURI options entered");\n')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '      mBrowsingContext, aURI, aLoadURIOptions, getter_AddRefs(loadState));\n',
                 '      mBrowsingContext, aURI, aLoadURIOptions, getter_AddRefs(loadState));\n'
                 '  OrbisTraceLoad("LoadURI load-state created", rv);\n')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '  rv = InternalLoad(aLoadState);\n  NS_ENSURE_SUCCESS(rv, rv);',
                 '  OrbisTraceLoad("LoadURI InternalLoad entered");\n'
                 '  rv = InternalLoad(aLoadState);\n'
                 '  OrbisTraceLoad("LoadURI InternalLoad returned", rv);\n'
                 '  NS_ENSURE_SUCCESS(rv, rv);')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '                                  Maybe<uint32_t> aCacheKey) {\n',
                 '                                  Maybe<uint32_t> aCacheKey) {\n'
                 '  OrbisTraceLoad("InternalLoad entered");\n')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '  rv = DoURILoad(aLoadState, aCacheKey, getter_AddRefs(req));\n',
                 '  OrbisTraceLoad("DoURILoad entered");\n'
                 '  rv = DoURILoad(aLoadState, aCacheKey, getter_AddRefs(req));\n'
                 '  OrbisTraceLoad("DoURILoad returned", rv);\n')
    replace_once(root, 'docshell/base/nsDocShell.cpp',
                 '  rv = aURILoader->OpenURI(aChannel, aOpenFlags, this);\n',
                 '  OrbisTraceLoad("URI loader OpenURI entered");\n'
                 '  rv = aURILoader->OpenURI(aChannel, aOpenFlags, this);\n'
                 '  OrbisTraceLoad("URI loader OpenURI returned", rv);\n')
    # Trace the actual async file metadata promise, without bypassing it.
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp', '#include "nsFileChannel.h"\n',
                 '#include "nsFileChannel.h"\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '#  include "mozilla/Atomics.h"\n'
                 'static void OrbisTraceFile(const char* stage, const void* channel, nsresult result = NS_OK) {\n'
                 '  static mozilla::Atomic<uint32_t, mozilla::Relaxed> emitted{0};\n'
                 '  uint32_t count = emitted;\n'
                 '  while (count < 80) {\n'
                 '    if (emitted.compareExchange(count, count + 1)) {\n'
                 '      printf_stderr("Orbis file channel: %p %s result=0x%08x\\n", channel, stage, unsigned(result));\n'
                 '      return;\n'
                 '    }\n'
                 '    count = emitted;\n'
                 '  }\n'
                 '}\n'
                 '#else\n'
                 '#  define OrbisTraceFile(...) ((void)0)\n'
                 '#endif\n')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 '                                            bool async) {\n  // we accept',
                 '                                            bool async) {\n'
                 '  OrbisTraceFile("MakeFileInputStream entered", this);\n  // we accept')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 '                                    async ? nsIFileInputStream::DEFER_OPEN : 0);\n',
                 '                                    async ? nsIFileInputStream::DEFER_OPEN : 0);\n'
                 '    OrbisTraceFile("local input stream created", this, rv);\n')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 '                                          nsIChannel** channel) {\n',
                 '                                          nsIChannel** channel) {\n'
                 '  OrbisTraceFile("OpenContentStream entered", this);\n')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 '  stream.swap(*result);\n  return NS_OK;\n',
                 '  stream.swap(*result);\n'
                 '  OrbisTraceFile("OpenContentStream returned", this);\n  return NS_OK;\n')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 'nsresult nsFileChannel::ListenerBlockingPromise(BlockingPromise** aPromise) {\n',
                 'nsresult nsFileChannel::ListenerBlockingPromise(BlockingPromise** aPromise) {\n'
                 '  OrbisTraceFile("ListenerBlockingPromise entered", this);\n')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 '  RefPtr<TaskQueue> taskQueue = TaskQueue::Create(sts.forget(), "FileChannel");\n',
                 '  OrbisTraceFile("metadata task queue created", this);\n'
                 '  RefPtr<TaskQueue> taskQueue = TaskQueue::Create(sts.forget(), "FileChannel");\n')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 '        nsresult rv = self->FixupContentLength(true);\n',
                 '        OrbisTraceFile("metadata worker entered", self.get());\n'
                 '        nsresult rv = self->FixupContentLength(true);\n'
                 '        OrbisTraceFile("metadata worker returned", self.get(), rv);\n')
    replace_once(root, 'netwerk/protocol/file/nsFileChannel.cpp',
                 '  rv = file->GetFileSize(&size);\n',
                 '  OrbisTraceFile("GetFileSize entered", this);\n'
                 '  rv = file->GetFileSize(&size);\n'
                 '  OrbisTraceFile("GetFileSize returned", this, rv);\n')
    # Bounded main-thread DOM script stages, retaining all compilation/execution.
    replace_once(root, 'dom/script/ScriptLoader.cpp', '#include "ScriptLoader.h"\n',
                 '#include "ScriptLoader.h"\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '#  include "nsDebug.h"\n'
                 'static void OrbisTraceScript(const char* stage) {\n'
                 '  static uint32_t emitted = 0;\n'
                 '  if (emitted < 64) {\n'
                 '    ++emitted;\n'
                 '    printf_stderr("Orbis DOM script: %s\\n", stage);\n'
                 '  }\n'
                 '}\n'
                 '#else\n'
                 '#  define OrbisTraceScript(...) ((void)0)\n'
                 '#endif\n')
    replace_once(root, 'dom/script/ScriptLoader.cpp',
                 'nsresult ScriptLoader::ProcessRequest(ScriptLoadRequest* aRequest) {\n',
                 'nsresult ScriptLoader::ProcessRequest(ScriptLoadRequest* aRequest) {\n'
                 '  OrbisTraceScript("ProcessRequest entered");\n')
    replace_once(root, 'dom/script/ScriptLoader.cpp',
                 'nsresult ScriptLoader::EvaluateScriptElement(ScriptLoadRequest* aRequest) {\n',
                 'nsresult ScriptLoader::EvaluateScriptElement(ScriptLoadRequest* aRequest) {\n'
                 '  OrbisTraceScript("EvaluateScriptElement entered");\n')
    replace_once(root, 'dom/script/ScriptLoader.cpp',
                 '  MOZ_ASSERT(!aRequest->IsWasmBytes());\n  nsAutoMicroTask mt;\n  AutoEntryScript aes(aGlobalObject, "EvaluateScript", true);\n',
                 '  MOZ_ASSERT(!aRequest->IsWasmBytes());\n'
                 '  OrbisTraceScript("EvaluateScript microtask scope entered");\n'
                 '  nsAutoMicroTask mt;\n'
                 '  OrbisTraceScript("AutoEntryScript entered");\n'
                 '  AutoEntryScript aes(aGlobalObject, "EvaluateScript", true);\n'
                 '  OrbisTraceScript("AutoEntryScript returned");\n')
    replace_once(root, 'dom/script/ScriptLoader.cpp',
                 '  InstantiateClassicScriptFromAny(cx, options, aRequest, &script,\n                                  introductionScript, erv);\n',
                 '  OrbisTraceScript("classic script instantiation entered");\n'
                 '  InstantiateClassicScriptFromAny(cx, options, aRequest, &script,\n                                  introductionScript, erv);\n'
                 '  OrbisTraceScript("classic script instantiation returned");\n')
    replace_once(root, 'dom/script/ScriptLoader.cpp',
                 '    ExecuteCompiledScript(cx, script, erv);\n',
                 '    OrbisTraceScript("ExecuteCompiledScript entered");\n'
                 '    ExecuteCompiledScript(cx, script, erv);\n'
                 '    OrbisTraceScript("ExecuteCompiledScript returned");\n')
    # Serial hardware is unavailable in this port. Reject the optional service
    # instead of using desktop UART ioctls or fabricating test devices.
    replace_once(root, 'dom/webserial/moz.build',
                 '    or CONFIG["OS_TARGET"] == "FreeBSD"\n',
                 '    or (CONFIG["OS_TARGET"] == "FreeBSD" and CONFIG["MOZ_WIDGET_TOOLKIT"] != "orbis")\n')
    replace_once(root, 'dom/webserial/SerialPlatformService.cpp',
                 '#if !defined(XP_WIN) && !defined(XP_MACOSX) && \\\n',
                 '#if defined(MOZ_WIDGET_ORBIS)\n'
                 'already_AddRefed<SerialPlatformService>\n'
                 'SerialPlatformService::GetInstanceImpl() { return nullptr; }\n'
                 '#elif !defined(XP_WIN) && !defined(XP_MACOSX) && \\\n')
    replace_once(root, 'dom/webserial/SerialPlatformService.cpp',
                 '      nsresult rv = mPtr->Init();',
                 '      nsresult rv = mPtr ? mPtr->Init() : NS_ERROR_NOT_IMPLEMENTED;')
    # Native controller input belongs to the application for now; use upstream's
    # no-device Gamepad fallback rather than importing GTK/udev monitoring.
    replace_once(root, 'dom/gamepad/moz.build',
                 'elif CONFIG["OS_ARCH"] in ("Linux", "FreeBSD", "DragonFly"):',
                 'elif CONFIG["OS_ARCH"] in ("Linux", "FreeBSD", "DragonFly") and CONFIG["MOZ_WIDGET_TOOLKIT"] != "orbis":')
    # Migrate the short-lived generic-protocol variant. Raw IPDL is not
    # preprocessed; keep the Orbis notification in its own selected protocol.
    generic = root / 'widget/generic/PCompositorWidget.ipdl'
    text = generic.read_text()
    restored = text.replace(
        'include protocol PCompositorBridge;\n\n#ifdef MOZ_WIDGET_ORBIS\n'
        'include "mozilla/GfxMessageUtils.h";\n'
        'using mozilla::LayoutDeviceIntSize from "Units.h";\n#endif\n',
        'include protocol PCompositorBridge;\n').replace(
        '  async __delete__();\n#ifdef MOZ_WIDGET_ORBIS\n'
        '  async NotifyClientSizeChanged(LayoutDeviceIntSize aClientSize);\n#endif\n',
        '  async __delete__();\n')
    if restored != text:
        generic.write_text(restored)
    ipdl_anchor = 'else:\n    IPDL_SOURCES = [\n        "generic/PCompositorWidget.ipdl",'
    unsorted_ipdl = ('elif toolkit == "orbis":\n    IPDL_SOURCES = [\n'
                     '        "orbis/PCompositorWidget.ipdl",\n'
                     '        "generic/PlatformWidgetTypes.ipdlh",\n'
                     '        "headless/HeadlessWidgetTypes.ipdlh",\n    ]\n')
    generic_types_ipdl = ('elif toolkit == "orbis":\n    IPDL_SOURCES = [\n'
                          '        "generic/PlatformWidgetTypes.ipdlh",\n'
                          '        "headless/HeadlessWidgetTypes.ipdlh",\n'
                          '        "orbis/PCompositorWidget.ipdl",\n    ]\n')
    replace_once(root, 'widget/moz.build',
                 (unsorted_ipdl + ipdl_anchor, generic_types_ipdl + ipdl_anchor, ipdl_anchor),
                 'elif toolkit == "orbis":\n    IPDL_SOURCES = [\n'
                 '        "headless/HeadlessWidgetTypes.ipdlh",\n'
                 '        "orbis/PCompositorWidget.ipdl",\n'
                 '        "orbis/PlatformWidgetTypes.ipdlh",\n    ]\n' + ipdl_anchor)
    replace_once(root, 'widget/InProcessCompositorWidget.cpp',
                 '#include "nsIWidget.h"\n',
                 '#include "nsIWidget.h"\n#ifdef MOZ_WIDGET_ORBIS\n'
                 '#  include "mozilla/widget/OrbisCompositorWidget.h"\n'
                 '#  include "mozilla/widget/PlatformWidgetTypes.h"\n#endif\n')
    replace_once(root, 'widget/InProcessCompositorWidget.cpp',
                 '  return new InProcessCompositorWidget(aOptions, widget);',
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  if (aInitData.type() == CompositorWidgetInitData::THeadlessCompositorWidgetInitData) {\n'
                 '    return new OrbisCompositorWidget(\n'
                 '        aInitData.get_HeadlessCompositorWidgetInitData(), aOptions,\n'
                 '        static_cast<HeadlessWidget*>(widget));\n'
                 '  }\n#endif\n'
                 '  return new InProcessCompositorWidget(aOptions, widget);')
    replace_once(root, 'gfx/webrender_bindings/Moz2DImageRenderer.cpp',
                 '#elif defined(ANDROID)\n    font.mUnscaledFont = new UnscaledFontFreeType(',
                 '#elif defined(ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                 '    font.mUnscaledFont = new UnscaledFontFreeType(')
    replace_once(root, 'gfx/webrender_bindings/Moz2DImageRenderer.cpp',
                 '#elif defined(ANDROID)\n      FontType::FREETYPE;',
                 '#elif defined(ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                 '      FontType::FREETYPE;')
    # Orbis initially requests full frames, including after resize/cancellation.
    # An empty completion region means release without publishing a failed frame.
    replace_once(root, 'gfx/webrender_bindings/RenderCompositorSWGL.cpp',
                 '#if defined(MOZ_WIDGET_ANDROID)\n  // XXX Add partial present support.',
                 '#if defined(MOZ_WIDGET_ANDROID) || defined(MOZ_WIDGET_ORBIS)\n'
                 '  // XXX Add partial present support.')
    replace_once(root, 'gfx/webrender_bindings/RenderCompositorSWGL.cpp',
                 '      mWidget->EndRemoteDrawingInRegion(mDT, mDirtyRegion);',
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '      mWidget->EndRemoteDrawingInRegion(mDT, LayoutDeviceIntRegion());\n'
                 '#else\n'
                 '      mWidget->EndRemoteDrawingInRegion(mDT, mDirtyRegion);\n#endif')
    replace_once(root, 'gfx/webrender_bindings/RenderCompositorSWGL.cpp',
                 '  // Done with the DT. Hand it back to the widget and clear out any trace of it.\n'
                 '  mWidget->EndRemoteDrawingInRegion(mDT, mDirtyRegion);',
                 '  // Done with the DT. Hand it back to the widget and clear out any trace of it.\n'
                 '#ifdef MOZ_WIDGET_ORBIS\n'
                 '  mWidget->EndRemoteDrawingInRegion(\n'
                 '      mDT, aDirty ? mDirtyRegion : LayoutDeviceIntRegion());\n'
                 '#else\n'
                 '  mWidget->EndRemoteDrawingInRegion(mDT, mDirtyRegion);\n#endif')
    replace_once(root, 'nsprpub/pr/include/md/_freebsd.h',
                 '#include "prthread.h"\n',
                 '#include "prthread.h"\n\n#ifdef __ORBIS__\n#include "_orbis.h"\n#else\n')
    replace_once(root, 'nsprpub/pr/include/md/_freebsd.h',
                 '#endif /* nspr_freebsd_defs_h___ */',
                 '#endif /* !__ORBIS__ */\n#endif /* nspr_freebsd_defs_h___ */')
    # These audited negative Android guards select only optional HW inference
    # actors. Keep generated IPDL and C++ interfaces consistent with their removal.
    for name in ('dom/ipc/PContent.ipdl', 'dom/ipc/ContentParent.cpp',
                 'dom/ipc/ContentParent.h', 'ipc/glue/PUtilityProcess.ipdl',
                 'ipc/glue/UtilityProcessChild.cpp', 'ipc/glue/UtilityProcessChild.h',
                 'ipc/glue/UtilityProcessHost.cpp', 'ipc/glue/UtilityProcessManager.cpp',
                 'ipc/glue/UtilityProcessManager.h', 'ipc/glue/UtilityProcessSandboxing.h'):
        path = root / name
        text = path.read_text()
        updated = re.sub(r'^#(\s*)ifndef ANDROID$',
                         r'#\1if !defined(ANDROID) && !defined(MOZ_WIDGET_ORBIS)',
                         text, flags=re.MULTILINE)
        if updated != text:
            path.write_text(updated)
    # ANGLE's portable Unix program-version inputs are identical on Linux and
    # Android. Select that generated response list for Orbis, not Windows code.
    replace_once(root, 'third_party/angle/angle_program_version_id_gn/moz.build',
                 'if CONFIG["OS_TARGET"] == "Linux":',
                 'if CONFIG["OS_TARGET"] == "Linux" or CONFIG["MOZ_WIDGET_TOOLKIT"] == "orbis":')
    replace_once(root, 'gfx/thebes/gfxFT2Fonts.cpp',
                 '#if defined(MOZ_WIDGET_GTK)',
                 '#if defined(MOZ_WIDGET_ORBIS)\n'
                 '#  include "gfxOrbisPlatform.h"\n'
                 '#  define gfxToolkitPlatform gfxOrbisPlatform\n'
                 '#elif defined(MOZ_WIDGET_GTK)')


if __name__ == '__main__':
    main()
