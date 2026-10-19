/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#ifndef MOZILLA_RENDER_COMPOSITOR_ORBIS_H
#define MOZILLA_RENDER_COMPOSITOR_ORBIS_H
#include "RenderCompositor.h"
#include "GLContext.h"
#include "mozilla/WeakPtr.h"
#include "nsITimer.h"
#include "../../orbisfox/OrbisGpuReadbackQueue.h"
namespace mozilla::wr {
class RenderCompositorOrbis final : public RenderCompositor, public SupportsWeakPtr {
 public:
  static UniquePtr<RenderCompositor> Create(
      const RefPtr<widget::CompositorWidget>& aWidget, nsACString& aError);
  RenderCompositorOrbis(const RefPtr<widget::CompositorWidget>& aWidget,
                       RefPtr<gl::GLContext>&& aGL);
  ~RenderCompositorOrbis() override;
  bool BeginFrame() override;
  RenderedFrameId EndFrame(const nsTArray<DeviceIntRect>& aDirtyRects) override;
  gl::GLContext* gl() const override { return mGL; }
  LayoutDeviceIntSize GetBufferSize() override;
  RenderedFrameId GetLastCompletedFrameId() override { return mCompleted; }
  RenderedFrameId UpdateFrameId() override;
  bool UseANGLE() const override { return false; }
  bool UseDComp() const override { return false; }
  bool IsPaused() override { return mPaused; }
  void Pause() override;
  bool Resume() override;
  bool WaitForGPU() override;
  // Called only on RenderThread, including the timer's RendererEvent.
  void PollReadbacks();
 private:
  void SchedulePoll();
  void Fail(const char* aReason, WebRenderError aError);
  RefPtr<gl::GLContext> mGL;
  using Queue = orbisfox::GpuReadbackQueue<gl::GLContext>;
  Queue mQueue;
  nsCOMPtr<nsITimer> mReadbackTimer;
  RenderedFrameId mCompleted{0}, mPendingFrame{0}, mPendingFence{0};
  LayoutDeviceIntSize mPendingSize{0,0};
  bool mFailed=false, mPaused=false, mPollScheduled=false;
};
} // namespace mozilla::wr
#endif
