// Host test for the issue #1 evidence helpers: create-protection survey and
// the crash-safe anonymous W^X trial markers. Pure policy; no executable memory.
#include "orbisfox/jit_trial.h"
#include <cassert>
#include <cstring>
#include <set>
#include <string>
#include <vector>
using namespace orbisfox;
struct FakeKernel {std::vector<int> requested;std::set<int> allowed;int nextFd=10;std::vector<int> closed;bool closeFails=false;};
struct FakeFiles {std::set<std::string> present;bool writable=true;std::set<std::string> undeletable;std::vector<std::string> log;};
static JitTrialFiles files(FakeFiles& fake){
  JitTrialFiles result;result.user=&fake;
  result.exists=[](void* p,const char* path){return static_cast<FakeFiles*>(p)->present.count(path)!=0;};
  result.createDurable=[](void* p,const char* path){auto& f=*static_cast<FakeFiles*>(p);if(!f.writable)return false;f.present.insert(path);f.log.push_back(std::string("create ")+path);return true;};
  result.remove=[](void* p,const char* path){auto& f=*static_cast<FakeFiles*>(p);if(f.undeletable.count(path))return false;f.present.erase(path);f.log.push_back(std::string("remove ")+path);return true;};
  return result;
}
int main(){
  // Survey: exact order RWX, RX, RW, R; only successful creates are closed.
  FakeKernel kernel;kernel.allowed={5,3};
  const auto survey=survey_jit_create(
    [](void* p,size_t bytes,int protection,int* fd)->int32_t{auto& k=*static_cast<FakeKernel*>(p);assert(bytes==16384);k.requested.push_back(protection);
      if(!k.allowed.count(protection))return int32_t(0x80020001u);*fd=k.nextFd++;return 0;},
    [](void* p,int fd)->int32_t{auto& k=*static_cast<FakeKernel*>(p);k.closed.push_back(fd);return k.closeFails?-1:0;},&kernel,16384);
  assert((kernel.requested==std::vector<int>{7,5,3,1}));
  assert(uint32_t(survey.rc[0])==0x80020001u&&survey.rc[1]==0&&survey.rc[2]==0&&uint32_t(survey.rc[3])==0x80020001u);
  assert((kernel.closed==std::vector<int>{10,11}));assert(survey.closeFailures==0);
  kernel.closeFails=true;kernel.closed.clear();
  const auto failing=survey_jit_create([](void* p,size_t,int protection,int* fd)->int32_t{auto& k=*static_cast<FakeKernel*>(p);if(!k.allowed.count(protection))return -1;*fd=k.nextFd++;return 0;},
    [](void* p,int fd)->int32_t{auto& k=*static_cast<FakeKernel*>(p);k.closed.push_back(fd);return k.closeFails?-1:0;},&kernel,16384);
  assert(failing.closeFailures==2);

  // Not requested: nothing written.
  FakeFiles fs;assert(decide_jit_trial(files(fs))==JitTrialDecision::notRequested);assert(fs.log.empty());
  // Requested: durable pending marker is written before the trial may run.
  fs.present.insert(jitTrialRequest);
  assert(decide_jit_trial(files(fs))==JitTrialDecision::run);assert(fs.present.count(jitTrialPending));
  // Gate returned: pending removed, request kept for the next boot.
  finish_jit_trial(files(fs));assert(!fs.present.count(jitTrialPending));assert(fs.present.count(jitTrialRequest));
  // A run that never returned leaves pending; next boot withdraws the request instead of crash-looping.
  assert(decide_jit_trial(files(fs))==JitTrialDecision::run);
  assert(decide_jit_trial(files(fs))==JitTrialDecision::previousAttemptCrashed);
  assert(!fs.present.count(jitTrialRequest)&&!fs.present.count(jitTrialPending));
  assert(decide_jit_trial(files(fs))==JitTrialDecision::notRequested);
  // If the request cannot be withdrawn, the pending marker stays so every
  // later boot keeps refusing instead of faulting on alternate boots.
  FakeFiles stuck;stuck.present={jitTrialRequest,jitTrialPending};stuck.undeletable.insert(jitTrialRequest);
  for(int boot=0;boot<3;++boot){assert(decide_jit_trial(files(stuck))==JitTrialDecision::previousAttemptCrashed);assert(stuck.present.count(jitTrialPending));}
  // Without a durable marker a fault could not be detected: never run.
  FakeFiles readOnly;readOnly.present.insert(jitTrialRequest);readOnly.writable=false;
  assert(decide_jit_trial(files(readOnly))==JitTrialDecision::markerUnwritable);
  assert(!strcmp(jit_trial_decision_name(JitTrialDecision::previousAttemptCrashed),"previous-attempt-did-not-return"));
  return 0;
}
