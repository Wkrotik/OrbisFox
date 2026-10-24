# Isolated shared-memory failure investigation

This is historical diagnostic work retained on `dev`, not a fix or a browser
performance claim. The crash-matched browser ELF and reports remain retained.
Early browser runs logged `SharedMemory` mmap failures with `EINVAL`; one
subsequently failed cache-stream serialization and another reached `RustMozCrash`
on the compositor thread. Later failure instrumentation established valid,
page-aligned requests with current backing files and a genuine available-flexible
memory query falling to zero before failures. That pressure correlation does not
identify every consumer or decode the exact Rust panic reason. Later GPU startup
heap corruption is a separate unresolved failure, not proof of a mapping fix.

## Failure-only browser records

`scripts/patch-gecko-layout.py` deterministically instruments the existing
`SharedMemoryPlatform_posix.cpp` mmap failure branch on Orbis only. Its detailed
records require the existing `SharedMemory` log module at Warning or higher;
this patch neither enables diagnostics nor changes the operator's marker.

It records errno, requested address/size/offset, protection and mapping flags,
fd, best-effort fstat result/backing size, descriptor flags and page size. Failed
metadata queries are explicitly marked as failures, not valid zero values. The
original mmap errno is restored even when logging/metadata queries change it.
A saturating atomic counter limits detailed records to 32 per process across
threads. No mapped bytes, URLs, filenames or content are dumped. No mapping
retry, changed flag, forced address or assertion suppression is introduced.

This code must be rebuilt into a browser before it can explain a browser run.
Compiling the changed native unified object alone does not update an installer.

## Standalone probe

```sh
python3 -m unittest discover -s tests -p 'shared_memory_diagnostics_test.py' -v
python3 scripts/build-shared-memory-probe.py --package
```

The build uses the selected public OpenOrbis SDK, the browser's private C++
headers/runtime and guarded native stat adapter. It emits only local artifacts
under `build/shared-memory-probe/`; it performs no console/network operations.
The installer has its own identity, `SHMP00001` / **Shared Memory Probe**. It does
not replace either browser. Extraction verifies its SELF, SFO identity, icon and
source archive. Source excludes SDK copies, private evidence and machine config.
Public redistribution still requires a separate licensing/release review.

After separately authorized installation and operator launch, it briefly runs
without a graphical UI, writes an exclusive new
`/data/orbisfox-shmem-probe/run-<pid>-<process-time>.log`, then requests normal
application-manager exit. It never accesses browser profiles, flags, history or
bookmarks and never opens a kernel reader. If normal exit is unavailable, the
operator can close this separate title; it deliberately avoids SDK main-return.
No prior logs are deleted or overwritten. The directory and log path reject
symlinks; shm names are unlinked only after this process successfully created
them with `O_EXCL`.

Tests exercise actual `shm_open` / reopen-read-only / unlink / ftruncate / mmap /
clone / freeze-equivalent writable-view teardown / page-offset map / byte checks
/ descriptor and mapping teardown. The read-only-write negative control must
genuinely fail. Version 1 also assumes misaligned offsets are rejected; the first
console run disproved that assumption for a larger backing file (see below).
Sizes include the native page size,
32/64/512 KiB and 4 MiB, then non-page lengths. Three pressure rounds retain up
to **16 MiB backing / 32 MiB read-only virtual views**, with non-FIFO teardown.
There are 56 creation cycles. The probe stops on the first unexpected failure;
failed uncertain releases are reported, not retried. Its detailed mmap records
are intentional output of this dedicated diagnostic title, not a browser logging
setting change.

### First console result (version 1)

The operator reported a normal Home exit. The retained log
`run-143-1833150.log` confirms 16 KiB and 32 KiB creation, writable/read-only
mappings and descriptor cloning succeeded, with genuine 16 KiB page size.
Read-only shared write attempts failed with `EACCES` as expected. A 16 KiB view
at offset 1 failed with `EINVAL` on a 16 KiB backing file, but succeeded on a
32 KiB backing file, returning an address ending in `001`.

The version-1 probe therefore emitted `RESULT FAIL` at its stricter offset
expectation, before the pressure/larger-size tests. This does **not** establish a
platform mapping fault or explain the browser crash. Do not interpret Home exit
as PASS, claim the pressure tests ran, or change browser offsets/flags based on
this result. Failure-argument logging was subsequently built into the actual browser and
produced the evidence summarized above; another standalone run with this same
version adds little evidence.

Evidence is retained under
`build/hardware-00.01-shmem/captures/1792327210071758752/` with a hash-bound fetch
report. Retrieval was read-only and changed no diagnostics setting.

### Evidence limits and next decision

- ASan/UBSan host runs use real host POSIX operations, not console APIs.
- A strict native link, SELF/package extraction and host pass do not prove
  console execution. A probe failure identifies the first rejected operation.
- This deliberately small executable does not include Gecko IPC serialization,
  GPU rendering, the browser allocator wrappers or its large-process memory
  pressure. A standalone pass does **not** clear those paths.
- If the probe passes on console, use an explicitly authorized diagnostic
  browser rebuild to capture the actual failing arguments. Do not increase
  pressure blindly or globally replace mmap/direct-memory ownership.
- Actual browser GPU-frame publication and GPU/SWGL performance comparisons
  remain separate validation after the crash cause is fixed. The startup shader
  gate alone is insufficient. Main-thread stall work remains subsequent.
