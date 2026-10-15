#include <cassert>
#include <cstdio>
enum class ExplicitActiveStatus {None, Active, Inactive};
struct WindowContext {bool current=true;bool IsCurrent() const{return current;}};
// Host boundary fields only. The getter below is actual pinned Gecko code;
// this test demonstrates policy, not parent-process IPC setter integration.
struct BrowsingContext {
    BrowsingContext* parent=nullptr;WindowContext* mParentWindow=nullptr;
    ExplicitActiveStatus explicitStatus=ExplicitActiveStatus::None;bool pip=false;
    bool GetControlsDocumentPiP() const{return pip;}
    bool IsTop() const{return parent==nullptr;}
    ExplicitActiveStatus GetExplicitActive() const{return explicitStatus;}
    const BrowsingContext* GetParent() const{return parent;}
    bool IsActive() const;
};
#define MOZ_ASSERT(condition,...) assert(condition)
#include "activeness-function.inc"
int main(){
    for(int cycle=0;cycle<32;++cycle){
        BrowsingContext root;assert(!root.IsActive());
        root.explicitStatus=ExplicitActiveStatus::Active;assert(root.IsActive());
        BrowsingContext child;child.parent=&root;assert(child.IsActive());
        child.explicitStatus=ExplicitActiveStatus::Inactive;assert(!child.IsActive());
        child.explicitStatus=ExplicitActiveStatus::None;
        WindowContext window;window.current=false;child.mParentWindow=&window;assert(!child.IsActive());
        window.current=true;assert(child.IsActive());
        root.explicitStatus=ExplicitActiveStatus::Inactive;assert(!root.IsActive());assert(!child.IsActive());
        root.pip=true;assert(root.IsActive());assert(child.IsActive());
    }
    puts("Actual BrowsingContext activeness getter: independent inactive / active / inactive / inherited / stale window / PiP, 32 cycles PASS");
}
