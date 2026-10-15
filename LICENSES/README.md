# License scope and redistribution

## Original code: MIT, with explicit exceptions

The maintainer selected **MIT** for original OrbisFox material in this source
release. `../LICENSE` grants that permission only for material the project owns.
It does not revoke licenses already granted for older releases or relicense
other authors' work.

MIT permits commercial use, modification and redistribution provided the
copyright and permission notice are retained in copies or substantial portions
of the software. It is not public-domain dedication, and does not promise
patent clearance or rights to Mozilla/Sony trademarks. This choice is available
only for material the maintainer has the right to relicense.

The following exceptions take precedence over the root license:

| Material | License / treatment |
| --- | --- |
| `gecko/**`, except the ANGLE file below | MPL-2.0; preserve existing headers and upstream notices, including for files without individual headers. |
| `gecko/third_party/angle/src/common/system_utils_orbis.cpp` | ANGLE BSD-3-Clause; `ANGLE-BSD-3-Clause.txt`. |
| `scripts/patch-gecko.py`, `scripts/patch-gecko-layout.py` | MPL-2.0; these contain modifications/excerpts of Mozilla source. |
| `scripts/build-libcxx.py` | Apache-2.0 WITH LLVM-exception; includes LLVM source modifications. |
| `scripts/ps4.ld`, `scripts/ps4-gecko.ld` | GPL-3.0-only; adapted from OpenOrbis's GPL-v3 linker script. |
| `src/ps4/piglet.cpp`, `src/ps4/videoout.cpp`, `scripts/package.py` | Retained under GPL-3.0-or-later conservatively because of the documented OpenOrbis sample adaptations. Do not claim these were relicensed to MIT. |
| `assets/licenses/**`, `LICENSES/**` | Each upstream license/notice retains its own terms. |
| Downloaded/generated dependencies in `.deps/`, `build/`, `dist/` | Their respective licenses, not the root MIT grant. See `../THIRD_PARTY.md`. |
| Embedded upstream code in patches or generated headers | The relevant upstream license still applies; a script's license does not override the license of code it transforms or emits. |

All other original OrbisFox source, tests, documentation and original artwork
are MIT unless a file states otherwise. New contributions follow the license
of the file/component being changed. Do not remove upstream notices.

## The complete browser is not MIT-only

Gecko's MPL does **not** generally require unrelated original application files
to be GPL. Likewise, running a GPL build tool does not automatically make its
output GPL. However, this project actually contains GPL-derived material; a
blanket MIT label would be inaccurate. The LGPL codec and other linked
components have additional obligations of their own.

Until the provenance of sample-derived material and the complete static link
is reviewed, use a conservative GPL-3.0-or-later-compatible distribution policy
for combined executables, retaining the separate MPL/LGPL/permissive notices.
This policy is not a claim that every component has been relicensed to GPL or
that a complete binary redistribution audit has passed. A fully permissive
combined release would require resolving/removing the remaining copyleft
components through lawful replacements or permission from their authors.

## Before distributing binaries

- Publish the exact matching OrbisFox source snapshot, patches, dependency pins,
  build/install instructions and license texts, not just a package or a link
  to a moving upstream branch.
- For GPL-covered work, provide the applicable complete corresponding source,
  including the relevant SDK/runtime modifications and build inputs. A toolchain
  binary download alone is not a substitute for its corresponding source.
- For statically linked LGPL FFmpeg, satisfy LGPL 2.1 section 6: provide the
  corresponding library source/modifications and a usable relinking route
  (appropriate application object files or sufficient corresponding source
  and build materials). Preserve the user's ability to modify/relink the
  library; do not impose incompatible reverse-engineering restrictions.
- Retain MPL source availability and the notices for all enabled Gecko
  dependencies, not just a copy of Mozilla's root `LICENSE` pointer file.
- Preserve LLVM, musl, stb, font and other component notices. Font reserved-name
  rules and trademark rights remain separate from source-code licensing.
- Review codec patent obligations for the intended distribution jurisdiction;
  an open-source copyright license is not patent clearance.

This preparation supplies a scoped license map and source-release tooling.
**Binary redistribution sign-off remains a release checklist item**, not an
assertion that all obligations have been fulfilled by changing `LICENSE`.
