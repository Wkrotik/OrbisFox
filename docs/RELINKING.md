# Binary source and static-library relinking

## Scope: verified exporter is legacy OpenOrbis only

The instructions below describe the existing **ORBF00001/OpenOrbis** object-only
kit. `main` now also contains the native **ps4-homebrew-dev/sdk v0.2.1** browser
(ORHB00001); this exporter is **not yet a verified relinking route for it**.
Do not use an old kit to satisfy a new-SDK binary release. The native application
uses a different CRT, system libc imports and isolated C++/Rust runtimes; the
musl allocator object and old linker command are not interchangeable with them.

Before publishing a native-SDK package, export its exact application/codec
objects, dependency source/configuration/notices and native linker inputs, then
successfully relink both unchanged and modified LGPL library inputs. Preserve
the exact ELF/source binding and keep proprietary firmware libraries out. Until
that route passes, the new binary release remains blocked; source publication
alone does not remove this requirement.

## Existing OpenOrbis release route

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
ORBISFOX_JOBS=4 make
make validate
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
SDK distribution. The required audited allocator object comes from the public
OpenOrbis musl runtime, whose notices are retained. Obtain the public,
hash-pinned OpenOrbis SDK with the source archive's `make bootstrap`.

With clang/lld and LLVM utilities installed on Linux:

```sh
tar -xzf orbisfox-<release>-relink.tar.gz
python3 orbisfox-relink/relink.py \
  --sdk /absolute/path/to/OpenOrbis/PS4Toolchain \
  --output /absolute/path/to/orbisfox.elf
```

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
  --sdk /absolute/path/to/OpenOrbis/PS4Toolchain \
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
4. Run `python3 scripts/build-media-codecs.py --jobs 4`. This rebuilds and
   namespaces the real codec/util/resampler archives. Use the three resulting
   files from `build/media-codecs/native/` with `--codecs` above.

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
