/* OrbisFox native software graphics platform. Licensed under MPL-2.0. */
#include "gfxOrbisPlatform.h"
#include "gfxFT2FontList.h"
#include "gfxImageSurface.h"
#include "mozilla/Assertions.h"
#include "mozilla/gfx/2D.h"

using namespace mozilla;
using namespace mozilla::gfx;

// Owned by gfxPlatform, released after its font-list shutdown.
static FT_Library sOrbisFTLibrary = nullptr;

gfxOrbisPlatform::gfxOrbisPlatform() {
  sOrbisFTLibrary = Factory::NewFTLibrary();
  MOZ_RELEASE_ASSERT(sOrbisFTLibrary, "Orbis FreeType initialization failed");
  Factory::SetFTLibrary(sOrbisFTLibrary);
}

gfxOrbisPlatform::~gfxOrbisPlatform() {
  Factory::SetFTLibrary(nullptr);
  Factory::ReleaseFTLibrary(sOrbisFTLibrary);
  sOrbisFTLibrary = nullptr;
}

already_AddRefed<gfxASurface> gfxOrbisPlatform::CreateOffscreenSurface(
    const IntSize& aSize, gfxImageFormat aFormat) {
  if (!Factory::AllowedSurfaceSize(aSize)) {
    return nullptr;
  }
  RefPtr<gfxASurface> surface = new gfxImageSurface(aSize, aFormat);
  return surface.forget();
}

bool gfxOrbisPlatform::CreatePlatformFontList() {
  return gfxPlatformFontList::Initialize(new gfxFT2FontList);
}

void gfxOrbisPlatform::ReadSystemFontList(mozilla::dom::SystemFontList* aList) {
  gfxFT2FontList::PlatformFontList()->ReadSystemFontList(aList);
}

already_AddRefed<mozilla::gfx::VsyncSource>
gfxOrbisPlatform::CreateGlobalHardwareVsyncSource() {
  // Follow upstream headless GTK's fallback; no VideoOut hardware-vsync claim.
  return GetSoftwareVsyncSource();
}

void gfxOrbisPlatform::GetCommonFallbackFonts(
    uint32_t, Script, FontPresentation, nsTArray<const char*>& aFonts) {
  // Initial offline fixture's bundled family only. This is not a complete
  // multilingual/system-font fallback policy for arbitrary websites.
  aFonts.AppendElement("Noto Sans");
}
