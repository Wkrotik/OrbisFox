#include "orbisfox/module_binding.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
using namespace orbisfox;
static int invocations = 0;
static int example_api(int value) { ++invocations; return value + 1; }
struct FakeModule {
    bool loaded = true, resolved = true, null_address = false;
    int32_t handle = 21;
    int loads = 0, lookups = 0;
    static bool load(void* user, const char* name, uint32_t id, int32_t* handle) {
        auto& f = *static_cast<FakeModule*>(user);
        ++f.loads;
        assert(strcmp(name, "libExample") == 0 && id == 0x80000011);
        *handle = f.handle;
        return f.loaded;
    }
    static bool resolve(void* user, int32_t handle, const char* name, void** address) {
        auto& f = *static_cast<FakeModule*>(user);
        ++f.lookups;
        assert(handle == f.handle && strcmp(name, "example_api") == 0);
        *address = f.null_address ? nullptr : reinterpret_cast<void*>(&example_api);
        return f.resolved;
    }
    ModuleBackend backend() { return {this, load, resolve}; }
};
int main() {
    FakeModule f;
    ModuleBinding module;
    int (*api)(int) = nullptr;
    assert(!module.bind("example_api", api) && api == nullptr && f.lookups == 0);
    assert(module.open(f.backend(), "libExample", 0x80000011));
    assert(module.bind("example_api", api));
    assert(api(41) == 42 && invocations == 1);
    f.resolved = false;
    assert(!module.bind("example_api", api) && api == nullptr);
    assert(invocations == 1); // failed resolution never invokes the API
    f.resolved = true; f.null_address = true;
    assert(!module.bind("example_api", api) && api == nullptr);
    f.null_address = false; f.loaded = false;
    int before = f.lookups;
    assert(!module.open(f.backend(), "libExample", 0x80000011));
    assert(!module.bind("example_api", api) && api == nullptr && f.lookups == before);
    f.loaded = true; f.handle = -1;
    assert(!module.open(f.backend(), "libExample", 0x80000011));
    assert(!module.bind("example_api", api) && f.lookups == before);
    int loads = f.loads;
    assert(!module.open({nullptr, nullptr, nullptr}, "libExample", 0x80000011));
    assert(!module.open(f.backend(), "", 0x80000011));
    assert(!module.open(f.backend(), nullptr, 0x80000011));
    assert(f.loads == loads);
    f.handle = 21;
    assert(module.open(f.backend(), "libExample", 0x80000011));
    assert(!module.bind(nullptr, api) && api == nullptr);
    assert(!module.bind("", api) && api == nullptr);
    assert(invocations == 1);
    puts("module binding: failed loads, invalid handles, unresolved/null symbols and success gating passed");
}
