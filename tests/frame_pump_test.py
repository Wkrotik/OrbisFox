"""Actual frame-pump branch with surface/callback doubles, not console proof."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FramePumpTest(unittest.TestCase):
    def test_failure_details_preserve_validation_and_mapping_lifetime(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ unavailable')
        source = (ROOT / 'gecko/widget/orbis/OrbisFoxHost.cpp').read_text()
        start = source.index('  uint64_t sequence = 0;', source.index('OrbisFoxHost::PumpFrame('))
        frame = source[start:source.index('  *aContinue = true;', start)]
        keyboard_start = source.index('    if(mKeyboardStatus < 1', source.index('OrbisFoxHost::PumpFrame('))
        keyboard = source[keyboard_start:source.index('    if (mKeyboardStatus == 2)', keyboard_start)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'frame.inc').write_text(frame)
            (path / 'keyboard.inc').write_text(keyboard)
            (path / 'test.cpp').write_text(r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
constexpr int NS_OK=0,NS_ERROR_UNEXPECTED=-1,NS_ERROR_FAILURE=-2;
#define NS_ENSURE_TRUE(test,result) do{if(!(test))return result;}while(0)
template<class T> using RefPtr=T*;
namespace gfx {
enum class SurfaceFormat {B8G8R8A8,Other};
struct DataSourceSurface {
 struct Size {int width=1280,height=720;} size;
 SurfaceFormat format=SurfaceFormat::B8G8R8A8;
 bool mapped=true,data=true;int stride=5120,maps=0,unmaps=0;
 Size GetSize()const{return size;}
 SurfaceFormat GetFormat()const{return format;}
 enum MapType {READ};
 struct ScopedMap {
  DataSourceSurface* surface;
  ScopedMap(DataSourceSurface* s,MapType):surface(s){++s->maps;}
  ~ScopedMap(){if(IsMapped())++surface->unmaps;}
  bool IsMapped()const{return surface->mapped;}
  const uint8_t* GetData()const{assert(IsMapped());static uint8_t pixel=0;return surface->data?&pixel:nullptr;}
  int GetStride()const{assert(IsMapped());return surface->stride;}
 };
};
}
static gfx::DataSourceSurface* latest=nullptr;
struct OrbisCompositorWidget {
 static gfx::DataSourceSurface* GetLatestFrame(uint64_t* sequence){*sequence=7;return latest;}
};
static unsigned presents=0;static bool presentOkay=true;
static std::vector<std::string> logs;
static void logMessage(void*,const char* text){logs.emplace_back(text);}
struct Callbacks {
 void* context=nullptr;
 void (*log)(void*,const char*)=logMessage;
 bool (*present)(void*,const uint8_t*,int,int,int)=[](void*,const uint8_t*,int,int,int){++presents;return presentOkay;};
} sCallbacks;
enum class OrbisPumpPhase {Mailbox,Map,Present};
struct PumpDiagnostics {void SetPhase(OrbisPumpPhase){}};
struct Host {
 uint64_t mLastSequence=0,mFramesPresented=0;unsigned mKeyboardStatus=0;
 int pump(){
  PumpDiagnostics pumpDiagnostics;
  const auto traceStage=[](const char*){};
#include "frame.inc"
  return NS_OK;
 }
 int keyboard(){
#include "keyboard.inc"
  return NS_OK;
 }
};
int main(){
 for(unsigned cycle=0;cycle<32;++cycle){
  gfx::DataSourceSurface surface;latest=&surface;Host host;
  presents=0;presentOkay=true;logs.clear();
  assert(host.pump()==NS_OK&&presents==1&&host.mFramesPresented==1&&surface.unmaps==1);
  assert(host.pump()==NS_OK&&presents==1&&surface.maps==1); // unchanged frame
  for(const auto size: {gfx::DataSourceSurface::Size{3840,2160},{0,720},{1280,721}}){
   surface={};surface.size=size;Host invalid;
   assert(invalid.pump()==NS_ERROR_UNEXPECTED&&invalid.mLastSequence==0&&surface.maps==0);
   assert(logs.back().find("Gecko pump failure: surface width=")==0);
  }
  surface={};surface.format=gfx::SurfaceFormat::Other;Host invalidFormat;
  assert(invalidFormat.pump()==NS_ERROR_UNEXPECTED&&surface.maps==0);
  for(unsigned failure=0;failure<4;++failure){
   surface={};if(failure==0)surface.mapped=false;if(failure==1)surface.data=false;
   if(failure==2)surface.stride=5119;if(failure==3)surface.stride=8193;
   Host invalid;assert(invalid.pump()==NS_ERROR_UNEXPECTED&&invalid.mLastSequence==0);
   assert(surface.unmaps==(surface.mapped?1:0));
   assert(logs.back().find("Gecko pump failure: mapping width=1280 height=720 mapped=")==0);
  }
  surface={};surface.stride=8192;Host boundary;assert(boundary.pump()==NS_OK&&boundary.mFramesPresented==1);
  surface={};presentOkay=false;Host failedPresent;
  assert(failedPresent.pump()==NS_ERROR_FAILURE&&failedPresent.mLastSequence==0&&surface.unmaps==1);
  latest=nullptr;Host empty;assert(empty.pump()==NS_OK&&empty.mFramesPresented==0);
  for(unsigned status=0;status<=5;++status){Host keyboard;keyboard.mKeyboardStatus=status;
   assert(keyboard.keyboard()==(status>=1&&status<=4?NS_OK:NS_ERROR_UNEXPECTED));
  }
  sCallbacks.log=nullptr;latest=&surface;surface.size.width=3840;
  Host noLogger;assert(noLogger.pump()==NS_ERROR_UNEXPECTED);sCallbacks.log=logMessage;
 }
}
''')
            binary = path / 'test'
            compiled = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Werror',
                                       '-fsanitize=address,undefined', '-g', str(path / 'test.cpp'),
                                       '-o', str(binary)], capture_output=True, text=True, check=False)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
