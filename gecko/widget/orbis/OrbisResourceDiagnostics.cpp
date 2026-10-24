/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "OrbisResourceDiagnostics.h"
#include <atomic>
namespace mozilla::widget {
namespace {
std::atomic<uint64_t> mapped{0}, peak{0}, maps{0}, unmaps{0}, mapFailures{0}, unmapFailures{0};
std::atomic<uint64_t> submitted{0}, published{0}, deferred{0}, gpuFailures{0};
std::atomic<uint64_t> enqueueMicros{0}, copyMicros{0}, polls{0}, waits{0}, waitMicros{0};
std::atomic<uint64_t> hardwareSelections{0}, softwareSelections{0}, createAttempts{0}, createSuccesses{0};
std::atomic<uint32_t> policyFlags{0}, configFlags{0}, hardwareStatus{UINT32_MAX}, webRenderStatus{UINT32_MAX}, creationResult{0};
}
OrbisResourceDiagnostics GetOrbisResourceDiagnostics() {
  // Independently sampled counters, not a transactional allocation census.
  return {mapped.load(),peak.load(),maps.load(),unmaps.load(),mapFailures.load(),
          unmapFailures.load(),submitted.load(),published.load(),deferred.load(),
          gpuFailures.load(),enqueueMicros.load(),copyMicros.load(),polls.load(),waits.load(),waitMicros.load()};
}
OrbisGraphicsDiagnostics GetOrbisGraphicsDiagnostics() {
  return {hardwareSelections.load(),softwareSelections.load(),createAttempts.load(),createSuccesses.load(),
          policyFlags.load(),configFlags.load(),hardwareStatus.load(),webRenderStatus.load(),creationResult.load()};
}
void RecordOrbisGraphicsConfig(bool hardware, bool webRender, uint32_t hwStatus, uint32_t wrStatus) {
  configFlags.store((hardware?1u:0u)|(webRender?2u:0u));
  hardwareStatus.store(hwStatus);webRenderStatus.store(wrStatus);
}
void RecordOrbisCompositorSelection(bool headless, bool acceleration, bool nativeReady,
                                   bool globalSoftware, bool selectedSoftware) {
  policyFlags.store((headless?1u:0u)|(acceleration?2u:0u)|(nativeReady?4u:0u)|
                    (globalSoftware?8u:0u)|(selectedSoftware?16u:0u));
  if (selectedSoftware) ++softwareSelections; else ++hardwareSelections;
}
void RecordOrbisGpuCreation(OrbisGpuCreation result) {
  ++createAttempts;
  if (result==OrbisGpuCreation::Ready) ++createSuccesses;
  creationResult.store(static_cast<uint32_t>(result));
}
void RecordOrbisSharedMap(size_t bytes, bool success) {
  if (!success) { ++mapFailures; return; }
  ++maps;
  const auto total = mapped.fetch_add(bytes) + bytes;
  auto old = peak.load();
  while (old < total && !peak.compare_exchange_weak(old,total)) {}
}
void RecordOrbisSharedUnmap(size_t bytes, bool success) {
  if (!success) { ++unmapFailures; return; }
  ++unmaps;
  mapped.fetch_sub(bytes);
}
void RecordOrbisGpuSubmit(uint64_t us) { ++submitted; enqueueMicros.fetch_add(us); }
void RecordOrbisGpuPublication(uint64_t us) { ++published; copyMicros.fetch_add(us); }
void RecordOrbisGpuDeferred() { ++deferred; }
void RecordOrbisGpuFailure() { ++gpuFailures; }
void RecordOrbisGpuPoll() { ++polls; }
void RecordOrbisGpuBackpressure(uint64_t us) { ++waits; waitMicros.fetch_add(us); }
} // namespace mozilla::widget
