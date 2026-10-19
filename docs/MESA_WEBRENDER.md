# Experimental Orbis Mesa / hardware WebRender

This experiment is retained on `dev`, not the release branch. The development
branch can host work beyond Mesa; its directory name does not select a renderer.
Mesa remains **experimental, disabled by default, and not ready for promotion**.
Host tests, native links and package extraction checks pass, but the latest
console candidate still crashes during startup. This checkpoint preserves the
OpenOrbis-based experiment before any new-SDK migration; it is not a release.

Console launches established the native Zink/RADV shader gate and earlier
flexible-memory exhaustion. An independent headless-widget default initially
forced software WebRender despite the gate; the selection correction exposed
startup heap corruption. Neither the standalone probe nor that correction
independently proves stable GPU browser-frame publication or a controlled
speedup. The original writer remains unresolved; assertions are preserved.

## Implemented rendering path

- `gecko/orbisfox/moz.configure` registers the default-off raw Gecko configure
  option `--enable-orbis-mesa`. The project build scripts expose it as `--mesa`;
  omitted, they explicitly keep Mesa disabled. Hardware is requested only after
  the native capability gate below, not just because the option was compiled.
- `scripts/patch-gecko-layout.py` supplies guarded static EGL loading through
  the actual `eglGetProcAddress`. It supplies neither a fabricated `PRLibrary`
  nor successful-looking dynamic-library handles. Non-Mesa loading is retained.
- When compiled and genuinely selected as hardware WebRender, the render thread
  requests an actual EGL GLES context with software contexts forbidden.
  `RenderCompositorOrbis` rejects missing/GLES-incompatible contexts and
  unexpected renderer identities. The expectation is native Zink/RADV, not
  llvmpipe or a host simulation.
- WebRender draws using that GL context. The surface is a bounded offscreen
  pbuffer, **not a second window surface or VideoOut presenter**. A GL context
  remains owned by Gecko's render thread.
- `RenderCompositorOrbis::EndFrame()` submits a bounded GLES3 pixel-pack-buffer
  readback. Two slots own their GPU fences; a busy ring coalesces at most one
  latest framebuffer request instead of growing a per-frame queue. A buffer is
  mapped only after a zero-timeout fence poll reports completion. A render-thread
  timer posts a weak-owner `RendererEvent`, so an idle page's final frame still
  completes without depending on the next frame. Teardown cancels the timer.
  When both slots and the latest request are occupied, WebRender applies a
  bounded wait on the oldest real fence (at most 250 ms), rather than issuing
  unbounded GPU work or dropping an idle page's final render. A failed/deadline
  wait requests normal WebRender recovery. This backpressure is not an every-
  frame synchronous readback; its count/time is reported separately.
- Upload-only WebRender updates also receive real completion fences. The last
  completed frame ID advances only after the corresponding GPU fence, preserving
  texture/resource lifetime. Read framebuffer, PBO and all pack state are restored.
  Bottom-origin RGBA is converted directly from a completed PBO into a fresh
  top-origin BGRA surface. Checked conversion rejects invalid dimensions,
  strides, insufficient storage, overflow and overlapping buffers.
- The completed immutable surface goes to `OrbisCompositorWidget`'s existing
  locked frame publication boundary. Pixel conversion, GPU work and native
  copying remain outside that publication lock. A failed frame is not published
  as successful and does not increment the published-frame sequence. Context,
  allocation, readback or publication errors notify Gecko's existing compositor
  recovery path once, rather than leaving a permanently frozen failure latch.
  Empty/minimized widgets are not treated as permanent GPU failures.
- The existing native UI worker remains the sole controller/cursor/VideoOut
  owner. No Gecko, DOM or font objects move to that worker.

This is actual GPU-rendering plumbing, not uploading an already software-painted
webpage to a texture. PBO submission, mapping and CPU conversion remain real
costs; GLES does not guarantee that a driver's PBO submission itself never
blocks. Cumulative enqueue/copy times and actual GPU publication counts are
available only through existing opt-in diagnostics. Host GLES fence/state/pixel
tests are not native performance evidence. Avoiding readback completely would
require a separately validated GPU buffer/fence protocol with the same single
scanout owner.

## Bounded memory and chrome work

The console's flexible pool, not its total physical RAM or address space, bounds
file/shared/stack mappings. The experimental policy uses the genuine available-
flexible-memory query once per second, including with diagnostics OFF. Below
48 MiB it queues Gecko's existing infallible memory-pressure notification; repeat
notifications are limited to one per 15 seconds, and recovery requires 64 MiB.
Failed queries never masquerade as zero memory. No thread touches DOM objects.

Decoded-image cache capacity is 48 MiB, with 5-second unused-surface expiration;
Gecko's own safe unused shared-image unmapping is enabled. Combined media memory
caches are bounded to 32 MiB, and at most one back/forward document is cached
(normal navigation/history still works by reloading evicted documents). These
are cache policies, not fabricated codec support or limits on live ownership.
They cannot guarantee that an active demanding page fits the flexible pool.

Existing opt-in diagnostics add actual shared-view map/unmap/failed-release
counters and a bounded SDK virtual-query census every 30 seconds. Virtual spans
are explicitly not physical usage; no region names/addresses or profile data are
added by the census. A failed unmap never decrements live counters or guesses a
new release address. SDK malloc and separate SDK/GC WB_ONION ownership remain
unchanged; there is no global mmap/allocator replacement or copied RWX path.

Chrome's 30 Hz supervisory UI avoids redundant reflected-property writes as well
as text/attribute writes. A regression checks zero unchanged property writes over
20 ticks in each of 32 lifecycle runs. This reduces avoidable chrome invalidation,
not long uninterrupted content-JavaScript tasks. Interpreted JS, layout and DOM
still share the main thread; this work does not claim to eliminate those stalls.

## Native dependency and selection implementation

- `scripts/build-orbis-mesa.py` builds pinned public Mesa, porting headers and
  real zlib against the browser's private C++ runtime. Its 14-archive closure
  forces only RADV; deduplication removes only byte-identical members. Thin member
  inputs are confined to the build tree and never deleted. Reports bind source,
  producer, configuration, runtime and final archive hashes. The response also
  binds two common runtime objects: real SDK `sysconf` forwarding and the checked
  GNM target table/static ABI-preserving thunks. Both the XUL link gate and final
  executable consume the same objects, not temporary stub implementations.
- A deterministic pinned-source patch removes Orbis window/scanout WSI, uses
  genuine headless implementations and advertises only pbuffer EGL configs.
  Linking does not add another VideoOut owner. Shader disk caching is disabled.
- The broad `orbis-compat` runtime archive is **not linked**. SDK allocation,
  mapping, clock, lock and wide-character implementations retain their owners.
  Native link-map checks confirm SDK regex callers and multibyte converters
  originate together in the original SDK, avoiding the probe's mixed-width ABI.
  The final-browser verifier requires the SDK section to occupy the actual public
  function's address, plus real EGL/RADV/adapter/gate and retained SWGL code
  bodies. It rejects broad compatibility archives and startup GPU-service imports;
  parser doubles exercise these rejection rules without claiming hardware proof.
- Native GNM binding validates all ten actual executable exports before
  publishing any targets. Enumeration errors, permission failures and failed
  module entries remain failures; path fallback retries only ENOENT. No guessed
  module selector, generated executable thunk or VideoOut interposition is used.
- Before XRE, an owned pbuffer test requires the actual Zink/RADV/ORBIS renderer,
  GLES 3, a compiled shader program, a real draw and expected pixel readback.
  `nativeGpuReady` is a read-only privileged bridge capability, false by default.
  Unavailable bindings or ordinary gate failures retain software preferences.
  Driver faults/assertions are not caught or disguised as recoverable success.
- Only this genuine capability permits the native platform past the normal
  headless/missing-desktop-gfxInfo WebRender barriers. Existing explicit disable,
  safe-mode, present blocklist and unrelated feature policies remain in force.
  `nsIWidget` also has an independent headless software-only default. Only when
  the native gate passes does the Orbis Mesa patch let this widget consult the
  genuine global hardware/software choice; it never forces that choice to GPU.
  Non-Mesa builds and failed gates preserve the original headless behavior.
  There is no invented desktop GPU service. JIT and Wasm policies are unchanged.
- The adapter still independently validates the real render-thread context.
  Passing a startup pixel test does not prove a browser frame or performance.
  Existing diagnostics record `graphics` selections, context creation attempts /
  successes, hardware/WebRender feature status, and creation result (0 not
  attempted, 1 ready, 2 no context, 3 make-current failed, 4 not RADV GLES3).
  Policy bits are headless=1, widget acceleration=2, native gate=4, global
  software=8, chosen software=16; config bits are hardware=1, WebRender=2.
  These distinguish policy fallback from context failure. Only increasing
  `gpu-submitted` / `gpu-published` counters establish the actual GPU frame path.

### Dispatch-allocation crash evidence

The first console run after the headless-selection correction failed an existing
SDK heap invariant. A free-bin chunk's size/link words contained the native
address of Mesa's `glthread_nop`. The allocation that detected this was a later
shader-compiler `ralloc_strcat`, not necessarily the writer. Final-ELF inspection
showed matching 13,112-byte GLapi allocation/copy/fill bounds, so a dispatch-count
mismatch is not established. This is distinct from earlier flexible-pool pressure.

The pinned Mesa producer now inserts allocation-neutral observations after the
GLapi allocation and initial copy, and before/after the glthread no-op fill. The
common bridge has a null observer in the strict XUL gate; native startup publishes
its observer before EGL/workers. With existing diagnostics OFF, it performs no
new metadata reads, locking or logging. When ON, it checks the existing SDK bin
invariants under the allocator lock, queries genuine user capacity (respecting
optional guarded allocations), and records at most 128 normal checkpoint lines.
An actual undersized allocation is logged and trapped before the next write;
heap invariant failures retain their existing trap and last-checkpoint context.
It does not change table allocation, original writes, allocator ownership, driver
threading, memory mappings or the diagnostics setting. Instrumentation may
perturb timing; passing these checkpoints is not proof of the eventual cause or
a runtime fix. The package includes both additional exact public patched files.

In the next console run, both dispatch fills passed their immediate checks with
13,136 bytes of genuine capacity for 13,112-byte tables. A later realloc detected
corruption containing different data. This does not prove the dispatch path
innocent: the existing audit checks only bin endpoints, not every interior node.
Mesa now requests before/after checks at every outer allocator API boundary only
while the existing runtime diagnostics setting is ON. Turning that setting OFF
restores the original browsing coverage; there is no new console marker or forced
capture flag. Failure records include current/last-good request pointers and
sizes, without dereferencing freed inputs. Original allocation behavior remains
unchanged; broader checking can perturb timing and is not a performance fix.

`python3 scripts/test-mesa-sdk-allocator.py` runs the existing genuine-SDK matrix,
then compiles the actual pinned, unchanged Mesa `ralloc.c` against the SDK
allocator wrappers and memory primitives. Eight host cases cover diagnostics
ON/OFF, both modeled SDK lock flags, and ordinary/modeled direct backing, always
with mremap unavailable: eight workers each exercise 128 ownership trees,
append/copy/fill, mapped-size shrinking, reparenting, destruction and cross-thread
handoff. This has passed with wrapper/Mesa ASan/UBSan instrumentation. SDK objects
remain unsanitized; Linux OS/direct-memory doubles, missing browser/GPU execution
and host thread/printf ABIs mean it is not a console reproduction.

### Reusable allocator flight recorder

With the existing diagnostics setting ON, the Mesa native runtime also keeps
`allocator-flight.bin` in its unique owned run directory. No new flag is needed
and this code never turns diagnostics on. A fixed 64-byte header plus at most
1,048,576 64-byte records bounds the file to 64 MiB + 64 bytes per run. Normal
writes are batched in 1,024-record blocks; the existing detected heap-fault path
flushes the final batch and fsyncs before preserving its assertion/trap. This is
not a full memory-write tracer or a runtime fix, and it cannot guarantee that an
unrelated fatal signal has flushed the last partial batch.

Records include sequence, immediate caller, input/result, request size,
operation-specific metadata, thread identity, nesting depth, and entry/exit/fault
phase. They cover wrapped allocator APIs, nested SDK map/copy helpers and Mesa
dispatch checkpoints. They never read allocation payloads or unwind stacks. The
original allocator, request semantics, errno and ownership remain unchanged.
The recorder uses static storage and the existing allocator mutex; its sink uses
native file APIs without stdio/heap allocation. Logging/checking can still
perturb timing and I/O; responsiveness must be measured with diagnostics OFF.

Checksums, sequence gaps, attempted/committed sequence counters and I/O failures
make missing or overwritten coverage explicit. A fault audit also reports
`flight-IO-error`. No automatic deletion of prior run evidence is introduced.
The read-only collector retrieves this file only from a metadata-validated run,
not an unattributed flat legacy file. Keep the matching deployment ELF/report.
To inspect an acquired trace locally:

```sh
python3 scripts/decode-allocator-flight.py /path/to/allocator-flight.bin --limit 80
python3 scripts/decode-allocator-flight.py /path/to/allocator-flight.bin \\
  --address 0xADDRESS_FROM_HEAP_AUDIT --limit 80
# Optional actual-code symbol lookup requires the matched ELF/hash and an explicit
# observed runtime load bias, not a guessed link address:
python3 scripts/decode-allocator-flight.py /path/to/allocator-flight.bin \\
  --elf /path/to/matched/orbisfox.elf --expected-elf-sha256 MATCHED_SHA256 \\
  --bias 0xOBSERVED_BIAS --limit 80
```

Address filtering includes requested payload ranges and 16-byte metadata
adjacency; these are candidates, not proof of capacity, liveness or ownership.
Host tests check the actual buffer/checksum layout, batching/generation reset,
serialized multithreaded recording, circular native-file writes, partial/error
writes and disabled/stale-generation behavior. The unchanged genuine-SDK/Mesa
replay also exercises the recorder; host doubles are not console execution.

## Experimental installer and data isolation

After a successful Mesa engine build, use the matching explicit flavor at every
stage; a flavor mismatch is rejected rather than silently packaging software or
an unverified driver closure:

```sh
python3 scripts/build-gecko-app.py --mesa --skip-engine-build
python3 scripts/package-gecko.py --mesa --resource-format omni
python3 scripts/verify-gecko-package.py
# Only with operator authorization and an explicit destination:
python3 scripts/deploy-console.py --host <console-IP> --port 2121
```

The package is `dist/gecko/OrbisFox-Mesa.pkg`, titled **OrbisFox Mesa Test**, with
separate title ID `ORME00001`. It does not replace the normal title/installer.
Native startup chooses `/data/orbisfox/mesa-profile` and `mesa-cache` for the
profile and temporary cache; normal builds retain `gecko-profile` and `cache`.
Privileged startup accepts only those native-owned profile paths, never an
arbitrary environment path. The experimental profile starts separately; it does
not import the working browser's bookmarks, cookies or settings. Existing
app-owned diagnostics/run/control locations under `/data/orbisfox` remain
shared and are not changed by deployment.

The installer carries public Mesa dependency sources, exact patched files,
notices, configuration and hash bindings. Both emitted and extracted SELF
metadata are checked, including the exact 136-byte authentication record and
PAID. Extraction checks every payload/resource hash and the distinct SFO
identity. Upload verifies the entire remote SHA-256 and preserves other
installers/diagnostic markers. Without `--capture`, deployment starts neither a
kernel reader nor a fixture server. Upload never installs or launches the app.

These are preparation/validation mechanisms, not console execution or a
performance result. Complete public-release source/relink sign-off remains open.

## Conservative GL submission policy

Before the first EGL context (including the startup shader gate), the native
Mesa lane sets and reads back `mesa_glthread=false`. Gecko already owns a render
thread; this suppresses only Mesa's optional CPU command-marshalling worker.
Zink/RADV GPU rendering, real shader compilation, GPU synchronization and the
native UI/VideoOut worker remain enabled. An environment setup failure leaves
the GPU gate unavailable rather than proceeding with an unchecked policy.
The operator tested this startup-stability candidate and reported that it still
crashes. Disabling the optional worker is therefore not a demonstrated repair of
the observed corruption. Console stability and GPU frame publication still need
proof. The normal software browser is unchanged. No system configuration is
written.

A retained allocator trace can also be exercised locally:

```sh
python3 scripts/replay-sdk-flight.py /path/to/allocator-flight.bin
```

This links the real pinned SDK allocator with the existing Linux OS doubles,
replays retained outer API geometry, and checks synthetic payloads through each
allocation lifetime. It exercises advertised usable capacity as well as requested
bytes. Earlier overwritten history, native mapping behavior, original client
writes, timing and GPU execution are **not** reproduced. The bounded trace may
contain allocations whose creation predates the retained window; unknown frees
are counted as skipped and unknown realloc inputs seed a new lifetime explicitly.
A passing replay narrows the investigation; it does not clear the console heap.

## Still required before promotion

1. Revalidate every new experimental installer, including dependency/source
   bindings and actual final-ELF implementation/SDK-owner/import checks. Previous
   complete engine/native links and package extraction are not proof of a new
   candidate's console stability or memory-pressure behavior.
2. Console pbuffer/browser execution: pixel orientation/alpha, navigation,
   scrolling, video, context loss, software recovery, IME and teardown. The
   standalone probe and host checks do not establish these browser results.
3. Controlled same-page comparison against SWGL, with diagnostics off for normal
   responsiveness measurements. Record frame times, CPU use and dropped frames;
   retain the software baseline if slower or unstable.
4. Complete source/license/relink bindings for any future distributable binary.
   This experiment does not authorize publication or reuse probe packages.

There is no CPU JIT, WebAssembly, hardware decoder or network fix implied by this
work. Layout, JavaScript and privileged chrome retain their current ownership
and security constraints. Enabling diagnostics, console deployment/installation,
publication and changes outside this experiment are separate operator actions.

## Focused validation

```sh
# Use a prepared pinned Git tree only as read-only fixture input.
# Its original widget/moz.build blob must be cached; tests do not fetch it.
ORBISFOX_GECKO_INPUT=/path/to/prepared/gecko-layout \
  python3 -m unittest discover -s tests -p 'mesa*_test.py' -v
python3 -m unittest discover -s tests -p 'orbis_resource_test.py' -v

for test in tests/browser*_test.js; do node "$test" || exit; done
```

The focused tests include a strict shared-library red/green link for the common
bridge, plus real integer/vector/stack forwarding and missing-target trapping.
They also cover sanitizer-checked pixel conversion, pinned-input drift,
Mesa-only and complete producer byte/mtime idempotence, and source-level default
and ownership guards. The whole producer also exercises the original pinned
widget input, not only already-patched files. Final-link proof parser doubles
cover unresolved/data symbols, incorrect SDK owners, lost software fallback and
forbidden runtime/imports. Producer transformations run in temporary copies.
The actual transformed widget-selection block is also compiled and executed
under ASan/UBSan in Mesa-on and Mesa-off modes, each checking all 32 combinations
of headless/widget/native-gate/global-software/force-selection inputs. It keeps
explicit software and failed-gate behavior while reproducing the old headless
selection failure before the fix.
Without pinned input, the fixture-dependent cases explicitly skip; that is
not equivalent to passing them.

Local validation also cross-compiled nine affected Gecko translation units in
both Mesa-on and Mesa-off modes, including the feature-policy code and bridge.
The bridge header was regenerated with pinned XPIDL. Native startup also compiled
in both modes, with object symbols confirming the GPU gate calls are present only
in the Mesa variant. Borrowed main dependencies were mounted read-only. A separate strict native dependency audit checked actual
EGL/RADV/gate code bodies, unchanged VideoOut imports and original SDK ABI owners.
Host EGL testing verifies that genuine llvmpipe does **not** qualify as the native
GPU. None of these checks proves a rendered GPU browser frame on the PS4.
