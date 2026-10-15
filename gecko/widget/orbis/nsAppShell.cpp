/* OrbisFox native event bridge. Licensed under MPL-2.0. */
#include "nsAppShell.h"
#include "OrbisFoxHost.h"
#include "nsThreadUtils.h"
#include "HeadlessScreenHelper.h"
#include "mozilla/UniquePtr.h"
#include "mozilla/Hal.h"
#include "mozilla/Atomics.h"
#include "nsDebug.h"
#include "mozilla/widget/ScreenManager.h"

namespace mozilla::widget {
static mozilla::Atomic<uint32_t, mozilla::Relaxed> sEventStage{0};
static mozilla::Atomic<uint64_t, mozilla::Relaxed> sSchedules{0}, sCallbacks{0};
OrbisEventDiagnostics GetOrbisEventDiagnostics() {
  return {sEventStage, sSchedules, sCallbacks};
}
}  // namespace mozilla::widget

nsAppShell::~nsAppShell() {
  if (mHalInitialized) {
    mozilla::hal::Shutdown();
    printf_stderr("Orbis HAL: shutdown\n");
  }
}

nsresult nsAppShell::Init() {
  MOZ_RELEASE_ASSERT(!mHalInitialized);
  // Like GTK/Windows: initialize the real HAL observers and wake-lock table
  // before any content can acquire audio/video wake locks.
  mozilla::hal::Init();
  mHalInitialized = true;
  printf_stderr("Orbis HAL: initialized wake-lock and platform observers\n");
  nsresult rv = nsBaseAppShell::Init();
  if (NS_FAILED(rv)) {
    return rv;
  }
  mozilla::widget::ScreenManager::GetSingleton().SetHelper(
      mozilla::MakeUnique<mozilla::widget::HeadlessScreenHelper>());
  return NS_OK;
}

void nsAppShell::ScheduleNativeEventCallback() {
  {
    mozilla::MonitorAutoLock lock(mWake);
    mPending = true;
    lock.Notify();
  }
  ++mozilla::widget::sSchedules;
  static mozilla::Atomic<uint32_t, mozilla::Relaxed> traces(0);
  if (traces < 8 && ++traces <= 8)
    printf_stderr("Orbis events: native callback scheduled\n");
}

bool nsAppShell::ProcessNextNativeEvent(bool aMayWait) {
  MOZ_ASSERT(NS_IsMainThread());
  mozilla::widget::sEventStage = 1;
  static uint32_t traces = 0;
  const bool trace = traces < 8;
  if (trace) {
    ++traces;
    printf_stderr("Orbis events: ProcessNextNativeEvent entered mayWait=%d\n", int(aMayWait));
  }
  {
    mozilla::MonitorAutoLock lock(mWake);
    while (!mPending) {
      if (!aMayWait) {
        mozilla::widget::sEventStage = 6;
        return false;
      }
      mozilla::widget::sEventStage = 2;
      lock.Wait();  // predicate loop handles spurious notifications
      mozilla::widget::sEventStage = 3;
    }
    mPending = false;
  }
  // Gecko dispatch may post again; never hold the native monitor across it.
  if (trace) printf_stderr("Orbis events: NativeEventCallback entered\n");
  mozilla::widget::sEventStage = 4;
  NativeEventCallback();
  ++mozilla::widget::sCallbacks;
  mozilla::widget::sEventStage = 5;
  if (trace) printf_stderr("Orbis events: NativeEventCallback returned\n");
  return true;
}
