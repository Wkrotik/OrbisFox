#include "OrbisTaskDiagnostics.h"
#include "nsIRunnable.h"
#include "nsINamed.h"
#include "nsCOMPtr.h"
#include "nsString.h"
#include "nsThreadUtils.h"
#include <atomic>
#include <pthread.h>
#include <string.h>
extern "C" uint64_t sceKernelGetProcessTime();
namespace mozilla::widget {
namespace {
std::atomic<uint64_t> activeStart{0},events{0},longEvents{0},lastMicros{0},maxMicros{0};
std::atomic<unsigned> activeDepth{0};
uint64_t stack[64]{};unsigned depth=0;char lastName[80]{},lastDetailedName[80]{};uint64_t lastDetailedMicros=0;
OrbisCompletedTask completed[16]{};uint64_t completedSerial=0;
pthread_mutex_t nameMutex=PTHREAD_MUTEX_INITIALIZER;
struct NameLock {NameLock(){if(pthread_mutex_lock(&nameMutex))__builtin_trap();}~NameLock(){if(pthread_mutex_unlock(&nameMutex))__builtin_trap();}};
}
OrbisMainTaskSpan::OrbisMainTaskSpan(nsIRunnable* task,bool detailed):task_(task),detailed_(detailed){
 if(!NS_IsMainThread() || depth==64)return;
 start_=sceKernelGetProcessTime();stack[depth++]=start_;tracked_=true;
 activeStart.store(start_);activeDepth.store(depth);
}
OrbisMainTaskSpan::~OrbisMainTaskSpan(){
 if(!tracked_)return;
 const uint64_t now=sceKernelGetProcessTime(),elapsed=now>=start_?now-start_:0;
 --depth;activeStart.store(depth?stack[depth-1]:0);activeDepth.store(depth);
 ++events;lastMicros.store(elapsed);if(elapsed>maxMicros.load())maxMicros.store(elapsed);
 if(elapsed<250000)return;
 ++longEvents;
 // Name retrieval happens after the task, without holding the diagnostic lock.
 // This span owns its reference even if RunnableTask already cleared its own.
 nsAutoCString name;nsCOMPtr<nsINamed> named=do_QueryInterface(task_);
 if(!named || NS_FAILED(named->GetName(name)))name.AssignLiteral("unnamed-Gecko-task");
 NameLock lock;unsigned n=0;
 for(const char* p=name.BeginReading();p!=name.EndReading();++p){char c=*p;if(n==sizeof(lastName)-1)break;lastName[n++]=c>=32&&c<=126?c:'?';}
 lastName[n]=0;
 if(detailed_){memcpy(lastDetailedName,lastName,sizeof(lastName));lastDetailedMicros=elapsed;}
 const uint64_t serial=++completedSerial;auto& record=completed[(serial-1)%16];
 record.serial=serial;record.ended=now;record.micros=elapsed;record.depth=depth+1;record.detailed=detailed_;
 memcpy(record.name,lastName,sizeof(lastName));
}
OrbisTaskDiagnostics GetOrbisTaskDiagnostics(){
 OrbisTaskDiagnostics result;
 result.activeStart=activeStart.load();result.depth=activeDepth.load();result.events=events.load();result.longEvents=longEvents.load();
 result.lastMicros=lastMicros.load();result.maxMicros=maxMicros.load();
 {NameLock lock;memcpy(result.lastLongName,lastName,sizeof(lastName));memcpy(result.lastDetailedName,lastDetailedName,sizeof(lastDetailedName));result.lastDetailedMicros=lastDetailedMicros;
  result.completedSerial=completedSerial;result.completedCount=completedSerial<16?unsigned(completedSerial):16;
  const uint64_t first=completedSerial-result.completedCount;
  for(unsigned i=0;i<result.completedCount;++i)result.completed[i]=completed[(first+i)%16];
 }return result;
}
}
