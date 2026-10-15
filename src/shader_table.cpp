#include "orbisfox/shader_table.h"
#include <string.h>

namespace orbisfox {
bool read_shader_name(MemoryReader r, uintptr_t address, char (&name)[max_shader_name]) {
    memset(name, 0, sizeof(name));
    if (!r.read || !address) return false;
    for (size_t i = 0; i < sizeof(name); ++i) {
        if (address > UINTPTR_MAX - i || !r.read(r.user, address + i, name + i, 1)) return false;
        if (!name[i]) return true;
        // Firmware shader identifiers are printable ASCII paths, not binary.
        if ((unsigned char)name[i] < 32 || (unsigned char)name[i] > 126) return false;
    }
    name[sizeof(name) - 1] = 0;
    return false;
}
ShaderLookup find_firmware_shader(MemoryReader r, uintptr_t table, const char* requested, size_t limit) {
    ShaderLookup result{ShaderLookupStatus::unreadable_table, {}, 0};
    if (!table || !requested || !*requested || !r.read) return result;
    uintptr_t position = table;
    for (size_t i = 0; i < limit; ++i) {
        FirmwareShaderEntry entry{};
        if (!r.read(r.user, position, &entry, sizeof(entry))) return result;
        result.inspected = i + 1;
        if (!entry.name) { result.status = ShaderLookupStatus::not_found; return result; }
        char name[max_shader_name];
        if (!read_shader_name(r, reinterpret_cast<uintptr_t>(entry.name), name)) {
            result.status = ShaderLookupStatus::invalid_name; return result;
        }
        if (strcmp(name, requested) == 0) {
            if (!entry.code || entry.length == 0 || entry.length > max_shader_bytes
                || reinterpret_cast<uintptr_t>(entry.code) > UINTPTR_MAX - (size_t)entry.length) {
                result.status = ShaderLookupStatus::invalid_blob; return result;
            }
            result.status = ShaderLookupStatus::found; result.entry = entry; return result;
        }
        if (position > UINTPTR_MAX - sizeof(entry)) return result;
        position += sizeof(entry);
    }
    result.status = ShaderLookupStatus::limit_reached;
    return result;
}
const char* shader_lookup_status(ShaderLookupStatus status) {
    switch (status) {
        case ShaderLookupStatus::found: return "FOUND";
        case ShaderLookupStatus::not_found: return "NOT FOUND";
        case ShaderLookupStatus::unreadable_table: return "UNREADABLE TABLE";
        case ShaderLookupStatus::invalid_name: return "INVALID NAME / POSSIBLE ABI MISMATCH";
        case ShaderLookupStatus::invalid_blob: return "INVALID BLOB";
        case ShaderLookupStatus::limit_reached: return "TABLE LIMIT REACHED";
    }
    return "UNKNOWN";
}
} // namespace orbisfox
