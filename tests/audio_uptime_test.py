"""Actual patched Gecko Now.cpp with explicit failing BOOTTIME/clock doubles.
Host-only ABI/branch proof, not firmware playback or suspend proof.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
class AudioUptimeTest(unittest.TestCase):
 def test_real_now_source_uses_supported_clock_and_preserves_errors(self):
  source=(ROOT/'.deps/gecko-layout/mozglue/misc/Now.cpp').read_text()
  self.assertIn('#  if defined(__ORBIS__)',source)
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp);(path/'mozilla').mkdir()
   (path/'Now.cpp').write_text(source)
   (path/'Now.h').write_text('#pragma once\n')
   (path/'mozilla/TimeStamp.h').write_text('#pragma once\n')
   (path/'mozilla/Maybe.h').write_text('#pragma once\n#include <optional>\nnamespace mozilla { template<class T> using Maybe=std::optional<T>; template<class T> Maybe<T> Some(T value){return value;} inline std::nullopt_t Nothing(){return std::nullopt;} }\n')
   (path/'test.cpp').write_text('''#include <time.h>
#include <errno.h>
#include <cassert>
static bool fail=false;static int selector=-1;
extern "C" int clock_gettime(clockid_t clock,timespec* ts) noexcept {
 selector=clock;if(fail||clock!=CLOCK_MONOTONIC){errno=EINVAL;return -1;}
 ts->tv_sec=123;ts->tv_nsec=456000000;return 0;
}
#define XP_UNIX 1
#define __ORBIS__ 1
#include "Now.cpp"
int main(){auto now=mozilla::NowIncludingSuspendMs();assert(now&&*now==123456&&selector==CLOCK_MONOTONIC);fail=true;assert(!mozilla::NowIncludingSuspendMs());}
''')
   subprocess.run(['clang++','-std=c++17','-fsanitize=address,undefined','-I'+tmp,str(path/'test.cpp'),'-o',str(path/'test')],check=True,capture_output=True)
   subprocess.run([str(path/'test')],check=True,capture_output=True)
 def test_native_gate_and_providerless_service_fail_closed(self):
  probe=(ROOT/'gecko/orbisfox/native/clock_probe.cpp').read_text()
  self.assertIn('mozilla::ProcessUptimeMs()',probe);self.assertIn('const bool ok = uptimeReady &&',probe)
  source=(ROOT/'.deps/gecko-layout/toolkit/components/geolocation/GeolocationService.cpp').read_text()
  begin=source.index('nsresult GeolocationService::Init()')
  end=source.index('GeolocationService::~GeolocationService()',begin)
  self.assertIn('if (!mProvider)',source[begin:end]);self.assertIn('return NS_ERROR_NOT_AVAILABLE;',source[begin:end]);self.assertIn('obs->RemoveObserver(this, "xpcom-shutdown")',source[begin:end])
