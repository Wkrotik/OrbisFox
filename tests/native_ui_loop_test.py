"""Actual native loop/thread/frame exchange, with device callbacks only mocked."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class NativeUiLoopTests(unittest.TestCase):
    def test_latest_frame_ownership_and_pointer_runs_without_main_pump(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ unavailable')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / 'test.cpp'
            source.write_text(r'''
#include "orbisfox/native_ui_loop.h"
#include <cassert>
#include <cstring>
#include <atomic>
#include <chrono>
#include <thread>
using namespace orbisfox;
struct Device {
 std::atomic<unsigned> outputs{0},inputs{0},buttons{0};
 std::atomic<unsigned char> corner{0};
 std::atomic<bool> failing{false};
 static bool poll(void* raw,UiPadSample& sample){auto& d=*static_cast<Device*>(raw);++d.inputs;sample.buttons=d.buttons;sample.leftX=200;sample.rightY=255;return true;}
 static bool present(void* raw,const Surface& frame){auto& d=*static_cast<Device*>(raw);assert(frame.pixels&&frame.stride==96*4);d.corner=frame.pixels[0];++d.outputs;return !d.failing;}
 static uint64_t now(void*){return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
 static void sleep(void*,uint32_t us){std::this_thread::sleep_for(std::chrono::microseconds(us));}
 UiLoopBackend backend(){return {this,poll,present,now,sleep};}
};
int main(){
 {
  unsigned char a[1024]{},b[1024]{},c[1024]{};LatestUiFrame frames;frames.initialize(a,b,c);
  memset(frames.writer(),1,sizeof(a));frames.publish();memset(frames.writer(),2,sizeof(a));frames.publish();
  uint64_t serial=0;const auto* latest=frames.read(serial);assert(serial==2&&latest[0]==2);
  // Producer may replace the mailbox repeatedly, never the held consumer slot.
  for(unsigned i=0;i<20;++i){memset(frames.writer(),3,sizeof(a));frames.publish();assert(latest[0]==2);}
  latest=frames.read(serial);assert(serial==22&&latest[0]==3);
  std::atomic<bool> done{false};
  std::thread producer([&]{for(unsigned i=0;i<20000;++i){memset(frames.writer(),4+i%200,sizeof(a));frames.publish();}done=true;});
  uint64_t previous=serial;
  do{
   latest=frames.read(serial);assert(serial>=previous);previous=serial;
   const unsigned char value=latest[0];assert(value==(serial==22?3:4+(serial-23)%200));
   for(unsigned i=0;i<sizeof(a);++i)assert(latest[i]==value);
  }while(!done);
  producer.join();latest=frames.read(serial);assert(serial==20022);
 }
 unsigned char initial[96*64*4];memset(initial,32,sizeof(initial));Surface image{initial,96,64,96*4};
 NativeUiLoop loop;Device d;
 assert(!loop.start({},1920,943,d.backend()));assert(loop.start(image,1920,943,d.backend()));
 assert(!loop.start(image,1920,943,d.backend()));
 // Main does no pumping/publishing while worker polls, moves and scans out.
 std::this_thread::sleep_for(std::chrono::milliseconds(180));
 auto stats=loop.stats();assert(stats.polls>=5&&stats.scanouts>=5&&stats.x>48&&stats.frameSerial==0&&!stats.failed);
 auto input=loop.consumeInput();assert(input.pad.connected&&input.x>48&&input.wheel.y<=64);
 assert(loop.consumeInput().wheel.y==0);
 // Worker retains both genuine R3 edges even while Gecko does not consume.
 d.buttons=4;Device::sleep(nullptr,64000);d.buttons=0;Device::sleep(nullptr,64000);
 input=loop.consumeInput();assert(input.edgeCount==2&&input.edges[0].down&&!input.edges[1].down&&input.edges[0].button==8192&&input.edges[1].button==8192);
 Surface target=loop.beginFrame();assert(target.pixels);memset(target.pixels,91,sizeof(initial));assert(loop.publishFrame());
 for(unsigned i=0;i<100&&d.corner!=91;++i)Device::sleep(nullptr,5000);
 assert(d.corner==91&&loop.stats().frameSerial==1);
 loop.pauseInput(true);std::this_thread::sleep_for(std::chrono::milliseconds(40));
 const int pausedX=loop.stats().x;const auto pausedOutputs=d.outputs.load();
 std::this_thread::sleep_for(std::chrono::milliseconds(40));assert(loop.stats().x==pausedX&&d.outputs==pausedOutputs);
 loop.setSpeed(0.25);loop.pauseInput(false);
 d.failing=true;memset(loop.beginFrame().pixels,92,sizeof(initial));assert(loop.publishFrame());
 for(unsigned i=0;i<100&&!loop.stats().failed;++i)Device::sleep(nullptr,5000);
 assert(loop.stats().failed&&!loop.publishFrame());loop.stop();assert(!loop.running()&&!loop.beginFrame().pixels);
 const unsigned before=d.inputs;Device::sleep(nullptr,32000);assert(d.inputs==before);
 d.failing=false;assert(loop.start(image,1920,943,d.backend()));Device::sleep(nullptr,32000);loop.stop();
}
''')
            binary = path / 'test'
            built = subprocess.run([compiler, '-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror',
                                    '-fsanitize=address,undefined', '-pthread',
                                    '-I' + str(ROOT / 'include'), str(source),
                                    str(ROOT / 'src/native_ui_loop.cpp'), str(ROOT / 'src/native_chrome.cpp'), str(ROOT / 'src/touch_cursor.cpp'),
                                    str(ROOT / 'src/surface.cpp'), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
