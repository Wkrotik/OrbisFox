#include "orbisfox/run_logs.h"
#include <orbis/libkernel.h>
#include <fcntl.h>
#include <stdint.h>
#include <atomic>
namespace {
char directory[128];int heapAuditFD=-1;
std::atomic<bool> enabled{false};std::atomic<unsigned long long> generation{0};
std::atomic_flag busy=ATOMIC_FLAG_INIT;
struct Lock {Lock(){while(busy.test_and_set(std::memory_order_acquire))__asm__ volatile("pause");}~Lock(){busy.clear(std::memory_order_release);}};
constexpr char marker[]="/data/orbisfox/diagnostics.enabled";
bool existsError(int rc){return rc==-17 || (static_cast<uint32_t>(rc)&0xffff)==17;}
struct Text {
  char bytes[768]{};size_t n=0;bool okay=true;
  void append(const char* p){while(*p){if(n+1>=sizeof(bytes)){okay=false;return;}bytes[n++]=*p++;}bytes[n]=0;}
  void hex(uint64_t x){char s[17];for(unsigned i=0;i<16;++i)s[i]="0123456789abcdef"[(x>>((15-i)*4))&15];s[16]=0;append(s);}
};
bool save(const char* path,const char* bytes,size_t n,bool exclusive){
  int fd=sceKernelOpen(path,O_WRONLY|O_CREAT|(exclusive?O_EXCL:O_TRUNC),0600);if(fd<0)return false;
  bool okay=true;size_t done=0;
  while(done<n){const intptr_t rc=static_cast<intptr_t>(sceKernelWrite(fd,bytes+done,n-done));if(rc<=0||size_t(rc)>n-done){okay=false;break;}done+=size_t(rc);}
  if(sceKernelFsync(fd)<0)okay=false;
  if(sceKernelClose(fd)<0)okay=false;return okay;
}
void stop(){enabled.store(false);if(heapAuditFD>=0){sceKernelClose(heapAuditFD);heapAuditFD=-1;}++generation;}
bool begin(){
  stop();
  int rc=sceKernelMkdir("/data/orbisfox",0700);if(rc<0&&!existsError(rc))return false;
  rc=sceKernelMkdir("/data/orbisfox/runs",0700);if(rc<0&&!existsError(rc))return false;
  OrbisKernelTimeval wall{};const int clockRc=sceKernelGettimeofday(&wall);
  const uint64_t process=sceKernelGetProcessTime();Text id;bool created=false;
  for(unsigned nonce=0;nonce<64;++nonce){
    id={};id.append("run-");id.hex(static_cast<uint64_t>(wall.tv_sec));id.append("-");id.hex(static_cast<uint64_t>(wall.tv_usec));id.append("-");id.hex(process);id.append("-");id.hex(nonce);
    Text path;path.append("/data/orbisfox/runs/");path.append(id.bytes);if(!path.okay||path.n>=sizeof(directory))return false;
    rc=sceKernelMkdir(path.bytes,0700);
    if(rc==0){for(size_t i=0;i<=path.n;++i)directory[i]=path.bytes[i];created=true;break;}
    if(!existsError(rc))return false;
  }
  if(!created)return false;
  Text metadata;metadata.append("{\"version\":\"0.68\",\"category\":\"gd\",\"diagnostics\":true,\"run_id\":\"");metadata.append(id.bytes);
  metadata.append("\",\"wall_seconds_hex\":\"");metadata.hex(static_cast<uint64_t>(wall.tv_sec));metadata.append("\",\"wall_usec_hex\":\"");metadata.hex(static_cast<uint64_t>(wall.tv_usec));
  metadata.append("\",\"process_usec_hex\":\"");metadata.hex(process);metadata.append("\",\"native_clock_ok\":");metadata.append(clockRc==0?"true":"false");metadata.append("}\n");
  char path[256];if(!orbisfox::make_run_log_path(path,sizeof(path),directory,"run-meta.json")||!metadata.okay||!save(path,metadata.bytes,metadata.n,true))return false;
  id.append("\n");if(!save("/data/orbisfox/run-id.next",id.bytes,id.n,false))return false;
  if(sceKernelRename("/data/orbisfox/run-id.next","/data/orbisfox/run-id.txt")<0)return false;
  if(!orbisfox::make_run_log_path(path,sizeof(path),directory,"heap-audit.log"))return false;
  heapAuditFD=sceKernelOpen(path,O_WRONLY|O_CREAT|O_EXCL,0600);if(heapAuditFD<0)return false;
  enabled.store(true);++generation;return true;
}
}
namespace orbisfox {
bool native_diagnostics_enabled(){return enabled.load();}
unsigned long long native_diagnostics_generation(){return generation.load();}
const char* native_run_log_directory(){return directory;} // Startup/main-thread metadata only.
bool copy_native_run_log_path(char* out,size_t capacity,const char* name){
  Lock lock;
  // Still validate the basename when disabled. /dev/null is not diagnostic storage.
  char validated[256];if(!make_run_log_path(validated,sizeof(validated),"/validation",name))return false;
  if(enabled.load())return make_run_log_path(out,capacity,directory,name);
  constexpr char nullPath[]="/dev/null";if(capacity<sizeof(nullPath))return false;
  for(size_t i=0;i<sizeof(nullPath);++i)out[i]=nullPath[i];return true;
}
bool native_write_heap_audit(const char* text,size_t size){
  Lock lock;if(!enabled.load()||heapAuditFD<0)return false;
  size_t written=0;
  while(written<size){const intptr_t rc=static_cast<intptr_t>(sceKernelWrite(heapAuditFD,text+written,size-written));if(rc<=0||size_t(rc)>size-written)return false;written+=size_t(rc);}
  return sceKernelFsync(heapAuditFD)==0;
}
bool initialize_native_run_logs(){
  // Before constructors: native file APIs and constant-initialized atomics only.
  Lock lock;stop();int fd=sceKernelOpen(marker,O_RDONLY,0);if(fd<0)return true;
  char bytes[3]{};const intptr_t n=static_cast<intptr_t>(sceKernelRead(fd,bytes,sizeof(bytes)));const int closed=sceKernelClose(fd);
  if(n!=2||bytes[0]!='1'||bytes[1]!='\n'||closed<0)return true;
  return begin();
}
bool set_native_diagnostics_enabled(bool value){
  Lock lock;if(value==enabled.load())return true;
  if(!value){
    // Persist OFF before reporting success. Do not touch other markers/profile.
    if(!save("/data/orbisfox/diagnostics.next","0\n",2,false)||sceKernelRename("/data/orbisfox/diagnostics.next",marker)<0)return false;
    stop();return true;
  }
  if(!begin())return false;
  if(!save("/data/orbisfox/diagnostics.next","1\n",2,false)||sceKernelRename("/data/orbisfox/diagnostics.next",marker)<0){stop();return false;}
  return true;
}
}
