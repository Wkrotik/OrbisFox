#include <cassert>
#include <cstdio>
// Field/DOM boundary doubles. Eligibility function is actual pinned Gecko code.
namespace mozilla {enum class LogLevel {Warning};}
#define MOZ_LOG(...) ((void)0)
#define NS_WARN_IF(condition) (condition)
static int gProcessIsolationLog = 0;
struct Element {bool mayChange=false;bool HasAttribute(const char16_t*) const{return mayChange;}};
const char16_t* operator ""_ns(const char16_t* value, unsigned long) {return value;}
struct WindowGlobalParent {bool inProcess=false;bool IsInProcess() const{return inProcess;}};
struct CanonicalBrowsingContext {
    bool content=true, remoteSubframes=false, windowless=false;Element* embedder=nullptr;
    bool IsContent() const{return content;}
    bool UseRemoteSubframes() const{return remoteSubframes;}
    CanonicalBrowsingContext* Top(){return this;}
    Element* GetEmbedderElement() const{return embedder;}
    bool Windowless() const{return windowless;}
};
#include "process-switch-policy.inc"
int main(){
    for(int cycle=0;cycle<32;++cycle){
        CanonicalBrowsingContext context;
        assert(ContextCanProcessSwitch(&context,nullptr,false)); // former bridge: missing embedder assumed switchable
        context.windowless=true;
        assert(!ContextCanProcessSwitch(&context,nullptr,false)); // supported standalone mode
        assert(ContextCanProcessSwitch(&context,nullptr,true)); // new tabs retain engine policy
        assert(!ContextCanProcessSwitch(nullptr,nullptr,false));
        context.content=false;assert(!ContextCanProcessSwitch(&context,nullptr,false));context.content=true;
        Element element;context.embedder=&element;
        assert(!ContextCanProcessSwitch(&context,nullptr,false));
        element.mayChange=true;assert(ContextCanProcessSwitch(&context,nullptr,false));
        WindowGlobalParent parent;assert(!ContextCanProcessSwitch(&context,&parent,false));
        context.remoteSubframes=true;assert(ContextCanProcessSwitch(&context,&parent,false));
        parent.inProcess=true;assert(!ContextCanProcessSwitch(&context,&parent,false));
    }
    puts("Actual process-switch eligibility: standalone / missing embedder / normal browser / chrome / subframes / new-tab policy, 32 cycles PASS");
}
