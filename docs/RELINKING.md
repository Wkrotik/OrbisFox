# Binary source and static-library relinking

## SDK lanes and release-specific verification

The exporter supports the native **ps4-homebrew-dev/sdk v0.2.1** browser
(**ORHB00001**, `--sdk homebrew`) and historical **OpenOrbis/ORBF00001**
(`--sdk openorbis`). Its default remains OpenOrbis. Native kits use the native
CRT, system libc imports and isolated C++/Rust runtimes, not the old musl
allocator or legacy linker command. Never mix the two lanes.

Each binary release still requires its own exact matching application/codec
objects, source/configuration/notices and linker inputs, plus successful
unchanged and modified-LGPL relink trials. An older kit or a unit-test pass does
not verify a new binary. Preserve the matching verification records; never
include proprietary firmware libraries in the public kit. Source publication alone does not
remove the binary-release requirements.

## Matching release materials

Tester releases should offer the installable `OrbisFox.pkg` first. Source and
relinking downloads accompany it for contributors and redistribution obligations;
they are not substitutes for the installer. Always use the materials attached to
the **same release**, rather than assuming current `main` matches an old package.

## Rebuild from source

The project source archive contains the application, maintained Gecko patches,
compiler/runtime adaptations, linker scripts and packaging instructions. Public
dependency revisions/hashes and their licenses are listed in `THIRD_PARTY.md` and
the producer scripts. Follow `CONTRIBUTING.md` for the complete build:

```sh
make bootstrap
ORBISFOX_SDK=homebrew ORBISFOX_JOBS=4 make
python3 scripts/verify-gecko-package.py --sdk homebrew
```

The native package contains generated Gecko `about:license` resources and notices
under `assets/misc/`. Original MIT files do not relicense Gecko/MPL, FFmpeg/LGPL,
LLVM or the designated GPL/OpenOrbis-derived material. See `LICENSES/README.md`.
The combined application/relink objects are distributed conservatively under
GPL-3.0-or-later-compatible terms, preserving component-specific licenses.

## Relink without rebuilding Gecko

The matching `orbisfox-*-relink.tar.gz` contains application object files,
materialized static archives, LLVM runtimes/notices, the exact linker script,
original isolated FFmpeg archives/configuration, FFmpeg source, and project
source. Debug information is removed, not code or symbols needed for relinking.
It contains **no proprietary SDK or firmware modules** and does not bundle an
SDK distribution. A native kit additionally includes the pinned public SDK's
corresponding CRT/runtime source archive. Fetch its matching public SDK using
`python3 scripts/fetch-homebrew-sdk.py`; `link.json` records the SDK lane and
hashes its input files. Legacy kits instead require the public OpenOrbis SDK
and its audited musl allocator object, with the relevant notices retained.

With clang/lld and LLVM utilities installed on Linux:

```sh
tar -xzf orbisfox-<release>-relink.tar.gz
python3 orbisfox-relink/relink.py \
  --sdk /absolute/path/to/ps4-homebrew-sdk-v0.2.1 \
  --output /absolute/path/to/orbisfox.elf
```

For an old OpenOrbis kit, use its matching `OpenOrbis/PS4Toolchain` directory
instead. The native SDK path is its root containing `bin/` and `target/`, not
`target/` alone. The driver verifies the pinned native SDK inputs before linking;
it does not prevent you from explicitly adapting your own copy for a modified SDK.

`verification.json` records the exported kit's test against the release ELF.
The execution image and every symbol record must be identical; only reordering
of non-loadable `.symtab` entries is permitted, because materializing thin
archives changes lld's symbol enumeration. Full file hashes and byte-identity
are recorded separately. That is link evidence, not a console execution test. `link.json` inventories exported files with
sizes/SHA-256 and records the argument vector; the driver does not use a shell.

To substitute modified LGPL libraries, provide all three matching static
archives, with their public/internal definitions consistently namespaced:

```sh
python3 orbisfox-relink/relink.py \
  --sdk /absolute/path/to/ps4-homebrew-sdk-v0.2.1 \
  --codecs /absolute/path/to/replacement-archives \
  --output /absolute/path/to/modified-orbisfox.elf
```

The filenames are `liborbis_avcodec.a`, `liborbis_swresample.a` and
`liborbis_avutil.a`. Preserve the FFmpeg 9 ABI used by Gecko's typed bindings;
changes to that ABI also require rebuilding the application.

### Build modified FFmpeg libraries

The original public FFmpeg archive is included in the kit and package. The
canonical `scripts/build-media-codecs.py` contains the complete configure,
Orbis capability adaptations and symbol-renaming steps. Its default hash checks
intentionally reject accidental changes; they are not a restriction on making
an explicit modified build. To use that pipeline for your fork:

1. Unpack and modify `ffmpeg-9.0.2` in a separate directory.
2. Create a new `.tar.xz` with that top-level directory name. In your project
   checkout, replace `.deps/downloads/ffmpeg-9.0.2.tar.xz` with the modified archive
   and update `SHA256` in your copy of `scripts/build-media-codecs.py` to its hash.
3. Use a separate checkout/output tree, or move the previous extracted
   `.deps/ffmpeg-9.0.2` aside so extraction and verification use the modified
   archive. Keep the original release materials intact.
4. Run `python3 scripts/build-media-codecs.py --sdk homebrew --jobs 4` for the
   native release. This rebuilds and namespaces the real codec/util/resampler
   archives in `build/media-codecs/native-homebrew/`. Legacy kits instead use
   `--sdk openorbis` and `build/media-codecs/native/`. Supply the matching three
   archives with `--codecs` above.

The included `codec-build/` files record the release configuration and symbol
map; they are not instructions to preserve an unmodified implementation. Users
may modify/relink the LGPL components and reverse-engineer the application for
debugging such modifications, as provided by the applicable licenses.

## Turn the modified ELF into an installable package

Use the public SDK `create-fself`, `create-gp4` and `PkgTool.Core` workflow in
`scripts/package-gecko.py`. That producer shows the title/content identifiers,
SELF flags, SFO fields and complete resource list. Do not rename an ELF to `.pkg`.
The normal source-build pipeline builds a matching report and packages it for
you; its verification gates deliberately reject an unrelated ELF substituted
into an old build report. If using the object-only route, convert the relinked
ELF to `eboot.bin`, replace that file in a copy of the original package's extracted
payload, regenerate its GP4, and rebuild/validate with the same public tools.
Retain all resource files and license notices. Install and launch manually on
your own homebrew-enabled console; no relink/export command contacts a console.

These engineering materials do not certify patent clearance, trademark rights,
production security, every modification, or compatibility with every firmware.
