#pragma once
// The genuine SDK allocator stays sole owner of all app C/C++/Rust heap data.
#define ORBISFOX_ALLOCATOR_WRAPPED_SYMBOLS \
  "malloc", "free", "realloc", "calloc", "aligned_alloc", \
  "posix_memalign", "memalign", "__memalign", "valloc", "malloc_usable_size"
