# Agent guide — OrbisFox

Applies to the whole repository. Read `README.md`, `CONTRIBUTING.md`,
`docs/PORTING.md`, `docs/HARDWARE.md`, `LICENSES/README.md` and the current
`SESSION_HANDOFF.md` before changing the project. This guide is for coding
agents; it does not authorize remote actions or override the operator.

## Current state and priorities

- Native PS4 Gecko browser; current implementation baseline **0.68**, source
  alpha preparation. Never describe it as stock Firefox or production-ready.
- Real layout/JS interpreter/NSS/SWGL/software codecs work; local playback has
  hardware evidence. YouTube/Twitch live playback and controlled WebSocket
  test-page loading remain broken in the latest report. YouTube chat was
  reported working. Do not reopen the already-solved missing-codec claim.
- Native JIT allocation is denied with EPERM `0x80020001`; genuine interpreter
  fallback. Ion/Wasm are off. Host executable-memory tests are not console proof.
- Website color scheme, fullscreen integration and native CPU-affinity count
  were implemented in 0.68. Their full console effect is not established.
- The operator paused browser feature/performance work pending further notice.
  Alpha documentation/licensing/housekeeping does not authorize resuming it.
- Release/publication/deployment/shutdown are separate actions: obtain current
  operator authorization. Historical handoff commands and endpoints are records,
  not standing permission for a new contributor. Do not delegate without consent.

## Source map and ownership

| Path | Role |
| --- | --- |
| `gecko/orbisfox/` | Canonical application overlay, host bridge/IDL, executable/GC memory, media adapters. |
| `gecko/orbisfox/fixtures/` | Privileged browser XHTML/CSS/JS, startup policy, model, host and UI. This is live app code, not merely test data. |
| `gecko/widget/orbis/` | Widget/app-shell/event loop, compositor and long-task diagnostics. |
| `gecko/**` elsewhere | Canonical Gecko patches/adapters, with upstream licenses retained. |
| `include/orbisfox/`, `src/`, `src/ps4/` | Native controller/presentation/chrome/mailbox and PS4 services/SDK adapters. |
| `scripts/patch-gecko*.py` | Deterministic pinned-upstream transformations. Test repeated application for byte and mtime stability. |
| `scripts/build-*.py`, `scripts/orbis-*`, `scripts/sdk-overlay.py` | Producers and compiler/ABI/runtime overlays. |
| `rust/`, `targets/` | Runtime probe and private Orbis Rust target; not a stock FreeBSD sysroot. |
| `tests/` | C++ sanitizer tests, Python producer/ABI tests and Node browser-shell doubles. |
| `.deps/` | Ignored, downloaded upstream/toolchains plus generated SDK/private runtimes. Never the sole home of a fix. |
| `build/`, `dist/` | Ignored output, active thin archives, retained packages, reports and private evidence. Not disposable scratch space. |

Modify canonical source and its producer. Editing only
`.deps/gecko-layout/` is not a durable change. Never run concurrent writers or
build producers against one object tree. Never delete thin-archive member inputs.

## Commands and validation

```sh
make bootstrap
ORBISFOX_JOBS=4 make                  # current browser; needs large disk/RAM
make validate
make test                            # full host suite, can fetch/build inputs
make source-release                  # source only; does not upload/publish
```

- Fresh build: `make gecko-build` supplies standalone runtime/JS prerequisites;
  `scripts/build-gecko-layout.py --jobs 4` builds full Gecko; then
  `scripts/build-gecko-app.py`, `scripts/package-gecko.py`, and
  `scripts/verify-gecko-package.py`. The default Make target chains these.
- `make pkg`/`make pkg-videoout` are historical standalone lanes, not the browser.
- Node focused tests: `tests/browser_shell_test.js`,
  `tests/browser_shell_host_test.js`, `tests/browser_shell_ui_test.js`,
  `tests/browser_fullscreen_test.js`, `tests/browser_network_observer_test.js`.
- Python suite: `python3 -m unittest discover -s tests -p '*_test.py'`.
  Some tests need downloaded SDK/source or host media encoders. Read failures;
  do not weaken or silently skip tests to get a green result.
- Source release: inspect `build/releases/source-release-report.json`, verify
  archive SHA and embedded manifest, ensure no `.deps`, `build`, `dist`, `.pi`,
  Git metadata, private logs or profiles are included.
- Report exactly what ran. Native link, package extraction, host doubles and
  console execution are **different evidence levels**. Do not claim one proves
  another. Use actual final-ELF disassembly/symbols when validating ABI paths.
- lld can localize real static functions: inspect `llvm-nm --defined-only`
  `t/T` bodies, not only globally visible symbols. Do not accept an unresolved
  symbol or a similarly named old implementation as proof of the new path.

## Security and runtime invariants

1. Chrome/system principal owns the native bridge; **never** expose it or
   system-principal wrappers to web content. Preserve origin, source, URI,
   referrer, policy and trusted-input checks. At most three nonremote content
   contexts. Single-process is a documented risk, not a content sandbox.
2. Preserve NSS certificate/hostname/time validation, entropy, file locks,
   storage semantics, allocator ownership and crash assertions. No TLS bypass,
   fake success return, fabricated MIME support or suppressed invariant.
3. SDK malloc remains the allocator owner. Keep recursive locking and bounded
   genuine realloc-copy handling. Do not globally replace mmap or route
   file/stack/JIT/partial-shrink mappings into direct memory.
4. SDK anonymous whole mappings and GC arena/nursery whole chunks have separate
   tracked WB_ONION memory (type **0**, not WC_GARLIC type 3). Exact ownership
   matters; uncertain release must not be guessed. Preserve the stable baseline.
5. JIT uses an owned W^X arena and an actual own-code execution gate **before
   JS_Init**. Denial must disable the backend honestly. No permission bypass,
   RWX heap, kernel patch or host-memfd result presented as console support.
6. Native UI worker owns controller/cursor/VideoOut. No Gecko, DOM, font objects
   or APIs off-main. POD scene + bounded command queue only. Frame mailbox has
   exclusive writer/mailbox/reader ownership; copy/render/scanout outside its
   short swap lock. Join workers before releasing buffers/services.
7. Native IME only; cancel remains cancel. Pause worker scanout during IME and
   preserve fresh-input gating. Do not introduce reentrant input dispatch.
8. Native clocks must honor SDK-to-firmware clock-ID translation; failed queries
   stay failures. CPU count uses the genuine thread-affinity API, with a
   conservative original-SDK fallback. Inspect real firmware return types.
9. Real FFmpeg APIs are typed and `orbis_media_` prefixed; preserve isolation
   from bundled FFVPX. Link real decoder objects/registrations, FFT functions
   and strict version checks. Never advertise a codec just by changing prefs.
10. AudioOut buffers cannot be reused before consumption; join before close.
    Preserve HAL startup/shutdown and monotonic process uptime contracts.
11. Settings are explicitly reloaded at startup and transactionally saved to
    `prefs.js`. Preserve rollback on save failure. App history is not Places or
    browsing-data deletion. Avoid strong references to old content documents.
12. Fullscreen requires genuine trusted/owned active content, Gecko permissions
    and real exit handling. Do not bypass focus/user-activation checks. Origin
    notices must describe the actual fullscreen frame without query strings.

## Diagnostics, console and private material

- Diagnostics **off by default**. Enabling capture or collecting private evidence
  requires the operator's explicit consent; do not change their diagnostics flag.
- Clear only known app-owned log files. Preserve profile, cache, bookmarks,
  history and unrelated markers. Reject symlinks and traversal; no broad remote
  delete or recursive cleanup of `/data`.
- Transfer via `scripts/deploy-console.py` only to an explicit destination after
  source/native/package validation. Verify the entire remote SHA-256, retain
  reports. Upload does not mean permission to install or launch.
- `scripts/fetch-console-crash.py` is bounded, atomic, read-only FTP acquisition;
  it opens no kernel reader. At most one owned kernel reader; verify current
  PID, command, socket and TTL before reuse/termination. Old PIDs expire.
- Never commit `.pi/`, captures, dumps, profiles, package/ELF files, SDK copies,
  proprietary docs/assets, credentials or private console addresses. A public
  source archive must use the allowlisted exporter, not `tar` of this directory.
- Keep matching crash ELF/source/report bindings. `dist/OrbisFox.pkg` is a
  protected local historical baseline when present, not a fresh-clone prerequisite.
  Keep full 0.56 rollback and retained crash pivots unless the operator changes
  retention. Do not run `make clean` casually; its confirmation is intentionally
  guarded. Never erase/download a large tree just to hide a build failure.

## Licensing, scope and communication

Original owned material defaults MIT; exceptions in `LICENSES/README.md` govern
Gecko/MPL, ANGLE/BSD, LLVM and designated OpenOrbis/GPL files. Do not infer that
root MIT relicenses dependencies. GPL/LGPL binary source/relinking compliance
is an open release gate. Do not copy proprietary SDK code/assets even if local
reference documentation is available.

Prefer small reviewable changes, one writer per worktree, focused failing
regressions and explicit uncertainty. Do not repeatedly regenerate narrative
release notes for routine engine iterations; update current contributor docs
when behavior/commands materially change. Do not call a preview 1.0-ready or
claim live streaming/JIT/GPU/WebAssembly support without real evidence.

At the end, summarize changed paths, tests, unresolved limits and any authorized
side effects. Never silently publish, upload, install, launch or power off.
