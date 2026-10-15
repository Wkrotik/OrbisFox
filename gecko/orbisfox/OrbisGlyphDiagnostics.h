#ifndef ORBISFOX_GLYPH_DIAGNOSTICS_H
#define ORBISFOX_GLYPH_DIAGNOSTICS_H
#include <stdint.h>
namespace orbisfox {
struct MissingGlyphStats {uint64_t draws=0;uint32_t codepoints[64]{};};
void record_missing_glyph(uint32_t codepoint);
MissingGlyphStats missing_glyph_stats();
}
#endif
