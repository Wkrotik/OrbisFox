/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "RenderCompositorOrbis.h"
#include "../../orbisfox/OrbisGpuReadback.h"
#include "mozilla/TimeStamp.h"
#include "mozilla/gfx/Logging.h"
#include "mozilla/webrender/RenderThread.h"
#include "mozilla/widget/OrbisCompositorWidget.h"
#include "mozilla/widget/OrbisResourceDiagnostics.h"

namespace mozilla::wr {
namespace {
uint64_t ElapsedMicros(const TimeStamp& start) {
  return uint64_t((TimeStamp::Now()-start).ToMicroseconds());
}
class OrbisReadbackEvent final : public RendererEvent {
 public:
  explicit OrbisReadbackEvent(RenderCompositorOrbis* owner) : mOwner(owner) {}
  void Run(RenderThread&, wr::WindowId) override {
    if (mOwner) mOwner->PollReadbacks();
  }
  const char* Name() override { return "OrbisGpuReadback"; }
 private:
  WeakPtr<RenderCompositorOrbis> mOwner;
};
}
UniquePtr<RenderCompositor>
RenderCompositorOrbis::Create(const RefPtr<widget::CompositorWidget>& widget,
                              nsACString& error) {
  // The native UI worker is still the ONLY VideoOut owner. Share WebRender's
  // shader context, never an unrelated EGL context or a second scanout queue.
  RefPtr<gl::GLContext> context=RenderThread::Get()->SingletonGL(error);
  if (!context) {
    widget::RecordOrbisGpuCreation(widget::OrbisGpuCreation::NoContext);
    if (error.IsEmpty()) error.AssignLiteral("FEATURE_FAILURE_ORBIS_MESA_NO_CONTEXT");
    return nullptr;
  }
  if (!context->MakeCurrent()) {
    widget::RecordOrbisGpuCreation(widget::OrbisGpuCreation::MakeCurrentFailed);
    error.AssignLiteral("FEATURE_FAILURE_ORBIS_MESA_MAKE_CURRENT");
    return nullptr;
  }
  if (!context->IsGLES() || context->Version()<300 ||
      context->RendererString().Find("RADV")==kNotFound) {
    widget::RecordOrbisGpuCreation(widget::OrbisGpuCreation::NotRadvES3);
    error.AssignLiteral("FEATURE_FAILURE_ORBIS_MESA_NOT_RADV_ES3");
    return nullptr;
  }
  auto compositor=MakeUnique<RenderCompositorOrbis>(widget,std::move(context));
  widget::RecordOrbisGpuCreation(widget::OrbisGpuCreation::Ready);
  return compositor;
}
RenderCompositorOrbis::RenderCompositorOrbis(
    const RefPtr<widget::CompositorWidget>& widget, RefPtr<gl::GLContext>&& gl)
    : RenderCompositor(widget),mGL(std::move(gl)) {}
RenderCompositorOrbis::~RenderCompositorOrbis() {
  DetachWeakPtr();
  if (mReadbackTimer) mReadbackTimer->Cancel();
  if (mGL->MakeCurrent()) mQueue.destroy(*mGL);
  widget::OrbisCompositorWidget::DiscardGpuFrame(mWidget);
}
LayoutDeviceIntSize RenderCompositorOrbis::GetBufferSize() {
  return mWidget->GetClientSize();
}
void RenderCompositorOrbis::Fail(const char* reason, WebRenderError error) {
  if (mFailed) return;
  mFailed=true;
  if (mReadbackTimer) mReadbackTimer->Cancel();
  widget::RecordOrbisGpuFailure();
  gfxCriticalNote << reason;
  RenderThread::Get()->HandleWebRenderError(error);
}
void RenderCompositorOrbis::Pause() {
  mPaused=true;
  if (mReadbackTimer) mReadbackTimer->Cancel();
  mPollScheduled=false;
}
bool RenderCompositorOrbis::Resume() {
  if (mFailed) return false;
  if (!mGL->MakeCurrent()) {
    Fail("Orbis GPU resume failed",WebRenderError::MAKE_CURRENT); return false;
  }
  mPaused=false;
  SchedulePoll();
  return true;
}
bool RenderCompositorOrbis::BeginFrame() {
  const auto size=GetBufferSize();
  if (mFailed || mPaused || size.width<=0 || size.height<=0) return false;
  if (size.width>1280 || size.height>720) {
    Fail("Orbis GPU viewport exceeds readback bounds",WebRenderError::RENDER); return false;
  }
  if (!mGL->MakeCurrent()) {
    Fail("Orbis GPU frame context failed",WebRenderError::MAKE_CURRENT); return false;
  }
  // Retire previous completed work before WebRender changes the framebuffer.
  PollReadbacks();
  if (mFailed) return false;
  mGL->fBindFramebuffer(LOCAL_GL_FRAMEBUFFER,0);
  return true;
}
RenderedFrameId RenderCompositorOrbis::EndFrame(
    const nsTArray<DeviceIntRect>& /*dirty*/) {
  const auto frame=GetNextRenderFrameId();
  if (mFailed || mPaused) return frame;
  const auto size=GetBufferSize();
  if (size.width<=0 || size.height<=0) return frame;
  if (size.width>1280 || size.height>720 || !mGL->MakeCurrent() ||
      mGL->fGetError()!=LOCAL_GL_NO_ERROR) {
    Fail("Orbis WebRender failed before GPU readback",WebRenderError::RENDER); return frame;
  }
  // At most two PBOs plus ONE coalesced latest framebuffer request. If both
  // slots are in flight, never overwrite them or grow a per-frame backlog.
  if (mPendingFrame.IsValid()) widget::RecordOrbisGpuDeferred();
  mPendingFrame=frame; mPendingSize=size;
  mPendingFence=RenderedFrameId{0}; // This later fence also covers prior uploads.
  PollReadbacks();
  return frame;
}
RenderedFrameId RenderCompositorOrbis::UpdateFrameId() {
  const auto frame=GetNextRenderFrameId();
  mPendingFence=frame;
  WaitForGPU();
  return frame;
}
bool RenderCompositorOrbis::WaitForGPU() {
  PollReadbacks();
  if (mFailed || mPaused) return !mFailed;
  // Bound actual GPU submissions, not merely PBO storage. Otherwise WebRender
  // can retain textures for an unlimited number of uncompleted frames while
  // the two readback slots are busy. Never skip an idle page's final render.
  if ((mPendingFrame.IsValid() || mPendingFence.IsValid()) && mQueue.pending()==Queue::capacity) {
    const auto start=TimeStamp::Now();
    const auto result=mQueue.waitOldest(*mGL,250000000);
    widget::RecordOrbisGpuBackpressure(ElapsedMicros(start));
    if (result!=Queue::Result::Ready) {
      Fail("Orbis GPU readback backpressure deadline failed",WebRenderError::RENDER);
      return false;
    }
    PollReadbacks();
  }
  return !mFailed;
}
void RenderCompositorOrbis::PollReadbacks() {
  MOZ_ASSERT(RenderThread::IsInRenderThread());
  mPollScheduled=false;
  if (mReadbackTimer) mReadbackTimer->Cancel();
  if (mFailed || mPaused) return;
  if (!mGL->MakeCurrent()) {
    Fail("Orbis GPU polling context failed",WebRenderError::MAKE_CURRENT); return;
  }
  widget::RecordOrbisGpuPoll();
  for (size_t i=0;i<Queue::capacity;++i) {
    RefPtr<gfx::DataSourceSurface> output;
    uint64_t completed=0;
    const auto start=TimeStamp::Now();
    const auto result=mQueue.poll(*mGL,[&](const uint8_t* bytes,size_t length,const Queue::Image& image) {
      completed=image.serial;
      if (!image.width) return true; // Completed upload-only update, no pixels.
      output=gfx::Factory::CreateDataSourceSurface(
          gfx::IntSize(image.width,image.height),gfx::SurfaceFormat::B8G8R8A8);
      if (!output) return false;
      gfx::DataSourceSurface::ScopedMap target(output,gfx::DataSourceSurface::WRITE);
      if (!target.IsMapped()) return false;
      return orbisfox::ConvertGpuRgbaToBgra(bytes,length,image.width*4,
          target.GetData(),size_t(target.GetStride())*image.height,target.GetStride(),
          image.width,image.height);
    });
    if (result==Queue::Result::Empty || result==Queue::Result::Pending) break;
    if (result==Queue::Result::Failed || !completed) {
      Fail("Orbis asynchronous GPU readback failed",WebRenderError::RENDER); return;
    }
    // The PBO has been successfully unmapped, and no writable CPU map remains.
    // Published references are immutable; native readers may retain them.
    if (output) {
      if (!widget::OrbisCompositorWidget::PublishGpuFrame(mWidget,output.forget())) {
        Fail("Orbis GPU frame rejected by native mailbox",WebRenderError::RENDER); return;
      }
      widget::RecordOrbisGpuPublication(ElapsedMicros(start));
    }
    mCompleted=RenderedFrameId{completed};
  }
  if (mPendingFrame.IsValid() && mQueue.pending()<Queue::capacity) {
    const auto start=TimeStamp::Now();
    const auto result=mQueue.enqueue(*mGL,mPendingSize.width,mPendingSize.height,mPendingFrame.mId);
    if (result==Queue::Result::Failed) {
      Fail("Orbis GPU PBO submission failed",WebRenderError::RENDER); return;
    }
    if (result==Queue::Result::Ready) {
      mPendingFrame=RenderedFrameId{0};
      widget::RecordOrbisGpuSubmit(ElapsedMicros(start));
    }
  }
  if (!mPendingFrame.IsValid() && mPendingFence.IsValid() && mQueue.pending()<Queue::capacity) {
    const auto result=mQueue.mark(*mGL,mPendingFence.mId);
    if (result==Queue::Result::Failed) {
      Fail("Orbis GPU upload fence failed",WebRenderError::RENDER); return;
    }
    if (result==Queue::Result::Ready) mPendingFence=RenderedFrameId{0};
  }
  SchedulePoll();
}
void RenderCompositorOrbis::SchedulePoll() {
  if (mFailed || mPaused || mPollScheduled ||
      (!mQueue.pending() && !mPendingFrame.IsValid() && !mPendingFence.IsValid())) return;
  nsCOMPtr<nsIThread> target=RenderThread::GetRenderThread();
  mPollScheduled=true;
  // Even an idle page's final frame must be published. The timer targets the
  // render thread and posts a RendererEvent rather than invoking WebRender or
  // using a compositor raw pointer from an arbitrary callback thread.
  const nsresult rv=NS_NewTimerWithFuncCallback(getter_AddRefs(mReadbackTimer),
      [](nsITimer*,void* owner) {
        auto* self=static_cast<RenderCompositorOrbis*>(owner);
        // This private event doesn't look up a window/renderer; WindowId{} is
        // unused, and the weak owner is checked on the same render thread.
        RenderThread::Get()->PostEvent(wr::WindowId{},MakeUnique<OrbisReadbackEvent>(self));
      },this,4,nsITimer::TYPE_ONE_SHOT,"OrbisGpuReadback"_ns,target);
  if (NS_FAILED(rv)) {
    mPollScheduled=false;
    Fail("Orbis GPU polling timer failed",WebRenderError::RENDER);
  }
}
} // namespace mozilla::wr
