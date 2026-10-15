#include "orbisfox/shader_table.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

using namespace orbisfox;
struct Fixture {
    uint8_t bytes[4096]{};
    uintptr_t address(size_t offset = 0) { return reinterpret_cast<uintptr_t>(bytes) + offset; }
    static bool read(void* user, uintptr_t source, void* destination, size_t length) {
        auto* f = static_cast<Fixture*>(user);
        const uintptr_t low = f->address();
        if (!destination || !length || source < low || source - low > sizeof(f->bytes)
            || length > sizeof(f->bytes) - (source - low)) return false;
        memcpy(destination, f->bytes + (source - low), length);
        return true;
    }
    MemoryReader reader() { return {this, read}; }
    void entry(size_t index, size_t name, uint64_t length, uintptr_t code) {
        FirmwareShaderEntry value{};
        value.name = reinterpret_cast<const char*>(address(name));
        value.length = length;
        value.code = reinterpret_cast<const uint8_t*>(code);
        memcpy(bytes + index * sizeof(value), &value, sizeof(value));
    }
};
int main() {
    Fixture f;
    strcpy(reinterpret_cast<char*>(f.bytes + 1024), "unrelated.vert");
    strcpy(reinterpret_cast<char*>(f.bytes + 1152), "texmap/v_2.vert");
    f.entry(0, 1024, 4, f.address(2048));
    f.entry(1, 1152, 16, f.address(2048));
    auto find = [&] { return find_firmware_shader(f.reader(), f.address(), "texmap/v_2.vert"); };
    ShaderLookup result = find();
    assert(result.status == ShaderLookupStatus::found && result.inspected == 2 && result.entry.length == 16);
    uint8_t snapshot[16];
    assert(f.reader().read(f.reader().user, reinterpret_cast<uintptr_t>(result.entry.code), snapshot, sizeof(snapshot)));
    assert(find_firmware_shader(f.reader(), f.address(), "missing").status == ShaderLookupStatus::not_found);
    assert(find_firmware_shader(f.reader(), f.address(), "missing", 1).status == ShaderLookupStatus::limit_reached);
    assert(find_firmware_shader(f.reader(), 1, "name").status == ShaderLookupStatus::unreadable_table);
    assert(find_firmware_shader(f.reader(), UINTPTR_MAX - 10, "name").status == ShaderLookupStatus::unreadable_table);
    assert(find_firmware_shader({nullptr, nullptr}, f.address(), "name").status == ShaderLookupStatus::unreadable_table);
    f.entry(1, 1152, 0, f.address(2048));
    assert(find().status == ShaderLookupStatus::invalid_blob);
    f.entry(1, 1152, max_shader_bytes + 1, f.address(2048));
    assert(find().status == ShaderLookupStatus::invalid_blob);
    f.entry(1, 1152, 16, UINTPTR_MAX - 5);
    assert(find().status == ShaderLookupStatus::invalid_blob);
    f.entry(1, 1152, 16, 0);
    assert(find().status == ShaderLookupStatus::invalid_blob);
    f.entry(1, 1152, 16, 1);
    // Lookup checks structure; caller must also validate/snapshot the blob.
    result = find();
    assert(result.status == ShaderLookupStatus::found);
    assert(!f.reader().read(f.reader().user, reinterpret_cast<uintptr_t>(result.entry.code), snapshot, sizeof(snapshot)));
    // An unmapped string must be rejected, not fed to strcmp.
    FirmwareShaderEntry malformed{};
    malformed.name = reinterpret_cast<const char*>(1);
    memcpy(f.bytes, &malformed, sizeof(malformed));
    assert(find().status == ShaderLookupStatus::invalid_name);
    f.entry(0, 1024, 4, f.address(2048));
    memset(f.bytes + 1024, 'a', max_shader_name); // no bounded terminator
    assert(find().status == ShaderLookupStatus::invalid_name);
    f.bytes[1024] = 1; // possible function bytes / wrong export ABI
    assert(find().status == ShaderLookupStatus::invalid_name);
    f.entry(0, 4090, 4, f.address(2048));
    memset(f.bytes + 4090, 'a', 6); // string crosses our readable region
    assert(find().status == ShaderLookupStatus::invalid_name);
    char name[max_shader_name];
    assert(!read_shader_name(f.reader(), UINTPTR_MAX - 5, name));
    puts("shader table: bounded reads, malformed ABI, missing names and blob limits passed");
}
