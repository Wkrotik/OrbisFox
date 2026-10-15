/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#ifndef widget_orbis_OrbisFoxHost_h
#define widget_orbis_OrbisFoxHost_h
#include "nsIOrbisFoxHost.h"
#include "nsIWindowlessBrowser.h"
#include "nsCOMPtr.h"
#include "nsIWidget.h"
#include "nsString.h"

namespace mozilla::widget {
struct OrbisFoxHostCallbacks {
  void* context = nullptr;
  bool (*present)(void*, const uint8_t*, uint32_t, uint32_t, uint32_t) = nullptr;
  bool (*poll)(void*, int32_t*, int32_t*, uint32_t*) = nullptr;
  void (*log)(void*, const char*) = nullptr;
  void (*checkpoint)(void*, uint32_t) = nullptr;
  bool nativeNetworkReady = false;
  void (*requestExit)(void*) = nullptr;
  void (*scroll)(void*, int32_t*, int32_t*) = nullptr;
  bool (*openKeyboard)(void*, const char16_t*, uint32_t, bool) = nullptr;
  uint32_t (*pollKeyboard)(void*, char16_t*, uint32_t) = nullptr;
  void (*cancelKeyboard)(void*) = nullptr;
  uint32_t (*keyboardConfirm)(void*) = nullptr;
  void (*cursorSpeed)(void*, double) = nullptr;
  bool (*chromeState)(void*, const char*) = nullptr;
  bool (*chromeAction)(void*, char*, uint32_t) = nullptr;
  bool (*pointerEvent)(void*, int32_t*, int32_t*, bool*, uint32_t*) = nullptr;
  bool (*diagnosticsEnabled)(void*) = nullptr;
  bool (*diagnostics)(void*, bool, char*, uint32_t) = nullptr;
};
// Install on the application thread before entering XPCShell; clear after it
// has shut down. Callbacks never run on the compositor or input worker threads.
void SetOrbisFoxHostCallbacks(const OrbisFoxHostCallbacks&);
// Diagnostic-only snapshots of independent atomics; safe off the main thread.
// Fields are approximate samples, not a synchronized event-history snapshot.
struct OrbisEventDiagnostics { uint32_t stage; uint64_t schedules; uint64_t callbacks; };
OrbisEventDiagnostics GetOrbisEventDiagnostics();

class OrbisFoxHost final : public nsIOrbisFoxHost {
 public:
  NS_DECL_ISUPPORTS
  NS_DECL_NSIORBISFOXHOST
 private:
  ~OrbisFoxHost() = default;
  nsresult Create(uint32_t, uint32_t, bool, nsIWindowlessBrowser**);
  nsresult OpenKeyboard(const nsAString&, bool, bool*);
  bool mPointerEnabled = true, mMouseDown = false, mMiddleDown = false, mIMEQuiesced = false;
  uint32_t mPointerButtons = 0;
  nsCOMPtr<nsIWindowlessBrowser> mBrowser;
  nsCOMPtr<nsIWidget> mWidget;
  int32_t mCursorX = 640, mCursorY = 360;
  uint32_t mButtons = 0, mKeyboardStatus = 0;
  int32_t mScrollX = 0, mScrollY = 0;
  nsString mKeyboardText;
  uint64_t mLastSequence = 0, mFramesPresented = 0;
  uint32_t mPumpTraces = 0;
};
}  // namespace mozilla::widget
#endif
