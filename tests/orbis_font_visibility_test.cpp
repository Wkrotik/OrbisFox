#include <cassert>
#include <cstdint>
#include <cstdio>
#include <iterator>
#include <string>
#include <strings.h>
#include <utility>
#include <vector>
using nsACString = std::string;
enum class FontVisibility { Unknown, Base, LangPack, User };
template<class T> struct nsTArray : std::vector<T> {
    template<class U> void AppendElement(U value) { this->push_back(value); }
};
// Host boundary doubles only: the production method bodies are included
// verbatim. The engine's real Unicode family comparator is target-compiled;
// this ASCII comparator exercises the shipped ASCII family policy here.
struct gfxFT2FontList {
    FontVisibility GetVisibilityForFamily(const nsACString&) const;
    nsTArray<std::pair<const char**, uint32_t>> GetFilteredPlatformFontLists();
    static bool FamilyInList(const nsACString& name, const char** list, size_t count) {
        for(size_t i=0;i<count;++i) if(!strcasecmp(name.c_str(),list[i])) return true;
        return false;
    }
};
#include "orbis-font-functions.inc"
int main() {
    gfxFT2FontList fonts;
    for(int cycle=0;cycle<32;++cycle) {
        for(auto name:{"Noto Sans","noto sans","NOTO SANS"})
            assert(fonts.GetVisibilityForFamily(name)==FontVisibility::Base);
        for(auto name:{"", "Roboto", "Droid Sans", "Noto Serif", "Noto Sans Extra", "Arial"})
            assert(fonts.GetVisibilityForFamily(name)==FontVisibility::User);
        auto lists=fonts.GetFilteredPlatformFontLists();
        assert(lists.size()==1 && lists[0].second==1);
        assert(std::string(lists[0].first[0])=="Noto Sans");
        lists.clear(); // caller owns the returned array, not the baseline list
        assert(fonts.GetFilteredPlatformFontLists().size()==1);
    }
    puts("Actual Orbis FT2 font policy: shipped base font / case / unknown families / filter list / lifetime, 32 cycles PASS");
}
