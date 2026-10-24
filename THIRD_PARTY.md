# Third-party code and notices

Original OrbisFox material is MIT **with the exceptions in
[LICENSES/README.md](LICENSES/README.md)**. Dependencies are not relicensed by
that grant. OrbisFox is not affiliated with Mozilla, Sony, ps4-homebrew-dev or OpenOrbis and
ships no Firefox artwork, proprietary SDK, firmware modules or shader binaries.

## Pinned components

| Component | Source / pin | License and role |
| --- | --- | --- |
| Gecko, SpiderMonkey, SWGL, NSPR, NSS and bundled libraries | [Mozilla Firefox](https://github.com/mozilla-firefox/firefox), commit `83cebcf5a522bf49667fd07084f04e8497de0eba` | MPL-2.0 and component-specific licenses. Actual native engine, layout, JS, rasterization, TLS and networking. `gecko/` contains the maintained overlay, not the entire upstream tree. |
| Current browser SDK | [ps4-homebrew-dev/sdk](https://github.com/ps4-homebrew-dev/sdk), v0.2.1 / `ecc8347aa20d7b3423405a5e94d7ab119485160d` | GPL-3.0-or-later startup/runtime supplements and file-specific historical BSD headers; native CRT, system libc/service imports and conversion/package tools. See `docs/HOMEBREW_SDK.md`. Complete corresponding-source/relink materials remain a binary-release gate. |
| OpenOrbis PS4 Toolchain (retained inputs and legacy lane) | [OpenOrbis](https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain), v0.5.3, tag commit `6929bafac0b565692ed61e66032a79185ee9cf65` | Repository GPL v3 and per-file terms. Current native SDK lane retains service declarations, stb and independent package extraction tooling; no OpenOrbis musl CRT/libc linked into that lane. The old build still uses its runtime/stubs/tools. |
| C++ runtimes | [LLVM](https://github.com/llvm/llvm-project), `2078da43e25a4623cab2d0d60decddf709aaea28` / llvmorg-21.1.8 | Apache-2.0 WITH LLVM-exception, including retained older notices; libc++, libc++abi, libunwind. Built privately with Orbis adaptations. |
| Rust standard library | Rust 1.99.0, source archive SHA-256 `3f1f9b7ed48f4596fc87889b7b3c61747336a55c9c22db1ab0c697e0aadb77aa` | MIT / Apache-2.0 and component notices. Private target/sysroot, not a stock FreeBSD runtime. Rust `libc` and other crates keep their own licenses. |
| Added software codecs | [FFmpeg](https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz), 9.0.2; SHA-256 `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` | LGPL-2.1-or-later configuration; GPL/nonfree/version3/network disabled. Real decoder/util/resampler archives, all defined symbols prefixed `orbis_media_`. |
| Existing FFVPX and media dependencies | Pinned Gecko's `media/ffvpx`, `media/libvpx`, `media/libopus`, `media/libvorbis`, etc. | FFmpeg LGPL and each codec's own notices. Kept distinct from the additional FFmpeg archives; consult upstream component files and build configuration. |
| ANGLE platform adapter | Pinned Gecko's ANGLE | BSD-3-Clause; the Orbis helper keeps that license. This does not establish working WebGL. |
| stb_truetype | Public OpenOrbis pin above; native SDK fetches the unchanged single header with SHA-256 `97233cfddd15dc96ea28d73b10599887584c38e3166b4cd3ef62934cb79b20e6` | MIT option selected; `assets/licenses/stb-truetype-MIT.txt`. Used for the native chrome font atlas; `scripts/fetch-native-font-header.py` avoids importing old SDK C/POSIX headers. |
| Noto Sans, Symbols 2, Math | [noto-fonts](https://github.com/notofonts/noto-fonts), `ffebf8c1ee449e544955a7e813c54f9b73848eac` | SIL OFL 1.1. Downloaded and hash-checked by `scripts/fetch-layout-assets.py`. |
| Noto Color Emoji | [noto-emoji](https://github.com/googlefonts/noto-emoji), `e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e` | SIL OFL 1.1, including reserved-font-name terms. |

Current SDK asset: `ps4-homebrew-sdk.zip`, 4,471,594 bytes, SHA-256
`fc021d7e6d53dcd1c73c87af4e0897012c62ffa5276289c0c3d898d71be80310`.
The historical OpenOrbis asset is `toolchain-llvm-18.2.zip`, SHA-256
`5006bb8629a40093b712fac971456fa4d5ad3fafaadb16d11c10b8a93b8b496f`.
Pin definitions and hashes in the producer scripts are authoritative.

Acknowledgements: **ps4-homebrew-dev/sdk contributors** for the current browser
SDK, native startup/runtime supplements and public service bindings. Mozilla,
LLVM, Rust, FFmpeg, OpenOrbis, font and other contributors retain the credits and
licenses below; the SDK migration is not a relicensing of their work.

## Default-off experimental Mesa dependencies

The following retained dependencies are used only for explicit legacy `--mesa`
builds; the current native-SDK software browser does not link them. Native-SDK
Mesa dependency migration is incomplete and mixed-SDK builds are rejected.

| Component | Source / pin | License and role |
| --- | --- | --- |
| Mesa PS4 | [orbis-ports/mesa-ps4](https://github.com/orbis-ports/mesa-ps4), `1a59cc147b54e3970814b37313e2f27357672e9d` | MIT and per-file/component notices, retained in the exact source archive. EGL/GLES, Zink, RADV and GPU shader compilation. |
| Porting headers | [orbis-ports/orbis-compat](https://github.com/orbis-ports/orbis-compat), `6922a7b6f4291a28edd239f1a4db50ed7aa00359` | MIT with the BSD-3-Clause `include/sys/ioccom.h` exception. Headers only; the broad runtime archive is not linked. |
| Porting kit | [orbis-ports/orbis-porting-kit](https://github.com/orbis-ports/orbis-porting-kit), `213b0c38ff25ea7ca402c8844a6494086d0f1cae` | MIT except the GPL-3.0-only `cmake/orbis-tls.ld`. Exact public source and notices retained; browser retains its own designated GPL linker script. |
| zlib | Mesa's pinned zlib 1.3.1 source and Meson wrap patch | zlib license and patch notices retained in their source archives. Real static compression library. |

The experimental installer stages these public source archives, the exact Mesa
patched files, dependency notices, native bridge source and build configuration
under `assets/misc/mesa/`, with a SHA-256 manifest. It includes no proprietary SDK
or firmware binaries. These materials do **not** by themselves complete the
browser's corresponding-source/relink or public redistribution checklist.

## OpenOrbis-derived material

The current native-SDK lane's separate service-declaration bundle retains 21 public
headers from the OpenOrbis pin above, with exact Git blob checks, original notices
and the upstream GPL-v3 LICENSE. It supplies only PS4 service declarations, not old
libc/POSIX headers, CRT or libraries; root MIT does not relicense these headers.
`scripts/fetch-homebrew-service-headers.py` is an original MIT producer, not a
license change to its downloaded inputs.

The linker scripts adapt OpenOrbis's GPL-v3 `link.x`; its license remains.
The original Piglet/VideoOut integration and packaging capabilities were
informed by OpenOrbis samples. Those designated files retain GPL terms rather
than pretending their provenance disappeared with the new MIT default.

Acknowledgements: OpenOrbis contributors; Specter; orbisdev and flat_z for
Piglet reverse engineering; Nikita Krapivin for the Piglet example.
No upstream artwork is reused.

The **legacy OpenOrbis** runtime includes the [OpenOrbis musl fork](https://github.com/OpenOrbis/musl)
and associated runtime/stub components. musl's MIT and other retained notices
must accompany distribution where applicable. `assets/licenses/musl-COPYRIGHT.txt`
preserves the fork's notice inventory from commit
`2b0bb8ce2fa64ac255cb656785729d159a5f074c`; this notice reference is not a claim
that the SDK's compiled libc was rebuilt from that later commit. The public SDK
root's GPL text is not a substitute for component notices or corresponding source.

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
An installer release must additionally attach its matching project source and
verified application relink kit, with exact dependency pins and build materials.
See [relinking instructions](docs/RELINKING.md) and the
[redistribution checklist](LICENSES/README.md#before-distributing-binaries).
Engineering verification is not patent/trademark clearance or a blanket legal
certification of third-party material.

Only public SDK inputs are used for the build. Firmware services are resolved
on-console; their binaries and proprietary SDK documentation are not included.
