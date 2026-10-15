/* OrbisFox native full-Gecko development launcher. */
#include "orbisfox/presenter.h"
#include "orbisfox/artwork.h"
#include "orbisfox/ps4_services.h"
#include "orbisfox/touch_cursor.h"
#include "orbisfox/stick_cursor.h"
#include "orbisfox/pointer_motion.h"
#include "orbisfox/native_ui_loop.h"
#include "orbisfox/stick_scroll.h"
#include "orbisfox/native_keyboard.h"
#include "orbisfox/keyboard_launch.h"
#include "orbisfox/native_stdio.h"
#include "orbisfox/native_audio.h"
#include "orbisfox/native_allocator.h"
#include "orbisfox/run_logs.h"
#include "orbisfox/sdk_heap_memory.h"
#include "../OrbisGCChunkMemory.h"
#include "../OrbisExecutableMemory.h"
#include "../OrbisGlyphDiagnostics.h"
#include "../OrbisTableFault.h"
#include "js/Initialization.h"
#include "orbisfox/jit_memory_probe.h"
#include "orbisfox/browser_controls.h"
static_assert(ORBIS_PAD_BUTTON_OPTIONS == 0x0008 && ORBIS_PAD_BUTTON_CIRCLE == 0x2000 &&
              ORBIS_PAD_BUTTON_CROSS == 0x4000 && ORBIS_PAD_BUTTON_TRIANGLE == 0x1000 &&
              ORBIS_PAD_BUTTON_SQUARE == 0x8000 && ORBIS_PAD_BUTTON_LEFT == 0x0080 &&
              ORBIS_PAD_BUTTON_RIGHT == 0x0020 && ORBIS_PAD_BUTTON_UP == 0x0010 &&
              ORBIS_PAD_BUTTON_DOWN == 0x0040 && ORBIS_PAD_BUTTON_L1 == 0x0400 &&
              ORBIS_PAD_BUTTON_R1 == 0x0800, "Browser control protocol SDK drift");
#include "orbisfox/rust_runtime.h"
#include "mozilla/widget/OrbisFoxHost.h"
#include "mozilla/widget/OrbisTaskDiagnostics.h"
#include "nsXULAppAPI.h"
#include "XREShellData.h"
#include "nsCOMPtr.h"
#include "nsIFile.h"
#include "nspr_link_probe.h"
#include "orbisfox/native_stat.h"
#include "orbisfox/native_clock.h"
#include "orbisfox/native_cpu.h"
#include "orbisfox/native_fcntl.h"
#include "orbisfox/native_network.h"
#include "mozilla/Bootstrap.h"
#include "mozilla/AutoSQLiteLifetime.h"
#include "sqlite3.h"
namespace orbisfox { bool probe_gecko_shared_memory(); bool probe_gecko_cxx_guards(); bool probe_gecko_skia_sync(); }
#include <atomic>
#include <pthread.h>
#include <errno.h>
#include <orbis/libkernel.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>

using namespace orbisfox;
namespace {
constexpr int width = 1280, height = 720;
struct NativeState {
  Presenter* presenter = nullptr;
  Surface surface{};
  Controller controller;
  NativeUiLoop nativeUi;
  uint64_t lastInputSerial=0;
  UiPointerEdge pointerEdges[16]{};unsigned pointerCount=0,pointerNext=0;
  TouchCursor touch;
  TimedStickCursor stickX, stickY;
  PointerPollClock pointerClock;
  double cursorSpeed=1.0;
  StickScroll scroll;
  ScrollDelta scrollDelta;
  NativeKeyboard keyboard;
  KeyboardLaunch keyboardLaunch;
  bool keyboardInputQuarantine = false;
  int x = width / 2, y = height / 2;
  bool exitRequested = false, shellControls = true;
  uint64_t frames = 0, fixtureAfterFrame = UINT64_MAX;
  uint64_t conversionMicros = 0, scanoutMicros = 0, conversionSamples = 0;
  bool fixtureCaptured = false;
  char error[180]{};
  // Monitor reads only these atomics, never controller/widget/Gecko objects.
  pthread_mutex_t monitorLogMutex=PTHREAD_MUTEX_INITIALIZER;
  uint64_t captureGeneration=0;
  std::atomic<bool> monitorStop{false};
  std::atomic<uint64_t> progress{0}, pollCount{0}, monitorFrames{0};
  std::atomic<uint32_t> monitorStage{0};
};
struct MonitorLogLock {
  NativeState& state;
  explicit MonitorLogLock(NativeState& s):state(s){if(pthread_mutex_lock(&state.monitorLogMutex))__builtin_trap();}
  ~MonitorLogLock(){if(pthread_mutex_unlock(&state.monitorLogMutex))__builtin_trap();}
};
void* monitor(void* opaque) {
  auto& state = *static_cast<NativeState*>(opaque);
  FILE* output=nullptr;uint64_t outputGeneration=0;
  uint64_t lastMissingGlyphDraws=0;
  for (unsigned sample = 0; !state.monitorStop.load(); ++sample) {
    {
      MonitorLogLock lock(state);
      const auto currentGeneration=native_diagnostics_generation();
      if(!native_diagnostics_enabled() || outputGeneration!=currentGeneration){if(output)fclose(output);output=nullptr;}
      bool newOutput=false;
      if(native_diagnostics_enabled() && !output){output=fopen(NativeRunLogPath("gecko-heartbeat.log").c_str(),"a");outputGeneration=currentGeneration;newOutput=output!=nullptr;}
      if(output){
  if(newOutput){fputs("Diagnostic samples only; atomic event snapshots and clocks, no Gecko-object calls, input polling or exit.\n"
        "stages: 0=outside-host 1=poll-entered 2=poll-returned 3=present-entered "
        "4=pixel-copy-complete 5=VideoOut-entered 6=present-returned 7=timer-entered 8=timer-returned\n", output);
  fputs("event stages: 1=entered 2=native-wait 3=woke 4=callback-entered 5=callback-returned 6=no-event; atomics sampled independently.\n"
        "SDK monotonic1 now translates to native4; raw native4 sampled separately.\n", output);}
    const auto events = mozilla::widget::GetOrbisEventDiagnostics();
    struct timespec mono{}, alternate{};
    const int monoResult = clock_gettime(CLOCK_MONOTONIC, &mono);
    const int alternateResult = orbisfox::firmware_clock_gettime(4, &alternate);
    fprintf(output, "sample=%u progress=%llu polls=%llu frames=%llu stage=%u event=%u scheduled=%llu callbacks=%llu "
            "native_us=%llu sdk_mono_id=%d rc=%d mono=%lld.%09ld clock4_rc=%d clock4=%lld.%09ld\n", sample,
            (unsigned long long)state.progress.load(), (unsigned long long)state.pollCount.load(),
            (unsigned long long)state.monitorFrames.load(), state.monitorStage.load(), events.stage,
            (unsigned long long)events.schedules, (unsigned long long)events.callbacks,
            (unsigned long long)sceKernelGetProcessTime(), CLOCK_MONOTONIC, monoResult,
            (long long)mono.tv_sec, mono.tv_nsec, alternateResult, (long long)alternate.tv_sec, alternate.tv_nsec);
    const auto ui=state.nativeUi.stats();
    fprintf(output,"native-ui sample=%u polls=%llu scanouts=%llu latest-frame=%llu cursor=%d,%d failed=%d wait-mean-us=%llu wait-max-us=%llu; no Gecko access\n",sample,
      (unsigned long long)ui.polls,(unsigned long long)ui.scanouts,(unsigned long long)ui.frameSerial,ui.x,ui.y,ui.failed,
      (unsigned long long)(ui.scanouts?ui.scanoutMicros/ui.scanouts:0),(unsigned long long)ui.maxScanoutMicros);
    const auto tasks=mozilla::widget::GetOrbisTaskDiagnostics();
    const uint64_t taskNow=sceKernelGetProcessTime();
    fprintf(output,"main-task sample=%u depth=%u active-age-us=%llu events=%llu long-events=%llu last-us=%llu max-inclusive-us=%llu last-long-name=%s detail-us=%llu detail-name=%s\n",
      sample,tasks.depth,(unsigned long long)(tasks.activeStart&&taskNow>=tasks.activeStart?taskNow-tasks.activeStart:0),
      (unsigned long long)tasks.events,(unsigned long long)tasks.longEvents,(unsigned long long)tasks.lastMicros,(unsigned long long)tasks.maxMicros,tasks.lastLongName,(unsigned long long)tasks.lastDetailedMicros,tasks.lastDetailedName);
    const auto glyphs=orbisfox::missing_glyph_stats();
    if(glyphs.draws!=lastMissingGlyphDraws){
      fprintf(output,"missing-glyph sample=%u draws=%llu codepoints-first64=",sample,(unsigned long long)glyphs.draws);
      for(auto codepoint:glyphs.codepoints)if(codepoint)fprintf(output,"U+%06x,",codepoint);
      fputc('\n',output);lastMissingGlyphDraws=glyphs.draws;
    }
    if(sample%10==0){
      const auto jit=orbisfox::orbis_jit_memory_stats();
      fprintf(output,"jit-memory sample=%u ready=%d claimed=%d shared-reserved=%zu committed=%zu phase=%u rc=0x%x\n",sample,jit.ready,jit.claimed,jit.reservedBytes,jit.committedBytes,jit.failedPhase,unsigned(jit.lastResult));
      const auto gc=orbisfox::gc_chunk_memory_stats();
      const auto sdk=orbisfox::sdk_direct_heap_stats();size_t available=0;
      const int32_t memoryResult=sceKernelAvailableFlexibleMemorySize(reinterpret_cast<size_t>(&available));
      fprintf(output,"memory sample=%u gc-direct-maps=%zu gc-direct-bytes=%zu gc-alloc-failures=%llu gc-map-failures=%llu sdk-direct-bytes=%zu flexible-rc=0x%x flexible-available-MiB-rounded=%zu\n",
        sample,gc.mappings,gc.bytes,(unsigned long long)gc.allocationFailures,(unsigned long long)gc.mapFailures,sdk.bytes,unsigned(memoryResult),available);
    }
    fflush(output);
      }
    }
    sceKernelUsleep(1000000);
  }
  if(output)fclose(output);
  return nullptr;
}
int clamp(int n, int a, int b) { return n < a ? a : n > b ? b : n; }
bool poll(void* opaque, int32_t* x, int32_t* y, uint32_t* buttons) {
  auto& state = *static_cast<NativeState*>(opaque);
  state.monitorStage.store(1); state.progress.fetch_add(1); state.pollCount.fetch_add(1);
  if(state.nativeUi.running()){
    if(state.nativeUi.stats().failed)return false;
    const auto input=state.nativeUi.consumeInput();
    state.pointerNext=0;state.pointerCount=input.edgeCount;for(unsigned i=0;i<input.edgeCount;++i)state.pointerEdges[i]=input.edges[i];
    state.x=input.x;state.y=input.y;state.scrollDelta={};*x=input.x;*y=input.y;*buttons=0;
    if(state.exitRequested||browser_exit_chord(input.pad.buttons,state.shellControls)){
      state.exitRequested=true;return false;
    }
    if(state.keyboardLaunch.pending()&&input.serial!=state.lastInputSerial)
      state.keyboardLaunch.tick(input.pad.connected?input.pad.buttons:UINT32_MAX,sceKernelGetProcessTime(),
        [&](const char16_t* draft,uint32_t length,bool address){
          const bool opened=state.keyboard.setAddressMode(address)&&state.keyboard.session.open(draft,length);
          log("Native IME: deferred init after two fresh release samples open=%d",int(opened));return opened;
        });
    state.lastInputSerial=input.serial;
    const bool paused=state.keyboard.session.active()||state.keyboardInputQuarantine;
    if(!state.keyboard.session.active()&&!state.keyboardLaunch.pending()&&input.pad.connected&&input.pad.buttons==0)
      state.keyboardInputQuarantine=false;
    state.nativeUi.pauseInput(state.keyboard.session.active()||state.keyboardInputQuarantine);
    if(input.pad.connected&&!paused){*buttons=browser_buttons(input.pad.buttons,state.shellControls)&~input.chromeMask;state.scrollDelta=input.chromeModal?ScrollDelta{}:input.wheel;}
    state.monitorStage.store(2);state.progress.fetch_add(1);return true;
  }
  OrbisPadData input{};
  *buttons = 0;
  state.scrollDelta = {};
  if (state.controller.poll(input)) {
    if (browser_exit_chord(input.buttons, state.shellControls)) {
      state.exitRequested = true;
      return false;
    }
    if(state.keyboardLaunch.pending()) state.keyboardLaunch.tick(input.buttons,sceKernelGetProcessTime(),
      [&](const char16_t* draft,uint32_t length,bool address){
        const bool opened=state.keyboard.setAddressMode(address)&&state.keyboard.session.open(draft,length);
        log("Native IME: deferred init after two all-buttons-released samples open=%d",int(opened));return opened;
      });
    if (state.keyboard.session.active() || state.keyboardInputQuarantine) {
      state.scroll.reset();
      state.stickX.reset(); state.stickY.reset(); state.pointerClock.reset();
      state.touch.reset();
      if (!state.keyboard.session.active() && !state.keyboardLaunch.pending() && input.buttons == 0) state.keyboardInputQuarantine = false;
      *x = state.x; *y = state.y;
      state.monitorStage.store(2); state.progress.fetch_add(1);
      return true;
    }
    const uint64_t inputNow=sceKernelGetProcessTime();
    const auto timing=state.pointerClock.update(inputNow);
    if(timing.discontinuity){state.touch.reset();state.stickX.reset();state.stickY.reset();}
    state.scrollDelta = state.scroll.update(input.rightStick.x, input.rightStick.y, inputNow);
    state.x = clamp(state.x + state.stickX.update(input.leftStick.x,state.cursorSpeed,timing.elapsed), 10, width - 11);
    state.y = clamp(state.y + state.stickY.update(input.leftStick.y,state.cursorSpeed,timing.elapsed), 10, height - 11);
    TouchPoint contacts[2]{};
    size_t count = input.touch.fingers > 2 ? 2 : input.touch.fingers;
    for (size_t i = 0; i < count; ++i)
      contacts[i] = {input.touch.touch[i].x, input.touch.touch[i].y, input.touch.touch[i].finger};
    // Stick movement owns the pointer while deflected; resting touch contacts
    // must not fight it. Re-anchor touch after a page stall or input-mode switch.
    if(stick_cursor_delta(input.leftStick.x)||stick_cursor_delta(input.leftStick.y))state.touch.reset();
    else state.touch.update(contacts, count, width, height, state.x, state.y);
    state.x = clamp(state.x, 10, width - 11);
    state.y = clamp(state.y, 10, height - 11);
    *buttons = browser_buttons(input.buttons, state.shellControls);
  } else {
    if(state.keyboardLaunch.pending())state.keyboardLaunch.tick(UINT32_MAX,sceKernelGetProcessTime(),
      [](const char16_t*,uint32_t,bool){return false;}); // Disconnected controller cannot authorize a launch.
    state.touch.reset();
    state.scroll.reset();
    state.stickX.reset(); state.stickY.reset(); state.pointerClock.reset();
  }
  *x = state.x; *y = state.y;
  state.monitorStage.store(2); state.progress.fetch_add(1);
  return true;
}
void hostLog(void* opaque, const char* message) {
  auto& state = *static_cast<NativeState*>(opaque);
  state.progress.fetch_add(1);
  if (strncmp(message, "Gecko timer callback entered:", 29) == 0) state.monitorStage.store(7);
  if (strncmp(message, "Gecko timer callback returned:", 30) == 0) state.monitorStage.store(8);
  log("%s", message);
  if (strncmp(message, "ERROR:", 6) == 0)
    snprintf(state.error, sizeof(state.error), "%s", message);
}
void checkpoint(void* opaque, uint32_t passed) {
  auto& state = *static_cast<NativeState*>(opaque);
  state.fixtureAfterFrame = state.frames < UINT64_MAX - 2 ? state.frames + 2 : UINT64_MAX;
  state.fixtureCaptured = false;
  log("Gecko fixture checkpoint: %u/8 passed; capture after two more published frames", passed);
}
bool present(void* opaque, const uint8_t* bgra, uint32_t w, uint32_t h, uint32_t stride) {
  auto& state = *static_cast<NativeState*>(opaque);
  state.monitorStage.store(3); state.progress.fetch_add(1);
  if (!bgra || !w || !h || w > width || h > height || stride < w * 4 || stride > 8192) return false;
  const uint64_t conversionStart = sceKernelGetProcessTime();
  // Full frames overwrite every pixel; clearing first is an unnecessary pass.
  const Surface target=state.nativeUi.running()?state.nativeUi.beginFrame():state.surface;
  if (w != width || h != height) fill_rect(target, 0, 0, width, height, {16,24,40,255});
  if (!blit_bgra_opaque(target, bgra, w, h, stride)) return false;
  state.conversionMicros += sceKernelGetProcessTime() - conversionStart;
  ++state.conversionSamples;
  const bool fixtureCapture = !state.fixtureCaptured && state.frames >= state.fixtureAfterFrame;
  const auto captureGeneration=native_diagnostics_generation();
  const bool capture = native_diagnostics_enabled() && (state.frames == 0 || fixtureCapture || state.captureGeneration!=captureGeneration);
  uint64_t hash = UINT64_C(14695981039346656037);
  for (uint32_t row = 0; row < h; ++row) {
    const auto* source = bgra + size_t(row) * stride;
    for (uint32_t column = 0; capture && column < w; ++column) {
      const auto* p = source + size_t(column) * 4;
      if (capture)
        for (unsigned channel = 0; channel < 4; ++channel) {
          hash ^= p[channel]; hash *= UINT64_C(1099511628211);
        }
    }
  }
  state.monitorStage.store(4); state.progress.fetch_add(1);
  if (capture) {
    state.captureGeneration=captureGeneration;
    const char* label = fixtureCapture ? "fixture-frame" : "first-frame";
    log("Gecko %s BGRA snapshot: %ux%u stride=%u FNV1a=%016llx", label, w, h, stride, (unsigned long long)hash);
    FILE* image = fopen(orbisfox::NativeRunLogPath(fixtureCapture ? "gecko-fixture-frame.bgra" :
                        "gecko-first-frame.bgra").c_str(), "wb");
    bool saved = image != nullptr;
    if (image) {
      for (uint32_t row = 0; row < h; ++row)
        if (fwrite(bgra + size_t(row) * stride, 4, w, image) != w) saved = false;
      if (fclose(image) != 0) saved = false;
    }
    log("Gecko %s raw BGRA capture: %s", label, saved ? "SAVED" : "FAILED");
    if (fixtureCapture) state.fixtureCaptured = true;
  }
  if(state.nativeUi.running()){
    // Copy complete before publishing; no Gecko/Surface references escape.
    if(native_diagnostics_enabled()&&state.error[0])text(target,20,675,state.error,1,{255,140,36,255});
    if(!state.nativeUi.publishFrame())return false;
    ++state.frames;state.monitorFrames.store(state.frames);
    if(state.frames%120==0){
      const auto ui=state.nativeUi.stats();
      log("Gecko published frames=%llu conversion-mean-us=%llu main-scanout-wait-us=0 worker-scanout-wait-mean-us=%llu",(unsigned long long)state.frames,
        (unsigned long long)(state.conversionSamples?state.conversionMicros/state.conversionSamples:0),
        (unsigned long long)(ui.scanouts?ui.scanoutMicros/ui.scanouts:0));
    }
    state.monitorStage.store(6);state.progress.fetch_add(1);return true;
  }
  fill_rect(state.surface, state.x - 8, state.y - 1, 17, 3, {255,140,36,255});
  fill_rect(state.surface, state.x - 1, state.y - 8, 3, 17, {255,140,36,255});
  if (native_diagnostics_enabled()&&state.error[0]) text(state.surface, 20, 675, state.error, 1, {255,140,36,255});
  state.monitorStage.store(5); state.progress.fetch_add(1);
  if (state.frames < 4) log("Gecko native present: VideoOut entered frame=%llu", (unsigned long long)state.frames);
  const uint64_t scanoutStart = sceKernelGetProcessTime();
  if (!state.presenter->present(state.surface)) return false;
  state.scanoutMicros += sceKernelGetProcessTime() - scanoutStart;
  if (state.frames < 4) log("Gecko native present: VideoOut returned frame=%llu", (unsigned long long)state.frames);
  ++state.frames;
  state.monitorFrames.store(state.frames);
  if (state.frames % 120 == 0)
    log("Native frame timing: frames=%llu conversion-mean-us=%llu scanout-wait-mean-us=%llu; not JS/layout timing",
        (unsigned long long)state.frames, (unsigned long long)(state.conversionMicros/state.conversionSamples),
        (unsigned long long)(state.scanoutMicros/state.frames));
  state.monitorStage.store(6); state.progress.fetch_add(1);
  return true;
}
}

int main() {
  setvbuf(stdout, nullptr, _IONBF, 0);
  orbisfox::set_table_fault_writer(orbisfox::native_write_heap_audit);
  const Diagnostics diagnostics = run_platform_probes(true);
  NativeState state;
  state.surface = {static_cast<uint8_t*>(malloc(size_t(width) * height * 4)), width, height, size_t(width) * 4};
  if (!state.surface.pixels) { log("Gecko launcher: surface allocation failed"); return EXIT_FAILURE; }
  state.presenter = &videoout_presenter();
  if (!state.presenter->init(width, height)) { log("Gecko launcher: VideoOut failed"); return EXIT_FAILURE; }
  if (!load_artwork("/app0/assets/splash.rgba", state.surface))
    fill_rect(state.surface, 0, 0, width, height, {16,24,40,255});
  state.presenter->present(state.surface);
  hide_splash_screen();
  if (access("/data/orbisfox/skip-controller", F_OK) != 0) state.controller.init();
  state.touch.set_resolution(state.controller.touch_resolution_x(), state.controller.touch_resolution_y());
  // Retain branded splash while real startup gates run. No development overlay.
  text(state.surface, 40, 660, "Starting OrbisFox...", 2, {235,242,255,255});
  state.presenter->present(state.surface);
  mkdir("/data/orbisfox/cache", 0700);
  mkdir("/data/orbisfox/gecko-profile", 0700);
  setenv("TMPDIR", "/data/orbisfox/cache", 1);
  setenv("HOME", "/data/orbisfox/gecko-profile", 1);
  // The pinned engine ignores the historical remote-autostart preference.
  // Use its supported nonofficial-build switch before any XRE initialization.
  if (setenv("MOZ_FORCE_DISABLE_E10S", "1", 1) != 0) {
    log("ERROR: cannot configure supported single-process Gecko mode errno=%d", errno);
    return EXIT_FAILURE;
  }
  const bool verboseLogging = access("/data/orbisfox/verbose-gecko-log", F_OK) == 0;
  setenv("MOZ_LOG", !native_diagnostics_enabled() ? "" : verboseLogging ?
      "timestamp,sync,SharedMemory:5,nsStreamPump:5,nsThreadPool:5,DocumentChannel:5,nsRedirect:5,ProcessIsolation:5,ScriptLoader:5,nsSocketTransport:5,nsHostResolver:5,nsHttp:3,mozStorage:5,cookie:5,userfonts:4" :
      "timestamp,nsHostResolver:3,nsHttp:2,mozStorage:2,cookie:2,userfonts:4", 1);
  log("Gecko detailed logging: %s; native lifecycle/security/failure logs retained", verboseLogging ? "verbose synchronous opt-in" : "bounded lower-volume buffered default");
  setenv("ORBISFOX_LOG_DIR",orbisfox::native_run_log_directory(),1);
  // Runtime diagnostics owns the log sink through LogModule::SetLogFile.
  // An environment override would prevent changing/closing it in Settings.
  unsetenv("MOZ_LOG_FILE");
  setenv("MOZ_HEADLESS", "1", 1);
  setenv("MOZ_HEADLESS_WIDTH", "1280", 1);
  setenv("MOZ_HEADLESS_HEIGHT", "720", 1);
  for (const char* path : {"/app0/gecko", "/app0/gecko/chrome.manifest", "/app0/gecko/greprefs.js",
                           "/app0/assets/gecko-startup.js", "/app0/assets/offline.html",
                           "/app0/assets/fonts/NotoSans-Regular.ttf"}) {
    struct stat info{};
    errno = 0;
    const int rc = stat(path, &info);
    const int error = errno;
    log("Gecko filesystem: %s stat=%d errno=%d mode=0x%x bytes=%lld", path,
        rc, error, unsigned(info.st_mode), static_cast<long long>(info.st_size));
  }
  errno = 0;
  const int directoryResult = chdir("/app0/gecko");
  const int directoryError = errno;
  log("Gecko filesystem: chdir GRE=%d errno=%d", directoryResult, directoryError);
  state.shellControls = access("/data/orbisfox/diagnostic-only", F_OK) != 0;
  mozilla::widget::SetOrbisFoxHostCallbacks({&state, present, poll, hostLog, checkpoint});
  char name[] = "/app0/eboot.bin", greFlag[] = "-g", appFlag[] = "-a";
  char gre[] = "/app0/gecko", fileFlag[] = "-f", script[] = "/app0/assets/gecko-startup.js";
  char* argv[] = {name, greFlag, gre, appFlag, gre, fileFlag, script, nullptr};
  log("Gecko XPConnect native initialization begin; pthread gate=%s", diagnostics.threads);
  log("Native CPU affinity: available=%d; SDK-compatible sysconf configured=%ld online=%ld; actual native query, no fixed CPU count",
      native_available_processor_count(), sysconf(_SC_NPROCESSORS_CONF), sysconf(_SC_NPROCESSORS_ONLN));
  const bool rustReady = probe_rust_runtime();
  log("Full-Gecko Rust ABI/allocation gate: %s", rustReady ? "PASS" : "FAIL");
  const bool filesystemReady = probe_native_filesystem_metadata();
  const bool nsprReady = rustReady && filesystemReady && probe_orbisfox_static_nspr(
      [](const char* message) { log("%s", message); });
  const bool clocksReady = nsprReady && probe_gecko_clocks();
  const bool cxxGuardsReady = clocksReady && probe_gecko_cxx_guards();
  const bool skiaSyncReady = cxxGuardsReady && probe_gecko_skia_sync();
  const bool allocatorReady = skiaSyncReady && probe_native_allocator();
  log("SDK heap bin audit: full startup checks; browsing checks at realloc, SDK copy and discard boundaries; arenas=%llu; no metadata writes or null skipping; not a crash fix claim",(unsigned long long)native_allocator_audited_arena_count());
  const bool stdioReady = allocatorReady && probe_native_stdio_locks();
  const bool fileLocksReady = stdioReady && probe_native_file_locks();
  const bool sharedMemoryReady = fileLocksReady && probe_gecko_shared_memory();
  // Capability selection must precede JS_Init, not happen in chrome JS.
  const bool audioReady=prepare_native_audio();
  fprintf(stdout,"Native AudioOut default endpoint ready=%d (silence/complete/close probe)\n",audioReady);fflush(stdout);
  const bool jitReady=sharedMemoryReady && prepare_native_jit_memory();
  if(!jitReady){JS::DisableJitBackend();log("Native baseline JIT: capability gate unavailable; supported interpreter fallback selected before JS_Init");}
  const bool heapDebugRequested = native_diagnostics_enabled() && access("/data/orbisfox/heap-debug", F_OK) == 0;
  bool heapDiagnosticsReady = !heapDebugRequested;
  if (sharedMemoryReady && heapDebugRequested) {
    const int fd = open(orbisfox::NativeRunLogPath("heap-diagnostics.bin").c_str(), O_CREAT|O_EXCL|O_RDWR, 0600);
    heapDiagnosticsReady = fd >= 0 && ftruncate(fd, 64+4096*64+768) == 0 && configure_native_allocator_diagnostics(fd);
    if (!heapDiagnosticsReady && fd >= 0) close(fd);
    // Successful fd stays owned until process exit, including late destructors.
    log("Native heap diagnostics: %s; real SDK backing, requested-size guards, 196608-block tracking limit / 16MiB records, 512-block / 8MiB requested-backing quarantine, v2 coverage trace. Saturation retains existing guards but new pointers use raw SDK without guards. Realloc copies/quarantines in this mode; slower diagnostic run, not a production fix.", heapDiagnosticsReady ? "ACTIVE" : "FAILED");
  } else log("Native heap diagnostics: off (opt-in /data/orbisfox/heap-debug); direct SDK allocator retained");
  bool greReady = false;
  if (sharedMemoryReady && heapDiagnosticsReady) {
    nsCOMPtr<nsIFile> greDirectory;
    const nsresult rv = XRE_GetFileFromPath(gre, getter_AddRefs(greDirectory));
    bool isDirectory = false;
    nsresult kindResult = NS_ERROR_FAILURE;
    if (NS_SUCCEEDED(rv)) kindResult = greDirectory->IsDirectory(&isDirectory);
    log("Gecko GRE directory: XRE_GetFileFromPath=0x%x IsDirectory=0x%x directory=%d",
        unsigned(rv), unsigned(kindResult), int(isDirectory));
    greReady = NS_SUCCEEDED(rv) && NS_SUCCEEDED(kindResult) && isDirectory;
  }
  // Use Firefox's real bootstrap owner, as its xpcshell stub does. In
  // particular BootstrapImpl owns AutoSQLiteLifetime across all XPCOM work.
  mozilla::Bootstrap::UniquePtr bootstrap;
  log("Gecko SQLite lifetime before bootstrap: rc=%d", mozilla::AutoSQLiteLifetime::getInitResult());
  if (greReady) {
    const int sqliteLogResult = sqlite3_config(SQLITE_CONFIG_LOG,
        +[](void*, int code, const char* message) {
          log("SQLite native diagnostic: code=%d primary=%d message=%s", code, code & 255, message);
        }, nullptr);
    log("SQLite real diagnostic callback registration: %d", sqliteLogResult);
    auto bootstrapResult = mozilla::GetBootstrap();
    if (bootstrapResult.isOk()) bootstrap = bootstrapResult.unwrap();
    else log("ERROR: Gecko singleton bootstrap creation failed");
  }
  const int sqliteResult = mozilla::AutoSQLiteLifetime::getInitResult();
  const bool sqliteVfsReady = bool(bootstrap) && sqliteResult == SQLITE_OK && install_sqlite_file_lock_adapter();
  const bool bootstrapReady = bool(bootstrap) && sqliteResult == SQLITE_OK && sqliteVfsReady;
  log("Gecko bootstrap / SQLite lifetime gate: owner=%d sqlite=%d ready=%d", int(bool(bootstrap)), sqliteResult, int(bootstrapReady));
  const bool networkReady = bootstrapReady && prepare_native_network();
  log("Native baseline JIT policy: capability=%d; Baseline/RegExp enabled only after own shared-code RW/RX proof; Ion/Wasm deferred",int(jitReady));
  mozilla::widget::SetOrbisFoxHostCallbacks({&state, present, poll, hostLog, checkpoint, networkReady,
    [](void* opaque) { static_cast<NativeState*>(opaque)->exitRequested = true; },
    [](void* opaque, int32_t* x, int32_t* y) {
      const auto& delta = static_cast<NativeState*>(opaque)->scrollDelta;
      *x = delta.x; *y = delta.y;
    },
    [](void* opaque, const char16_t* draft, uint32_t length, bool address) {
      auto& state = *static_cast<NativeState*>(opaque);
      const bool queued = !state.keyboard.session.active() && state.keyboardLaunch.queue(draft,length,address,sceKernelGetProcessTime());
      if (queued){state.keyboardInputQuarantine=true;state.nativeUi.pauseInput(true);}
      log("Native IME: queued=%d; %s",int(queued),queued?"awaiting controller release; initialization not yet attempted":"HTML fallback");
      return queued;
    },
    [](void* opaque, char16_t* output, uint32_t capacity) -> uint32_t {
      auto& state = *static_cast<NativeState*>(opaque);
      if(state.keyboardLaunch.pending())return KeyboardSession::Running;
      if(state.keyboardLaunch.failed())return KeyboardSession::Error;
      auto& session = state.keyboard.session;
      const auto status = session.poll();
      if (status == KeyboardSession::Accepted && capacity >= KeyboardSession::limit + 1)
        for (size_t i=0; i<=KeyboardSession::limit; ++i) output[i] = session.text()[i];
      return status;
    },
    [](void* opaque) {auto& state=*static_cast<NativeState*>(opaque);state.keyboardLaunch.cancel();state.keyboard.session.cancel();},
    [](void* opaque) -> uint32_t {return static_cast<NativeState*>(opaque)->keyboard.confirmButton();},
    [](void* opaque,double speed) {auto& state=*static_cast<NativeState*>(opaque);state.cursorSpeed=speed;state.nativeUi.setSpeed(speed);},
    [](void* opaque,const char* wire){return static_cast<NativeState*>(opaque)->nativeUi.setChrome(wire);},
    [](void* opaque,char* out,uint32_t capacity){return static_cast<NativeState*>(opaque)->nativeUi.takeChromeAction(out,capacity);},
    [](void* opaque,int32_t* x,int32_t* y,bool* down,uint32_t* button){auto& state=*static_cast<NativeState*>(opaque);if(state.pointerNext>=state.pointerCount)return false;const auto& edge=state.pointerEdges[state.pointerNext++];*x=edge.x;*y=edge.y;*down=edge.down;*button=edge.button;return true;},
    [](void*){return native_diagnostics_enabled();},
    [](void* opaque,bool value,char* out,uint32_t capacity){
      auto& state=*static_cast<NativeState*>(opaque);MonitorLogLock lock(state);
      if(!set_native_diagnostics_enabled(value))return false;
      close_log();return copy_native_run_log_path(out,capacity,"gecko-load.log");
    }});
  XREShellData shellData{};
  log("Gecko XPConnect entry: verified GRE directory=%d bootstrap=%d", int(greReady), int(bootstrapReady));
  pthread_t monitorThread{};
  const int monitorResult = bootstrapReady ? pthread_create(&monitorThread, nullptr, monitor, &state) : -1;
  log("Gecko independent heartbeat probe: create=%d; samples only, not a recovery thread", monitorResult);
  const bool uiReady=bootstrapReady&&state.nativeUi.start(state.surface,state.controller.touch_resolution_x(),state.controller.touch_resolution_y(),{
    &state,
    [](void* opaque,UiPadSample& sample){
      OrbisPadData raw{};if(!static_cast<NativeState*>(opaque)->controller.poll(raw))return false;
      sample.buttons=raw.buttons;sample.leftX=raw.leftStick.x;sample.leftY=raw.leftStick.y;
      sample.rightX=raw.rightStick.x;sample.rightY=raw.rightStick.y;sample.contactCount=raw.touch.fingers>2?2:raw.touch.fingers;
      for(size_t i=0;i<sample.contactCount;++i)sample.contacts[i]={raw.touch.touch[i].x,raw.touch.touch[i].y,raw.touch.touch[i].finger};
      return true;
    },
    [](void* opaque,const Surface& image){return static_cast<NativeState*>(opaque)->presenter->present(image);},
    [](void*){return uint64_t(sceKernelGetProcessTime());},
    [](void*,uint32_t usecs){sceKernelUsleep(usecs);}});
  log("Independent native controller/cursor/VideoOut loop: %s; latest completed RGBA only, no Gecko access; native chrome interaction/menu independent; DOM page actions queued to Gecko main",uiReady?"STARTED":"FAILED");
  const int result = uiReady ? bootstrap->XRE_XPCShellMain(7, argv, environ, &shellData) : EXIT_FAILURE;
  state.nativeUi.stop(); // join before reusing controller/Presenter on ended screen
  state.monitorStop.store(true);
  if (monitorResult == 0) pthread_join(monitorThread, nullptr);
  mozilla::widget::SetOrbisFoxHostCallbacks({});
  bootstrap.reset(); // Dispose in libxul, then shut SQLite down after XPCOM.
  // Never steal a live engine's code arena if JS_ShutDown has not run yet.
  if(!orbisfox::orbis_jit_memory_stats().claimed)orbisfox::shutdown_orbis_executable_memory();
  if (heapDebugRequested && heapDiagnosticsReady)
    log("Native heap diagnostic shutdown drain/trace IO: %s", checkpoint_native_allocator_diagnostics() ? "PASS (not whole-heap proof)" : "FAIL");
  log("Gecko SQLite lifetime shutdown result: %d", mozilla::AutoSQLiteLifetime::getInitResult());
  log("Gecko XPConnect shutdown returned %d; %llu VideoOut frames", result, (unsigned long long)state.frames);
  // Keep VideoOut/controller operational if startup fails or the OS exit request
  // returns. Never fall back to a raw process exit after graphics initialization.
  if (state.exitRequested) request_system_exit();
  state.shellControls = false; // Native ended/error screen always keeps Options exit.
  for (;;) {
    fill_rect(state.surface, 0, 0, width, height, {16,24,40,255});
    text(state.surface, 40, 40, "OrbisFox stopped", 3, {255,140,36,255});
    char message[120];
    snprintf(message, sizeof(message), "Unable to continue (code %d). Please restart OrbisFox.", result);
    text(state.surface, 40, 120, message, 2, {235,242,255,255});
    if(native_diagnostics_enabled())text(state.surface, 40, 190, "Diagnostics were saved for this session.", 2, {174,191,214,255});
    text(state.surface, 40, 260, "Options: Exit. You can also close OrbisFox using the PS button.", 2, {174,191,214,255});
    if (native_diagnostics_enabled()&&state.error[0]) text(state.surface, 40, 340, state.error, 1, {255,140,36,255});
    state.presenter->present(state.surface);
    int32_t x, y; uint32_t buttons;
    state.exitRequested = false;
    if (!poll(&state, &x, &y, &buttons)) {
      request_system_exit();
      sceKernelUsleep(300000);
    }
    sceKernelUsleep(16000);
  }
}
