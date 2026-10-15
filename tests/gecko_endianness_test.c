/* Host behavior and target compilation only; not NSS/firmware certification. */
#include HEADER

#define CHECK_BITS(bits, type, value) do {                                   \
  uint8_t bytes[10];                                                         \
  const type v = (type)(value);                                              \
  memset(bytes, 0xa5, sizeof(bytes));                                         \
  store##bits##_le(bytes + 1, v);                                            \
  if (load##bits##_le(bytes + 1) != v) return 1;                              \
  for (unsigned j = 0; j < bits / 8; ++j)                                    \
    if (bytes[j + 1] != (uint8_t)((uint64_t)v >> (8 * j))) return 2;          \
  if (bytes[0] != 0xa5 || bytes[bits / 8 + 1] != 0xa5) return 3;            \
  store##bits##_be(bytes + 1, v);                                            \
  if (load##bits##_be(bytes + 1) != v) return 4;                              \
  for (unsigned j = 0; j < bits / 8; ++j)                                    \
    if (bytes[j + 1] != (uint8_t)((uint64_t)v >> (8 * (bits / 8 - j - 1))))  \
      return 5;                                                             \
  if (bytes[0] != 0xa5 || bytes[bits / 8 + 1] != 0xa5) return 6;            \
} while (0)

int main(void) {
  const uint64_t values[] = {0, 1, UINT64_MAX, UINT64_C(0x8000800080008000),
                            UINT64_C(0x0123456789abcdef)};
  for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
    CHECK_BITS(16, uint16_t, values[i]);
    CHECK_BITS(32, uint32_t, values[i]);
    CHECK_BITS(64, uint64_t, values[i]);
  }
  return 0;
}
