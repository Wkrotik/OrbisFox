#include <cassert>
#include <functional>
#include <cstdint>
#include <vector>
static double fakeMilliseconds=0;
struct TimeStamp {
 double value;
 static TimeStamp Now(){return {fakeMilliseconds};}
 TimeStamp operator-(TimeStamp other)const{return {value-other.value};}
 double ToMilliseconds()const{return value;}
};
struct Callbacks {void* context=nullptr;bool(*pointerEvent)(void*,int32_t*,int32_t*,bool*,uint32_t*)=nullptr;} sCallbacks;
struct Edge {int32_t x,y;bool down;uint32_t button=1;};
struct EdgeQueue {std::vector<Edge> edges;size_t next=0;};
bool edgeCallback(void* opaque,int32_t* x,int32_t* y,bool* down,uint32_t* button){auto& q=*static_cast<EdgeQueue*>(opaque);if(q.next==q.edges.size())return false;const auto& e=q.edges[q.next++];*x=e.x;*y=e.y;*down=e.down;*button=e.button;return true;}
using nsresult=int;
#define NS_IMETHODIMP nsresult
#define NS_ERROR_NOT_SAME_THREAD 1
#define NS_ERROR_INVALID_ARG 2
#define NS_OK 0
#define NS_ENSURE_TRUE(value,error) do{if(!(value))return error;}while(0)
#define MOZ_TRY(value) do{const auto result=(value);if(result)return result;}while(0)
bool NS_IsMainThread(){return true;}
struct LayoutDeviceIntPoint {int x,y;};
enum class MouseButton {ePrimary,eMiddle,eNotPressed};
struct nsIWidget {
  enum class NativeMouseMessage {ButtonDown,ButtonUp,Move};
  enum class NativeModifiers {NO_MODIFIERS};
  std::function<void(NativeMouseMessage)> callback;
  unsigned up=0,down=0,moves=0,depth=0,middleUp=0,middleDown=0;
  int SynthesizeNativeMouseEvent(LayoutDeviceIntPoint,NativeMouseMessage message,MouseButton button,NativeModifiers,void*) {
    assert(++depth<4);
    if(button==MouseButton::eMiddle){if(message==NativeMouseMessage::ButtonDown)++middleDown;if(message==NativeMouseMessage::ButtonUp)++middleUp;}
    if(message==NativeMouseMessage::ButtonUp)++up;
    if(message==NativeMouseMessage::ButtonDown)++down;
    if(message==NativeMouseMessage::Move)++moves;
    if(callback)callback(message);--depth;return 0;
  }
};
class TestHost {
public:
  bool mPointerEnabled=true,mMouseDown=false,mMiddleDown=false;
  unsigned mPointerButtons=0,mButtons=0;int mCursorX=40,mCursorY=40;
  nsIWidget* mWidget;
  explicit TestHost(nsIWidget& w):mWidget(&w){}
  nsresult SetPointerInputEnabled(bool);
  nsresult pump(unsigned buttons,bool move=false) {
    const unsigned oldButtons=mPointerButtons;const int oldX=mCursorX,oldY=mCursorY;
    if(move)++mCursorX;mButtons=buttons;auto* widget=mWidget;
#include "pump-input.inc"
    return 0;
  }
};
#include "set-pointer.inc"
int main(){
  using Msg=nsIWidget::NativeMouseMessage;
  for(unsigned cycle=0;cycle<32;++cycle){
    nsIWidget widget;TestHost host(widget);unsigned activations=0;
    widget.callback=[&](Msg msg){if(msg==Msg::ButtonUp){++activations;assert(!host.mMouseDown);assert(host.SetPointerInputEnabled(false)==0);assert(host.SetPointerInputEnabled(true)==0);}};
    assert(!host.pump(1));assert(!host.pump(0));assert(activations==1&&widget.up==1&&widget.down==1);
    assert(!host.pump(0));assert(activations==1);
    assert(!host.pump(1));assert(!host.SetPointerInputEnabled(false));assert(activations==2&&widget.up==2);
    assert(!host.pump(1));assert(!host.pump(0));assert(activations==2); // held re-enable isn't a new click
    widget.callback=nullptr;host.SetPointerInputEnabled(true);host.pump(1);
    widget.callback=[&](Msg msg){if(msg==Msg::ButtonUp){assert(!host.mMouseDown);host.SetPointerInputEnabled(false);}};
    host.pump(9);const auto releases=widget.up;assert(!host.mPointerEnabled);host.SetPointerInputEnabled(true);host.pump(9);assert(widget.up==releases);
    host.pump(0);widget.callback=[&](Msg msg){if(msg==Msg::Move)host.SetPointerInputEnabled(false);};
    const auto downs=widget.down;host.pump(1,true);assert(widget.down==downs&&!host.mPointerEnabled);
  }
  for(unsigned cycle=0;cycle<32;++cycle){
    nsIWidget widget;TestHost host(widget);EdgeQueue queue{{{120,300,true},{120,300,false}},0};sCallbacks={&queue,edgeCallback};
    unsigned activations=0;widget.callback=[&](Msg msg){if(msg==Msg::ButtonUp){++activations;assert(!host.mMouseDown);host.SetPointerInputEnabled(false);host.SetPointerInputEnabled(true);}};
    assert(!host.pump(0));assert(widget.down==1&&widget.up==1&&activations==1&&!host.mMouseDown);
    assert(!host.pump(0));assert(activations==1);
    queue={{{120,300,true},{120,300,false}},0};host.SetPointerInputEnabled(false);assert(!host.pump(0));assert(queue.next==2&&activations==1);
    host.SetPointerInputEnabled(true);queue={{{1280,0,true}},0};assert(host.pump(0)==NS_ERROR_INVALID_ARG);
    sCallbacks={};
  }
  // A slow handler yields between complete edges, never consuming queued input
  // or applying a newer polled release ahead of an older queued press.
  for(unsigned button: {1u,8192u}){
    nsIWidget widget;TestHost host(widget);
    EdgeQueue queue{{{120,300,true,button},{120,300,false,button},{120,300,true,button},{120,300,false,button}},0};
    sCallbacks={&queue,edgeCallback};fakeMilliseconds=0;
    widget.callback=[&](Msg msg){if(msg==Msg::Move)fakeMilliseconds+=5;};
    for(unsigned i=1;i<=4;++i){
      assert(!host.pump(0));assert(queue.next==i);
      assert(widget.down==(i+1)/2&&widget.up==i/2);
      assert((button==1?host.mMouseDown:host.mMiddleDown)==bool(i%2));
    }
    assert(!host.pump(0));assert(widget.down==2&&widget.up==2);
    sCallbacks={};
  }
  // Even cheap queues retain FIFO ownership across the existing 16-edge cap.
  {
    nsIWidget widget;TestHost host(widget);EdgeQueue queue;
    for(unsigned i=0;i<18;++i)queue.edges.push_back({120,300,bool(!(i%2))});
    sCallbacks={&queue,edgeCallback};assert(!host.pump(1));
    assert(queue.next==16&&widget.down==8&&widget.up==8&&!host.mMouseDown);
    assert(!host.pump(0));assert(queue.next==18&&widget.down==9&&widget.up==9);
    sCallbacks={};
  }
  // Real middle edges use independent ownership and survive delayed polling.
  nsIWidget widget;TestHost host(widget);EdgeQueue middle{{{200,300,true,8192},{200,300,false,8192}},0};sCallbacks={&middle,edgeCallback};
  widget.callback=[&](Msg msg){if(msg==Msg::ButtonUp){assert(!host.mMiddleDown);host.SetPointerInputEnabled(false);host.SetPointerInputEnabled(true);}};
  assert(!host.pump(0));assert(widget.down==1&&widget.up==1&&widget.middleDown==1&&widget.middleUp==1&&!host.mMiddleDown);
  sCallbacks={};widget.callback=nullptr;host.pump(8192);assert(host.mMiddleDown);host.SetPointerInputEnabled(false);assert(!host.mMiddleDown&&widget.up==2);
}
