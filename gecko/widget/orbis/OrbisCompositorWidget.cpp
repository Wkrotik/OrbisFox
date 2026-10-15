/* OrbisFox software compositor surface. Licensed under MPL-2.0. */
#include "OrbisCompositorWidget.h"
#include "mozilla/Assertions.h"

namespace mozilla::widget {
using namespace gfx;

DataMutex<OrbisCompositorWidget::FrameState>& OrbisCompositorWidget::Frames() {
  // One bounded offline viewport. Initialize lazily, after the native CRT.
  static DataMutex<FrameState> mailbox{FrameState{}, "OrbisFoxFrameMailbox"};
  return mailbox;
}

already_AddRefed<DrawTarget> OrbisCompositorWidget::StartRemoteDrawing() {
  if (mDrawing) {
    return nullptr;
  }
  const IntSize size = GetClientSize().ToUnknownSize();
  if (size.width <= 0 || size.height <= 0 || size.width > 1280 ||
      size.height > 720 || !Factory::AllowedSurfaceSize(size)) {
    return nullptr;
  }
  if (!mTarget || mTarget->GetSize() != size) {
    mTarget = Factory::CreateDrawTarget(BackendType::SKIA, size,
                                       SurfaceFormat::B8G8R8A8);
    if (!mTarget || !mTarget->IsValid()) {
      mTarget = nullptr;
      return nullptr;
    }
    // Fully initialize newly allocated buffers. Later dirty-region draws must
    // preserve the remainder of the preceding frame.
    mTarget->ClearRect(Rect(0, 0, size.width, size.height));
  }
  mDrawing = true;
  return do_AddRef(mTarget);
}

void OrbisCompositorWidget::EndRemoteDrawing() {
  if (!mDrawing) {
    return;
  }
  mDrawing = false;
  mTarget->Flush();
  RefPtr<SourceSurface> snapshot = mTarget->Snapshot();
  RefPtr<DataSourceSurface> surface = snapshot ? snapshot->GetDataSurface() : nullptr;
  if (!surface || surface->GetFormat() != SurfaceFormat::B8G8R8A8) {
    return;
  }
  // Snapshot's copy-on-write ownership prevents the next SWGL frame from
  // modifying a surface retained by the application thread.
  auto frame = Frames().Lock();
  frame->surface = surface;
  frame->owner = this;
  ++frame->sequence;
}

void OrbisCompositorWidget::EndRemoteDrawingInRegion(
    DrawTarget* aTarget, const LayoutDeviceIntRegion& aRegion) {
  MOZ_RELEASE_ASSERT(!mDrawing || aTarget == mTarget.get());
  if (aRegion.IsEmpty()) {
    // SWGL cancellation or mapping failure: retain the last published frame.
    mDrawing = false;
    return;
  }
  EndRemoteDrawing();
}

void OrbisCompositorWidget::CleanupRemoteDrawing() {
  mDrawing = false;
  mTarget = nullptr;
  auto frame = Frames().Lock();
  if (frame->owner == this) {
    frame->surface = nullptr;
    frame->owner = nullptr;
    ++frame->sequence;
  }
}

void OrbisCompositorWidget::DiscardFrames() {
  auto frame = Frames().Lock();
  frame->surface = nullptr;
  frame->owner = nullptr;
  ++frame->sequence;
}

already_AddRefed<DataSourceSurface> OrbisCompositorWidget::GetLatestFrame(
    uint64_t* aSequence) {
  auto frame = Frames().Lock();
  if (aSequence) {
    *aSequence = frame->sequence;
  }
  return do_AddRef(frame->surface);
}

}  // namespace mozilla::widget
