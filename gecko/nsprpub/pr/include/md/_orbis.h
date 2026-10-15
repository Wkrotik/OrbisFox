/* OrbisFox native pthread/POSIX NSPR definitions. Licensed under MPL-2.0. */
#ifndef nspr_orbis_defs_h
#define nspr_orbis_defs_h
#include "prthread.h"
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/uio.h>

// BSD socket-availability request, using the SDK's native IOC encoding.
// Do not substitute LINUX_FIONREAD (0x541b). Firmware behavior is not yet tested.
#ifndef FIONREAD
#  define FIONREAD _IOR('f', 127, int)
#endif

#ifndef _PR_PTHREADS
#  error "Orbis NSPR requires native pthreads; user-space BSD context switching is unsupported"
#endif

#define PR_LINKER_ARCH "orbis"
#define _PR_SI_SYSNAME "ORBIS"
#define _PR_SI_ARCHITECTURE "amd64"
#define PR_DLL_SUFFIX ".so"
#define _PR_VMBASE 0x30000000
#define _PR_STACK_VMBASE 0x50000000
#define _MD_DEFAULT_STACK_SIZE 65536L
#define _MD_MMAP_FLAGS MAP_PRIVATE
#undef HAVE_STACK_GROWING_UP

// The application contains real statically linked Gecko/NSS libraries.
// OpenOrbis dlopen() is unavailable; never claim desktop DLL support.
#undef HAVE_DLL
#undef USE_DLFCN
#define _PR_ORBIS_STATIC_LINKER 1
#define _PR_HAVE_SOCKADDR_LEN
#define _PR_HAVE_LARGE_OFF_T
#define _PR_STAT_HAS_ST_ATIM
#define _PR_POLL_AVAILABLE
#define _PR_INET6
#define _PR_HAVE_INET_NTOP
#define _PR_HAVE_GETADDRINFO
#define _PR_HAVE_GETHOSTBYNAME2
#define _PR_INET6_PROBE
#define _PR_IPV6_V6ONLY_PROBE
#define _PR_HAVE_CLOCK_MONOTONIC
#define USE_SETJMP

// SDK stat exposes st_atim/st_mtim, not FreeBSD's st_atimespec/st_mtimespec.
// No SysV semaphore/shared-memory capability is claimed for Orbis.
extern void _MD_EarlyInit(void);
#define _MD_EARLY_INIT _MD_EarlyInit
#define _MD_FINAL_INIT _PR_UnixInit

// Use the firmware-bound POSIX entry points. Never assume FreeBSD syscall IDs.
#define _MD_SELECT(nfds, r, w, e, tv) select(nfds, r, w, e, tv)
#define _MD_POLL(fds, nfds, timeout) poll(fds, nfds, timeout)
#ifndef INADDR_LOOPBACK
#  define INADDR_LOOPBACK ((unsigned long)0x7F000001)
#endif
#endif
