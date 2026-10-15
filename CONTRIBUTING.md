# Contributing to OrbisFox

Thanks for helping an early native browser port become useful. This is a source
alpha, not desktop Firefox with a different build switch. Read the limitations
in [README.md](README.md) before proposing compatibility or performance claims.

## First setup

Use a Linux host with Git, Bash, Python 3, Node.js, GNU make, curl, unzip, tar/xz,
clang/clang++, lld and LLVM tools (`llvm-ar`, `llvm-ranlib`, `llvm-nm`,
`llvm-objcopy`, `llvm-strip`, `llvm-objdump`), CMake/Ninja, and a sanitizer-capable
host C++ compiler. Gecko also needs its normal Linux host tools/libraries,
including pkg-config and the supported Python environment. Match Rust/cargo to
`scripts/bootstrap-rust.py`'s pinned 1.99.0 sources; install a matching public
compiler if unavailable. No proprietary SDK is required or accepted.

Reserve at least 100 GB of disk and enough RAM for large C++/Rust translation
units. All downloaded sources/toolchains stay under `.deps/`; output stays under
`build/` and `dist/`. These directories are intentionally ignored, not committed.
Do not use `make clean` as routine troubleshooting: existing developer trees
contain rollback packages, active thin-archive inputs and irreplaceable evidence.

```sh
make bootstrap                       # public, hash-pinned OpenOrbis v0.5.3
ORBISFOX_JOBS=4 make                  # complete browser pipeline
make validate
make test
```

The default pipeline builds the standalone runtime/SpiderMonkey prerequisites
before the full engine. This is intentional: several regression and embedding
inputs still live in `build/gecko-spidermonkey/`. `make pkg` is the historical
standalone application, **not** the browser. A missing historical
`dist/OrbisFox.pkg` is acceptable on a fresh checkout; an existing one is protected.

Useful focused stages after initial setup:

```sh
make gecko-build                     # runtime/standalone SpiderMonkey lane
python3 scripts/build-gecko-layout.py --jobs 4
python3 scripts/build-gecko-app.py
python3 scripts/package-gecko.py
python3 scripts/verify-gecko-package.py
```

The full engine builder has a separate `--jobs` setting (default four).
`ORBISFOX_JOBS` controls the standalone build. Avoid launching two producers
against the same object directory. Tests may download/build pinned host inputs;
`make test` is not a dependency-free lint target. Media tests need host
`ffmpeg`/`ffprobe` with libx264, AAC, VP8/VP9, Opus, Vorbis, FLAC and MP3 test
encoders. These encoders are host-only fixture tools.

A fresh, dependency-free subset for editing the shell/model is:

```sh
node tests/browser_shell_test.js
node tests/browser_shell_ui_test.js
node tests/browser_shell_host_test.js
node tests/browser_fullscreen_test.js
node tests/browser_network_observer_test.js
python3 -m unittest discover -s tests -p 'source_release_test.py'
```

## Where to change things

See [the architecture map](docs/PORTING.md). In particular:

- Maintain Gecko changes in **`gecko/` and producer scripts**, not only in
  `.deps/gecko-layout/`. Producers copy/patch the latter and can overwrite it.
- Keep compiler/SDK ABI fixes in wrappers/overlays with focused tests and
  actual final-ELF verification. A stock FreeBSD header or Linux host result is
  not evidence of the console ABI.
- Keep browser shell/model/UI tests with shell changes. Changes crossing the
  native host IDL need UUID regeneration and synchronized fixtures/adapters.
- Keep codec feature claims tied to real decoder lookup and actual decoded
  frames/samples, not preference toggles or MIME strings.

## Patch expectations

1. Describe the issue, hypothesis and reproduction before a broad rewrite.
2. Keep one coherent change per PR; avoid formatting-only churn in vendor patches.
3. Add a regression that fails before the fix. Preserve existing assertions and
   error paths; do not turn genuine failures into success to make a page load.
4. Run relevant focused tests, then `make test` when dependencies are available.
   Report what was not run and why. Never equate a sanitizer/host double with
   firmware validation.
5. For native changes, build and verify the actual linked ELF/package. Retain
   package/ELF SHA-256 and matching source/build reports. Hardware evidence must
   identify version, model, firmware, run and reproduction steps.
6. Use clear commits, preferably `fix(scope): intent`, `feat(scope): intent`,
   `docs: intent` or `test: intent`. Do not commit downloads, packages or captures.

Do not bypass TLS validation, origin/principal checks, file locks, allocator
ownership, fullscreen permissions or assertions. Never expose privileged native
objects to web content. Do not add a permission bypass, RWX heap or fabricated
API result as a JIT/media fix.

## Reporting bugs and performance

Include version/commit, console model, firmware/homebrew version, exact URL when
safe, expected/actual result, reproducible steps and whether diagnostics were on.
For playback include codec/resolution, progressive vs MediaSource/live, and
local-fixture vs remote-site results. For slowness separate navigation timing,
main-thread stalls, decode quality, frame presentation and native cursor behavior.
Do not infer a leak from one increasing memory sample or CPU percentages from
our last-long-task label; it is not a sampled CPU profile.

Diagnostics are off by default. Enable briefly in Settings only with the tester's
consent. `scripts/fetch-console-crash.py --version <version> --logs-only` is
read-only and opens no kernel reader. Always pass the intended destination
options for your console; do not inherit another developer's addresses. Treat
logs, profiles, dumps, URLs and screenshots as private until manually redacted.

Native installation/launch is an operator action. Transfers require an explicitly
chosen console, verify the full remote SHA and must never silently install,
launch, change unrelated settings or erase profile data. Kernel capture is
separate opt-in, with at most one verified, bounded reader.

## Licensing and authorship

New original files default to MIT. Changes to existing files follow their
component license; Gecko/derived Mozilla patches are MPL, the ANGLE helper is
BSD, and designated OpenOrbis-derived files remain GPL. Consult
[LICENSES/README.md](LICENSES/README.md) before copying or moving code. Add a
license/provenance entry for every new dependency. Preserve upstream headers.

By submitting a patch, you confirm you have the right to contribute it under the
applicable component license. No CLA or assignment is required. Do not submit
proprietary SDK material, firmware binaries, shader binaries, private keys or
unlicensed artwork. Contributions are recorded in Git history.

## Preparing an alpha

Run `make source-release` to build a reproducible, allowlisted source archive
with an embedded per-file SHA-256 manifest and a read-back verification report.
It is a source artifact, **not** complete corresponding source for every linked
binary dependency. Follow [docs/RELEASING.md](docs/RELEASING.md) before publishing.
No automated command in this preparation publishes a repository or release.
