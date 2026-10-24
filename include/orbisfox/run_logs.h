#pragma once
#include <stddef.h>
namespace orbisfox {
bool initialize_native_run_logs();
bool native_diagnostics_enabled();
bool set_native_diagnostics_enabled(bool enabled);
unsigned long long native_diagnostics_generation();
bool copy_native_run_log_path(char* output,size_t capacity,const char* name);
const char* native_run_log_directory();
bool native_write_heap_audit(const char* text,size_t size);
struct AllocatorFlightEvent;
// Called with the existing allocator mutex held; native file APIs only.
bool native_write_allocator_flight(const AllocatorFlightEvent* events,size_t count,
                                  unsigned long long generation,bool force);
// Log paths only; never move profile, databases, cache or diagnostic markers.
inline bool make_run_log_path(char* output,size_t capacity,const char* directory,const char* name){
  if(!output || !capacity || !directory || !*directory || !name || !*name)return false;
  if(name[0]=='.' && (!name[1] || (name[1]=='.' && !name[2])))return false;
  for(const char* p=name;*p;++p)if(!((*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||*p=='.'||*p=='-'||*p=='_'))return false;
  size_t n=0;
  for(const char* p=directory;*p;++p){if(n+1>=capacity)return false;output[n++]=*p;}
  if(n+1>=capacity)return false;output[n++]='/';
  for(const char* p=name;*p;++p){if(n+1>=capacity)return false;output[n++]=*p;}
  output[n]=0;return true;
}
class NativeRunLogPath {
  char path_[256]{};
 public:
  explicit NativeRunLogPath(const char* name){if(!copy_native_run_log_path(path_,sizeof(path_),name))__builtin_trap();}
  const char* c_str() const {return path_;}
};
}
