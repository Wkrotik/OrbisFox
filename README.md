# OrbisFox

**An experimental native Gecko browser for homebrew-enabled PlayStation 4.**

OrbisFox runs real Gecko HTML/CSS layout, SpiderMonkey JavaScript, NSS networking,
Software WebRender and software audio/video decoding on PS4. It is not a wrapper
around the system browser, a remote-rendering client or a reskinned diagnostic UI.

## Current SDK baseline

`main` includes the pre-uBO browser checkpoint **`95137c3`**, built with
[`ps4-homebrew-dev/sdk` v0.2.1](https://github.com/ps4-homebrew-dev/sdk)
(commit `ecc8347aa20d7b3423405a5e94d7ab119485160d`). Thanks to its contributors
for the native CRT, system-library bindings and build tools. This lane uses real
console libc imports and separate C++/Rust runtimes, not the old OpenOrbis musl
runtime. See [the SDK guide](docs/HOMEBREW_SDK.md) for details.

The merged baseline includes the custom keyboard/R2 Enter, reversible reduced
motion, optional Portable Baseline Interpreter, and bounded input/worker-teardown
changes. Native browsing has console evidence, but long stalls and crashes
remain; these changes are not a demonstrated overall speedup. **uBO is excluded.**

OpenOrbis contributors remain credited for retained service headers, the font
implementation, linker/sample-derived code and independent package tooling.
Changing SDKs does not remove their provenance or licenses; see
[THIRD_PARTY.md](THIRD_PARTY.md). The default-off
[Mesa/WebRender experiment](docs/MESA_WEBRENDER.md) is not part of the new-SDK
software-rendered package and is not a proven fix for the Mesa startup crash.

## Project status

OrbisFox is an **early alpha for developers and testers**, not a polished or
production-hardened browser. Heavy sites can be very slow, and streaming and
web-application compatibility are incomplete. Substantial platform work remains
before it can be a reliable everyday browser.

See [Releases](https://github.com/Wkrotik/OrbisFox/releases) for published versions,
downloads and build-specific testing notes, and
[Issues](https://github.com/Wkrotik/OrbisFox/issues) for known bugs and planned
work. This README covers the project, architecture and basic usage rather than
tracking individual release results.

### Working and implemented

- Native 1280×720 browser with up to **three nonremote tabs**.
- Real Gecko layout and JavaScript interpretation; HTTP/HTTPS through Gecko/NSS.
- Controller pointer/scrolling, custom chrome keyboard, navigation, zoom and find-in-page; native PS4 IME backend retained for later repair.
- Bookmarks, application history, recent sites and settings persisted in the profile.
- Firefox-style address bar: plausible hosts navigate (localhost/IP literals over
  HTTP), everything else searches; `@ddg`, `@wiki` and other one-off search keywords.
- Recently closed tabs, per-entry history deletion, custom home page, optional
  "open previous tabs at startup", Global Privacy Control and clearing cookies/site data.
- Site identity indicator (lock / "Not Secure") with a site-information panel and
  readable load-error messages instead of raw status codes.
- Native pointer/chrome feedback on a separate worker; actual content and
  Gecko-backed UI still share the main thread.
- Software H.264/AAC and VP8/VP9/Opus/Vorbis/FLAC/MP3 decoding and native AudioOut.
  Controlled local WebM, MP4 and fragmented-MP4/MediaSource playback was observed
  on-console. Site compatibility is a separate matter.
- Noto Latin, symbols, math and color-emoji fallback fonts; not complete CJK coverage.
- Opt-in diagnostics, off by default, with application-log cleanup in Settings.
- Website light/dark/system preference and site-fullscreen integration.

### Important limits

| Area | Current reality |
| --- | --- |
| JavaScript | No working native JIT on tested firmware; the real execution gate returns EPERM. Optional Portable Baseline interprets CacheIR without generated code; no overall speedup is established. |
| WebAssembly | Not supported by the current native backend. |
| Graphics | CPU Software WebRender/SWGL plus VideoOut presentation; no accelerated page rendering, supported WebGL/WebGPU or hardware video decoder. |
| Responsiveness | Multi-second main-thread stalls have been measured. A moving native cursor does not mean the page is responsive. |
| Streaming | Live-stream compatibility is incomplete. Local playback does not establish remote-player, MediaSource/live or DRM compatibility. |
| WebSockets | Gecko's implementation is present; API availability alone does not establish end-to-end console/site compatibility. |
| Isolation | Content is in-process, with no desktop-style content sandbox. Chrome/web principal checks remain enforced, but are not process isolation. Avoid sensitive accounts and untrusted browsing. |
| Compatibility | No uBO, supported extension platform, DRM/CDM integration or full desktop Firefox UI. Website support depends on the APIs and platform capabilities it requires. |

## Build on Linux

Expect a large first build: reserve **at least 100 GB of disk**, substantial
RAM and a lengthy engine build. Start with four jobs rather than assuming all
host cores fit in memory. The build fetches hash/revision-pinned public sources;
it does not need a proprietary PlayStation SDK.

Host requirements include Git, Bash, Python 3, Node.js, GNU make, curl, unzip,
tar/xz, clang/clang++, lld, LLVM utilities, CMake, Ninja, a C++ host compiler with
ASan/UBSan, Rust/cargo, and the normal Gecko Linux host prerequisites. Rust must
match the script's pinned **1.99.0** source version. Tested tooling included
clang/lld 23.1.1; arbitrary compiler/runtime substitutions are not certified.
Host media tests additionally need `ffmpeg`/`ffprobe` with the test encoders.
See [contributor setup](CONTRIBUTING.md) for details and build-lane distinctions.

From the project root:

```sh
python3 scripts/build-gecko-app.py --sdk homebrew --portable-baseline --jobs 4
python3 scripts/package-gecko.py --sdk homebrew --resource-format omni
python3 scripts/verify-gecko-package.py --sdk homebrew
ORBISFOX_SDK=homebrew make test          # host regressions; not a PS4 emulator
make source-release                    # source only; not an upload/publication
```

Select `--sdk homebrew` explicitly: unqualified `make` and producers still default
to the historical OpenOrbis lane. Omit `--portable-baseline` for the generic JS
interpreter. Do not swap SDKs in an existing engine object tree or reuse old-SDK
archives; the producers reject mixed identities. The new SDK and isolated runtime
prerequisites are fetched/built by the engine pipeline.

Primary browser artifacts:

- `dist/gecko-homebrew/OrbisFox-Homebrew.pkg` — **OrbisFox SDK Test**, title ID `ORHB00001`.
- `dist/gecko-homebrew/orbisfox.elf` — matching native ELF for debugging.
- `build/gecko-app-homebrew/build-report.json` — native link/source binding.
- `dist/gecko-homebrew/build-report.json` and `build/gecko-app-homebrew/extracted-payload-report.json` — package verification.
- `/data/orbisfox/homebrew-profile` — separate from the old ORBF00001 browser
  profile; no automatic migration. Back up important data before switching.
- `build/releases/orbisfox-<version>-alpha-source.tar.gz` and `.sha256` — source export.

The old `make pkg` and `make pkg-videoout` targets build **standalone bring-up
lanes**, not the current full browser. Default `make` now selects `pkg-gecko`.
There is no requirement to possess the maintainer's historical baseline package
in a fresh checkout; if one exists it must remain unchanged.

## Console testing and controls

Install and launch manually using your existing homebrew package installer on a
console you own. Support is not established across every PS4 model/firmware.
Record the model, firmware and homebrew environment with every report. Installing
an app is not a firmware modification, and this project provides no jailbreak.

| Control | Action |
| --- | --- |
| Left stick / touchpad | Move pointer |
| Right stick | Scroll |
| Cross | Click / activate |
| Circle | Close overlay or send Escape |
| Square | Open custom keyboard; delete while typing (hold to repeat) |
| Triangle | Reload / stop; space while typing |
| Options | Menu / leave fullscreen |
| L1 / R1 | Previous / next tab; move caret while typing |
| L2 / R2 | Back / forward; **R2 is Enter while typing** |
| L3 | Find in page |
| R3 | Middle click; link to background tab, tab to close |
| D-pad | Navigate browser controls/menu/keyboard keys |
| Options + Circle | Exit OrbisFox |

The current SDK browser uses a custom chrome keyboard for address/search, Find and
standard text inputs/textareas. R2 submits chrome drafts or sends Enter to a
single-line page field; in a textarea it inserts a newline. Done closes page
entry without submitting. Circle discards chrome drafts, but cannot undo live
page edits. Password drafts are masked and cleared on close. Sony's backend is
retained for later repair; suggestions and a Settings selector are deferred.
The keyboard runs on Gecko's main thread and can still stall during long tasks.
The pre-uBO implementation is now included in `main`.

Settings includes the full Controls guide. Profile data lives under
`/data/orbisfox/`. Diagnostics are **off by default**; enable only for a controlled
reproduction, collect evidence, then disable again. Logs may contain private
URLs or identifiers: never publish raw profile data or captures without review.

Transfers are explicit and never install or launch the package:

```sh
python3 scripts/deploy-console.py --sdk homebrew --host <console-IP> --port 2121
```

No kernel capture is started unless explicitly requested with `--capture`.
Do not publish the maintainer's local console addresses, logs or dumps.

## Contribute

Start with [CONTRIBUTING.md](CONTRIBUTING.md), [architecture](docs/PORTING.md),
[hardware/evidence guidance](docs/HARDWARE.md) and [release gates](docs/RELEASING.md).
Agents must also read [AGENTS.md](AGENTS.md).

High-impact work includes supported JIT/executable-memory integration, profiling
and scheduling, native hardware video decoding, accelerated rendering, working
live-stream networking/player paths, memory budgets, and enforceable isolation.
Please bring measurements and reproducible tests, not advertised features that
lack a real backend.

## License

**Original OrbisFox code is MIT, with explicit exceptions. The complete browser
is not MIT-only.** MIT permits use, modification and redistribution with the
copyright and permission notice retained. Gecko/MPL, FFmpeg/LGPL, LLVM, fonts
and GPL/OpenOrbis-derived material retain their respective terms. See [LICENSE](LICENSE), the
[file/component license map](LICENSES/README.md) and [THIRD_PARTY.md](THIRD_PARTY.md).
Binary corresponding-source/relinking compliance remains a release gate.

OrbisFox is independent of Mozilla, Sony, ps4-homebrew-dev and OpenOrbis. No Firefox branding,
proprietary SDK, firmware modules or proprietary shader binaries are bundled.
