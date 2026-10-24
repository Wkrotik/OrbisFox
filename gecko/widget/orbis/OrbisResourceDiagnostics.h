/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#ifndef ORBIS_RESOURCE_DIAGNOSTICS_H
#define ORBIS_RESOURCE_DIAGNOSTICS_H
#include <cstddef>
#include <cstdint>
namespace mozilla::widget {
struct OrbisResourceDiagnostics {
  uint64_t sharedMappedBytes, sharedPeakBytes, sharedMaps, sharedUnmaps;
  uint64_t sharedMapFailures, sharedUnmapFailures;
  uint64_t gpuSubmitted, gpuPublished, gpuDeferred, gpuFailures;
  uint64_t gpuEnqueueMicros, gpuCopyMicros, gpuPolls, gpuWaits, gpuWaitMicros;
};
OrbisResourceDiagnostics GetOrbisResourceDiagnostics();
// Selection evidence is not GPU execution evidence. Flags encode headless=1,
// widget acceleration=2, native gate=4, global software=8, chosen software=16.
struct OrbisGraphicsDiagnostics {
  uint64_t hardwareSelections, softwareSelections, createAttempts, createSuccesses;
  uint32_t policyFlags, configFlags, hardwareStatus, webRenderStatus, creationResult;
};
enum class OrbisGpuCreation : uint32_t {
  NotAttempted=0, Ready=1, NoContext=2, MakeCurrentFailed=3, NotRadvES3=4
};
OrbisGraphicsDiagnostics GetOrbisGraphicsDiagnostics();
void RecordOrbisGraphicsConfig(bool aHardware, bool aWebRender,
                              uint32_t aHardwareStatus, uint32_t aWebRenderStatus);
void RecordOrbisCompositorSelection(bool aHeadless, bool aSupportsAcceleration,
                                   bool aNativeReady, bool aGlobalSoftware,
                                   bool aSelectedSoftware);
void RecordOrbisGpuCreation(OrbisGpuCreation aResult);
void RecordOrbisSharedMap(size_t aBytes, bool aSuccess);
void RecordOrbisSharedUnmap(size_t aBytes, bool aSuccess);
void RecordOrbisGpuSubmit(uint64_t aMicros);
void RecordOrbisGpuPublication(uint64_t aMicros);
void RecordOrbisGpuDeferred();
void RecordOrbisGpuFailure();
void RecordOrbisGpuPoll();
void RecordOrbisGpuBackpressure(uint64_t aMicros);
} // namespace mozilla::widget
#endif
