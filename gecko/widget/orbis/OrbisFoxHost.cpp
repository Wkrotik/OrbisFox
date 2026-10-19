/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "OrbisFoxHost.h"
#include "OrbisGfxInfo.h"
#include "OrbisCompositorWidget.h"
#include "mozilla/gfx/gfxVars.h"
#include "mozilla/orbisfox/OrbisExecutableMemory.h"
#include "mozilla/orbisfox/OrbisAudioBackend.h"
#include "nsThreadUtils.h"
#include "nsString.h"
#include "mozilla/ResultExtensions.h"
#include "mozilla/TextEvents.h"
#include "mozilla/Logging.h"

nsresult OrbisCreateVisibleBrowser(uint32_t, uint32_t, nsIWindowlessBrowser**,
                                   nsIWidget**, bool);

namespace mozilla::widget {
static OrbisFoxHostCallbacks sCallbacks;
void SetOrbisFoxHostCallbacks(const OrbisFoxHostCallbacks& aCallbacks) {
  sCallbacks = aCallbacks;
}
NS_IMPL_ISUPPORTS(OrbisFoxHost, nsIOrbisFoxHost)

NS_IMETHODIMP OrbisFoxHost::GetNativeNetworkReady(bool* aReady) {
  NS_ENSURE_ARG_POINTER(aReady);
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  *aReady = sCallbacks.nativeNetworkReady;
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::GetNativeJitReady(bool* aReady) {
  NS_ENSURE_ARG_POINTER(aReady);
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  *aReady = orbisfox::orbis_jit_memory_stats().ready;
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::GetNativeGpuReady(bool* aReady) {
  NS_ENSURE_ARG_POINTER(aReady);
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  *aReady = IsOrbisMesaGpuReady();
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::GetNativeAudioReady(bool* aReady) {
  NS_ENSURE_ARG_POINTER(aReady);
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  *aReady = orbisfox::orbis_audio_backend_ready();
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::CreateBrowser(uint32_t aWidth, uint32_t aHeight,
                                        nsIWindowlessBrowser** aResult) {
  return Create(aWidth, aHeight, false, aResult);
}
NS_IMETHODIMP OrbisFoxHost::CreateChromeBrowser(uint32_t aWidth, uint32_t aHeight,
                                              nsIWindowlessBrowser** aResult) {
  return Create(aWidth, aHeight, true, aResult);
}
nsresult OrbisFoxHost::Create(uint32_t aWidth, uint32_t aHeight, bool aChrome,
                            nsIWindowlessBrowser** aResult) {
  NS_ENSURE_ARG_POINTER(aResult);
  *aResult = nullptr;
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  NS_ENSURE_FALSE(mBrowser, NS_ERROR_ALREADY_INITIALIZED);
  NS_ENSURE_TRUE(sCallbacks.present && sCallbacks.poll, NS_ERROR_NOT_INITIALIZED);
  if (sCallbacks.log) sCallbacks.log(sCallbacks.context, "Gecko browser: visible widget/context creation begin");
  nsresult rv = OrbisCreateVisibleBrowser(aWidth, aHeight, getter_AddRefs(mBrowser),
                                         getter_AddRefs(mWidget), aChrome);
  NS_ENSURE_SUCCESS(rv, rv);
  if (sCallbacks.log) sCallbacks.log(sCallbacks.context, "Gecko browser: visible widget/context creation completed");
  nsCOMPtr<nsIWindowlessBrowser> result = mBrowser;
  result.forget(aResult);
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::RequestExit() {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  NS_ENSURE_TRUE(sCallbacks.requestExit, NS_ERROR_NOT_INITIALIZED);
  sCallbacks.requestExit(sCallbacks.context);
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::OpenAddressKeyboard(const nsAString& aDraft, bool* aOpened) {
  return OpenKeyboard(aDraft, true, aOpened);
}
NS_IMETHODIMP OrbisFoxHost::OpenTextKeyboard(const nsAString& aDraft, bool* aOpened) {
  return OpenKeyboard(aDraft, false, aOpened);
}
NS_IMETHODIMP OrbisFoxHost::GetKeyboardConfirmButton(uint32_t* aValue) {
  NS_ENSURE_ARG_POINTER(aValue);
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  *aValue = sCallbacks.keyboardConfirm ? sCallbacks.keyboardConfirm(sCallbacks.context) : 0;
  return NS_OK;
}
nsresult OrbisFoxHost::OpenKeyboard(const nsAString& aDraft, bool aAddress, bool* aOpened) {
  NS_ENSURE_ARG_POINTER(aOpened);
  *aOpened = false;
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  if (!sCallbacks.openKeyboard || aDraft.Length() > 512 || mKeyboardStatus == 1) return NS_OK;
  nsAutoString draft(aDraft);
  *aOpened = sCallbacks.openKeyboard(sCallbacks.context, draft.get(), draft.Length(), aAddress);
  if (*aOpened) {mKeyboardStatus = 1; mKeyboardText.Truncate();}
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::CancelAddressKeyboard() {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  if (sCallbacks.cancelKeyboard) sCallbacks.cancelKeyboard(sCallbacks.context);
  mKeyboardStatus = 0; mKeyboardText.Truncate();
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetKeyboardStatus(uint32_t* aStatus) {
  NS_ENSURE_ARG_POINTER(aStatus);
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  *aStatus = mKeyboardStatus; return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetKeyboardText(nsAString& aText) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  aText.Assign(mKeyboardText); return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetScrollX(int32_t* aValue) {
  NS_ENSURE_ARG_POINTER(aValue); *aValue = mScrollX; return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetScrollY(int32_t* aValue) {
  NS_ENSURE_ARG_POINTER(aValue); *aValue = mScrollY; return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::GetDiagnosticsEnabled(bool* aEnabled) {
  NS_ENSURE_ARG_POINTER(aEnabled);
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  *aEnabled=sCallbacks.diagnosticsEnabled && sCallbacks.diagnosticsEnabled(sCallbacks.context);
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::SetDiagnosticsEnabled(bool aEnabled) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  NS_ENSURE_TRUE(sCallbacks.diagnostics, NS_ERROR_NOT_AVAILABLE);
  char path[256]{};
  NS_ENSURE_TRUE(sCallbacks.diagnostics(sCallbacks.context,aEnabled,path,sizeof(path)),NS_ERROR_FAILURE);
  // No MOZ_LOG_FILE environment override: runtime redirection closes the old
  // owned output; OFF writes neither profile logs nor diagnostic run files.
  LogModule::SetLogFile(aEnabled ? path : "/dev/null");
  for(const char* module : {"SharedMemory","nsStreamPump","nsThreadPool","DocumentChannel","nsRedirect","ProcessIsolation","ScriptLoader","nsSocketTransport","nsHostResolver","nsHttp","mozStorage","cookie","userfonts"})
    LogModule::Get(module)->SetLevel(aEnabled ? LogLevel::Info : LogLevel::Disabled);
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::SetNativeChromeState(const nsACString& aState) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  if (aState.Length() > 4096 || aState.FindChar('\0') != kNotFound) return NS_ERROR_INVALID_ARG;
  NS_ENSURE_TRUE(sCallbacks.chromeState, NS_ERROR_NOT_AVAILABLE);
  nsAutoCString state(aState);
  return sCallbacks.chromeState(sCallbacks.context, state.get()) ? NS_OK : NS_ERROR_INVALID_ARG;
}
NS_IMETHODIMP OrbisFoxHost::TakeNativeChromeAction(nsACString& aAction) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  aAction.Truncate();char action[48]{};
  if (sCallbacks.chromeAction && sCallbacks.chromeAction(sCallbacks.context, action, sizeof(action))) aAction.Assign(action);
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::SetCursorSpeed(double aMultiplier) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  if (!(aMultiplier >= 0.25 && aMultiplier <= 3.0)) return NS_ERROR_INVALID_ARG;
  if (!sCallbacks.cursorSpeed) return NS_ERROR_NOT_AVAILABLE;
  sCallbacks.cursorSpeed(sCallbacks.context, aMultiplier);
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::SendEscape() {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  nsCOMPtr<nsIWidget> widget=mWidget;
  NS_ENSURE_TRUE(widget, NS_ERROR_NOT_INITIALIZED);
  for(auto message : {eKeyDown,eKeyUp}) {
    WidgetKeyboardEvent event(true,message,widget);
    event.mKeyCode=27; // DOM_VK_ESCAPE.
    event.mKeyNameIndex=KEY_NAME_INDEX_Escape;
    event.mCodeNameIndex=CODE_NAME_INDEX_Escape;
    // DispatchEvent returns consumption status, not an nsresult.
    (void)widget->DispatchEvent(&event);
  }
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::SetPointerInputEnabled(bool aEnabled) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  const bool release = mPointerEnabled && !aEnabled && mMouseDown && mWidget;
  // Dispatch is synchronous and can reenter chrome/native methods. Publish
  // ownership before release: never synthesize the same mouse-up recursively.
  const bool releaseMiddle = mPointerEnabled && !aEnabled && mMiddleDown && mWidget;
  mPointerEnabled = aEnabled;
  if (!aEnabled) {mMouseDown = false;mMiddleDown=false;}
  mPointerButtons = mButtons;
  if (release) {
    MOZ_TRY(mWidget->SynthesizeNativeMouseEvent(LayoutDeviceIntPoint(mCursorX, mCursorY),
        nsIWidget::NativeMouseMessage::ButtonUp, MouseButton::ePrimary,
        nsIWidget::NativeModifiers::NO_MODIFIERS, nullptr));
  }
  if(releaseMiddle) {
    MOZ_TRY(mWidget->SynthesizeNativeMouseEvent(LayoutDeviceIntPoint(mCursorX,mCursorY),
        nsIWidget::NativeMouseMessage::ButtonUp,MouseButton::eMiddle,
        nsIWidget::NativeModifiers::NO_MODIFIERS,nullptr));
  }
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::PumpFrame(bool* aContinue) {
  NS_ENSURE_ARG_POINTER(aContinue);
  *aContinue = false;
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  NS_ENSURE_TRUE(sCallbacks.present && sCallbacks.poll, NS_ERROR_NOT_INITIALIZED);
  const bool trace = mPumpTraces < 8;
  if (trace) ++mPumpTraces;
  const auto traceStage = [&](const char* message) {
    if (trace && sCallbacks.log) sCallbacks.log(sCallbacks.context, message);
  };
  traceStage("Gecko pump: controller poll entered");
  const int32_t oldX = mCursorX, oldY = mCursorY;
  const uint32_t oldButtons = mPointerButtons;
  if (!sCallbacks.poll(sCallbacks.context, &mCursorX, &mCursorY, &mButtons)) {
    return NS_OK;
  }
  mScrollX = mScrollY = 0;
  if (sCallbacks.scroll) sCallbacks.scroll(sCallbacks.context, &mScrollX, &mScrollY);
  NS_ENSURE_TRUE(mScrollX >= -64 && mScrollX <= 64 && mScrollY >= -64 && mScrollY <= 64,
                NS_ERROR_INVALID_ARG);
  if (mKeyboardStatus == 1 && sCallbacks.pollKeyboard) {
    char16_t text[513]{};
    mKeyboardStatus = sCallbacks.pollKeyboard(sCallbacks.context, text, 513);
    NS_ENSURE_TRUE(mKeyboardStatus >= 1 && mKeyboardStatus <= 4, NS_ERROR_UNEXPECTED);
    if (mKeyboardStatus == 2) {
      size_t length = 0;
      while (length < 513 && text[length]) ++length;
      NS_ENSURE_TRUE(length <= 512, NS_ERROR_INVALID_ARG);
      mKeyboardText.Assign(text, length);
    }
  }
  // System dialog owns display/input. Keep status polling alive but do not
  // submit application VideoOut frames or pointer events over the native IME.
  if (mKeyboardStatus == 1) {
    if (!mIMEQuiesced && sCallbacks.log) sCallbacks.log(sCallbacks.context, "Native IME: application pointer/presentation paused; real system dialog owns display");
    mIMEQuiesced = true; *aContinue = true; return NS_OK;
  }
  if (mIMEQuiesced && sCallbacks.log) sCallbacks.log(sCallbacks.context, "Native IME: application presentation resumed after terminal result");
  mIMEQuiesced = false;
  traceStage("Gecko pump: controller poll returned; input synthesis entered");
  NS_ENSURE_TRUE(mCursorX >= 0 && mCursorX < 1280 && mCursorY >= 0 &&
                mCursorY < 720, NS_ERROR_INVALID_ARG);
  // The callback normalizes controller controls: bit 0 is the primary button,
  // bit 1 requests fixture reload. Use Gecko's real headless input dispatch.
  nsCOMPtr<nsIWidget> widget = mWidget;
  const bool controllerIntent = (mButtons & 8190) != 0;
  // Publish edge snapshot before dispatch, which may change pointer ownership.
  mPointerButtons = mButtons;
  if (widget && mPointerEnabled && controllerIntent && mMouseDown) {
    mMouseDown = false;
    MOZ_TRY(widget->SynthesizeNativeMouseEvent(LayoutDeviceIntPoint(mCursorX, mCursorY),
        nsIWidget::NativeMouseMessage::ButtonUp, MouseButton::ePrimary,
        nsIWidget::NativeModifiers::NO_MODIFIERS, nullptr));
  }
  if(widget && mPointerEnabled && controllerIntent && mMiddleDown) {
    mMiddleDown=false;
    MOZ_TRY(widget->SynthesizeNativeMouseEvent(LayoutDeviceIntPoint(mCursorX,mCursorY),
        nsIWidget::NativeMouseMessage::ButtonUp,MouseButton::eMiddle,
        nsIWidget::NativeModifiers::NO_MODIFIERS,nullptr));
  }
  bool replayedPointer = false;
  if (sCallbacks.pointerEvent) {
    for (unsigned i = 0; i < 16; ++i) {
      int32_t x = 0, y = 0; bool down = false;uint32_t button=0;
      if (!sCallbacks.pointerEvent(sCallbacks.context, &x, &y, &down,&button)) break;
      NS_ENSURE_TRUE(x >= 0 && x < 1280 && y >= 0 && y < 720 && (button==1||button==8192), NS_ERROR_INVALID_ARG);
      bool& held=button==1?mMouseDown:mMiddleDown;
      if (!widget || !mPointerEnabled || controllerIntent || down == held) continue;
      const LayoutDeviceIntPoint edgePoint(x, y);
      MOZ_TRY(widget->SynthesizeNativeMouseEvent(edgePoint, nsIWidget::NativeMouseMessage::Move,
          MouseButton::eNotPressed, nsIWidget::NativeModifiers::NO_MODIFIERS, nullptr));
      if (!mPointerEnabled) continue;
      replayedPointer = true;
      held = down;
      MOZ_TRY(widget->SynthesizeNativeMouseEvent(edgePoint,
          down ? nsIWidget::NativeMouseMessage::ButtonDown : nsIWidget::NativeMouseMessage::ButtonUp,
          button==1?MouseButton::ePrimary:MouseButton::eMiddle, nsIWidget::NativeModifiers::NO_MODIFIERS, nullptr));
    }
  }
  if (widget && mPointerEnabled && !controllerIntent) {
    const LayoutDeviceIntPoint point(mCursorX, mCursorY);
    const auto mods = nsIWidget::NativeModifiers::NO_MODIFIERS;
    if (oldX != mCursorX || oldY != mCursorY || replayedPointer) {
      MOZ_TRY(widget->SynthesizeNativeMouseEvent(point, nsIWidget::NativeMouseMessage::Move,
                  MouseButton::eNotPressed, mods, nullptr));
    }
    if (mPointerEnabled && (sCallbacks.pointerEvent ? (bool(mButtons & 1) != mMouseDown) : bool((oldButtons ^ mButtons) & 1)) && ((mButtons & 1) || mMouseDown)) {
      const bool down = (mButtons & 1) != 0;
      mMouseDown = down;
      MOZ_TRY(widget->SynthesizeNativeMouseEvent(point,
                  down ? nsIWidget::NativeMouseMessage::ButtonDown : nsIWidget::NativeMouseMessage::ButtonUp,
                  MouseButton::ePrimary, mods, nullptr));
    }
    if(mPointerEnabled && (sCallbacks.pointerEvent ? (bool(mButtons&8192)!=mMiddleDown) : bool((oldButtons^mButtons)&8192)) && ((mButtons&8192)||mMiddleDown)) {
      mMiddleDown=(mButtons&8192)!=0;
      MOZ_TRY(widget->SynthesizeNativeMouseEvent(point,
          mMiddleDown?nsIWidget::NativeMouseMessage::ButtonDown:nsIWidget::NativeMouseMessage::ButtonUp,
          MouseButton::eMiddle,mods,nullptr));
    }
  }
  traceStage("Gecko pump: input synthesis returned; frame mailbox entered");
  uint64_t sequence = 0;
  RefPtr<gfx::DataSourceSurface> surface = OrbisCompositorWidget::GetLatestFrame(&sequence);
  traceStage(surface ? "Gecko pump: frame mailbox returned a surface" :
                       "Gecko pump: frame mailbox returned no surface");
  if (surface && sequence != mLastSequence) {
    const auto size = surface->GetSize();
    NS_ENSURE_TRUE(size.width > 0 && size.height > 0 && size.width <= 1280 &&
                  size.height <= 720 && surface->GetFormat() == gfx::SurfaceFormat::B8G8R8A8,
                  NS_ERROR_UNEXPECTED);
    traceStage("Gecko pump: surface mapping entered");
    gfx::DataSourceSurface::ScopedMap map(surface, gfx::DataSourceSurface::READ);
    traceStage("Gecko pump: surface mapping returned");
    NS_ENSURE_TRUE(map.IsMapped() && map.GetData() && map.GetStride() >= size.width * 4 &&
                  map.GetStride() <= 8192, NS_ERROR_UNEXPECTED);
    traceStage("Gecko pump: native presentation entered");
    const bool presented = sCallbacks.present(sCallbacks.context, map.GetData(), size.width,
                                              size.height, map.GetStride());
    traceStage("Gecko pump: native presentation returned");
    NS_ENSURE_TRUE(presented, NS_ERROR_FAILURE);
    mLastSequence = sequence;
    ++mFramesPresented;
  }
  *aContinue = true;
  traceStage("Gecko pump: completed");
  return NS_OK;
}

NS_IMETHODIMP OrbisFoxHost::CloseBrowser() {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  nsresult rv = NS_OK;
  MOZ_TRY(CancelAddressKeyboard());
  mScrollX = mScrollY = 0;
  mWidget = nullptr;
  if (mBrowser) {
    rv = mBrowser->Close();
    mBrowser = nullptr;
  }
  OrbisCompositorWidget::DiscardFrames();
  return rv;
}
NS_IMETHODIMP OrbisFoxHost::FixtureCheckpoint(uint32_t aPassed) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  NS_ENSURE_TRUE(aPassed <= 8, NS_ERROR_INVALID_ARG);
  if (sCallbacks.checkpoint) sCallbacks.checkpoint(sCallbacks.context, aPassed);
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::Log(const nsACString& aMessage) {
  NS_ENSURE_TRUE(NS_IsMainThread(), NS_ERROR_NOT_SAME_THREAD);
  NS_ENSURE_TRUE(aMessage.Length() <= 4096, NS_ERROR_INVALID_ARG);
  if (sCallbacks.log) {
    nsAutoCString message(aMessage);
    sCallbacks.log(sCallbacks.context, message.get());
  }
  return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetCursorX(int32_t* aValue) {
  NS_ENSURE_ARG_POINTER(aValue); *aValue = mCursorX; return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetCursorY(int32_t* aValue) {
  NS_ENSURE_ARG_POINTER(aValue); *aValue = mCursorY; return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetButtons(uint32_t* aValue) {
  NS_ENSURE_ARG_POINTER(aValue); *aValue = mButtons; return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetFramesPresented(uint64_t* aValue) {
  NS_ENSURE_ARG_POINTER(aValue); *aValue = mFramesPresented; return NS_OK;
}
NS_IMETHODIMP OrbisFoxHost::GetSoftwareWebRender(bool* aValue) {
  NS_ENSURE_ARG_POINTER(aValue);
  *aValue = gfx::gfxVars::UseSoftwareWebRender();
  return NS_OK;
}
}  // namespace mozilla::widget
