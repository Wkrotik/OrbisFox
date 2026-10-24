# Hardware testing and evidence

## Evidence levels

Keep these claims separate:

1. Source/configuration inspection.
2. Host tests, sanitizer checks and firmware doubles.
3. Actual native compile/link, ELF verification and package extraction/hash checks.
4. Controlled on-console reproduction with matching package/ELF/source.
5. Broad hardware/site compatibility testing.

Only level 4 proves a native path executed on a console; none of these alone is
production certification. A passing synthetic clip is not a passing live player.
The maintained implementation baseline is 0.69. `main` now includes pre-uBO
checkpoint `95137c3` on ps4-homebrew-dev/sdk v0.2.1. Earlier ORBF00001/OpenOrbis
results below remain historical evidence, not measurements of the new SDK.

## Current observations

- Native browsing, bookmark/settings persistence, fonts and local playback have
  console evidence. The maintainer reported no crashes in the 0.66 test session.
- Controlled 0.67 WebM/MP4/MediaSource clips ran around five seconds/120 frames
  with respectively 0/0/1 dropped frames. H.264/AAC capability became available
  after actual decoders were added, not after a MIME override.
- YouTube chat was reported working after 0.67. YouTube/Twitch livestreams still
  stall; remote video can stutter while local clips/audio remain smooth.
- Native executable-memory creation returned EPERM `0x80020001`. The JS
  interpreter fallback is intentional, and WebAssembly is not supported.
- The latest controlled WebSocket test page still failed to open on-console.
  Host RFC6455 fixture tests do not settle that issue.
- Main-thread stalls of multiple seconds were captured; no validated percentage
  allocation among JS/layout/render/decode exists yet.
- 0.68 includes fullscreen, content color-scheme and CPU-affinity-count changes.
  They require broader console validation; do not claim they solved live playback.
- Native-SDK browsing sessions and genuine Portable Baseline entry were observed;
  O2/Portable Baseline did not establish an overall responsiveness improvement.
  Multi-second stalls and CE-34878-0 crashes remain; see `HOMEBREW_SDK.md`.
- The merged custom keyboard/R2 Enter path has focused host regressions. Broader
  hardware coverage of focus, canceled keydown, multiline newlines, passwords and
  held-button release is still required. The SDK browser (ORHB00001), legacy
  browser (ORBF00001) and standalone SDK Dialog Probe are different test targets.
- uBO experiments are excluded from this merged checkpoint. Do not attribute
  their blank-popup/navigation failures to the pre-uBO package.

Early bring-up was reported on firmware 11.00 / GoldHEN v2.4b18.12. Do not
infer that all later runs or every console model share that environment. Ask
for exact model, firmware and homebrew version with each new report.

## Safe reproduction workflow

1. Build/verify a candidate and retain its full package and ELF SHA-256, exact
   source snapshot, native report and package extraction report.
2. Choose the target explicitly. Uploading is not installing or launching;
   those remain the operator's actions. Do not alter unrelated console settings.
3. Diagnostics are off by default. Enable in Settings only for a controlled
   reproduction with consent; note whether they were enabled when timing.
4. Preserve the run and matching crash dump before relaunching; the OS may
   replace old dumps. Use read-only bounded collection, not remote cleanup.
5. Disable diagnostics after acquisition. Review/redact evidence before sharing.

```sh
python3 scripts/deploy-console.py --sdk homebrew --host <console-IP> --port 2121
python3 scripts/fetch-console-crash.py --host <console-IP> --port 2121 \
  --version <version> --logs-only --out build/hardware-<version>/reproduction
```

Deployment does not enable the application's diagnostics flag. `--capture` is a
separate explicit kernel-log opt-in; only one verified owned reader may exist.
Check PID, command, socket and TTL before reuse or termination. The fetcher
opens no kernel reader. Never reuse a historical PID blindly.

Run logs live under `/data/orbisfox/runs/` only when enabled. Profile, bookmarks,
history, cache and unrelated markers are not log-cleanup targets. Do not commit
raw logs, kernel output, dumps, captures, profiles or screenshots with private
URLs. Historical raw evidence and the original bring-up notes are retained
locally under ignored `build/project-history/` and hardware archive directories.

## Opt-in resource packaging trial

The unqualified package default remains unpacked; the recommended SDK commands
explicitly select `omni`. A packaging-only candidate can use Gecko's
existing `omni.ja` loader instead of thousands of separate resource files:

```sh
python3 scripts/package-gecko.py --sdk homebrew --resource-format omni
python3 scripts/verify-gecko-package.py --sdk homebrew
```

Build/verify the native application first, including any local native changes.
Retain the previous package, ELF and reports before producing the candidate.
The archive uses ZIP **stored** entries: unchanged resource bytes, no compression,
feature removal or executable changes. Generated preferences and chrome manifests
are included; small loose compatibility copies remain for filesystem diagnostics.
Extraction validation checks every archived resource against its original hash,
not just the outer archive. Fonts, licenses and codec source remain packaged.

The maintainer reported a successful console trial of the compact candidate with
local scrolling changes, and confirmed that L3 Find / R3 middle-click work as
expected; no button remapping was needed. This is reported hardware feedback, not
an independently captured compatibility or performance result. The trial reduced
the package from 482,148,352 to 327,811,072 bytes without resource compression.

Broader validation should cover startup, Home/Library/Settings, fonts/emoji, Find,
scrolling, normal navigation, fullscreen and controlled media before making this
the default. Record cold/warm loading and memory observations too: archive file
mapping is a different I/O pattern. Keep the unpacked package as rollback; a
smaller extracted image alone does not establish that Gecko loaded it.

## Controlled fixtures

These are bounded local HTTP services, not public production servers. Use the
complete `http://` URL; address entry can otherwise default to HTTPS. Do not
weaken TLS to make a plain HTTP test work. The console must reach the chosen host
and its firewall must allow the explicit test port.

```sh
python3 scripts/prepare-media-fixture.py --host <host-LAN-IP> --serve-seconds 7200
python3 scripts/serve-browser-network.py --host <host-LAN-IP> --port 8767 --seconds 7200
```

- Media on port 8766: actual host-generated VP9/Opus WebM, progressive H.264/AAC
  MP4 and fragmented MP4/MediaSource. Moving pattern + five-second tone.
- Networking on port 8767: HTTP fetch, same-origin iframe and real masked
  WebSocket nonce echo/normal close. Exact Host/Origin checks are intentional.
- These fixtures are HTTP/WS only; they do not establish WSS, TLS or all server
  implementations. A page that never opens has not completed its WebSocket test.
- Servers have bounded lifetime/concurrency. Verify process ownership, stop
  only your instances and never claim host PASS is console PASS.

For regressions record URL, codec/resolution, ready state, actual frame/drop
counts, cold/warm timing, diagnostics state and the run/package binding.
