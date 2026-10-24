# Alpha release checklist

## Current native-SDK baseline

`main` includes pre-uBO checkpoint `95137c3`, ps4-homebrew-dev/sdk v0.2.1,
and the custom keyboard. Keep any release **pre-release / experimental**.
Select `--sdk homebrew` for build/package/verification and record title ID
**ORHB00001**, its separate homebrew profile, and the exact final source commit.
There is no uBO implementation in this baseline. The unqualified build and
existing relink exporter still target the historical OpenOrbis lane.

**Publication remains blocked** until a fresh matching native-SDK package and
complete source/relink artifacts pass the gates below. A retained developer
package or a legacy relink kit must not be relabeled as this release. A draft
changelog is in [RELEASE_NOTES.md](RELEASE_NOTES.md); it is not a published release
or evidence that these gates passed.

## Release artifacts

A tester release must offer an **installable PS4 `.pkg`**, clearly marked
experimental. The source archive is an accompanying contributor/compliance
artifact, not the installer. Rebuild and verify the native application/package
against the release's exact source; do not relabel an old package as containing
later source, resource or licensing changes.

Attach:

- `OrbisFox-<release>.pkg` and its SHA-256 — the download for console users.
- Matching allowlisted project source and SHA-256.
- A verified static-library relink kit and SHA-256, following
  [RELINKING.md](RELINKING.md), with source/dependency/license materials.

State the title ID, manual installation instructions, known failures and what
was actually tested. Keep implementation details in release notes, not a
constantly versioned README. None of these commands installs/launches an app or
authorizes a console connection. Publication requires the operator's permission.

## Source archive

- [ ] Choose the maintainer's public handle/repository location and review the
  contributor list. Do not infer identity from a local username.
- [ ] Review README limitations: no working JIT/Wasm/GPU rendering/hardware
  decode, poor heavy-site performance, unresolved livestream and local test-page
  failures, in-process/no-content-sandbox risk.
- [ ] Confirm the scoped MIT grant is authorized for all original material.
  Retain the exception map and original upstream notices; get permission for
  any independently authored contribution before attempting to relicense it.
- [ ] Run focused tests and `make test`; retain the report outside public source.
  A fresh full dependency/build run is distinct from tests in the maintainer's
  existing workspace. State which one was actually performed.
- [ ] Run `make source-release`. Verify `.sha256` and the embedded
  `SOURCE-MANIFEST.json`; review the allowlisted file inventory.
- [ ] Confirm no SDK/runtime downloads, Git metadata, `.pi`, `.env`, private
  logs/dumps/profiles, packages, ELFs or proprietary reference material are in
  the archive. Do not upload the entire working directory.
- [ ] Inspect the Git staging list before an initial commit. No credentials,
  personal evidence or generated dependency trees may be staged.
- [ ] When ready, create a signed/annotated source tag and publish intentionally.
  No release URL, remote or public upload is invented by these scripts.

The exporter normalizes timestamps/ownership, preserves source executable bits,
embeds per-file sizes/SHA-256, and reads the archive back before success.
It does not certify copyright ownership or scan arbitrary source text for every
possible secret. Human review is still required.

## Additional gates before any binary release

- [ ] Build against the exact source snapshot, public dependency pins and recorded
  toolchain, with all native/package checks passing. Preserve ELF/package hashes.
- [ ] Provide complete applicable GPL corresponding source, including required
  runtime/toolchain modifications, notices, build and installation materials.
- [ ] Provide the LGPL library source/configuration/modifications and a usable
  static relinking route satisfying LGPL 2.1 section 6. Shipping an FFmpeg tar
  alone is not a complete application relinking solution.
- [ ] Complete MPL source availability and the full enabled third-party notice
  inventory; review font, LLVM, SDK/runtime and codec obligations.
- [ ] Review distribution rights/patents/trademarks for target jurisdictions.
  See `LICENSES/README.md` and `THIRD_PARTY.md`.
- [ ] Record actual console launch/exit, repeated navigation, settings persistence,
  custom keyboard/R2 Enter, fullscreen/color preference, memory pressure and
  controlled playback. Sony's retained native IME is not the default.
  For an experimental tester build, explicitly identify untested paths and
  retained baseline evidence rather than inventing a fresh console pass.
- [ ] Record current failed streaming/WebSocket tests honestly. If distributing
  a developer binary with these limitations, mark it experimental, not fixed.
- [ ] Keep diagnostics off by default; ensure public artifacts contain no tester
  browsing data or captures. User alone installs/launches test builds.

## Before calling it 1.0

A responsive, repeatable hardware/site acceptance suite; an actionable security
update process; reviewed isolation/privileges; bounded memory and recovery;
accurate capability reporting; and proven legal/source distribution materials.
A working local clip or a valid package signature is not sufficient.

Performance priorities include supported native JIT, hardware decoding/rendering,
main-thread profiling/scheduling and presentation costs. These are roadmap items,
not features the source alpha already has.
