#pragma once

namespace orbisfox {
// Count cores in the calling thread's genuine native affinity mask.
// Zero means unavailable; never invent a machine/core count.
int native_available_processor_count();
}
