/* OrbisFox software compositor surface. Licensed under MPL-2.0. */
#include "OrbisCompositorWidget.h"
#include "OrbisTaskDiagnostics.h"
#include "mozilla/Assertions.h"
#include <atomic>

namespace mozilla::widget {
using namespace gfx;

namespace {
// Relaxed counters: written by the compositor thread, sampled by the native
// heartbeat monitor. Individually atomic; a sample may straddle one frame.
std::atomic<uint64_t> sFrames{0}, sCancelled{0}, sDrawMicros{0}, sMaxDrawMicros{0},
    sFlushMicros{0}, sSnapshotMicros{0}, sMaxSnapshotMicros{0};
uint64_t Micros(const TimeStamp& aStart, const TimeStamp& aEnd) {
  const double value = (aEnd - aStart).ToMicroseconds();
  return value > 0 ? uint64_t(value) : 0;
}
void RaiseMax(std::atomic<uint64_t>& aMax, uint64_t aValue) {
  uint64_t current = aMax.load(std::memory_order_relaxed);
  while (aValue > current &&
         !aMax.compare_exchange_weak(current, aValue, std::memory_order_relaxed)) {
  }
}
}  // namespace

OrbisCompositorTiming GetOrbisCompositorTiming() {
  OrbisCompositorTiming timing;
  timing.frames = sFrames.load(std::memory_order_relaxed);
  timing.cancelled = sCancelled.load(std::memory_order_relaxed);
  timing.drawMicros = sDrawMicros.load(std::memory_order_relaxed);
  timing.maxDrawMicros = sMaxDrawMicros.load(std::memory_order_relaxed);
  timing.flushMicros = sFlushMicros.load(std::memory_order_relaxed);
  timing.snapshotMicros = sSnapshotMicros.load(std::memory_order_relaxed);
  timing.maxSnapshotMicros = sMaxSnapshotMicros.load(std::memory_order_relaxed);
  return timing;
}

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
  mDrawStart = TimeStamp::Now();
  return do_AddRef(mTarget);
}

void OrbisCompositorWidget::EndRemoteDrawing() {
  if (!mDrawing) {
    return;
  }
  mDrawing = false;
  const TimeStamp drawEnd = TimeStamp::Now();
  mTarget->Flush();
  const TimeStamp flushEnd = TimeStamp::Now();
  RefPtr<SourceSurface> snapshot = mTarget->Snapshot();
  RefPtr<DataSourceSurface> surface = snapshot ? snapshot->GetDataSurface() : nullptr;
  const TimeStamp snapshotEnd = TimeStamp::Now();
  if (!surface || surface->GetFormat() != SurfaceFormat::B8G8R8A8) {
    return;
  }
  const uint64_t draw = Micros(mDrawStart, drawEnd);
  const uint64_t snapshotMicros = Micros(flushEnd, snapshotEnd);
  sDrawMicros.fetch_add(draw, std::memory_order_relaxed);
  RaiseMax(sMaxDrawMicros, draw);
  sFlushMicros.fetch_add(Micros(drawEnd, flushEnd), std::memory_order_relaxed);
  sSnapshotMicros.fetch_add(snapshotMicros, std::memory_order_relaxed);
  RaiseMax(sMaxSnapshotMicros, snapshotMicros);
  sFrames.fetch_add(1, std::memory_order_relaxed);
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
    if (mDrawing) {
      sCancelled.fetch_add(1, std::memory_order_relaxed);
    }
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
