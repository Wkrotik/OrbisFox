#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Small vendor-gated standalone SpiderMonkey platform adaptations."""
from pathlib import Path
import sys


def patch(root):
    updates = {
        'js/src/threading/posix/ThreadPlatformData.h': [
            ('#if defined(__DragonFly__) || defined(__FreeBSD__) || defined(__OpenBSD__)',
             '#if (defined(__DragonFly__) || defined(__FreeBSD__) || defined(__OpenBSD__)) && !defined(__ORBIS__)')],
        'js/src/util/NativeStack.cpp': [
            ('#  if defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__DragonFly__)',
             '#  if (defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__DragonFly__)) && !defined(__ORBIS__)')],
        'mozglue/baseprofiler/core/ProfilerUtils.cpp': [
            ('#  elif defined(XP_FREEBSD)', '''#  elif defined(__ORBIS__)
#    include <orbis/libkernel.h>
namespace mozilla::baseprofiler {
BaseProfilerThreadId profiler_current_thread_id() {
  const int32_t id = scePthreadGetthreadid();
  if (id < 0) return BaseProfilerThreadId{};
  return BaseProfilerThreadId::FromNativeId(
      static_cast<BaseProfilerThreadId::NativeType>(id));
}
}  // namespace mozilla::baseprofiler
#  elif defined(XP_FREEBSD)''')],
        'mozglue/misc/TimeStamp_posix.cpp': [
            ('#if defined(__DragonFly__) || defined(__FreeBSD__) || defined(__NetBSD__) || \\\n    defined(__OpenBSD__)',
             '#if (defined(__DragonFly__) || defined(__FreeBSD__) || defined(__NetBSD__) || \\\n    defined(__OpenBSD__)) && !defined(__ORBIS__)'),
            ('#if defined(__DragonFly__) || defined(__FreeBSD__)\n',
             '#if (defined(__DragonFly__) || defined(__FreeBSD__)) && !defined(__ORBIS__)\n'),
            ('#include <time.h>', '#include <time.h>\n#ifdef __ORBIS__\n#  include <orbis/libkernel.h>\n#endif'),
            ('#elif defined(__DragonFly__) || defined(__FreeBSD__) || defined(__NetBSD__) || \\\n    defined(__OpenBSD__)',
             '#elif defined(__ORBIS__)\nuint64_t TimeStamp::ComputeProcessUptime() { return sceKernelGetProcessTime(); }\n#elif defined(__DragonFly__) || defined(__FreeBSD__) || defined(__NetBSD__) || \\\n    defined(__OpenBSD__)')],
        'mozglue/misc/Mutex_posix.cpp': [
            ('#elif (defined(__linux__) && defined(__GLIBC__)) || defined(__FreeBSD__)',
             '#elif defined(__ORBIS__)\n#  define MUTEX_KIND PTHREAD_MUTEX_NORMAL\n#elif (defined(__linux__) && defined(__GLIBC__)) || defined(__FreeBSD__)')],
        'mfbt/RandomNum.cpp': [
            ('#  define USE_ARC4RANDOM', '#  if !defined(__ORBIS__)\n#    define USE_ARC4RANDOM\n#  endif')],
        'js/src/threading/posix/PosixThread.cpp': [
            ('#ifdef HAVE_PTHREAD_GETNAME_NP',
             '#if defined(HAVE_PTHREAD_GETNAME_NP) && !defined(__ORBIS__)')],
    }
    # SDK pthread.h already declares its nonportable stack APIs. Thread-name
    # retrieval is optional: keep the existing empty-name fallback rather than
    # invoking a firmware-only ABI that hasn't been verified.
    for relative, edits in updates.items():
        file = root / relative
        text = file.read_text()
        for old, new in edits:
            if new in text:
                continue
            if text.count(old) != 1:
                raise RuntimeError(f'Unexpected Gecko platform source: {relative}')
            text = text.replace(old, new)
        if file.read_text() != text:
            file.write_text(text)


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
