#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
using nsresult = int32_t;
using nsACString = std::string;
using nsCString = std::string;
constexpr nsresult NS_ERROR_INVALID_ARG = -1, NS_ERROR_NOT_AVAILABLE = -2;
#define NS_SUCCEEDED(rv) ((rv) >= 0)
// Host-only XPCOM boundary doubles; production functions below are extracted
// verbatim from the actual Orbis header and patched gfxPlatform.cpp.
struct nsIGfxInfo {
    static constexpr int FEATURE_STATUS_UNKNOWN = 0, FEATURE_STATUS_OK = 1;
    int status = 0, calls = 0, feature = 0;
    nsresult result = 0;
    nsresult GetFeatureStatus(int f, nsACString&, int* output) {
        ++calls; feature = f; *output = status; return result;
    }
};
static nsIGfxInfo* service;
template<class T> struct nsCOMPtr {
    T* ptr;
    nsCOMPtr(T* p) : ptr(p) {}
    operator T*() const { return ptr; }
};
#define ORBISFOX_GFXINFO_SERVICE() service
#define ORBISFOX_GFX_FEATURE_STATUS(info, ...) GetOptionalGfxFeatureStatus(info, __VA_ARGS__)
#include "optional-gfx-functions.inc"
int main() {
    for (int cycle = 0; cycle < 32; ++cycle) {
        int status = 999; nsCString failure;
        service = nullptr;
        assert(GetOptionalGfxFeatureStatus(nullptr, 21, failure, &status) == NS_ERROR_NOT_AVAILABLE);
        assert(status == nsIGfxInfo::FEATURE_STATUS_UNKNOWN);
        assert(GetOptionalGfxFeatureStatus(nullptr, 21, failure, nullptr) == NS_ERROR_INVALID_ARG);
        assert(!IsFeatureSupported(21, false));
        assert(IsFeatureSupported(21, true));
        nsIGfxInfo info; service = &info;
        assert(GetOptionalGfxFeatureStatus(&info, 21, failure, nullptr) == NS_ERROR_INVALID_ARG);
        assert(info.calls == 0);
        info.status = nsIGfxInfo::FEATURE_STATUS_OK;
        assert(IsFeatureSupported(21, false)); assert(info.feature == 21 && info.calls == 1);
        info.status = 2; assert(!IsFeatureSupported(21, true));
        info.result = -5;
        assert(!IsFeatureSupported(21, false)); assert(IsFeatureSupported(21, true));
        assert(GetOptionalGfxFeatureStatus(&info, 22, failure, &status) == -5);
        service = nullptr;
    }
    puts("Actual optional-GfxInfo helper/caller: absent / failure / OK / blocked / default matrix, 32 cycles PASS");
}
