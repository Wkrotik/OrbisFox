"""Native cursor timing math, not actual Pad samples or firmware responsiveness."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class PointerMotionTest(unittest.TestCase):
    def test_clock_scaled_motion_and_touch_reanchoring(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ unavailable')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'test.cpp').write_text(r'''
#include "orbisfox/pointer_motion.h"
#include "orbisfox/touch_cursor.h"
#include <cassert>
using namespace orbisfox;
int main(){
 for(double speed:{0.25,1.0,1.5,3.0}){
  TimedStickCursor fast,normal;
  int a=0,b=0;
  for(unsigned i=0;i<160;++i)a+=fast.update(255,speed,1000);
  for(unsigned i=0;i<10;++i)b+=normal.update(255,speed,16000);
  assert(a==b);
  assert(fast.update(128,speed,16000)==0);
  assert(fast.update(255,speed,0)==0);
  assert(normal.update(0,speed,16000)<0);
 }
 PointerPollClock clock;
 assert(clock.update(100000).elapsed==0);
 assert(clock.update(101000).elapsed==1000);
 assert(clock.update(141000).elapsed==16000);
 auto gap=clock.update(2000000);assert(gap.discontinuity&&gap.elapsed==0);
 assert(clock.update(2016000).elapsed==16000);
 assert(clock.update(2016000).discontinuity);
 assert(clock.update(1000).discontinuity);
 clock.reset();assert(clock.update(3000).elapsed==0);
 TouchCursor touch;int x=400,y=300;
 TouchPoint sample{100,100,1};
 assert(!touch.update(&sample,1,1280,720,x,y));
 sample.x=130;assert(touch.update(&sample,1,1280,720,x,y));
 const int previous=x;
 // Native poll resets/reanchors after a stalled page; stale displacement
 // must not become an immediate several-hundred-pixel cursor jump.
 touch.reset();sample.x=900;
 assert(!touch.update(&sample,1,1280,720,x,y));assert(x==previous);
 sample.x=930;assert(touch.update(&sample,1,1280,720,x,y));assert(x-previous==20);
}
''')
            binary = path / 'test'
            result = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                     '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                                     '-include', 'initializer_list', '-I' + str(ROOT / 'include'),
                                     str(path / 'test.cpp'), str(ROOT / 'src/touch_cursor.cpp'), '-o', str(binary)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
