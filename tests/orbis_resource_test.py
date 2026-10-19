# SPDX-License-Identifier: MIT
"""Real shared policies/counters and bounded asynchronous readback, not console proof."""
from pathlib import Path
import os, subprocess, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
class ResourceTests(unittest.TestCase):
 def compile_run(self,code,extra=(),libraries=(),env=None):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);cpp=p/'test.cpp';cpp.write_text(code)
   subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
    '-fno-omit-frame-pointer','-pthread','-I'+str(ROOT/'include'),'-I'+str(ROOT/'gecko/orbisfox'),
    '-I'+str(ROOT/'gecko/widget/orbis'),str(cpp),*map(str,extra),*libraries,'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True,env=env)
 def test_pressure_hysteresis_failed_queries_and_bounded_notifications(self):
  self.compile_run(r'''
#include "orbisfox/memory_pressure.h"
#include "orbisfox/vm_summary.h"
#include "OrbisResourceDiagnostics.h"
#include <cassert>
#include <thread>
int main(){using P=orbisfox::FlexibleMemoryPressure;using E=P::Event;P p;
 assert(p.sample(-1,0,0)==E::None&&!p.pressured());
 assert(p.sample(0,P::lowBytes,0)==E::None);
 assert(p.sample(0,P::lowBytes-1,1)==E::Low&&p.pressured());
 for(unsigned i=0;i<100;++i)assert(p.sample(0,0,2+i)==E::None);
 assert(p.sample(-1,100000000,20000000)==E::None&&p.pressured());
 assert(p.sample(0,0,15000001)==E::Low);
 assert(p.sample(0,0,1)==E::None); // Clock rollback isn't a burst of notifications.
 assert(p.sample(0,P::recoverBytes-1,15000002)==E::None);
 assert(p.sample(0,P::recoverBytes,15000003)==E::Recovered&&!p.pressured());
 assert(p.sample(0,P::recoverBytes,15000004)==E::None);
 assert(p.sample(0,0,15000005)==E::Low);
 struct Info {void* unk01;void* unk02;bool isFlexibleMemory,isDirectMemory,isStack,isCommitted;};
 unsigned calls=0;
 auto census=orbisfox::summarizeVm<Info>([&](const void* address,int flags,Info* i,size_t size){
  assert(flags==1&&size==sizeof(Info));++calls;
  if(calls==3)return -12;
  const auto start=reinterpret_cast<uintptr_t>(address);
  *i={reinterpret_cast<void*>(start+16),reinterpret_cast<void*>(start+4096),calls==1,calls==2,calls==1,true};return 0;
 });
 assert(calls==3&&census.regions==2&&census.flexibleBytes==4080&&census.directBytes==4080);
 assert(census.stackBytes==4080&&census.committedFlexibleBytes==4080&&census.lastResult==-12&&!census.truncated);
 census=orbisfox::summarizeVm<Info>([](const void*,int,Info* i,size_t){*i={};return 0;});assert(census.malformed);
 census=orbisfox::summarizeVm<Info>([](const void* address,int,Info* i,size_t){
  const auto n=reinterpret_cast<uintptr_t>(address);*i={reinterpret_cast<void*>(n),reinterpret_cast<void*>(n+4096),true,false,false,true};return 0;
 });assert(census.truncated&&census.regions==2048);
 using namespace mozilla::widget;
 std::thread workers[4];for(auto& t:workers)t=std::thread([]{for(unsigned i=0;i<1000;++i){RecordOrbisSharedMap(16384,true);RecordOrbisSharedUnmap(16384,true);}});
 for(auto& t:workers)t.join();auto s=GetOrbisResourceDiagnostics();assert(s.sharedMappedBytes==0&&s.sharedMaps==4000&&s.sharedUnmaps==4000&&s.sharedPeakBytes>=16384);
 RecordOrbisSharedMap(16384,true);RecordOrbisSharedUnmap(16384,false);RecordOrbisSharedMap(16384,false);
 s=GetOrbisResourceDiagnostics();assert(s.sharedMappedBytes==16384&&s.sharedMapFailures==1&&s.sharedUnmapFailures==1);
 RecordOrbisSharedUnmap(16384,true);assert(GetOrbisResourceDiagnostics().sharedMappedBytes==0);
 auto g=GetOrbisGraphicsDiagnostics();assert(g.hardwareSelections==0&&g.creationResult==0&&g.hardwareStatus==UINT32_MAX);
 RecordOrbisGraphicsConfig(true,true,1,2);
 RecordOrbisCompositorSelection(true,true,true,false,false);
 RecordOrbisGpuCreation(OrbisGpuCreation::Ready);
 g=GetOrbisGraphicsDiagnostics();assert(g.hardwareSelections==1&&g.softwareSelections==0&&g.policyFlags==7&&g.configFlags==3);
 assert(g.hardwareStatus==1&&g.webRenderStatus==2&&g.createAttempts==1&&g.createSuccesses==1&&g.creationResult==1);
 RecordOrbisCompositorSelection(true,true,true,true,true);
 RecordOrbisGpuCreation(OrbisGpuCreation::NoContext);
 g=GetOrbisGraphicsDiagnostics();assert(g.hardwareSelections==1&&g.softwareSelections==1&&g.policyFlags==31);
 assert(g.createAttempts==2&&g.createSuccesses==1&&g.creationResult==2);
 for(auto& t:workers)t=std::thread([]{for(unsigned i=0;i<1000;++i)RecordOrbisCompositorSelection(true,true,false,true,true);});
 for(auto& t:workers)t.join();g=GetOrbisGraphicsDiagnostics();assert(g.softwareSelections==4001&&g.hardwareSelections==1);
}
''',[ROOT/'gecko/widget/orbis/OrbisResourceDiagnostics.cpp'])
 def test_real_gles_pbo_fences_state_pixels_and_idle_frame(self):
  self.compile_run(r'''
#include "OrbisGpuReadbackQueue.h"
#include "OrbisGpuReadback.h"
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <array>
#include <cassert>
#include <chrono>
#include <thread>
struct GL {
 bool timeout=false,failedWait=false,failedMap=false,failedUnmap=false;
 unsigned maps=0,waits=0;
 void fGetIntegerv(GLenum p,GLint* v){glGetIntegerv(p,v);} void fGenBuffers(GLsizei n,GLuint* p){glGenBuffers(n,p);}
 void fDeleteBuffers(GLsizei n,const GLuint* p){glDeleteBuffers(n,p);} void fBindBuffer(GLenum t,GLuint b){glBindBuffer(t,b);}
 void fBindFramebuffer(GLenum t,GLuint b){glBindFramebuffer(t,b);} void fBufferData(GLenum t,GLsizeiptr n,const void* p,GLenum u){glBufferData(t,n,p,u);}
 void fPixelStorei(GLenum p,GLint v){glPixelStorei(p,v);} void fReadPixels(GLint x,GLint y,GLsizei w,GLsizei h,GLenum f,GLenum t,void* p){glReadPixels(x,y,w,h,f,t,p);}
 GLenum fGetError(){return glGetError();} GLsync fFenceSync(GLenum c,GLbitfield f){return glFenceSync(c,f);} void fDeleteSync(GLsync s){glDeleteSync(s);}
 GLenum fClientWaitSync(GLsync s,GLbitfield f,GLuint64 n){assert(n<=250000000&&f==0);if(n)++waits;if(timeout)return GL_TIMEOUT_EXPIRED;if(failedWait)return GL_WAIT_FAILED;return glClientWaitSync(s,f,n);}
 void fFlush(){glFlush();} void* fMapBufferRange(GLenum t,GLintptr o,GLsizeiptr n,GLbitfield f){++maps;if(failedMap)return nullptr;return glMapBufferRange(t,o,n,f);}
 GLboolean fUnmapBuffer(GLenum t){const auto result=glUnmapBuffer(t);return failedUnmap?GL_FALSE:result;}
};
int main(){auto d=eglGetDisplay(EGL_DEFAULT_DISPLAY);assert(d!=EGL_NO_DISPLAY);assert(eglInitialize(d,nullptr,nullptr));
 const EGLint attrs[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};EGLConfig config;EGLint count;
 assert(eglChooseConfig(d,attrs,&config,1,&count)&&count==1);assert(eglBindAPI(EGL_OPENGL_ES_API));
 const EGLint ca[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE},sa[]={EGL_WIDTH,8,EGL_HEIGHT,4,EGL_NONE};auto c=eglCreateContext(d,config,EGL_NO_CONTEXT,ca);auto s=eglCreatePbufferSurface(d,config,sa);
 assert(c!=EGL_NO_CONTEXT&&s!=EGL_NO_SURFACE&&eglMakeCurrent(d,s,s,c));
 GL gl;using Q=orbisfox::GpuReadbackQueue<GL>;Q q;
 GLuint saved=0,fbo=0;glGenBuffers(1,&saved);glBindBuffer(GL_PIXEL_PACK_BUFFER,saved);glBufferData(GL_PIXEL_PACK_BUFFER,1024,nullptr,GL_STREAM_READ);
 glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_READ_FRAMEBUFFER,fbo);
 glPixelStorei(GL_PACK_ALIGNMENT,8);glPixelStorei(GL_PACK_ROW_LENGTH,11);glPixelStorei(GL_PACK_SKIP_PIXELS,2);glPixelStorei(GL_PACK_SKIP_ROWS,1);
 for(uint64_t serial=1;serial<=2;++serial){glClearColor((serial==1?64.0f:128.0f)/255.0f,128.0f/255.0f,191.0f/255.0f,1);glClear(GL_COLOR_BUFFER_BIT);assert(q.enqueue(gl,8,4,serial)==Q::Result::Ready);
  GLint v;glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING,&v);assert(GLuint(v)==fbo);glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&v);assert(GLuint(v)==saved);
  glGetIntegerv(GL_PACK_ROW_LENGTH,&v);assert(v==11);glGetIntegerv(GL_PACK_SKIP_PIXELS,&v);assert(v==2);glGetIntegerv(GL_PACK_SKIP_ROWS,&v);assert(v==1);glGetIntegerv(GL_PACK_ALIGNMENT,&v);assert(v==8);
 }
 assert(q.pending()==2&&q.enqueue(gl,8,4,3)==Q::Result::Full);
 gl.timeout=true;assert(q.poll(gl,[](auto...){assert(false);return false;})==Q::Result::Pending);
 assert(gl.maps==0&&q.pending()==2);
 assert(q.waitOldest(gl,1000000)==Q::Result::Pending&&gl.maps==0&&gl.waits==1);
 assert(q.waitOldest(gl,250000001)==Q::Result::Failed&&gl.waits==1);
 gl.timeout=false;assert(q.waitOldest(gl,250000000)==Q::Result::Ready&&gl.maps==0&&gl.waits==2);
 unsigned completed=0;
 for(unsigned i=0;i<2000&&q.pending();++i){auto r=q.poll(gl,[&](const uint8_t* data,size_t bytes,Q::Image image){
  assert(image.serial==++completed&&bytes==128);std::array<uint8_t,128> out{};
  assert(orbisfox::ConvertGpuRgbaToBgra(data,bytes,32,out.data(),out.size(),32,8,4));
  for(size_t p=0;p<128;p+=4){assert(out[p]==191&&out[p+1]==128&&out[p+2]==(completed==1?64:128)&&out[p+3]==255);}return true;
 });assert(r==Q::Result::Ready||r==Q::Result::Pending);if(r==Q::Result::Pending)std::this_thread::sleep_for(std::chrono::milliseconds(1));}
 assert(completed==2&&q.pending()==0);assert(q.poll(gl,[](auto...){return false;})==Q::Result::Empty);
 assert(q.enqueue(gl,1281,4,3)==Q::Result::Failed);
 assert(q.mark(gl,3)==Q::Result::Ready);
 for(unsigned i=0;i<2000&&q.pending();++i){auto result=q.poll(gl,[](const uint8_t* data,size_t length,Q::Image image){assert(!data&&!length&&!image.width&&image.serial==3);return true;});
  assert(result==Q::Result::Ready||result==Q::Result::Pending);if(result==Q::Result::Pending)std::this_thread::sleep_for(std::chrono::milliseconds(1));}
 assert(q.pending()==0); // An idle final frame/update needs no future enqueue.
 assert(q.mark(gl,4)==Q::Result::Ready);gl.failedWait=true;
 assert(q.poll(gl,[](auto...){assert(false);return true;})==Q::Result::Failed);gl.failedWait=false;q.destroy(gl);
 for(int failure=0;failure<3;++failure){assert(q.enqueue(gl,8,4,5)==Q::Result::Ready);gl.failedMap=failure==0;gl.failedUnmap=failure==1;
  bool failed=false;for(unsigned i=0;i<2000&&!failed;++i){auto result=q.poll(gl,[&](auto...){return failure!=2;});assert(result==Q::Result::Pending||result==Q::Result::Failed);failed=result==Q::Result::Failed;if(!failed)std::this_thread::sleep_for(std::chrono::milliseconds(1));}
  assert(failed);gl.failedMap=gl.failedUnmap=false;q.destroy(gl);}
 assert(glGetError()==GL_NO_ERROR);
 glBindFramebuffer(GL_READ_FRAMEBUFFER,0);glDeleteFramebuffers(1,&fbo);glDeleteBuffers(1,&saved);
 eglMakeCurrent(d,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);eglDestroySurface(d,s);eglDestroyContext(d,c);eglTerminate(d);
}
''',libraries=['-lEGL','-lGLESv2'],env=dict(os.environ,EGL_PLATFORM='surfaceless',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',ASAN_OPTIONS='detect_leaks=0'))
if __name__=='__main__':unittest.main()
