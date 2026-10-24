/* OrbisFox optional graphics-information lookup. Licensed under MPL-2.0. */
#ifndef widget_orbis_OrbisGfxInfo_h
#define widget_orbis_OrbisGfxInfo_h
#include "nsCOMPtr.h"
#include "nsIGfxInfo.h"
#include "nsServiceManagerUtils.h"

#ifdef MOZ_ORBIS_MESA
extern "C" bool orbis_mesa_gpu_ready() __attribute__((weak));
#endif

namespace mozilla::widget {
inline bool IsOrbisMesaGpuReady() {
#ifdef MOZ_ORBIS_MESA
  // Real startup GLES shader/pixel gate, not an invented GfxInfo device/status.
  return orbis_mesa_gpu_ready && orbis_mesa_gpu_ready();
#else
  return false;
#endif
}
inline nsresult GetOptionalGfxFeatureStatus(nsIGfxInfo* aInfo, int32_t aFeature,
                                          nsACString& aFailureId, int32_t* aStatus) {
  if (!aStatus) return NS_ERROR_INVALID_ARG;
  *aStatus = nsIGfxInfo::FEATURE_STATUS_UNKNOWN;
  // Explicit absence, not successful invented GPU/driver information.
  if (!aInfo) return NS_ERROR_NOT_AVAILABLE;
  return aInfo->GetFeatureStatus(aFeature, aFailureId, aStatus);
}
inline already_AddRefed<nsIGfxInfo> GetOptionalGfxInfo() {
  // No native GPU-information service is registered during software-only
  // bring-up. A missing contract returns null, not invented device/driver data.
  nsCOMPtr<nsIGfxInfo> info = do_GetService("@mozilla.org/gfx/info;1");
  return info.forget();
}
}  // namespace mozilla::widget
#endif
