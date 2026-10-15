# Third-party code and notices

Original OrbisFox material is MIT **with the exceptions in
[LICENSES/README.md](LICENSES/README.md)**. Dependencies are not relicensed by
that grant. OrbisFox is not affiliated with Mozilla, Sony or OpenOrbis and
ships no Firefox artwork, proprietary SDK, firmware modules or shader binaries.

## Pinned components

| Component | Source / pin | License and role |
| --- | --- | --- |
| Gecko, SpiderMonkey, SWGL, NSPR, NSS and bundled libraries | [Mozilla Firefox](https://github.com/mozilla-firefox/firefox), commit `83cebcf5a522bf49667fd07084f04e8497de0eba` | MPL-2.0 and component-specific licenses. Actual native engine, layout, JS, rasterization, TLS and networking. `gecko/` contains the maintained overlay, not the entire upstream tree. |
| OpenOrbis PS4 Toolchain | [OpenOrbis](https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain), v0.5.3, tag commit `6929bafac0b565692ed61e66032a79185ee9cf65` | Repository GPL v3; individual runtime/header components retain their own terms. SDK stubs/runtime and host conversion tools. |
| C++ runtimes | [LLVM](https://github.com/llvm/llvm-project), `2078da43e25a4623cab2d0d60decddf709aaea28` / llvmorg-21.1.8 | Apache-2.0 WITH LLVM-exception, including retained older notices; libc++, libc++abi, libunwind. Built privately with Orbis adaptations. |
| Rust standard library | Rust 1.99.0, source archive SHA-256 `3f1f9b7ed48f4596fc87889b7b3c61747336a55c9c22db1ab0c697e0aadb77aa` | MIT / Apache-2.0 and component notices. Private target/sysroot, not a stock FreeBSD runtime. Rust `libc` and other crates keep their own licenses. |
| Added software codecs | [FFmpeg](https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz), 9.0.2; SHA-256 `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` | LGPL-2.1-or-later configuration; GPL/nonfree/version3/network disabled. Real decoder/util/resampler archives, all defined symbols prefixed `orbis_media_`. |
| Existing FFVPX and media dependencies | Pinned Gecko's `media/ffvpx`, `media/libvpx`, `media/libopus`, `media/libvorbis`, etc. | FFmpeg LGPL and each codec's own notices. Kept distinct from the additional FFmpeg archives; consult upstream component files and build configuration. |
| ANGLE platform adapter | Pinned Gecko's ANGLE | BSD-3-Clause; the Orbis helper keeps that license. This does not establish working WebGL. |
| stb_truetype | Public OpenOrbis SDK copy | MIT option selected; `assets/licenses/stb-truetype-MIT.txt`. Used for the native chrome font atlas. |
| Noto Sans, Symbols 2, Math | [noto-fonts](https://github.com/notofonts/noto-fonts), `ffebf8c1ee449e544955a7e813c54f9b73848eac` | SIL OFL 1.1. Downloaded and hash-checked by `scripts/fetch-layout-assets.py`. |
| Noto Color Emoji | [noto-emoji](https://github.com/googlefonts/noto-emoji), `e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e` | SIL OFL 1.1, including reserved-font-name terms. |

The SDK asset is `toolchain-llvm-18.2.zip`, SHA-256
`5006bb8629a40093b712fac971456fa4d5ad3fafaadb16d11c10b8a93b8b496f`.
Pin definitions and hashes in the producer scripts are authoritative.

## OpenOrbis-derived material

The linker scripts adapt OpenOrbis's GPL-v3 `link.x`; its license remains.
The original Piglet/VideoOut integration and packaging capabilities were
informed by OpenOrbis samples. Those designated files retain GPL terms rather
than pretending their provenance disappeared with the new MIT default.

Acknowledgements: OpenOrbis contributors; Specter; orbisdev and flat_z for
Piglet reverse engineering; Nikita Krapivin for the Piglet example.
No upstream artwork is reused.

The SDK runtime includes the [OpenOrbis musl fork](https://github.com/OpenOrbis/musl)
and associated runtime/stub components. musl's MIT and other retained notices
must accompany distribution where applicable. The public SDK root's GPL text
is not a substitute for component notices or exact corresponding source.

## Host-only tools and fixtures

- LibOrbisPkg / PkgTool: [maxton/LibOrbisPkg](https://github.com/maxton/LibOrbisPkg),
  LGPL v3; supplied notice in the SDK's `bin/linux/LICENSE.txt`.
- LLVM/clang/lld, Rust/cargo, cbindgen and NASM are host build tools; consult their
  own licenses if redistributing them. They are not shipped in the source archive.
- Host `ffmpeg` and libx264/AAC encoders generate controlled test media. GPL host
  encoder code is **not** added to the application's LGPL decoder build. Fixture
  binaries are generated under ignored `build/`, not bundled in the source release.

## Where notices live

The exact Gecko checkout's `toolkit/content/license.html.mako`,
`toolkit/content/licenses/`, per-file headers and component `LICENSE`/`COPYING`
files describe its dependencies. Gecko's root `LICENSE` is a **pointer**, not
the complete attribution inventory. Preserve the generated about:license
resources as well as the dependency source notices when packaging.

The native package producer stages project/license-scope notices, Mozilla's
pointer, LLVM notices, stb, OFL and LGPL texts. It also stages the exact added
FFmpeg source archive, configuration, build report and builder script.
This alone is **not** a complete GPL/LGPL corresponding-source/relinking audit.
Follow [the redistribution checklist](LICENSES/README.md#before-distributing-binaries).

Only public SDK inputs are used for the build. Firmware services are resolved
on-console; their binaries and proprietary SDK documentation are not included.
