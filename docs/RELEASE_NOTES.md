# OrbisFox 0.69 Alpha — native SDK prerelease candidate

**Experimental PS4 browser. Not production-ready.**

This is the pre-uBO baseline merged from `95137c3`, versioned as 0.69. The package
uses internal version **00.69**. Publication requires a fresh matching package and
verified native-SDK source/relink materials; check the GitHub prerelease for asset
availability rather than treating these candidate notes as a download announcement.

## Changes

- Switch the browser to **ps4-homebrew-dev/sdk v0.2.1**, with isolated C++/Rust
  runtimes and real console libc imports.
- Add a custom controller keyboard, including **R2 for Enter**. Keep Sony's
  native keyboard backend for later repair.
- Add a saved reduced-motion setting and an optional **Portable Baseline
  interpreter**. This is not native JIT; no overall speed improvement is claimed.
- Bound input replay and use asynchronous finished-worker teardown to reduce
  unnecessary main-thread waits; add diagnostics and regression coverage.
- Update SDK acknowledgements and contributor/build documentation. Retain
  OpenOrbis and other upstream notices for the components still used.

**No uBO implementation is included.**

## Installation identity and limits

The SDK package uses **ORHB00001 / OrbisFox SDK Test**, separately from the old
ORBF00001 browser. It uses `/data/orbisfox/homebrew-profile`; existing browser
bookmarks/settings/history are not automatically migrated. Install manually on a
compatible homebrew-enabled PS4 when a validated package is published.

Long stalls and crashes remain. Native JIT, WebAssembly, GPU rendering, hardware
decoding and DRM are unavailable. YouTube/Twitch live playback and controlled
WebSocket page loading are not established as fixed. Retain the in-process/no-
content-sandbox warning. Diagnostics stay off by default.

Fresh native build, package extraction and unchanged/modified-library relink
verification are release gates, not console acceptance. No new console acceptance
run is claimed for this candidate; earlier dev-worktree evidence is separate.
