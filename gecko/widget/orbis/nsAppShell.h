/* OrbisFox native event bridge. Licensed under MPL-2.0. */
#ifndef orbis_nsAppShell_h
#define orbis_nsAppShell_h

#include "mozilla/Monitor.h"
#include "nsBaseAppShell.h"

// No GTK, X11, Wayland or Sony SDK event-loop dependency. The embedding pumps
// XPCOM from its owner thread; worker posts wake a blocking native-event wait.
class nsAppShell final : public nsBaseAppShell {
 public:
  nsAppShell() : mWake("OrbisFox::nsAppShell") {}
  nsresult Init();

 protected:
  ~nsAppShell() override;
  void ScheduleNativeEventCallback() override;
  bool ProcessNextNativeEvent(bool aMayWait) override;

 private:
  mozilla::Monitor mWake;
  bool mHalInitialized = false;
  bool mPending = false;  // guarded by mWake; coalesced, never a message count
};
#endif
