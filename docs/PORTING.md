# Architecture and porting guide

This is the current implementation map, not the original pre-Gecko proposal.
Historical bring-up notes and raw captures are retained locally under ignored
`build/`; they must not be mistaken for the source alpha's capabilities.

## Actual pipeline

```text
Privileged XHTML/JS chrome ─── native host bridge (chrome only)
        │
        ├── up to 3 nonremote Gecko content contexts
        │      HTML/CSS + SpiderMonkey interpreter + Gecko/NSS networking
        │      software FFmpeg decoding → Cubeb/AudioOut
        │
        └── Gecko layout → Software WebRender/SWGL
                          → owned compositor snapshot
                          → frame mailbox
                          → native UI/VideoOut worker → console display
```

`gecko/` is the **canonical overlay**, not a full vendored Gecko checkout.
The pinned public upstream source is fetched into `.deps/gecko-layout/` and
patched/copied by the producers. Maintain changes in the overlay or patch
scripts and prove producer idempotence. Direct edits to `.deps/` are temporary.

## Build lanes

- `build/gecko-spidermonkey/`: standalone runtime/JS regression lane. Still
  supplies required build/test inputs; do not delete it just because full Gecko
  now exists. `scripts/configure-gecko.py` builds missing private runtimes.
- `build/gecko-layout/`: actual full engine, NSS/NSPR, layout, SWGL and media.
  Produced by `scripts/build-gecko-layout.py`; not a host Firefox executable.
- `build/gecko-app/`, `dist/gecko/`: native ELF/conversion/package stage.
  `scripts/build-gecko-app.py` folds actual engine/codec objects and checks the
  final native symbol closure, ABI bridges and source binding.
- `build/media-codecs/{host,native}/`: isolated FFmpeg 9.0.2 static libraries.
  The host lane proves real decoder behavior under sanitizers; it is not linked
  into the PS4 executable. All defined native globals are namespaced to avoid
  collision with Gecko's retained FFVPX implementation.
- `build/gecko-host/`, `build/swgl/`: host regression dependencies, not PS4 proof.
- `dist/OrbisFox.pkg`: optional retained standalone baseline, never the current
  browser package. Fresh source checkouts need not include any old binary.

The C frontend's FreeBSD target spelling is not proof of ABI compatibility.
OpenOrbis has a musl-derived runtime, firmware-specific APIs and distinct clock,
thread, allocator and file-descriptor contracts. Private libc++/Rust sysroots,
SDK overlays and explicit final-ELF checks are intentional.

## Main thread vs native worker

Gecko/DOM and browser-shell JS stay on the main thread. Content tabs are
nonremote. A long script/layout task can therefore block actual browser actions.
A native worker independently polls the controller, renders pointer/limited
chrome feedback and presents cached frames. It receives immutable POD scenes
and bounded commands—not live Gecko objects or font handles.

`include/orbisfox/native_ui_loop.h`, `src/native_ui_loop.cpp` and
`src/native_chrome.cpp` describe ownership. The frame mailbox rotates exclusive
writer/mailbox/reader slots; pixel copying and scanout happen outside the small
swap lock. The worker is joined before shared resources are released. Native
IME, retained for later repair, temporarily pauses scanout and requires fresh
input before opening. The dev browser now defaults to a main-thread custom
keyboard, using real Gecko field editors with validated page ownership. It
masks passwords and blocks pointer/native chrome through button release on
close. R2 is Enter while typing; it must not leak into Forward after closing.
See `docs/HOMEBREW_SDK.md` for scope, cancel semantics and remaining limits.

Do not move DOM work onto this worker or introduce nested event pumping to
make an action appear immediate. Proper process/thread isolation is future work.

## Memory and native runtime

The genuine SDK allocator remains the owner. Recursive locking and a bounded
realloc-copy correction preserve its semantics. Only tracked SDK anonymous
whole maps and separately owned GC arena/nursery chunks use cached game direct
memory (**WB_ONION, type 0**). Global mmap, file mappings, stacks, JIT pages and
partial shrinking allocations do not share that shortcut.

Native clock translation is necessary: the SDK and firmware clock identifiers
are not interchangeable. Process uptime must be real and advancing. The 0.68
CPU-count adapter queries genuine current-thread affinity; unsupported/failed
queries preserve a conservative original-SDK fallback. Console validation of its
practical scheduling effect is still needed.

## JavaScript and graphics

`OrbisExecutableMemory` implements an owned 64 MiB arena, 16 KiB page accounting
and W^X transitions. Native startup attempts an actual own-code execution gate
before `JS_Init`. Tested firmware denies shared-code creation with EPERM; the
backend is disabled honestly. Baseline/RegExp may only use a proven native gate;
Ion and WebAssembly are not enabled. A Linux memfd test cannot change this fact.

Software WebRender/SWGL rasterizes on the CPU. VideoOut scanout is not accelerated
page rendering. The historical Piglet presenter/sample is not a supported GPU
WebRender or WebGL backend; arbitrary shader compilation and the required driver
interfaces remain unsolved. GPU rendering and hardware video decoding would be
separate substantial integrations, not preference changes.

## Media and networking

Real FFmpeg APIs are bound through 64 typed wrapper entries with strict version
and function checks. Added decoder archives include H.264/AAC and preserve
VP8/VP9/Opus/Vorbis/FLAC/MP3 support. FFT functions remain real. Capability queries
must follow actual decoder availability, never hand-written optimistic MIME lists.

`cubeb_orbis.cpp` and `src/ps4/native_audio.cpp` provide genuine AudioOut, 48 kHz
S16 stereo output/resampling. Preserve consumption-before-reuse and join-before-
close. HAL lifecycle and process uptime are needed for Gecko media controls.

HTTP/HTTPS and WebSockets use Gecko's networking implementation. The controlled
WebSocket page still failed to open on the console; that is not proof that the
protocol is absent, nor proof it works end-to-end. YouTube chat was reported
working, while YouTube/Twitch livestreams still stall. Missing DRM or WebAssembly
can independently prevent some players from working.

## Shell, profile and permissions

- `browser-shell-model.js`: bounded data models and validated settings.
- `browser-shell-host.js`: privileged host, content ownership and navigation,
  transactional persistence and bounded opt-in observations.
- `browser-shell-ui.js`, `browser.xhtml`, `browser.css`: chrome UI and state.
- `gecko-startup.js`: profile reload followed by enforced native policy.

Explicitly load saved preferences before UI and explicitly save `prefs.js` on
changes. Preserve rollback when writes fail. App history is a bounded separate
list, not Places or deletion of cookies/cache. Avoid roots retaining old documents.
Website color scheme uses Gecko's content-only preference; fullscreen uses real
trusted content/focus/permissions, not a CSS simulation or permission bypass.

Chrome has a system principal; web content must never receive its bridge or
objects. Keep same-origin image policy, referrers, permissions, trusted controller
input and bounded link-opening behavior. Current in-process browsing lacks a
content sandbox; that limitation cannot be fixed by claiming principal checks
provide process isolation.

## Performance work that needs evidence

Interpreter-only JS, software rasterization, software decode and shared-main-
thread scheduling compete on relatively weak Jaguar CPU cores. Frame conversion/
copying, allocator serialization, profile I/O and diagnostics may add cost.
We have multi-second main-thread stalls, not a trustworthy percentage breakdown.
The last-long-task label is not a sampled CPU profile, and growing heaps alone
are not a demonstrated leak. Keep functional load failures separate from speed.

Useful future work: bounded event-loop timing/profiling; supported executable
memory; hardware decode/rendering; frame conversion/copy budgets; cold/warm
network timing; MSE/live-player errors; enforceable content isolation; memory
pressure and recovery. Preserve correctness/security while measuring changes.
