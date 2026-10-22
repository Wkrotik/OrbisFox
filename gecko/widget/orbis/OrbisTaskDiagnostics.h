#ifndef ORBISFOX_TASK_DIAGNOSTICS_H
#define ORBISFOX_TASK_DIAGNOSTICS_H
#include <stdint.h>
#include "nsCOMPtr.h"
class nsIRunnable;
namespace mozilla::widget {
struct OrbisCompletedTask {
  uint64_t serial=0,ended=0,micros=0;unsigned depth=0;bool detailed=false;char name[80]{};
};
struct OrbisTaskDiagnostics {
  uint64_t activeStart=0,events=0,longEvents=0,lastMicros=0,maxMicros=0;
  uint64_t lastDetailedMicros=0;unsigned depth=0;char lastLongName[80]{},lastDetailedName[80]{};
  // Chronological, bounded history of >=250 ms completions. Nested times overlap.
  uint64_t completedSerial=0;unsigned completedCount=0;OrbisCompletedTask completed[16]{};
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
// Inclusive, approximate phase samples; zero means idle/disabled. No page data.
enum class OrbisPumpPhase : unsigned { Idle, Poll, Input, Mailbox, Map, Present, Count };
struct OrbisPumpDiagnostics {
 unsigned phase=0;uint64_t activeStart=0;
 uint64_t lastMicros[unsigned(OrbisPumpPhase::Count)]{},maxMicros[unsigned(OrbisPumpPhase::Count)]{};
};
class OrbisPumpSpan {
 bool tracked_=false;unsigned phase_=0,previousPhase_=0;uint64_t start_=0,previousStart_=0;
 OrbisPumpSpan(const OrbisPumpSpan&)=delete;
 OrbisPumpSpan& operator=(const OrbisPumpSpan&)=delete;
 public:
 explicit OrbisPumpSpan(bool enabled);
 ~OrbisPumpSpan();
 void SetPhase(OrbisPumpPhase phase);
};
OrbisPumpDiagnostics GetOrbisPumpDiagnostics();
}
#endif
