# New SDK runtime evaluation (`dev`)

The operator has authorized an in-place SDK conversion in the existing `dev`
checkout. Conversion is **in progress**, not a working native-SDK browser release.
The standalone C probe passed on console, including the revised return-Home path;
this does not prove that the browser's C++ shutdown or Mesa crash is fixed. The
working browser checkout remains untouched. No third browser tree is used, no JIT
work is included, and retained rollback/crash artifacts and thin archive inputs
must not be deleted to make room without approval.

## Pinned inputs

- SDK: <https://github.com/ps4-homebrew-dev/sdk>, **v0.2.1**,
  commit `ecc8347aa20d7b3423405a5e94d7ab119485160d`.
- Release archive: `ps4-homebrew-sdk.zip`, **4,471,594 bytes**,
  SHA-256 `fc021d7e6d53dcd1c73c87af4e0897012c62ffa5276289c0c3d898d71be80310`.
- Download/extraction is confined to ignored `.deps/`; expanded SDK is about
  **14 MB**. Inventory is checked against the pinned archive, including rejection
  of additional files and symlinks. No system installation or package manager.
- The release's own compiler wrapper chooses the installed LLVM. The build report
  records its version; this is not yet a pinned complete browser toolchain.

The SDK links its startup/supplementary libc with the console's real
`libSceLibcInternal`, kernel, Sysmodule and Net libraries. It is not a differently
named build of OpenOrbis musl. Current browser allocator interception and private
C++ runtime must **not** simply be mixed with it. Its latest pinned commit removes
C11 thread-library support after Mesa issues; native pthreads remain available.

## Build locally

```sh
python3 scripts/fetch-homebrew-sdk.py
python3 -m unittest discover -s tests -p homebrew_sdk_test.py
python3 scripts/build-homebrew-sdk-probe.py --package
```

Each build owns a new `build/homebrew-sdk-probe/<build-id>/` directory. The pointer
`build/homebrew-sdk-probe/latest-build.json` names its report. The new SDK produces
the ELF, converted SELF, SFO, GP4 and PKG. Existing OpenOrbis **PkgTool is used only
as an independent package validator/extractor**, never for the probe's native link.
The report retains source hashes, SDK inventory identity, commands, native link
map, declared system dependencies, emitted SELF checks and extracted payload checks.
No build command uploads, installs, launches, changes diagnostics or deletes outputs.

## What the probe checks

- Real CRT constructor dispatch before `main`.
- Native monotonic/realtime clocks, resolution, sleep and CPU-count query.
- malloc/calloc, reported usable capacity, aligned allocation and genuine realloc
  grow/shrink preservation, including the historical 262144 → 50201 boundary.
- Four simultaneous workers: compiler TLS identity/initialization, pthread keys
  and destructors, once initialization, recursive mutexes and concurrent allocation.
- Condition-variable timeout using a real realtime deadline.
- File write/sync/readback, guarded `fstat` ABI and lock/unlock calls. These lock
  calls **do not establish cross-process exclusion or SQLite correctness**.
- Anonymous shared memory, descriptor cloning, aligned offset/read-only views,
  byte coherence, RW ↔ R protection changes and owned-view teardown. It does not
  assume unaligned offsets must fail, and never requests executable memory.

The app is **OrbisFox SDK Probe**, title ID `OSDK00001`, distinct from both browser
installers and prior probes. When explicitly installed/launched by the operator,
it writes only new unique run directories under `/data/orbisfox/sdk-probe/`.
No existing profile, bookmarks, history, cache, markers or logs are removed. There
is no GUI; a successful run is expected to return Home. Inspect `runtime.log` for
`RESULT PASS`, not the exit animation alone. A watchdog exits with failure after
about 30 seconds if the tested runtime remains responsive enough to schedule it.

### Isolated CommonDialog/IME test

```sh
python3 scripts/build-homebrew-sdk-probe.py --dialog --package
```

This keeps the same pinned SDK/CRT and **OSDK00001** title, with probe version
**00.02** and title **OrbisFox SDK Dialog Probe**. Installing it replaces the
older SDK probe, not either browser. It selects dialog checks instead of the
allocator/filesystem/shared-memory workload; it does not rebuild Gecko, update
SDK parameters or enable Mesa/JIT. Public service declarations are fetched and
identity-checked separately; no old SDK runtime is linked.

The probe resolves executable firmware exports, initializes UserService, checks
an active user, then calls the genuine `sceCommonDialogInitialize`. Every error
remains a failure. Only if that succeeds does it open two UTF-16 IME dialogs:

1. Type uppercase **OK** and confirm.
2. Cancel the second dialog.

Each dialog has a 45-second polling deadline. Result/action and real termination
must succeed; no entered text is logged. Static buffers remain alive even if a
firmware call refuses termination. The overall watchdog is 120 seconds. Normal
completion uses the existing explicit teardown/return-Home hook. Inspect the new
unique `sdk-probe/run-*/runtime.log` for the exact CommonDialog return and final
`RESULT`; returning Home alone proves nothing. The log also identifies dialog mode.

The source/declaration fingerprints and native SELF/PKG payload are independently
verified before upload. This is a C service reproducer with no Gecko, controller
worker or VideoOut owner. A failure here narrows the reproducer but does **not**
by itself establish an SDK defect: service/process/foreground preconditions still
need attribution before proposing an upstream patch. A success also does not
prove that the browser's later lifecycle is correct. Host firmware doubles cover
success, the observed `0x80b8000e`, failed bindings/flags, timeouts, clock failure,
result/cancel handling and cleanup; only console execution tests the real service.

### Custom keyboard (SDK dev browser)

The operator selected a custom chrome keyboard as the browser default, leaving
Sony's native backend intact for later repair. The protected `orbisfox/` main
checkout is not part of this change. SDK selection, package identity/profile,
allocator and shutdown paths are unchanged; continue to select the native SDK
explicitly with `ORBISFOX_SDK=homebrew` / `--sdk homebrew`.

D-pad chooses keys, Cross types, Triangle inserts space, Square deletes (held
repeat), L1/R1 move the caret, and **R2 is Enter**. Address/search and Find use
confirmable drafts. In single-line page fields, Enter dispatches trusted Gecko
keydown/keypress/keyup after revalidating/refocusing the owned field; canceled
keydown suppresses keypress. In textareas, Enter inserts a newline and stays
open. Done closes page entry without submitting. Circle discards chrome drafts;
page edits are live and cannot be undone merely by closing the keyboard.

Page updates use the real field editor, with tab/document/frame/principal/focus
and unchanged-value checks before edits. Password drafts are masked and cleared
on close. Native chrome and pointer input are disabled while editing and until
all buttons are released afterward, preventing held R2 from becoming Forward.
The retained native IME still requires presentation quiescence if used later.

Initial scope: 512 UTF-16 units, Latin/symbol keys, standard text/search/email/
URL/tel/password fields and textareas. Rich contenteditable, complex-script
composition, predictive suggestions and the custom/Sony Settings selector are
not implemented. Chrome rendering and page edits remain main-thread work and
can stall with Gecko. Host doubles/sanitizers are not console validation; actual
keyboard layout, trusted form submission and focus behavior need a fresh
native-SDK build and console test. The standalone dialog probe above remains
separate and is not the browser's default keyboard.

### Main-thread stall investigation (#4)

The operator's October 21 browsing runs confirm multi-second stalls on this SDK:
maximum inclusive main-thread tasks were 8.51 s and 7.71 s in two different runs.
The latest run recorded 7.71 s of script-loader work and a 1.80 s browser-shell
callback near shutdown. Task names and inclusive times are not a CPU breakdown;
nested work overlaps, and these workloads are not a controlled old/new SDK
comparison. Faster YouTube/page loading is operator feedback, not a benchmark.

The reported stopped screen followed a caught `NS_ERROR_UNEXPECTED` from
`pumpFrame()`, then orderly Gecko shutdown. This is an application error path,
not evidence of an OS crash or successful 4K decoding. Existing logs do not
identify which pump validation failed. Do not bypass surface bounds, formats or
mapping checks to keep playback apparently running.

The uploaded diagnostic candidate adds:
- A fixed 16-entry history of completed main-thread spans >=250 ms, carrying
  process-time completion timestamps, inclusive duration, depth and whether the
  name is a detailed runnable or an outer event span. The existing monitor emits
  each entry once and reports overwritten records; this is not an exhaustive
  profiler. A newly enabled capture does not replay pre-capture completions.
- Opt-in, slow-only (>=250 ms) shell callback phase timings using the chrome
  window's monotonic performance clock: native actions, frame pump, chrome init,
  input, tab state, probes/session and rendering. Labels and numeric times only;
  no page text, credentials or new URL fields.
- Exact keyboard-status, surface-size/format and map/stride failure messages,
  retaining the original pump error returns and cleanup.

The first run of that candidate retained 247 long-span completion records, with
no bounded-history loss reported. Its longest detailed spans were a 10.38 s
`TimeoutExecutor Runnable`, an 8.09 s view-transition update task, and 5.83 s in
`nsHtml5ExecutorReflusher`. A timeout-executor span can contain multiple callbacks;
these are inclusive task durations, not proof of one expensive JavaScript call.
Slow shell callbacks included 2.45 s processing native actions; close-tab commands
preceded the slow native-action samples. Routine chrome rendering is not the
largest measured source of these stalls.

The operator reported a crash at the end. Unlike the earlier caught pump error,
this run ended abruptly, without a pump-failure message or orderly-shutdown
record. No owned title core dump was available. The final memory sample recorded
85,983,232 bytes of flexible memory available and no tracked GC allocation/map
failures; native libc heap totals are unavailable and samples are coarse, so this
does not rule out an allocation failure between samples. The crash cause remains
unresolved: do not infer a native faulting function, OOM, or a network root cause
from the last logged event alone.

These are attribution changes, not a demonstrated stall fix. Correlate completion
`end-us` with heartbeat `native_us` and controlled HTTP/media events for #7;
separately compare diagnostics off/on before judging a speedup. Host sanitizer
and shell-double tests do not establish console timing. No fresh capture flag,
console launch, build or deployment is authorized merely by this documentation.

### O2 candidate and reduced motion

The native-SDK configure producer now explicitly uses `--enable-optimize=-O2`
and records the effective Gecko optimization flags in its configure report.
Previously the generic FreeBSD target fell back to `-O` (Clang `-O1`), including
SpiderMonkey's interpreter. This is native compiler optimization, not JavaScript
JIT enablement. The legacy SDK configuration is unchanged. Compare the same
workload and diagnostics state; no console speedup is established by this change.

Settings → General → Website appearance includes **Reduced motion**, off by
default for new/legacy profiles. It is reversible and saved through the existing
transactional settings path; a failed save restores the previous setting and
runtime preference. It writes Gecko's real `ui.prefersReducedMotion` integer
preference (`1` on, `0` off), rather than injecting CSS or disabling scripts.
Websites may ignore it or require reload before adapting. Leave it off for the
initial O2 comparison, then compare it independently. Host tests do not establish
how a particular console website responds to live preference changes.

### Portable Baseline Interpreter: isolated host gate

Checkpoint `0efacd9` retains the O2/reduced-motion/stall-diagnostics candidate.
The isolated host command does not modify the native configure lane, its object
tree, application policy or package. From this dev checkout, run:

```sh
python3 scripts/test-portable-baseline.py --jobs 2
python3 -m unittest discover -s tests -p 'portable_baseline_test.py'
```

This requires the existing pinned `.deps/gecko-layout` sources, Linux host
Clang/Rust/cbindgen, Bubblewrap and GDB. It builds a separate, interpreter-only
SpiderMonkey shell in `build/portable-baseline-host/` using `-O2`, without Intl
or debug symbols. Nothing is fetched, installed or deployed by this command.
The protected sibling `orbisfox` checkout, when present, is mounted read-only.

Both modes use `--no-jit-backend` before JS initialization. The portable mode
needs **both** `--portable-baseline` and `--portable-baseline-eager`: eager alone
only changes the warmup threshold and can silently leave the generic interpreter
running. The generic control explicitly disables the portable backend. Check
`probe-report.json` and the retained per-mode logs, not just a successful build.
GDB must observe actual entry into `js::pbl::PortableBaselineInterpret` only in
the portable mode; merely finding a symbol or setting a breakpoint is not proof.

The first host gate passed property/getter/proxy/call/closure/exception, typed
array, regular expression, retained-object GC, generator/async fallback and
stack-overflow checks. Both modes produced matching results and honored a
0.1-second interrupt with shell exit status 6. This is a small semantic probe,
not the complete upstream suite, GC-zeal testing, a browser benchmark or PS4
proof. Its elapsed times include explicit GC and cannot predict console stalls.
A native candidate still needs build/runtime selection, ABI and memory/stack
validation while retaining the genuine denied-JIT fallback. No speedup or
console compatibility is established by the host gate.

### Portable Baseline Interpreter: opt-in native candidate

After the host gate, select the experiment explicitly (native SDK only):

```sh
python3 scripts/build-gecko-app.py --sdk homebrew --portable-baseline --jobs 4
python3 scripts/package-gecko.py --sdk homebrew --resource-format omni
```

The configure producer passes `--disable-jit`,
`--enable-portable-baseline-interp` and
`--enable-portable-baseline-interp-force`. The last option actually selects the
portable backend; it is not the host shell's eager/warmup-only switch. Native
code generation is absent (`JS_CODEGEN_NONE`). The normal warmup threshold and
upstream generic fallbacks for unsupported scripts remain intact. O2, SWGL,
GC policy and the reversible reduced-motion setting are otherwise unchanged.

The application disables the native JIT backend before JS initialization and
skips executable-memory probing in this mode: portable CacheIR execution needs
no permission bypass or generated code. `nativeJitReady` remains false; native
RegExp JIT, Ion and Wasm are not advertised. Builds without the experiment retain
the genuine owned-code W^X capability gate and denied-JIT fallback unchanged.
Rebuilding with `--skip-engine-build` rejects a mismatched configured mode.

Final-ELF validation requires nonempty defined portable-core FUNC bodies (weak
C++ template bodies are valid; data tables/imports are not). The core sets one
atomic bit on entry. Existing opt-in heartbeat logs report
`portable-baseline ... core-entered=1 native-codegen=0` after actual entry;
`core-entered=0` is not execution proof. This observes entry only, not correct
completion of every script, coverage, time spent or a performance improvement.
Nothing enables diagnostics automatically.

Native linking and package extraction are separate gates from console startup,
stack/GC behavior and website compatibility. No console execution or speedup is
established yet. The prior package, ELF and reports are retained together under
`build/hardware-0.68-homebrew/retained/pre-portable-baseline-*`; the host probe's
`native-rollback-path.txt` records the exact private local retention path. uBO
and collector-policy changes are intentionally excluded from this comparison.

### Console exit finding

The first native probe completed all 52 checks, closed its result file and printed
its final message, then raised SIGSYS in `libkernel_sys.sprx` during the SDK CRT's
`exit()` call. The captured application return address matched that exact call in
the hash-bound local ELF. Thus a passing runtime log did not establish clean
application termination; it was not evidence of a failed allocator test either.

The probe now supplies the SDK's weak `catchReturnFromMain` application hook. After
its explicit worker/resource teardown, it flushes stdio and records `APP_EXIT`,
then requests genuine `sceSystemServiceLoadExec("exit", NULL)` termination. The
SDK resolves the real SystemService library; no system binary is copied. A zero
service return is treated as an accepted asynchronous request, with a genuine
monotonic five-second termination deadline. A failed request or expired deadline
is recorded and traps rather than claiming successful termination or retrying
the denied exit path. The native
link checker requires the strong owned hook and the real service dependency.

This is a **C-probe lifecycle adapter**, not a global `exit`/`_exit` replacement,
not a general C++ destructor/atexit solution and not a modified SDK CRT. All probe
owned workers, mappings, files and synchronization objects are released before
the normal successful hook. Early test failures still remain failures. Host service
doubles exercise nonreturning termination, rejection and an accepted request that
never terminates. The operator confirmed that the revised probe completes and
returns Home without crashing. Full SDK C++/atexit/loader cleanup remains a
separate migration gate.

## Browser conversion: current boundaries

The SDK selection is explicit (`ORBISFOX_SDK=homebrew` or supported producers'
`--sdk homebrew`). It does not change the default OpenOrbis build. Unknown SDKs,
old include/library paths, mismatched runtime identities and legacy native-app
consumption of a native-SDK engine fail closed instead of producing a mixed ABI.
A separate native SWGL application-link lane is implemented with SDK-bound
runtimes, genuine CRT ownership and final-ELF checks. The complete native engine
and browser executable now pass their strict links and final application audits.
The native software-rendered SELF/PKG lane also passes local production and
independent payload/resource extraction checks. This is still host build evidence:
console startup, rendering, networking and C++ shutdown remain unvalidated.
No console-validated native-SDK browser installer or redistribution signoff is
claimed.

Prerequisites and bounded source/configuration checks:

```sh
python3 scripts/build-homebrew-libcxx.py --jobs 4
python3 scripts/bootstrap-homebrew-rust.py
python3 scripts/build-homebrew-rust.py --jobs 4
python3 scripts/fetch-homebrew-service-headers.py
python3 scripts/fetch-native-font-header.py
python3 scripts/build-media-codecs.py --sdk homebrew --jobs 4
python3 scripts/configure-gecko-layout.py --sdk homebrew
ORBISFOX_SDK=homebrew make -C build/gecko-layout mozilla-config.h install-dist/include
python3 -m unittest discover -s tests -p 'homebrew_*_test.py'
```

The header export above is required after fresh configuration; configure alone
does not generate `mozilla-config.h` or install NSPR's header links. It does not
compile the engine. After the object-tree ownership/space review and approved
retirement of the previous experimental engine, the complete engine producer is:

```sh
python3 scripts/build-gecko-layout.py --sdk homebrew --jobs 4
```

It builds/checks the native C++/Rust/media prerequisites and rejects mismatched
SDK/object-tree identities. Native Rust cache identity changes fail closed rather
than deleting possibly referenced objects. This is not permission to overwrite a
legacy engine or remove thin-archive inputs. The native engine deliberately uses
SWGL; `--sdk homebrew --mesa` is rejected until the new SDK's Mesa closure is ported.
After a successful engine build, the native application command is:

```sh
python3 scripts/build-gecko-app.py --sdk homebrew --skip-engine-build --jobs 4
```

It owns `build/gecko-app-homebrew`, not the legacy output directory. It retains
the common actual-code checks for codecs, NSS trust, HAL, input/UI ownership,
Skia, GC backing and the Rust ABI. Native-specific checks require system-libc
heap/stdio/clock imports, real thread IDs and native CRT preinit/constructor
layout; old musl replacements/private bins/heap mmap interception are rejected.
The application lane also rejects native Mesa before starting a producer.

The isolated software-rendered package lane is explicit as well:

```sh
python3 scripts/package-gecko.py --sdk homebrew --resource-format omni
python3 scripts/verify-gecko-package.py --sdk homebrew
```

It uses the pinned SDK's SELF, SFO, GP4 and PKG producers, then independently
validates/extracts with OpenOrbis PkgTool. Outputs are confined to
`build/gecko-app-homebrew` and `dist/gecko-homebrew/OrbisFox-Homebrew.pkg`;
legacy/Mesa installers are not overwritten. The separate title is **OrbisFox SDK
Test**, `ORHB00001`, with `/data/orbisfox/homebrew-profile` and
`/data/orbisfox/homebrew-cache`; it does not migrate an existing browser profile.
The packager checks the linked ELF/source/SDK identity and requires the shipped
FFmpeg source, producer and configuration to match the application's captured
codec build. A small real SDK package/extraction fixture and deliberately changed
metadata/materials tests exercise these checks; those fixtures are not browser
execution. `omni` retains unchanged ZIP_STORED resources and no hardware-validation
claim. There is no upload, installation, launch or redistribution authorization
in either command.

The successful local reports are `build/gecko-layout/build-report.json` and
`build/gecko-app-homebrew/build-report.json`; the executable is
`build/gecko-app-homebrew/orbisfox.elf`. These do not certify console startup,
C++ shutdown, networking or rendering. C++ runtimes use the project's pinned LLVM 21.1.8 sources,
not the companion ports repository's different libc++ version. The Rust core,
alloc and compiler-builtins libraries use a separate native-SDK target/sysroot.

Completed local checks, with their limits:

- C++ runtime build and native C++/Rust link smoke tests against the selected SDK;
  no claim of console execution of those C++/Rust smoke tests. Native libc++abi
  guards use the SDK's real `pthread_getthreadid_np` rather than silently losing
  recursive-initialization detection when Linux's `SYS_gettid` is unavailable.
  The runtime producer checks actual guard code bodies and the genuine thread-ID
  import in its installed archive. Final application audits follow actual x86-64
  call instructions through GOT relocations: the SDK merges import thunks into
  `.text`, where disassembler nearest-symbol labels can be unrelated. The same
  audit verifies Skia's real pthread wait and rejects incorrect import bindings;
  it does not infer calls merely from undefined symbols. The real frame-mailbox
  reader body is explicitly retained for its final ownership-code audit even
  when its runtime calls are inlined. Host ASan/UBSan tests cover contention,
  initializer abort/retry and fatal recursion/invalid IDs; these are not console
  constructor or shutdown evidence.
- Native Rust pipes and socket acceptance select upstream's checked
  `pipe`/`accept` plus CLOEXEC fallbacks instead of missing `pipe2`/`accept4`.
  The rebuilt full standard-library archive is checked for the real imports.
  Vendored `socket2` likewise uses its upstream `accept` and checked `FD_CLOEXEC`
  handling for the native SDK; its original/patched native archive test requires
  the old `accept4` import to disappear and real `accept`/`fcntl` imports to remain.
  The same pinned crate is registered as a workspace path patch, so Make/Cargo
  watch the adapted source instead of silently reusing immutable-registry CGUs.
  No Rust object cache or thin-archive member is deleted to force a rebuild.
  Rust `File::set_times`, path timestamp updates and Unix peer-credential queries
  currently return explicit `Unsupported` errors: this SDK lacks the required
  precise/omitted/no-follow timestamp APIs and `getpeereid`. No timestamps or
  peer identities are fabricated. These are outstanding API limitations, not
  proof of browser storage behavior or console descriptor handling.
- Missing native capabilities use genuine existing alternatives: checked
  `waitpid`, libevent's TCP/UDP names and unknown-protocol failure, CCTZ's portable
  parser, and getrandom's `/dev/urandom` backend with unchanged entropy/error
  checks. The CCTZ parser selection belongs to the actual generated GN leaf;
  setting `DEFINES` only on its parent does not reach that compilation unit. Vendored Rust checksums stay validated and are updated with the source.
  Native HTTPS DNS-record queries return `NS_ERROR_NOT_AVAILABLE`, not a
  successful empty answer; ordinary SDK address resolution is separate. No
  global missing-libc API stubs are introduced and strict undefined-symbol
  checking remains enabled.
- `python3 scripts/verify-startup.py ELF --sdk homebrew` validates real PIE
  entry code, the single relocated preinit logger, native constructor/finalizer
  arrays and their dynamic bounds. It rejects the legacy initializer table,
  duplicate logger execution and pointers without actual code bodies. Native
  SDK `.ctors`/`.dtors` can produce PROGBITS arrays; validation follows their
  real CRT/dynamic bounds rather than assuming the section type. This is ELF
  layout evidence, not console execution or C++ shutdown proof.
- Native-SDK Gecko configure/backend generation and targeted widget compilation,
  not a complete Gecko rebuild or native browser launch. The old experimental
  engine and its dependent external thin archives were retired together only
  after operator approval; a fresh native-SDK configuration replaces them.
- The native clock diagnostic adapter links against the SDK's actual
  `clock_gettime`, with no application-defined libc/pthread clock overrides or
  musl-to-BSD enum translation. Actual SDK-header regression checks retain
  monotonic ID 4 and process-CPU ID 15; host sanitizer doubles check output
  guards and error propagation. The legacy clock adapter still passes its
  independent sanitizer suite. These checks are not native browser timing or
  condition-variable execution evidence.
- Native stat/lstat/fstat use the SDK's real BSD records without defining global
  replacements. Compile-time offsets and the native no-GC link check retain the
  120-byte stat/32-byte flock ABI. SQLite's explicit lock hook forwards native BSD
  records, preserves errno and rejects guard overruns rather than translating them
  as musl records. Native-header host doubles check these paths; cross-process
  console locking still needs separate validation.
- Both native allocator call sites account for the SDK's missing `memalign`
  declaration and import the real native-libc export, rather than exporting a
  same-named browser replacement. Object-symbol checks require an undefined
  import and no replacement body. The upstream `posix_memalign` fallback remains
  for configurations that genuinely lack the symbol. Bindgen uses libc++ wrappers, genuine LLVM
  resource headers and then BSD C headers, matching the native compiler's order;
  actual libclang tests retain the native wchar/pthread/clock ABI. These are build
  regressions, not evidence of complete browser allocation or Rust execution.
- Native application allocation retains system-libc imports and excludes the
  old musl wrappers, private-bin reads, external heap lock, realloc-copy workaround
  and heap mmap interception. The existing startup gate still checks data reuse,
  realloc growth/shrink preservation, calloc zeroing, alignment and eight-worker
  allocation handoff. It does not require musl-specific chunk spacing or fabricate
  protected-entry counters. Native no-GC link/import checks and host sanitizer
  tests cover normal operation, partial thread-creation failure and corrupted
  zero-fill rejection; these are not console allocator evidence. Native heap size
  accounting is reported unavailable, not zero. Requested legacy `heap-debug`
  mode is explicitly unsupported and blocks startup rather than pretending that
  guards are active; no diagnostic flag is changed automatically.
- Native stdio imports the SDK's real stream-lock operations, with no musl
  interposers, fabricated entry counters or raw legacy TCB reads. The existing
  four-thread probe still requires all 4,096 buffered records to be intact and
  unique. Its native branch passes 32 host ASan/UBSan cycles; a native no-GC link
  checks the real imports. Neither result proves console stream contention.
- C++20 `Maybe` storage now supports literal values with nontrivial copy
  constructors, including FreeBSD libc++ ABI v1's `std::pair`. The native ABI
  and type-trait checks are retained, not overridden. Real SDK compilation
  checks SpiderMonkey's constant-evaluated language parser; host sanitizers
  check copy/move/reset/destructor ownership. Only trivially destructible
  payloads use the new constexpr destructor; nontrivial DOM record/union
  cleanup retains lazy instantiation. Actual generated localization bindings
  compile, and nontrivial storage keeps its original type-trait classification.
  No layout or allocator change.
- Native early logging uses the SDK CRT's real `.preinit_array`, after its libc
  environment initialization and before its own constructor loop. Native ELF
  checks resolve the actual array slot (including PIE relocations); host tests
  check once-only ordering and unchanged diagnostics-off behavior. These are
  not console C++ startup/shutdown evidence.
- Before pre-XPCOM Gecko probes, the application establishes upstream
  `ScopedLogging` and `LogModule::Init`, retaining that owner through bootstrap
  teardown. A clone failure can enter `LazyLogModule` even with logging disabled;
  skipping the error log is not a substitute for the required lifecycle.
  Native descriptor cloning uses checked `dup`/`F_GETFD`/`F_SETFD`, never
  `F_DUPFD_CLOEXEC`: command 17 returned unrelated descriptor 0 with errno 0 on
  the tested console. An errno-triggered fallback cannot detect that result.
  This applies to MFBT, Rust std's shared `BorrowedFd` clone and socket2; failed
  flag setup closes only the new owned copy and preserves the operation error.
  Native `FileHandleHelper` provides contextual validity for libc++'s `reset`,
  so a genuine descriptor 0 is released instead of mistaken for a null pointer.
  The IPC descriptor shuffler instead needs `F_DUPFD`'s minimum-slot semantics,
  checks its lower bound and CLOEXEC setup, and rejects bad results. That IPC
  branch still needs console validation; it does not enable subprocesses.
  Duplication retains access mode and close-on-exec but is not atomic across
  fork/exec, matching the documented single-process embedding constraint.
  Clone errors are also preserved across lazy logging and log I/O. Host
  sanitizers and SDK compilation cover these paths; resolving the observed
  console startup crash still requires a new console run.
- A native-only `catchReturnFromMain` application boundary is separately compiled
  and tested for the native final-link lane. It requests the real application
  manager after automatic C++ object teardown, never interposes `exit`, and
  rejects failed requests/clocks or bounded timeouts with a real fail-fast trap.
  Host doubles cover immediate/asynchronous termination, rejection, stuck time,
  backwards/failed clocks and failed sleeps. It does not run or certify SDK
  global C++/atexit/loader cleanup. Full browser console shutdown remains open.
- Native libffi retains its System V x86-64 backend. The SDK compiler cannot
  build the optional Microsoft `ms_abi` backend; native preparation explicitly
  rejects Windows ABI requests with `FFI_BAD_ABI`, and malformed direct calls
  abort instead of using the wrong convention. Tests execute actual SDK-compiled
  SysV code with host libc for integer, large-struct and variadic calls. This is
  ABI evidence, not firmware execution or dynamic callback/JIT support.
- Native libevent uses its existing checked `pipe`/`fcntl` fallback where the
  SDK lacks `pipe2`. Embedded RNG helpers have private names to avoid native BSD
  public-declaration collisions; the RNG implementation, device-entropy path and
  initialization failures are unchanged. Tests compile the real RNG unit and
  check that aliases cannot leak into later unified-build units.
- All six configured NSPR C translation units compile and link into an ELF with
  `--no-gc-sections`. This deliberately keeps APIs that an ordinary tiny smoke
  executable could discard. Host sanitizer tests cover the private netdb adapters;
  native DNS, network concurrency and browser NSS behavior remain untested.
- All 445 configured NSS C/C++ translation units pass native-SDK syntax checks;
  this excludes assembly, complete NSS linking, TLS validation and console use.
- The embedded dav1d decoder retains its existing `posix_memalign` allocation
  branch. Native preparation avoids the SDK's intentionally unusable `malloc.h`
  only when that declared POSIX branch is available; it does not replace an
  allocator or disable the decoder. Actual native compilation of the failing
  CDF unit and host alignment/error-path tests pass, not console AV1 playback.
- Isolated native-SDK FFmpeg archives build and link in full with
  `--whole-archive --no-gc-sections`, retaining the real decoder/FFT code. They
  remain `orbis_media_` prefixed and use a separate `native-homebrew` output/report.
  FFVPX's native shared-library targets use the SDK's real system-libc math
  imports instead of requesting an unavailable separate `libm`. No dummy math
  library or replacement implementations are supplied; native no-GC link tests
  retain the actual imported math functions. Neither linking nor symbol presence
  establishes decode/playback on console.

### Public PS4 service declarations

The new SDK does not ship the application's public controller, VideoOut, IME and
other PS4 service headers. `scripts/fetch-homebrew-service-headers.py` supplies a
separate **21-header declaration-only** bundle from the existing public OpenOrbis
pin. Every file's Git blob identity is fixed; GPL LICENSE/notices are retained.
The exact inventory rejects extra files, symlinks and edits. No old libc/POSIX
headers, CRT, allocator, libraries or SDK overlay are imported. Never add the
whole old SDK include directory to a native build.

`tests/homebrew_services_test.py` compiles 12 native application/service units
against those declarations and the new SDK's actual POSIX/C++ types. Compilation
does not prove native initialization, thread ownership, allocator selection or
successful shutdown; the native application producer has separate final-link
checks and is not a console-validated browser.
The broader application compile audit also covers native chrome, launcher and
all startup probes (31 units), without the old heap-mapping adapter. Native SDK
launches select `/data/orbisfox/homebrew-profile` and `homebrew-cache`, independently
of GPU success. Neither the working profile nor the previous Mesa profile is
selected, copied, migrated or deleted. Startup accepts only the three exact
owned profile paths and fails closed for arbitrary paths/traversal. The actual
clock probe uses native IDs 4/15/14 unchanged, not the old musl translation.

The existing native chrome rasterizer requires `stb_truetype.h`, previously found
through the old SDK include directory. `scripts/fetch-native-font-header.py`
fetches that **single unchanged MIT header** at the existing public pin, into
`.deps/native-font-header`. It verifies SHA-256 and exact inventory and refuses
unknown edits; no old C/POSIX headers are made visible. Keep the existing stb MIT
notice. This is a source dependency, not a font-rendering or threading redesign.

SpiderMonkey's native SDK thread naming uses the actual `pthread_np.h`
declaration. Its stack-limit initialization uses genuine `pthread_attr_get_np`
and `pthread_attr_getstack`, not a Linux `pthread_getattr_np` alias or guessed
stack bounds. Initialization/query/release failures, empty bounds and address
overflow retain fatal checks. SDK whole-unit compilation and native-object host
doubles cover these paths; console thread-stack behavior remains unproven.

When the native SDK supplies `dladdr` and `_Unwind_Backtrace`, upstream
`StackWalk.cpp` owns `DemangleSymbol`. The Orbis fallback is compiled only when
that provider is absent. SDK/host capability-matrix tests require exactly one
real definition and retain strict duplicate-symbol rejection; they do not prove
console stack walking or exception unwinding.

The embedded Abseil alternate signal-stack code explicitly converts allocator
results to its real `stack_t::ss_sp` field type (`char*` in these BSD headers).
Both mmap and malloc branches retain their allocation sizes/protections and
fatal failure checks. This is a compilation fix, not permission to install new
signal handlers or suppress console crash evidence.

Application link-input discovery is now shared with the guarded legacy producer
in `scripts/gecko-link-inputs.py`. It reads the actual XUL/XPCShell, static NSS,
FFVPX and NSPR object inventories, rejects missing/cross-tree inputs and desktop
freebl loaders, and requires the explicitly selected engine Rust archive. It
does not select a CRT/runtime or relax final-ELF proof. Fixture tests of both
SDK inventories and the existing application producer pass. The native lane
uses this same discovery and common proof with its actual SDK CRT/runtime,
while SDK-specific boundary and startup checks replace the old musl checks.
A native no-GC ELF fixture exercises that real linker command. The complete
browser executable now also passes the common and SDK-specific final checks;
no console execution is inferred from either link.

### Resolver limitation in the pinned SDK

SDK v0.2.1 has an **IPv4-only hostname resolver**: its `getaddrinfo` rejects
`PF_INET6`, and it has no `gethostbyname2` or `getprotobynumber` implementation.
The private NSPR adapter delegates IPv4 to the actual SDK resolver and rejects
unsupported families with `EAFNOSUPPORT`/`NO_RECOVERY`; it never returns IPv4
bytes labeled as native IPv6. Existing NSPR `PR_AI_V4MAPPED` handling is retained.
Protocol-number lookups query the SDK's real named records and verify their
returned number, under the existing NSPR lock. No public libc API is fabricated.

This does **not** restore native AAAA/IPv6 hostname resolution. Resolver coverage
is an explicit remaining migration gate, not equivalent networking to the working
browser. NSS certificate/hostname checks must remain intact regardless of which
resolver supplies an address.

## Evidence and remaining gates

Host ASan/UBSan execution checks logic on the host, not the SDK's native runtime.
Native linking is not SELF/package verification or console execution. Complete
Gecko/Rust/NSPR/NSS and application links have passed. Native application startup,
allocator/clock/filesystem behavior, C++ shutdown, resolver coverage, actual TLS,
cross-process SQLite locking, media playback, native UI ownership and GPU
publication still require separate console validation. The first native console
runs reached the allocator/stdio/file-lock gates and shared-memory freeze. The
next run after the logging-lifecycle repair did not reproduce the early logging
fault, but startup still stops when the cloned readonly mapping is invalid. This
is not a working native browser or proof that earlier Mesa corruption is fixed.

The shared-memory preflight now captures each operation's errno independently;
a successful descriptor fallback can leave an earlier `EINVAL` in errno. With
existing diagnostics enabled only, failure records include descriptor access,
flags, backing size/identity, available flexible memory and a plain-dup readonly
mapping comparison on the same synthetic backing. The new console evidence
showed source fd 16 with 16384 bytes, a purported clone fd 0 with zero-byte
unrelated backing, and a genuine `dup` fd 15 that mapped the same source readonly
successfully. Available flexible memory was 242221056 bytes, not exhausted.
These comparisons record no web content and cannot make a failed gate pass.
`SharedMemory:2` enables the existing bounded low-level failure records only in
the diagnostics-on default log configuration; it does not enable diagnostics or
alter the operator's flag. Host sanitizer tests check errno attribution, FD/view
cleanup and diagnostics-off behavior. Additional actual-body regressions trap
command 17 returning success-shaped zero, check descriptor-0 ownership, and
cover CLOEXEC setup failures and error cleanup. The corrected application still
needs a console run; this evidence does not establish native browser readiness.

A source/configuration prerequisite check is not a full browser migration.

Licensing is file-specific. The owned probe is MIT, its packaging producer uses
GPL-covered project helpers, and the SDK includes GPL-3.0-or-later startup/runtime
sources and mixed historical BSD headers. The local package includes owned source
and this exact upstream pin, **not a complete SDK corresponding-source/relink kit**.
Public redistribution requires a separate source/license review; a successful local
package check is not that sign-off. Never include proprietary system libraries.
