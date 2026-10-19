/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <utility>
namespace orbisfox {
// GLES3 PBO ring. Only the render thread owns these buffers and fences.
// Normal polling never waits. Only explicit full-queue backpressure can wait
// (capped at 250 ms), with no overwrite of in-flight storage or glFinish.
// GL is a real GLContext or a host GL adapter, exercising identical code.
template<class GL> class GpuReadbackQueue {
 public:
  enum class Result { Empty, Pending, Ready, Full, Failed };
  static constexpr size_t capacity = 2;
  using Sync = decltype(std::declval<GL&>().fFenceSync(0,0));
  struct Image { int width, height; uint64_t serial; };
  size_t pending() const { return count_; }
  Result enqueue(GL& gl, int width, int height, uint64_t serial) {
    if (count_ == capacity) return Result::Full;
    if (width <= 0 || height <= 0 || width > 1280 || height > 720) return Result::Failed;
    PackState state(gl);
    auto& slot = slots_[(head_ + count_) % capacity];
    if (!slot.buffer) gl.fGenBuffers(1,&slot.buffer);
    if (!slot.buffer) return Result::Failed;
    gl.fBindFramebuffer(0x8CA8,0); // READ_FRAMEBUFFER, owned offscreen default
    gl.fBindBuffer(0x88EB,slot.buffer); // PIXEL_PACK_BUFFER
    const size_t bytes = size_t(width) * height * 4;
    if (slot.bytes != bytes) {
      gl.fBufferData(0x88EB,bytes,nullptr,0x88E1); // STREAM_READ
      if (gl.fGetError() != 0) return Result::Failed;
      slot.bytes = bytes;
    }
    gl.fPixelStorei(0x0D05,4); // PACK_ALIGNMENT
    gl.fPixelStorei(0x0D02,0); // PACK_ROW_LENGTH
    gl.fPixelStorei(0x0D04,0); // PACK_SKIP_PIXELS
    gl.fPixelStorei(0x0D03,0); // PACK_SKIP_ROWS
    gl.fReadPixels(0,0,width,height,0x1908,0x1401,nullptr); // RGBA/UNSIGNED_BYTE, offset 0
    if (gl.fGetError() != 0) return Result::Failed;
    slot.fence = gl.fFenceSync(0x9117,0); // SYNC_GPU_COMMANDS_COMPLETE
    if (!slot.fence || gl.fGetError() != 0) {
      if (slot.fence) gl.fDeleteSync(slot.fence);
      slot.fence = nullptr; return Result::Failed;
    }
    slot.image = {width,height,serial};
    ++count_;
    gl.fFlush(); // Ensure an otherwise idle last frame reaches the GPU.
    return gl.fGetError() == 0 ? Result::Ready : Result::Failed;
  }
  // A non-rendering WR update can still upload textures. Retire it using a
  // fence, without inventing a completed frame or an unnecessary pixel copy.
  Result mark(GL& gl,uint64_t serial) {
    if (count_==capacity) return Result::Full;
    auto& slot=slots_[(head_+count_)%capacity];
    slot.fence=gl.fFenceSync(0x9117,0);
    if (!slot.fence || gl.fGetError()!=0) {
      if (slot.fence) gl.fDeleteSync(slot.fence);
      slot.fence=nullptr; return Result::Failed;
    }
    slot.image={0,0,serial}; ++count_; gl.fFlush();
    return gl.fGetError()==0 ? Result::Ready : Result::Failed;
  }
  Result waitOldest(GL& gl,uint64_t timeoutNanos) {
    if (!count_) return Result::Empty;
    if (timeoutNanos>250000000) return Result::Failed;
    const auto status=gl.fClientWaitSync(slots_[head_].fence,0,timeoutNanos);
    if (gl.fGetError()!=0) return Result::Failed;
    if (status==0x911B) return Result::Pending;
    return status==0x911A || status==0x911C ? Result::Ready : Result::Failed;
  }
  template<class Copy> Result poll(GL& gl, Copy&& copy) {
    if (!count_) return Result::Empty;
    auto& slot = slots_[head_];
    const auto status = gl.fClientWaitSync(slot.fence,0,0); // never block
    if (status == 0x911B) return Result::Pending; // TIMEOUT_EXPIRED
    if (status != 0x911A && status != 0x911C) return Result::Failed;
    if (!slot.image.width) {
      const bool copied=copy(nullptr,0,slot.image);
      gl.fDeleteSync(slot.fence); slot.fence=nullptr;
      head_=(head_+1)%capacity; --count_;
      return copied && gl.fGetError()==0 ? Result::Ready : Result::Failed;
    }
    int previous = 0;
    gl.fGetIntegerv(0x88ED,&previous); // PIXEL_PACK_BUFFER_BINDING
    gl.fBindBuffer(0x88EB,slot.buffer);
    const auto* data = static_cast<const uint8_t*>(gl.fMapBufferRange(0x88EB,0,slot.bytes,1));
    if (!data) { gl.fBindBuffer(0x88EB,previous); return Result::Failed; }
    const bool copied = copy(data,slot.bytes,slot.image);
    const bool unmapped = gl.fUnmapBuffer(0x88EB) != 0;
    gl.fBindBuffer(0x88EB,previous);
    gl.fDeleteSync(slot.fence); slot.fence = nullptr;
    head_ = (head_ + 1) % capacity; --count_;
    return copied && unmapped && gl.fGetError() == 0 ? Result::Ready : Result::Failed;
  }
  // GL deletion defers destruction of storage still used by submitted commands.
  // Never map/read an unretired buffer during teardown.
  void destroy(GL& gl) {
    for (auto& slot : slots_) {
      if (slot.fence) gl.fDeleteSync(slot.fence);
      if (slot.buffer) gl.fDeleteBuffers(1,&slot.buffer);
      slot = {};
    }
    count_ = head_ = 0;
  }
 private:
  struct Slot { uint32_t buffer=0; size_t bytes=0; Sync fence=nullptr; Image image{}; };
  struct PackState {
    GL& gl; int fbo=0,buffer=0,alignment=0,row=0,pixels=0,rows=0;
    explicit PackState(GL& g):gl(g) {
      gl.fGetIntegerv(0x8CAA,&fbo); gl.fGetIntegerv(0x88ED,&buffer);
      gl.fGetIntegerv(0x0D05,&alignment); gl.fGetIntegerv(0x0D02,&row);
      gl.fGetIntegerv(0x0D04,&pixels); gl.fGetIntegerv(0x0D03,&rows);
    }
    ~PackState() {
      gl.fBindFramebuffer(0x8CA8,fbo); gl.fBindBuffer(0x88EB,buffer);
      gl.fPixelStorei(0x0D05,alignment); gl.fPixelStorei(0x0D02,row);
      gl.fPixelStorei(0x0D04,pixels); gl.fPixelStorei(0x0D03,rows);
    }
  };
  std::array<Slot,capacity> slots_{};
  size_t head_=0,count_=0;
};
} // namespace orbisfox
