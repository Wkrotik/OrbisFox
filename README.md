# OrbisFox

**An experimental native Gecko browser for homebrew-enabled PlayStation 4.**

OrbisFox runs real Gecko HTML/CSS layout, SpiderMonkey JavaScript, NSS networking,
Software WebRender and software audio/video decoding on PS4. It is not a wrapper
around the system browser, a remote-rendering client or a reskinned diagnostic UI.

## Development branch

`dev` is an experimental development branch, not a release or stability promise.
It retains the default-off [Mesa/WebRender experiment](docs/MESA_WEBRENDER.md),
its diagnostic tools and host tests. The latest Mesa console candidate still
crashes during startup; a passing host suite or native link does not establish
console stability. New-SDK migration has not been implemented in this checkpoint.
Use `main` and the published releases for the existing software-rendered baseline.

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
- Controller pointer/scrolling, native PS4 IME, navigation, zoom and find-in-page.
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
| JavaScript | No working native JIT on the tested firmware; the real executable-memory gate returns EPERM and falls back to the interpreter. |
| WebAssembly | Not supported by the current native backend. |
| Graphics | CPU Software WebRender/SWGL plus VideoOut presentation; no accelerated page rendering, supported WebGL/WebGPU or hardware video decoder. |
| Responsiveness | Multi-second main-thread stalls have been measured. A moving native cursor does not mean the page is responsive. |
| Streaming | Live-stream compatibility is incomplete. Local playback does not establish remote-player, MediaSource/live or DRM compatibility. |
| WebSockets | Gecko's implementation is present; API availability alone does not establish end-to-end console/site compatibility. |
| Isolation | Content is in-process, with no desktop-style content sandbox. Chrome/web principal checks remain enforced, but are not process isolation. Avoid sensitive accounts and untrusted browsing. |
| Compatibility | No DRM/CDM integration, extension platform or full desktop Firefox UI. Website support depends on the APIs and platform capabilities it requires. |

## Build on Linux

Expect a large first build: plan for **30 GB or more of free disk**, substantial
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
make bootstrap                         # public OpenOrbis SDK v0.5.3, hash checked
ORBISFOX_JOBS=4 make                    # runtime/JS prerequisites, full engine, native app, package
make validate                          # verify the full browser package
make test                              # host regressions; not a PS4 emulator
make source-release                    # verified, source-only alpha archive
```

An existing compatible SDK can be selected with
`OO_PS4_TOOLCHAIN=/absolute/path/to/OpenOrbis/PS4Toolchain`. The pinned local
layout is the reproducible default. Do not swap SDKs in an existing output tree
without auditing/rebuilding the affected ABI/runtime inputs.

Primary browser artifacts:

- `dist/gecko/OrbisFox.pkg` — experimental browser package, title ID `ORBF00001`.
- `dist/gecko/orbisfox.elf` — matching native ELF for debugging.
- `build/gecko-app/build-report.json` — native link and source-binding evidence.
- `dist/gecko/build-report.json` and `build/gecko-app/extracted-payload-report.json` — package extraction/hash checks.
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
| Square | Address / search entry via native IME |
| Triangle | Reload / stop |
| Options | Menu / leave fullscreen |
| L1 / R1 | Previous / next tab |
| L2 / R2 | Back / forward |
| L3 | Find in page |
| R3 | Middle click; link to background tab, tab to close |
| D-pad | Navigate browser controls/menu |
| Options + Circle | Exit OrbisFox |

Settings includes the full Controls guide. Profile data lives under
`/data/orbisfox/`. Diagnostics are **off by default**; enable only for a controlled
reproduction, collect evidence, then disable again. Logs may contain private
URLs or identifiers: never publish raw profile data or captures without review.

Transfers are explicit and never install or launch the package:

```sh
make upload CONSOLE_HOST=<console-IP> CONSOLE_PORT=2121
# Or, for an already verified candidate:
python3 scripts/deploy-console.py --host <console-IP> --port 2121
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

OrbisFox is independent of Mozilla, Sony and OpenOrbis. No Firefox branding,
proprietary SDK, firmware modules or proprietary shader binaries are bundled.
