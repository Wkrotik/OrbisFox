/* OrbisFox compositor mailbox. Licensed under MPL-2.0. */
#ifndef widget_orbis_OrbisCompositorWidget_h
#define widget_orbis_OrbisCompositorWidget_h

#include "mozilla/DataMutex.h"
#include "mozilla/gfx/2D.h"
#include "mozilla/widget/HeadlessCompositorWidget.h"

namespace mozilla::widget {

// SWGL draw target and immutable hardware-readback mailbox. Only the native UI
// worker presents VideoOut; Gecko render-thread contexts never own scanout.
class OrbisCompositorWidget final : public HeadlessCompositorWidget {
 public:
  using HeadlessCompositorWidget::HeadlessCompositorWidget;

  already_AddRefed<gfx::DrawTarget> StartRemoteDrawing() override;
  void EndRemoteDrawing() override;
  void EndRemoteDrawingInRegion(gfx::DrawTarget*,
                               const LayoutDeviceIntRegion&) override;
  void CleanupRemoteDrawing() override;

  // Thread-safe immutable snapshot + sequence. Null means no completed frame.
  // Holding the snapshot keeps it valid across subsequent draws and cleanup.
  static already_AddRefed<gfx::DataSourceSurface> GetLatestFrame(uint64_t* aSequence);
  static void DiscardFrames();
  // Caller must finish all writable maps and relinquish its mutable reference.
  static bool PublishGpuFrame(const CompositorWidget* aOwner,
                             already_AddRefed<gfx::DataSourceSurface> aSurface);
  static void DiscardGpuFrame(const CompositorWidget* aOwner);

 private:
  struct FrameState {
    RefPtr<gfx::DataSourceSurface> surface;
    uint64_t sequence = 0;
    const CompositorWidget* owner = nullptr;
  };
  static DataMutex<FrameState>& Frames();
  // Compositor-thread-only state. The initial offline viewport is bounded.
  RefPtr<gfx::DrawTarget> mTarget;
  bool mDrawing = false;
};

}  // namespace mozilla::widget
#endif
