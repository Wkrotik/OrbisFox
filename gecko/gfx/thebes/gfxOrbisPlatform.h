/* OrbisFox native software graphics platform. Licensed under MPL-2.0. */
#ifndef gfxOrbisPlatform_h
#define gfxOrbisPlatform_h
#include "gfxPlatform.h"

class gfxOrbisPlatform final : public gfxPlatform {
 public:
  gfxOrbisPlatform();
  ~gfxOrbisPlatform() override;
  already_AddRefed<gfxASurface> CreateOffscreenSurface(
      const IntSize&, gfxImageFormat) override;
  bool CreatePlatformFontList() override;
  void ReadSystemFontList(mozilla::dom::SystemFontList*) override;
  void GetCommonFallbackFonts(uint32_t, Script, FontPresentation,
                             nsTArray<const char*>&) override;
  already_AddRefed<mozilla::gfx::VsyncSource> CreateGlobalHardwareVsyncSource()
      override;
  bool FontHintingEnabled() override { return true; }
  static bool CheckVariationFontSupport() { return true; }

 protected:
  bool AccelerateLayersByDefault() override { return false; }
};
#endif
