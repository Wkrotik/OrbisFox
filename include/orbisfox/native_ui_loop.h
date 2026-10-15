#pragma once
#include "orbisfox/surface.h"
#include "orbisfox/native_chrome.h"
#include "orbisfox/touch_cursor.h"
#include "orbisfox/stick_scroll.h"
#include <atomic>
#include <pthread.h>
namespace orbisfox {
struct UiPadSample {
  bool connected=false;
  uint32_t buttons=0;
  uint8_t leftX=128,leftY=128,rightX=128,rightY=128;
  TouchPoint contacts[2]{};
  size_t contactCount=0;
};
struct UiPointerEdge {int x=0,y=0;bool down=false;uint64_t stamp=0;uint32_t button=1;};
struct UiInputSnapshot {
  UiPadSample pad{};
  uint32_t chromeMask=0;
  bool chromeModal=false;
  UiPointerEdge edges[16]{};unsigned edgeCount=0;
  int x=0,y=0;
  ScrollDelta wheel{};
  uint64_t serial=0,stamp=0;
};
struct UiLoopBackend {
  void* user=nullptr;
  bool (*poll)(void*,UiPadSample&)=nullptr;
  bool (*present)(void*,const Surface&)=nullptr;
  uint64_t (*now)(void*)=nullptr;
  void (*sleep)(void*,uint32_t)=nullptr;
};
// Three exclusive roles: main-thread writer, latest published frame, worker
// reader. Swaps hold a tiny lock; pixel copying and scanout never hold it.
class LatestUiFrame {
  pthread_mutex_t mutex_=PTHREAD_MUTEX_INITIALIZER;
  uint8_t* slots_[3]{};
  unsigned writer_=0,reader_=1,ready_=2;
  bool pending_=false;
  uint64_t serial_=0,readSerial_=0;
 public:
  LatestUiFrame()=default;
  ~LatestUiFrame();
  LatestUiFrame(const LatestUiFrame&)=delete;
  LatestUiFrame& operator=(const LatestUiFrame&)=delete;
  void initialize(uint8_t* a,uint8_t* b,uint8_t* c);
  uint8_t* writer() const {return slots_[writer_];} // producer only
  void publish(); // producer only
  const uint8_t* read(uint64_t& serial); // one consumer; valid until next read
};
struct UiLoopStats {
  uint64_t polls=0,scanouts=0,frameSerial=0,scanoutMicros=0,maxScanoutMicros=0;
  int x=0,y=0;
  bool failed=false;
};
class NativeUiLoop {
  LatestUiFrame frames_;
  NativeChrome chrome_;
  pthread_mutex_t inputMutex_=PTHREAD_MUTEX_INITIALIZER;
  UiInputSnapshot input_{};
  UiLoopBackend backend_{};
  Surface output_{};
  uint8_t* storage_=nullptr;
  uint16_t touchX_=1920,touchY_=943;
  pthread_t thread_{};
  bool started_=false;
  uint64_t lastConsumer_=0;
  std::atomic<bool> stop_{false},paused_{false},failed_{false};
  std::atomic<double> speed_{1.0};
  std::atomic<uint64_t> polls_{0},scanouts_{0},frameSerial_{0},scanoutMicros_{0},maxScanoutMicros_{0};
  std::atomic<int> x_{0},y_{0};
  static void* entry(void* opaque);
  void run();
 public:
  NativeUiLoop()=default;
  ~NativeUiLoop();
  NativeUiLoop(const NativeUiLoop&)=delete;
  NativeUiLoop& operator=(const NativeUiLoop&)=delete;
  bool start(const Surface& initial,uint16_t touchX,uint16_t touchY,const UiLoopBackend& backend);
  void stop(); // join before freeing buffers or reusing controller/Presenter
  bool running() const {return started_;} // main-thread lifecycle only
  Surface beginFrame(); // main thread's exclusive normalized RGBA staging slot
  bool publishFrame();
  UiInputSnapshot consumeInput(); // latest sample; bounded wheel backlog
  void pauseInput(bool pause){paused_.store(pause);} // Also quiesce scanout for native IME.
  void setSpeed(double speed){speed_.store(speed);}
  UiLoopStats stats() const;
  bool setChrome(const char* wire){ChromeScene scene{};if(wire&&*wire&&!parse_chrome_scene(wire,scene))return false;chrome_.update(scene);return true;}
  bool takeChromeAction(char* out,size_t capacity){return chrome_.take(out,capacity);}
};
}
