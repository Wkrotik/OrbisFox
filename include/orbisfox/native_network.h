#pragma once
namespace orbisfox {
// Actual module load/initialization/symbol readiness only, not DNS/HTTP proof.
bool prepare_native_network();
}
