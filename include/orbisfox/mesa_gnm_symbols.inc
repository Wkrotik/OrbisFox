// SPDX-License-Identifier: MIT
// Static ABI-preserving tail jumps: do not invent missing GNM prototypes.
// No VideoOut interposition; the existing native worker owns presentation.
ORBIS_MESA_GNM(0, sceGnmAreSubmitsAllowed)
ORBIS_MESA_GNM(1, sceGnmDrawInitDefaultHardwareState)
ORBIS_MESA_GNM(2, sceGnmDrawInitToDefaultContextState)
ORBIS_MESA_GNM(3, sceGnmFlushGarlic)
ORBIS_MESA_GNM(4, sceGnmGetTheTessellationFactorRingBufferBaseAddress)
ORBIS_MESA_GNM(5, sceGnmSetHsShader)
ORBIS_MESA_GNM(6, sceGnmSetLsShader)
ORBIS_MESA_GNM(7, sceGnmSetVsShader)
ORBIS_MESA_GNM(8, sceGnmSubmitCommandBuffers)
ORBIS_MESA_GNM(9, sceGnmSubmitDone)
