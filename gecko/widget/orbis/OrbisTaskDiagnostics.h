#ifndef ORBISFOX_TASK_DIAGNOSTICS_H
#define ORBISFOX_TASK_DIAGNOSTICS_H
#include <stdint.h>
#include "nsCOMPtr.h"
class nsIRunnable;
namespace mozilla::widget {
struct OrbisTaskDiagnostics {
  uint64_t activeStart=0,events=0,longEvents=0,lastMicros=0,maxMicros=0;
  uint64_t lastDetailedMicros=0;unsigned depth=0;char lastLongName[80]{},lastDetailedName[80]{};
};
// Observational only. No nested event pumping, task cancellation or dispatch
// policy changes. Durations include nested event loops, if a runnable spins one.
class OrbisMainTaskSpan {
  // RunnableTask clears its own reference before this span is destroyed.
  // Own the runnable through post-Run name lookup; never keep a borrowed root.
  nsCOMPtr<nsIRunnable> task_;uint64_t start_=0;bool tracked_=false,detailed_=false;
  OrbisMainTaskSpan(const OrbisMainTaskSpan&)=delete;
  OrbisMainTaskSpan& operator=(const OrbisMainTaskSpan&)=delete;
 public:
  explicit OrbisMainTaskSpan(nsIRunnable* task,bool detailed=false);
  ~OrbisMainTaskSpan();
};
OrbisTaskDiagnostics GetOrbisTaskDiagnostics();
// Software compositor cost per published frame (issue #2), recorded on the
// compositor thread by OrbisCompositorWidget. "draw" is the time between
// handing SWGL the draw target and its EndRemoteDrawing (WebRender's software
// raster/composite of that frame); "flush" and "snapshot" are the DrawTarget
// Flush and Snapshot+GetDataSurface that follow. Observational only.
struct OrbisCompositorTiming {
  uint64_t frames=0,cancelled=0,drawMicros=0,maxDrawMicros=0,flushMicros=0,snapshotMicros=0,maxSnapshotMicros=0;
};
OrbisCompositorTiming GetOrbisCompositorTiming();
}
#endif
