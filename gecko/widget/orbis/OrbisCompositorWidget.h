/* OrbisFox software compositor surface. Licensed under MPL-2.0. */
#ifndef widget_orbis_OrbisCompositorWidget_h
#define widget_orbis_OrbisCompositorWidget_h

#include "mozilla/DataMutex.h"
#include "mozilla/TimeStamp.h"
#include "mozilla/gfx/2D.h"
#include "mozilla/widget/HeadlessCompositorWidget.h"

namespace mozilla::widget {

// A real BGRA draw target for RenderCompositorSWGL. Publication is separate
// from VideoOut presentation, which must remain on the application's thread.
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

 private:
  struct FrameState {
    RefPtr<gfx::DataSourceSurface> surface;
    uint64_t sequence = 0;
    const OrbisCompositorWidget* owner = nullptr;
  };
  static DataMutex<FrameState>& Frames();
  // Compositor-thread-only state. The initial offline viewport is bounded.
  RefPtr<gfx::DrawTarget> mTarget;
  bool mDrawing = false;
  TimeStamp mDrawStart;  // Compositor thread only; see OrbisCompositorTiming.
};

}  // namespace mozilla::widget
#endif
