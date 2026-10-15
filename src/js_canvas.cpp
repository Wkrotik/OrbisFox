#define _POSIX_C_SOURCE 200809L
#include "orbisfox/js_canvas.h"
#include <jsapi.h>
#include <js/Initialization.h>
#include <js/Context.h>
#include <js/Stack.h>
#include <js/GlobalObject.h>
#include <js/Realm.h>
#include <js/RealmOptions.h>
#include <js/CompilationAndEvaluation.h>
#include <js/SourceText.h>
#include <js/CallAndConstruct.h>
#include <js/Interrupt.h>
#include <js/Conversions.h>
#include <js/CharacterEncoding.h>
#include <js/PropertyAndElement.h>
#include <js/GCAPI.h>
#include <mozilla/Utf8.h>
#include <atomic>
#include <math.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <new>

namespace orbisfox {
namespace {
constexpr size_t source_limit = 128 * 1024;
constexpr uint32_t command_limit = 512;
static bool runtime_initialized = false;
static bool runtime_shut_down = false;
static unsigned live_contexts = 0;
static const JSClass global_class = {"OrbisFox", JSCLASS_GLOBAL_FLAGS, &JS::DefaultGlobalClassOps,
                                    nullptr, nullptr, nullptr};
uint64_t now_ns() {
    timespec t{};
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) return 0;
    return static_cast<uint64_t>(t.tv_sec) * 1000000000ULL + static_cast<uint64_t>(t.tv_nsec);
}
// No browser/DOM shims: each assertion exercises the real interpreter/runtime.
constexpr const char* self_test = R"JS(
(() => {
  let n = 0;
  function check(v) { if (!v) throw Error('self-test ' + n); ++n; }
  check(Array.from({length:64}, (_, i) => i*i).reduce((a,b) => a+b, 0) === 85344);
  check(2n ** 64n === 18446744073709551616n);
  check(new Map([['fox',42]]).get('fox') === 42);
  check(new Set([1,1,2]).size === 2);
  check(new Uint32Array([0xffffffff])[0] === 4294967295);
  check(Array.from('OrbisFox: 🦊').length === 11);
  check(JSON.parse(JSON.stringify({ok:[1,2,3]})).ok[2] === 3);
  check(/(fox)+/u.test('foxfox'));
  check((({a:{b=5}={}}={}) => b)() === 5);
  check(({deep:{v:7}})?.deep?.v === 7 && (null ?? 9) === 9);
  const s = Symbol('fox'); check(({[s]:8})[s] === 8);
  function* g() { yield 1; yield 2; } check([...g()].join('') === '12');
  return n;
})()
)JS";
}

struct JsCanvas::State {
    JSContext* cx = nullptr;
    JS::PersistentRootedObject* global = nullptr;
    JS::PersistentRootedValue* frame = nullptr;
    Logger logger = nullptr;
    Surface* target = nullptr;
    uint32_t command_count = 0;
    unsigned passed = 0;
    pthread_t watchdog{};
    bool watchdog_started = false;
    std::atomic<bool> stopping{false};
    std::atomic<bool> timed_out{false};
    std::atomic<uint64_t> deadline{0};

    void mark(const char* message) { if (logger) logger(message); }
    void begin(unsigned timeout_ms) {
        timed_out.store(false);
        deadline.store(now_ns() + static_cast<uint64_t>(timeout_ms) * 1000000ULL);
    }
    void end() { deadline.store(0); }
    static void* watch(void* arg) {
        auto& s = *static_cast<State*>(arg);
        while (!s.stopping.load()) {
            uint64_t limit = s.deadline.load();
            if (limit && now_ns() >= limit) {
                s.timed_out.store(true);
                JS_RequestInterruptCallback(s.cx); // Explicitly thread-safe JSAPI.
            }
            usleep(2000);
        }
        return nullptr;
    }
    static bool interrupt(JSContext* cx) {
        auto& s = *static_cast<State*>(JS_GetContextPrivate(cx));
        const uint64_t limit = s.deadline.load();
        // A stale watchdog request from the previous evaluation must not cancel
        // a new one. Judge the current deadline, not the diagnostic timeout flag.
        return !limit || now_ns() < limit;
    }
    static bool numbers(JSContext* cx, const JS::CallArgs& args, unsigned count) {
        if (args.length() < count) { JS_ReportErrorASCII(cx, "paint: missing argument"); return false; }
        for (unsigned i = 0; i < count; ++i) {
            if (!args[i].isNumber() || !isfinite(args[i].toNumber())) {
                JS_ReportErrorASCII(cx, "paint: finite numbers required"); return false;
            }
        }
        return true;
    }
    static bool ready(JSContext* cx) {
        auto& s = *static_cast<State*>(JS_GetContextPrivate(cx));
        if (!s.target || s.command_count >= command_limit) {
            JS_ReportErrorASCII(cx, "paint: inactive surface or command limit exceeded"); return false;
        }
        ++s.command_count;
        return true;
    }
    static Color color(double value) {
        auto rgb = static_cast<uint32_t>(value);
        return {static_cast<uint8_t>(rgb >> 16), static_cast<uint8_t>(rgb >> 8), static_cast<uint8_t>(rgb), 255};
    }
    static bool clear(JSContext* cx, unsigned argc, JS::Value* vp) {
        auto args = JS::CallArgsFromVp(argc, vp);
        if (!numbers(cx, args, 1) || args[0].toNumber() < 0 || args[0].toNumber() > 0xffffff) {
            JS_ReportErrorASCII(cx, "paint.clear: color out of range"); return false;
        }
        if (!ready(cx)) return false;
        auto& s = *static_cast<State*>(JS_GetContextPrivate(cx));
        fill_rect(*s.target, 0, 0, s.target->width, s.target->height, color(args[0].toNumber()));
        args.rval().setUndefined(); return true;
    }
    static bool rect(JSContext* cx, unsigned argc, JS::Value* vp) {
        auto args = JS::CallArgsFromVp(argc, vp);
        if (!numbers(cx, args, 5)) return false;
        for (unsigned i = 0; i < 4; ++i) {
            if (args[i].toNumber() < -4096 || args[i].toNumber() > 4096) {
                JS_ReportErrorASCII(cx, "paint.rect: bounds out of range"); return false;
            }
        }
        if (args[2].toNumber() < 0 || args[3].toNumber() < 0 || args[4].toNumber() < 0 || args[4].toNumber() > 0xffffff) {
            JS_ReportErrorASCII(cx, "paint.rect: invalid dimensions/color"); return false;
        }
        if (!ready(cx)) return false;
        auto& s = *static_cast<State*>(JS_GetContextPrivate(cx));
        fill_rect(*s.target, static_cast<int>(args[0].toNumber()), static_cast<int>(args[1].toNumber()),
                  static_cast<int>(args[2].toNumber()), static_cast<int>(args[3].toNumber()), color(args[4].toNumber()));
        args.rval().setUndefined(); return true;
    }
    static bool label(JSContext* cx, unsigned argc, JS::Value* vp) {
        auto args = JS::CallArgsFromVp(argc, vp);
        if (argc < 5 || !args[0].isNumber() || !args[1].isNumber() || !args[2].isString() ||
            !args[3].isInt32() || !args[4].isNumber()) {
            JS_ReportErrorASCII(cx, "paint.text: invalid arguments"); return false;
        }
        double x = args[0].toNumber(), y = args[1].toNumber(), rgb = args[4].toNumber();
        int scale = args[3].toInt32();
        if (!isfinite(x) || !isfinite(y) || !isfinite(rgb) || x < -4096 || x > 4096 || y < -4096 || y > 4096 ||
            rgb < 0 || rgb > 0xffffff || scale < 1 || scale > 5 || JS_GetStringLength(args[2].toString()) > 120) {
            JS_ReportErrorASCII(cx, "paint.text: bounds out of range"); return false;
        }
        JS::RootedString str(cx, args[2].toString());
        JS::UniqueChars encoded = JS_EncodeStringToUTF8(cx, str);
        if (!encoded || !ready(cx)) return false;
        auto& s = *static_cast<State*>(JS_GetContextPrivate(cx));
        text(*s.target, static_cast<int>(x), static_cast<int>(y), encoded.get(), scale, color(rgb));
        args.rval().setUndefined(); return true;
    }
};

JsCanvas::~JsCanvas() { stop(); }
const char* JsCanvas::error() const { return error_; }
uint32_t JsCanvas::commands() const { return state_ ? state_->command_count : 0; }
unsigned JsCanvas::self_tests() const { return state_ ? state_->passed : 0; }

bool JsCanvas::init(Logger logger) {
    if (state_) return true;
    if (live_contexts != 0) { snprintf(error_, sizeof(error_), "JAVASCRIPT CONTEXT ALREADY ACTIVE"); return false; }
    if (runtime_shut_down) { snprintf(error_, sizeof(error_), "JAVASCRIPT RUNTIME SHUT DOWN"); return false; }
    state_ = new (std::nothrow) State;
    if (!state_) return false;
    struct InitGuard {
        JsCanvas* owner;
        bool success = false;
        ~InitGuard() { if (!success) owner->stop(); }
    } guard{this};
    State& s = *state_; s.logger = logger;
    if (!runtime_initialized) {
        s.mark("SpiderMonkey: JS_Init begin (JIT disabled)");
        JS::DisableJitBackend();
        if (!JS_Init()) { snprintf(error_, sizeof(error_), "JS_INIT FAILED"); stop(); return false; }
        runtime_initialized = true;
        s.mark("SpiderMonkey: JS_Init OK");
    }
    s.mark("SpiderMonkey: JS_NewContext begin - 32 MiB GC heap limit");
    s.cx = JS_NewContext(32 * 1024 * 1024);
    if (!s.cx) { snprintf(error_, sizeof(error_), "JS_NEWCONTEXT FAILED"); stop(); return false; }
    ++live_contexts;
    JS_SetContextPrivate(s.cx, &s);
    JS_SetNativeStackQuota(s.cx, 512 * 1024);
    JS_SetGCParameter(s.cx, JSGC_MAX_BYTES, 32 * 1024 * 1024);
    s.mark("SpiderMonkey: InitSelfHostedCode begin");
    if (!JS::InitSelfHostedCode(s.cx)) { snprintf(error_, sizeof(error_), "SELF-HOSTED CODE FAILED"); stop(); return false; }
    s.mark("SpiderMonkey: InitSelfHostedCode OK");
    {
        JS::RealmOptions options;
        options.creationOptions().setSharedMemoryAndAtomicsEnabled(false);
        JS::RootedObject global(s.cx, JS_NewGlobalObject(s.cx, &global_class, nullptr, JS::FireOnNewGlobalHook, options));
        if (!global) { snprintf(error_, sizeof(error_), "GLOBAL ALLOCATION FAILED"); return false; }
        s.global = new (std::nothrow) JS::PersistentRootedObject(s.cx, global);
        if (!s.global) { snprintf(error_, sizeof(error_), "GLOBAL ROOT ALLOCATION FAILED"); return false; }
        JSAutoRealm realm(s.cx, global);
        if (!JS::InitRealmStandardClasses(s.cx)) { snprintf(error_, sizeof(error_), "STANDARD CLASSES FAILED"); return false; }
        JS::RootedObject paint(s.cx, JS_NewPlainObject(s.cx));
        if (!paint || !JS_DefineFunction(s.cx, paint, "clear", State::clear, 1, 0) ||
            !JS_DefineFunction(s.cx, paint, "rect", State::rect, 5, 0) ||
            !JS_DefineFunction(s.cx, paint, "text", State::label, 5, 0) ||
            !JS_DefineProperty(s.cx, global, "paint", paint, JSPROP_READONLY | JSPROP_PERMANENT)) {
            snprintf(error_, sizeof(error_), "DRAWING BRIDGE FAILED"); return false;
        }
    }
    if (!now_ns() || !JS_AddInterruptCallback(s.cx, State::interrupt) || pthread_create(&s.watchdog, nullptr, State::watch, &s)) {
        snprintf(error_, sizeof(error_), "WATCHDOG INITIALIZATION FAILED"); stop(); return false;
    }
    s.watchdog_started = true;
    s.mark("SpiderMonkey: 12 native JavaScript language self-tests begin");
    int passed = 0;
    if (!evaluate_integer(self_test, strlen(self_test), passed, 2000) || passed != 12) {
        s.mark("SpiderMonkey: language self-tests FAILED"); stop(); return false;
    }
    s.passed = static_cast<unsigned>(passed);
    s.mark("SpiderMonkey: 12/12 JavaScript language self-tests OK");
    snprintf(error_, sizeof(error_), "OK");
    guard.success = true;
    return true;
}

bool JsCanvas::evaluate_integer(const char* code, size_t length, int& result, unsigned timeout_ms) {
    if (!state_ || !state_->cx || !state_->global || !code || !length || length > source_limit || timeout_ms < 1 || timeout_ms > 5000) return false;
    State& s = *state_;
    JSAutoRealm realm(s.cx, *s.global);
    s.begin(timeout_ms);
    JS::CompileOptions options(s.cx); options.setFileAndLine("orbisfox-local.js", 1);
    JS::SourceText<mozilla::Utf8Unit> source;
    JS::RootedValue value(s.cx);
    bool ok = source.init(s.cx, code, length, JS::SourceOwnership::Borrowed) && JS::Evaluate(s.cx, options, source, &value);
    s.end();
    if (!ok || !value.isInt32()) {
        snprintf(error_, sizeof(error_), "%s", s.timed_out.load() ? "JAVASCRIPT EXECUTION TIMEOUT" : "JAVASCRIPT ERROR OR NON-INTEGER RESULT");
        JS_ClearPendingException(s.cx); return false;
    }
    result = value.toInt32(); return true;
}

bool JsCanvas::load_demo(const char* path) {
    if (!state_ || !state_->cx || !state_->global || !path) return false;
    FILE* file = fopen(path, "rb");
    if (!file) { snprintf(error_, sizeof(error_), "BUNDLED SCRIPT MISSING"); return false; }
    char* code = new (std::nothrow) char[source_limit + 1];
    if (!code) { fclose(file); return false; }
    size_t length = fread(code, 1, source_limit + 1, file);
    bool bad = ferror(file) || length > source_limit; fclose(file);
    int result = 0;
    bool ok = !bad && evaluate_integer(code, length, result, 2000) && result == 1;
    delete[] code;
    if (!ok) return false;
    State& s = *state_;
    JSAutoRealm realm(s.cx, *s.global);
    JS::RootedValue function(s.cx);
    if (!JS_GetProperty(s.cx, *s.global, "orbisfoxFrame", &function) || !function.isObject() || !JS::IsCallable(&function.toObject())) return false;
    delete s.frame;
    s.frame = new (std::nothrow) JS::PersistentRootedValue(s.cx, function);
    s.mark("SpiderMonkey: bundled interactive script compiled OK");
    return s.frame != nullptr;
}

bool JsCanvas::render(Surface& surface, int x, int y, bool click, double elapsed) {
    if (!state_ || !state_->frame || !valid(surface) || !isfinite(elapsed)) return false;
    State& s = *state_;
    JSAutoRealm realm(s.cx, *s.global);
    JS::RootedValueArray<4> args(s.cx);
    args[0].setInt32(x); args[1].setInt32(y); args[2].setBoolean(click); args[3].setDouble(elapsed);
    JS::RootedValue result(s.cx);
    s.target = &surface; s.command_count = 0; s.begin(100);
    bool ok = JS::Call(s.cx, *s.global, *s.frame, args, &result);
    s.end(); s.target = nullptr;
    if (!ok) {
        snprintf(error_, sizeof(error_), "%s", s.timed_out.load() ? "JAVASCRIPT FRAME TIMEOUT" : "JAVASCRIPT FRAME ERROR");
        JS_ClearPendingException(s.cx);
    }
    return ok;
}

void JsCanvas::stop() {
    if (!state_) return;
    State& s = *state_;
    s.stopping.store(true);
    if (s.watchdog_started) pthread_join(s.watchdog, nullptr);
    delete s.frame; delete s.global;
    if (s.cx) { JS_DestroyContext(s.cx); --live_contexts; }
    delete state_; state_ = nullptr;
}
void shutdown_javascript_runtime() {
    if (runtime_initialized && !runtime_shut_down && live_contexts == 0) {
        JS_ShutDown(); runtime_shut_down = true;
    }
}
}
