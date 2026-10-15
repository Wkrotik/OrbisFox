#pragma once
#include <stddef.h>
#include <stdint.h>

namespace orbisfox {
// Reverse-engineered OpenOrbis table layout, NOT guaranteed across firmware.
// Never dereference pointers from this record before validating their mapping.
struct FirmwareShaderEntry {
    const char* name;
    uint8_t hash[16];
    uint64_t length;
    const uint8_t* code;
};
static_assert(sizeof(FirmwareShaderEntry) == 40, "Shader table requires x86-64 layout");
static_assert(offsetof(FirmwareShaderEntry, length) == 24, "Unexpected shader ABI");
static_assert(offsetof(FirmwareShaderEntry, code) == 32, "Unexpected shader ABI");
struct MemoryReader {
    void* user;
    bool (*read)(void* user, uintptr_t address, void* destination, size_t bytes);
};
enum class ShaderLookupStatus { found, not_found, unreadable_table, invalid_name, invalid_blob, limit_reached };
struct ShaderLookup {
    ShaderLookupStatus status;
    FirmwareShaderEntry entry;
    size_t inspected;
};
constexpr size_t max_shader_bytes = 1024 * 1024;
constexpr size_t max_shader_name = 128;
bool read_shader_name(MemoryReader reader, uintptr_t address, char (&name)[max_shader_name]);
ShaderLookup find_firmware_shader(MemoryReader reader, uintptr_t table, const char* requested,
                                 size_t limit = 4096);
const char* shader_lookup_status(ShaderLookupStatus status);
} // namespace orbisfox
