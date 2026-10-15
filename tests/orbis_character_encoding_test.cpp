#include "js/CharacterEncoding.h"
#include "js/Context.h"
#include "js/GlobalObject.h"
#include "js/Initialization.h"
#include "js/Realm.h"
#include "js/RootingAPI.h"
#include "jsapi.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
extern "C" size_t orbis_sdk_wcslen(const uint16_t*);
// Isolate only the actual patched functions from the host's unified object.
JS::UniqueChars actualOrbisNativeToUtf8(JSContext*, const char*) __asm__("orbis_test_native_to_utf8");
JS::UniqueChars actualOrbisUtf8ToNative(JSContext*, const char*) __asm__("orbis_test_utf8_to_native");
static const JSClass globalClass = {"Orbis UTF-8 regression", JSCLASS_GLOBAL_FLAGS, &JS::DefaultGlobalClassOps};
int main() {
    static_assert(sizeof(wchar_t) == 4);
    const wchar_t cppWide[] = L"/app0/assets/gecko-startup.js";
    const uint16_t sdkWide[] = {'/','a','p','p','0',0};
    // Actual SDK object reads 16-bit units, even though C++ wchar_t is 32-bit.
    assert(orbis_sdk_wcslen(sdkWide) == 5);
    assert(orbis_sdk_wcslen(reinterpret_cast<const uint16_t*>(cppWide)) == 1);
    assert(JS_Init());
    JSContext* cx = JS_NewContext(32 * 1024 * 1024);
    assert(cx && JS::InitSelfHostedCode(cx));
    {
        JS::RealmOptions options;
        JS::RootedObject global(cx, JS_NewGlobalObject(cx, &globalClass, nullptr, JS::FireOnNewGlobalHook, options));
        assert(global);
        JSAutoRealm realm(cx, global);
        assert(JS::InitRealmStandardClasses(cx));
        const char* good[] = {"", "/app0/assets/gecko-startup.js", "native path with spaces.html",
                             "/data/orbisfox/\xc3\xa9-\xe6\xb5\x8f\xe8\xa7\x88-\xf0\x9f\xa6\x8a.html"};
        const char* bad[] = {"\x80", "\xc0\xaf", "\xe2\x82", "\xed\xa0\x80", "\xf4\x90\x80\x80", "\xff"};
        for (int cycle = 0; cycle < 32; ++cycle) {
            for (const char* path : good) {
                auto utf8 = actualOrbisNativeToUtf8(cx, path);
                assert(utf8 && strcmp(utf8.get(), path) == 0);
                auto native = actualOrbisUtf8ToNative(cx, utf8.get());
                assert(native && strcmp(native.get(), path) == 0);
            }
            for (const char* path : bad) {
                auto utf8 = actualOrbisNativeToUtf8(cx, path);
                assert(!utf8 && JS_IsExceptionPending(cx)); JS_ClearPendingException(cx);
                auto native = actualOrbisUtf8ToNative(cx, path);
                assert(!native && JS_IsExceptionPending(cx)); JS_ClearPendingException(cx);
            }
            JS_GC(cx);
        }
    }
    JS_DestroyContext(cx); JS_ShutDown();
    puts("Actual Orbis-gated SpiderMonkey UTF-8 conversion: 32 cycles PASS; SDK 16-bit wchar mismatch reproduced");
}
