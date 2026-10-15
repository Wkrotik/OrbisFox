#include "orbisfox/native_ui_loop.h"
#include "orbisfox/pointer_motion.h"
#include "orbisfox/stick_cursor.h"
#include "orbisfox/browser_controls.h"
#include <stdlib.h>
#include <string.h>
namespace orbisfox {
namespace {
struct Lock {
  pthread_mutex_t& mutex;
  explicit Lock(pthread_mutex_t& value):mutex(value){if(pthread_mutex_lock(&mutex))__builtin_trap();}
  ~Lock(){if(pthread_mutex_unlock(&mutex))__builtin_trap();}
};
int clamp(int value,int low,int high){return value<low?low:value>high?high:value;}
}
LatestUiFrame::~LatestUiFrame(){if(pthread_mutex_destroy(&mutex_))__builtin_trap();}
void LatestUiFrame::initialize(uint8_t* a,uint8_t* b,uint8_t* c){
  if(!a||!b||!c||a==b||a==c||b==c)__builtin_trap();
  slots_[0]=a;slots_[1]=b;slots_[2]=c;writer_=0;reader_=1;ready_=2;
  pending_=false;serial_=readSerial_=0;
}
void LatestUiFrame::publish(){
  Lock lock(mutex_);if(serial_==UINT64_MAX)__builtin_trap();
  const unsigned old=writer_;writer_=ready_;ready_=old;pending_=true;++serial_;
}
const uint8_t* LatestUiFrame::read(uint64_t& serial){
  Lock lock(mutex_);
  if(pending_){const unsigned old=reader_;reader_=ready_;ready_=old;pending_=false;readSerial_=serial_;}
  serial=readSerial_;return slots_[reader_];
}
NativeUiLoop::~NativeUiLoop(){stop();if(pthread_mutex_destroy(&inputMutex_))__builtin_trap();}
bool NativeUiLoop::start(const Surface& initial,uint16_t touchX,uint16_t touchY,const UiLoopBackend& backend){
  if(started_||!initial.pixels||initial.width<32||initial.height<32||initial.width>4096||initial.height>4096||
     initial.stride!=size_t(initial.width)*4||!backend.poll||!backend.present||!backend.now||!backend.sleep)return false;
  if(!prepare_native_chrome_font())return false;
  const size_t bytes=initial.stride*size_t(initial.height);
  storage_=static_cast<uint8_t*>(malloc(bytes*4));if(!storage_)return false;
  for(unsigned i=0;i<4;++i)memcpy(storage_+bytes*i,initial.pixels,bytes);
  frames_.initialize(storage_,storage_+bytes,storage_+bytes*2);
  output_={storage_+bytes*3,initial.width,initial.height,initial.stride};backend_=backend;
  touchX_=touchX;touchY_=touchY;stop_.store(false);failed_.store(false);paused_.store(false);
  polls_.store(0);scanouts_.store(0);frameSerial_.store(0);scanoutMicros_.store(0);maxScanoutMicros_.store(0);
  x_.store(initial.width/2);y_.store(initial.height/2);
  input_={};input_.x=initial.width/2;input_.y=initial.height/2;lastConsumer_=backend_.now(backend_.user);
  if(pthread_create(&thread_,nullptr,entry,this)){free(storage_);storage_=nullptr;output_={};return false;}
  started_=true;return true;
}
void NativeUiLoop::stop(){
  if(started_){stop_.store(true);if(pthread_join(thread_,nullptr))__builtin_trap();started_=false;}
  free(storage_);storage_=nullptr;output_={};
}
Surface NativeUiLoop::beginFrame(){return started_?Surface{frames_.writer(),output_.width,output_.height,output_.stride}:Surface{};}
bool NativeUiLoop::publishFrame(){if(!started_||failed_.load())return false;frames_.publish();return true;}
UiInputSnapshot NativeUiLoop::consumeInput(){
  Lock lock(inputMutex_);UiInputSnapshot result=input_;input_.wheel={};input_.edgeCount=0;
  const uint64_t now=backend_.now(backend_.user);
  unsigned count=0;for(unsigned i=0;i<result.edgeCount;++i)if(now>=result.edges[i].stamp&&now-result.edges[i].stamp<=2000000)result.edges[count++]=result.edges[i];result.edgeCount=count;
  // Scroll expires quickly; trusted pointer edges have a bounded2s lifetime.
  if(now<result.stamp||now-result.stamp>64000)result.wheel={};
  lastConsumer_=now;return result;
}
UiLoopStats NativeUiLoop::stats()const{return{polls_.load(),scanouts_.load(),frameSerial_.load(),scanoutMicros_.load(),maxScanoutMicros_.load(),x_.load(),y_.load(),failed_.load()};}
void* NativeUiLoop::entry(void* opaque){static_cast<NativeUiLoop*>(opaque)->run();return nullptr;}
void NativeUiLoop::run(){
  TouchCursor touch;touch.set_resolution(touchX_,touchY_);TimedStickCursor stickX,stickY;
  PointerPollClock clock;StickScroll scroll;double oldSpeed=speed_.load();
  int x=output_.width/2,y=output_.height/2;uint64_t serial=0,inputSerial=0,lastPresented=UINT64_MAX;
  int lastX=-1,lastY=-1;bool lastPaused=false,primary=false,middle=false;uint64_t lastChrome=UINT64_MAX;
  while(!stop_.load()){
    const uint64_t begin=backend_.now(backend_.user);
    UiPadSample pad{};pad.connected=backend_.poll(backend_.user,pad);polls_.fetch_add(1);
    const auto timing=clock.update(begin);ScrollDelta wheel{};
    const double speed=speed_.load();
    if(timing.discontinuity||speed!=oldSpeed){touch.reset();stickX.reset();stickY.reset();oldSpeed=speed;}
    if(pad.connected&&!paused_.load()){
      wheel=scroll.update(pad.rightX,pad.rightY,begin);
      x=clamp(x+stickX.update(pad.leftX,speed,timing.elapsed),10,output_.width-11);
      y=clamp(y+stickY.update(pad.leftY,speed,timing.elapsed),10,output_.height-11);
      if(stick_cursor_delta(pad.leftX)||stick_cursor_delta(pad.leftY))touch.reset();
      else touch.update(pad.contacts,pad.contactCount,output_.width,output_.height,x,y);
      x=clamp(x,10,output_.width-11);y=clamp(y,10,output_.height-11);
    }else{touch.reset();stickX.reset();stickY.reset();clock.reset();scroll.reset();}
    const uint32_t chromeMask=paused_.load()?0:chrome_.input(pad.connected?browser_buttons(pad.buttons,true):0,x,y);
    const bool chromeModal=chrome_.modal();
    {
      Lock lock(inputMutex_);
      input_.chromeMask=chromeMask;input_.chromeModal=chromeModal;
      const uint32_t contentButtons=browser_buttons(pad.buttons,true)&~chromeMask;
      const bool pointer=pad.connected&&!paused_.load()&&!(contentButtons&8190);
      const bool down=pointer&&(contentButtons&1),middleDown=pointer&&(contentButtons&8192);
      if(down!=primary){if(input_.edgeCount==16)input_.edgeCount=0;input_.edges[input_.edgeCount++]={x,y,down,begin,1};primary=down;}
      if(middleDown!=middle){if(input_.edgeCount==16)input_.edgeCount=0;input_.edges[input_.edgeCount++]={x,y,middleDown,begin,8192};middle=middleDown;}
      if(begin<lastConsumer_||begin-lastConsumer_>64000)input_.wheel={};
      // At most roughly two normal samples; never replay a load-stall backlog.
      input_.wheel.x=clamp(input_.wheel.x+wheel.x,-64,64);
      input_.wheel.y=clamp(input_.wheel.y+wheel.y,-64,64);
      input_.pad=pad;input_.x=x;input_.y=y;input_.stamp=begin;input_.serial=++inputSerial;
    }
    x_.store(x);y_.store(y);
    const uint8_t* frame=frames_.read(serial);frameSerial_.store(serial);
    const bool paused=paused_.load();
    // Native IME owns presentation while modal. Main's deferred open requires
    // two different published input serials, so pre-pause scanout has finished.
    if(paused)lastPaused=true;
    const uint64_t chromeRevision=chrome_.revision();
    if(!paused&&(serial!=lastPresented||x!=lastX||y!=lastY||lastPaused||chromeRevision!=lastChrome)){
      memcpy(output_.pixels,frame,output_.stride*size_t(output_.height));
      chrome_.render(output_);
      if(!paused){
        fill_rect(output_,x-8,y-1,17,3,{255,140,36,255});
        fill_rect(output_,x-1,y-8,3,17,{255,140,36,255});
      }
      const uint64_t waitBegin=backend_.now(backend_.user);
      if(!backend_.present(backend_.user,output_)){failed_.store(true);break;}
      const uint64_t waitEnd=backend_.now(backend_.user);
      const uint64_t waited=waitEnd>=waitBegin?waitEnd-waitBegin:0;
      scanoutMicros_.fetch_add(waited);if(waited>maxScanoutMicros_.load())maxScanoutMicros_.store(waited);
      scanouts_.fetch_add(1);lastPresented=serial;lastX=x;lastY=y;lastPaused=paused;lastChrome=chromeRevision;
    }
    const uint64_t end=backend_.now(backend_.user);
    if(end>=begin&&end-begin<16000)backend_.sleep(backend_.user,uint32_t(16000-(end-begin)));
  }
}
}
