# Alpha release checklist

## Scope of this preparation

This is a **source alpha based on implementation 0.68**, not 1.0 and not a newly
certified binary. Documentation/license/producer changes after the existing
0.68 package require a new matching build/source binding before distributing a
new binary. Do not relabel an old ELF/package or claim it contains these changes.

This checklist does not publish a Git repository, create a remote, install an
application or authorize a console connection.

## Source alpha

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
- [ ] Test actual console launch/exit, repeated navigation, settings persistence,
  IME, fullscreen and color preference, memory pressure and controlled playback.
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
