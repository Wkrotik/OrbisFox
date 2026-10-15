#ifdef ORBISFOX_FULL_GECKO
#include "orbisfox/native_stdio.h"
#include <pthread.h>
#include <atomic>
#include <stdio.h>
#include <stdarg.h>
#include <sys/types.h>
#include <errno.h>
#include <unistd.h>
namespace {
// Do not introduce an unaudited SDK/native pthread_once_t layout boundary.
std::atomic<unsigned> initializationState{0};
std::atomic<uint64_t> entryLocks{0};
pthread_mutex_t mutex{};
int initialization=-1;
void initialize() {
  pthread_mutexattr_t attr{};
  int result=pthread_mutexattr_init(&attr);
  if(result) {initialization=result;return;}
  result=pthread_mutexattr_settype(&attr,PTHREAD_MUTEX_RECURSIVE);
  if(!result) result=pthread_mutex_init(&mutex,&attr);
  const int destroyed=pthread_mutexattr_destroy(&attr);
  initialization=result?result:destroyed;
}
void require(bool okay) {
  if(okay) return;
  // Cannot safely report a failed lock using the stream we're protecting.
  static const char message[]="OrbisFox: genuine stdio mutex operation failed\n";
  write(STDERR_FILENO,message,sizeof(message)-1);
  __builtin_trap();
}
}
namespace orbisfox {
uint64_t native_stdio_entry_lock_count() {return entryLocks.load(std::memory_order_relaxed);}
bool initialize_native_stdio_locks() {
  unsigned expected=0;
  if(initializationState.compare_exchange_strong(expected,1)) {
    initialize();
    initializationState.store(2,std::memory_order_release);
  } else {
    while(initializationState.load(std::memory_order_acquire)==1)
      __asm__ volatile("pause");
  }
  return initialization==0;
}
}
// A single recursive mutex serializes SDK streams without assuming FILE or
// native TCB layouts. SDK FLOCK/FUNLOCK need an int indicating acquired lock.
// Public flock/trylock/unlock use the same ownership domain as buffered calls.
// Never destroy it: SDK/Gecko shutdown may still use streams after XPCOM ends.
namespace {
void acquireStreams() {
  require(orbisfox::initialize_native_stdio_locks());
  require(pthread_mutex_lock(&mutex)==0);
}
void releaseStreams() {require(pthread_mutex_unlock(&mutex)==0);}
}
extern "C" void flockfile(FILE*) {acquireStreams();}
extern "C" int ftrylockfile(FILE*) {
  require(orbisfox::initialize_native_stdio_locks());
  return pthread_mutex_trylock(&mutex);
}
extern "C" void funlockfile(FILE*) {releaseStreams();}
extern "C" int __lockfile(FILE* file) {flockfile(file);return 1;}
extern "C" void __unlockfile(FILE* file) {funlockfile(file);}

namespace {
struct LockedStream {
  explicit LockedStream(FILE*) {acquireStreams();entryLocks.fetch_add(1,std::memory_order_relaxed);}
  ~LockedStream(){releaseStreams();} // No dereference: fclose may free FILE.
};
}
// Native pthread_create does not run musl's libc.threaded bootstrap. __fdopen
// can therefore set FILE.lock=-1 and SDK FLOCK skips __lockfile altogether.
// Protect the public entry points independently of that SDK-private flag.
// --wrap keeps the genuine SDK implementations; no FILE layout or libc flags
// are overwritten, and no musl allocator/thread bootstrap is enabled blindly.
#define WRAPPED(result,name,parameters,arguments,stream) \
  extern "C" result __real_##name parameters; \
  extern "C" result __wrap_##name parameters {LockedStream lock(stream);return __real_##name arguments;}
WRAPPED(int,vfprintf,(FILE* file,const char* format,va_list args),(file,format,args),file)
WRAPPED(int,vprintf,(const char* format,va_list args),(format,args),stdout)
WRAPPED(int,puts,(const char* text),(text),stdout)
WRAPPED(int,putchar,(int value),(value),stdout)
extern "C" int __wrap_fprintf(FILE* file,const char* format,...) {
  LockedStream lock(file);va_list args;va_start(args,format);
  const int result=__real_vfprintf(file,format,args);va_end(args);return result;
}
extern "C" int __wrap_printf(const char* format,...) {
  LockedStream lock(stdout);va_list args;va_start(args,format);
  const int result=__real_vfprintf(stdout,format,args);va_end(args);return result;
}
WRAPPED(size_t,fwrite,(const void* data,size_t size,size_t count,FILE* file),(data,size,count,file),file)
WRAPPED(int,fflush,(FILE* file),(file),file)
WRAPPED(int,fputc,(int value,FILE* file),(value,file),file)
WRAPPED(int,putc,(int value,FILE* file),(value,file),file)
WRAPPED(int,fputs,(const char* text,FILE* file),(text,file),file)
WRAPPED(FILE*,fopen,(const char* path,const char* mode),(path,mode),nullptr)
WRAPPED(FILE*,fdopen,(int fd,const char* mode),(fd,mode),nullptr)
WRAPPED(FILE*,freopen,(const char* path,const char* mode,FILE* file),(path,mode,file),file)
WRAPPED(int,fclose,(FILE* file),(file),file)
WRAPPED(int,setvbuf,(FILE* file,char* buffer,int mode,size_t size),(file,buffer,mode,size),file)
WRAPPED(size_t,fread,(void* data,size_t size,size_t count,FILE* file),(data,size,count,file),file)
WRAPPED(char*,fgets,(char* text,int length,FILE* file),(text,length,file),file)
WRAPPED(int,fgetc,(FILE* file),(file),file)
WRAPPED(int,getc,(FILE* file),(file),file)
WRAPPED(int,ungetc,(int value,FILE* file),(value,file),file)
WRAPPED(int,vfscanf,(FILE* file,const char* format,va_list args),(file,format,args),file)
WRAPPED(int,fseek,(FILE* file,long offset,int whence),(file,offset,whence),file)
WRAPPED(long,ftell,(FILE* file),(file),file)
WRAPPED(int,fseeko,(FILE* file,off_t offset,int whence),(file,offset,whence),file)
WRAPPED(off_t,ftello,(FILE* file),(file),file)
#undef WRAPPED
extern "C" void __real_perror(const char*);
extern "C" void __wrap_perror(const char* message) {
  const int saved=errno;LockedStream lock(stderr);errno=saved;__real_perror(message);
}
extern "C" void __real_setbuf(FILE*,char*);
extern "C" void __wrap_setbuf(FILE* file,char* buffer) {LockedStream lock(file);__real_setbuf(file,buffer);}
extern "C" void __real_rewind(FILE*);
extern "C" void __wrap_rewind(FILE* file) {LockedStream lock(file);__real_rewind(file);}
extern "C" void __real_clearerr(FILE*);
extern "C" void __wrap_clearerr(FILE* file) {LockedStream lock(file);__real_clearerr(file);}
#define STATUS(name) \
  extern "C" int __real_##name(FILE*); \
  extern "C" int __wrap_##name(FILE* file) {LockedStream lock(file);return __real_##name(file);}
STATUS(feof)
STATUS(ferror)
#undef STATUS
#endif
