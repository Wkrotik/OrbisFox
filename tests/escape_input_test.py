"""Compile actual Escape/Enter dispatch against explicit event/widget doubles."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EscapeInputTests(unittest.TestCase):
    def test_actual_methods_dispatch_trusted_keys_and_respect_cancellation_and_thread(self):
        source = (ROOT / 'gecko/widget/orbis/OrbisFoxHost.cpp').read_text()
        start = source.index('NS_IMETHODIMP OrbisFoxHost::SendEscape()')
        end = source.index('\nNS_IMETHODIMP OrbisFoxHost::SetPointerInputEnabled', start)
        method = source[start:end]
        compiler = shutil.which('clang++')
        self.assertIsNotNone(compiler)
        fixture = r'''
#include <cassert>
#include <initializer_list>
#include <vector>
#define NS_IMETHODIMP int
#define NS_ENSURE_TRUE(value,error) do {if(!(value))return error;} while(0)
constexpr int NS_OK=0,NS_ERROR_NOT_SAME_THREAD=1,NS_ERROR_NOT_INITIALIZED=2;
bool mainThread=true;bool NS_IsMainThread(){return mainThread;}
enum EventMessage{eKeyDown,eKeyPress,eKeyUp};
constexpr int KEY_NAME_INDEX_Escape=100,CODE_NAME_INDEX_Escape=200;
constexpr int KEY_NAME_INDEX_Enter=101,CODE_NAME_INDEX_Enter=201;
struct nsIWidget;
template<class T> using nsCOMPtr=T*;
struct WidgetKeyboardEvent {
 bool trusted;EventMessage message;nsIWidget* widget;
 int mKeyCode=0,mKeyNameIndex=0,mCodeNameIndex=0;
 struct {bool mDefaultPrevented=false;} mFlags;
 WidgetKeyboardEvent(bool t,EventMessage m,nsIWidget* w):trusted(t),message(m),widget(w){}
};
struct nsIWidget {
 std::vector<WidgetKeyboardEvent> events;bool cancelDown=false;
 int DispatchEvent(WidgetKeyboardEvent* event){events.push_back(*event);event->mFlags.mDefaultPrevented=cancelDown&&event->message==eKeyDown;return 1;}
};
struct OrbisFoxHost {nsIWidget* mWidget=nullptr;int SendEscape();int SendEnter();};
'''
        test = r'''
int main(){
 for(int cycle=0;cycle<32;++cycle){
  nsIWidget widget;OrbisFoxHost host{&widget};
  mainThread=false;assert(host.SendEscape()==NS_ERROR_NOT_SAME_THREAD&&widget.events.empty());mainThread=true;
  host.mWidget=nullptr;assert(host.SendEscape()==NS_ERROR_NOT_INITIALIZED&&widget.events.empty());host.mWidget=&widget;
  assert(host.SendEscape()==NS_OK&&widget.events.size()==2);
  assert(widget.events[0].message==eKeyDown&&widget.events[1].message==eKeyUp);
  for(const auto& event:widget.events)assert(event.trusted&&event.widget==&widget&&event.mKeyCode==27&&event.mKeyNameIndex==KEY_NAME_INDEX_Escape&&event.mCodeNameIndex==CODE_NAME_INDEX_Escape);
  widget.events.clear();mainThread=false;assert(host.SendEnter()==NS_ERROR_NOT_SAME_THREAD&&widget.events.empty());mainThread=true;
  host.mWidget=nullptr;assert(host.SendEnter()==NS_ERROR_NOT_INITIALIZED&&widget.events.empty());host.mWidget=&widget;
  assert(host.SendEnter()==NS_OK&&widget.events.size()==3);
  assert(widget.events[0].message==eKeyDown&&widget.events[1].message==eKeyPress&&widget.events[2].message==eKeyUp);
  for(const auto& event:widget.events)assert(event.trusted&&event.widget==&widget&&event.mKeyCode==13&&event.mKeyNameIndex==KEY_NAME_INDEX_Enter&&event.mCodeNameIndex==CODE_NAME_INDEX_Enter);
  widget.events.clear();widget.cancelDown=true;assert(host.SendEnter()==NS_OK&&widget.events.size()==2);
  assert(widget.events[0].message==eKeyDown&&widget.events[1].message==eKeyUp);
 }
}
'''
        with tempfile.TemporaryDirectory(prefix='orbisfox-escape-') as temporary:
            directory = Path(temporary)
            cpp, exe = directory / 'test.cpp', directory / 'test'
            cpp.write_text(fixture + method + test)
            subprocess.run([compiler, '-std=c++20', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', str(cpp), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
