#include "orbisfox/js_canvas.h"
#include <assert.h>
#include <chrono>
#include <stdio.h>
#include <string.h>
#include <vector>
#include <stdlib.h>
#include <unistd.h>
static bool load_source(orbisfox::JsCanvas& js, const char* code) {
    char path[] = "/tmp/orbisfox-js-test-XXXXXX";
    int fd = mkstemp(path); assert(fd >= 0);
    assert(write(fd, code, strlen(code)) == static_cast<ssize_t>(strlen(code)));
    close(fd);
    bool result = js.load_demo(path);
    unlink(path);
    return result;
}
using namespace orbisfox;
static void log_line(const char* value) { puts(value); }
int main() {
    JsCanvas js;
    assert(js.init(log_line));
    assert(js.self_tests() == 12);
    JsCanvas second;
    assert(!second.init());
    int result = 0;
    const char* modern = "Number((2n**32n)/2n) === 2147483648 ? 42 : 0";
    assert(js.evaluate_integer(modern, strlen(modern), result));
    assert(result == 42);
    const char* gc_stress = "(() => {let sum=0; for(let i=0;i<600;++i){const a=new Array(10000).fill(i);sum+=a[99]}return sum})()";
    assert(js.evaluate_integer(gc_stress, strlen(gc_stress), result, 2000));
    assert(result == 179700);
    const char* invalid = "let = )";
    assert(!js.evaluate_integer(invalid, strlen(invalid), result));
    const char* infinite = "while(true) {}";
    auto before = std::chrono::steady_clock::now();
    assert(!js.evaluate_integer(infinite, strlen(infinite), result, 30));
    assert(std::chrono::steady_clock::now() - before < std::chrono::seconds(2));
    assert(strstr(js.error(), "TIMEOUT"));
    assert(js.evaluate_integer("40+2", 4, result));
    assert(result == 42);
    assert(!js.evaluate_integer("42", 2, result, 0));
    assert(!js.evaluate_integer("42", 2, result, 5001));
    assert(!js.evaluate_integer("42", 128*1024+1, result));
    assert(js.load_demo("assets/playground.js"));
    std::vector<uint8_t> pixels(1280 * 720 * 4);
    Surface surface{pixels.data(), 1280, 720, 1280 * 4};
    assert(js.render(surface, 100, 200, false, 0));
    assert(js.commands() > 100 && js.commands() < 512);
    assert(pixels[3] == 255);
    const auto first = pixels;
    assert(js.render(surface, 100, 200, false, 1000));
    assert(first != pixels);
    assert(js.render(surface, 100, 200, true, 1016));
    assert(js.load_demo("assets/playground.js"));
    assert(js.render(surface, 100, 200, false, 1032));
    // Callback validation, exception recovery and quotas use the same bridge as PS4.
    const char* bad_bridge = "orbisfoxFrame = () => paint.rect(0,0,NaN,1,0); 1";
    assert(load_source(js, bad_bridge));
    assert(!js.render(surface, 1, 1, false, 1048));
    const char* bad_text = "orbisfoxFrame = () => paint.text(0,0,'x',999,0); 1";
    assert(load_source(js, bad_text));
    assert(!js.render(surface, 1, 1, false, 1049));
    assert(load_source(js, "orbisfoxFrame = () => {for(let i=0;i<1000;++i) paint.rect(0,0,1,1,0)}; 1"));
    assert(!js.render(surface, 1, 1, false, 1050));
    assert(js.commands() == 512);
    assert(load_source(js, "orbisfoxFrame = () => {while(true){}}; 1"));
    assert(!js.render(surface, 1, 1, false, 1051));
    assert(strstr(js.error(), "TIMEOUT"));
    assert(js.load_demo("assets/playground.js"));
    assert(js.render(surface, 1, 1, false, 1050));
    assert(!js.load_demo("/missing/orbisfox-script.js"));
    js.stop();
    // Context teardown/recreation is permitted; global runtime is initialized once.
    assert(js.init());
    js.stop();
    shutdown_javascript_runtime();
    assert(!js.init());
    puts("SpiderMonkey host embedding: language / rendering / timeout / recovery / teardown OK");
}
