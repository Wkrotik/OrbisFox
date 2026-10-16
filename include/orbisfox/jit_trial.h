#pragma once
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
// Console evidence for issue #1. Both helpers are pure policy over injected
// callbacks so the host suite can exercise them; native_jit.cpp supplies the
// real libkernel/file operations.

// Which maximum protections does sceKernelJitCreateSharedMemory accept? Each
// attempt only creates and closes a one-page shared-code object: nothing is
// mapped, written or executed. Result order: RWX, RX, RW, R.
struct JitCreateSurvey {int32_t rc[4]{};int closeFailures=0;};
constexpr int jitSurveyProtections[4]={7,5,3,1};
inline JitCreateSurvey survey_jit_create(int32_t (*create)(void*,size_t,int,int*),int32_t (*close)(void*,int),void* user,size_t bytes){
  JitCreateSurvey result;
  for(int i=0;i<4;++i){
    int fd=-1;result.rc[i]=create(user,bytes,jitSurveyProtections[i],&fd);
    if(result.rc[i]==0&&fd>=0&&close(user,fd)!=0)++result.closeFailures;
  }
  return result;
}

// Opt-in, evidence-only trial of the existing own-code execution gate on
// anonymous W^X memory (mmap RW, mprotect RX; never RWX). The arena is
// released afterwards; SpiderMonkey's JIT is not enabled by a pass. Executing
// from such a page may fault on firmware that forbids it, so the trial is
// crash-safe: a durable pending marker is written first and removed only
// after the gate returned and the arena was released.
// A pending marker found at startup means the previous trial never returned;
// the request is then withdrawn so the console does not crash-loop.
constexpr const char* jitTrialRequest="/data/orbisfox/probe-anonymous-jit";
constexpr const char* jitTrialPending="/data/orbisfox/probe-anonymous-jit.pending";
enum class JitTrialDecision {notRequested,run,previousAttemptCrashed,markerUnwritable};
struct JitTrialFiles {
  void* user=nullptr;
  bool (*exists)(void*,const char*)=nullptr;
  bool (*createDurable)(void*,const char*)=nullptr; // create + fsync; false on any failure
  bool (*remove)(void*,const char*)=nullptr;
};
inline JitTrialDecision decide_jit_trial(const JitTrialFiles& files){
  if(files.exists(files.user,jitTrialPending)){
    // Keep the pending marker unless the request is really gone; otherwise
    // the next boot would see no pending marker and fault again.
    if(files.remove(files.user,jitTrialRequest))files.remove(files.user,jitTrialPending);
    return JitTrialDecision::previousAttemptCrashed;
  }
  if(!files.exists(files.user,jitTrialRequest))return JitTrialDecision::notRequested;
  // Without a durable pending marker a fault could not be detected next boot.
  if(!files.createDurable(files.user,jitTrialPending))return JitTrialDecision::markerUnwritable;
  return JitTrialDecision::run;
}
// Call only after the gate returned (pass or honest failure).
inline void finish_jit_trial(const JitTrialFiles& files){files.remove(files.user,jitTrialPending);}
inline const char* jit_trial_decision_name(JitTrialDecision decision){
  switch(decision){
    case JitTrialDecision::notRequested:return "not-requested";
    case JitTrialDecision::run:return "run";
    case JitTrialDecision::previousAttemptCrashed:return "previous-attempt-did-not-return";
    case JitTrialDecision::markerUnwritable:return "pending-marker-unwritable";
  }
  return "unknown";
}
}
