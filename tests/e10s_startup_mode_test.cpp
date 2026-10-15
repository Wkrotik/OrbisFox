#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
// Boundary doubles only; policy/caching function included from pinned Gecko.
static bool parentProcess = true;
static bool nonLocalConnectionsDisabled = false;
static bool gBrowserTabsRemoteAutostartInitialized = false;
static bool gBrowserTabsRemoteAutostart = false;
enum E10sStatus {kE10sEnabledByDefault, kE10sForceDisabled};
static E10sStatus gBrowserTabsRemoteStatus = kE10sEnabledByDefault;
static bool XRE_IsParentProcess() {return parentProcess;}
static const char* PR_GetEnv(const char* key) {return std::getenv(key);}
namespace xpc {static bool AreNonLocalConnectionsDisabled() {return nonLocalConnectionsDisabled;}}
#include "e10s-policy.inc"
static void reset(bool parent=true, bool offline=false) {
    parentProcess=parent; nonLocalConnectionsDisabled=offline;
    gBrowserTabsRemoteAutostartInitialized=false;gBrowserTabsRemoteAutostart=false;
}
int main() {
    for (int cycle=0;cycle<32;++cycle) {
        for (bool offline:{false,true}) {
            reset(true,offline);unsetenv("MOZ_FORCE_DISABLE_E10S");
            assert(BrowserTabsRemoteAutostart());
            assert(setenv("MOZ_FORCE_DISABLE_E10S","1",1)==0);
            assert(BrowserTabsRemoteAutostart()); // too late: cached true
            reset(true,offline);
#ifdef MOZILLA_OFFICIAL
            const bool expectedRemote=!offline;
#else
            const bool expectedRemote=false;
#endif
            assert(BrowserTabsRemoteAutostart()==expectedRemote);
            assert(gBrowserTabsRemoteStatus==(expectedRemote?kE10sEnabledByDefault:kE10sForceDisabled));
            unsetenv("MOZ_FORCE_DISABLE_E10S");
            assert(BrowserTabsRemoteAutostart()==expectedRemote); // cached
            for (const char* value:{"0","true","01",""}) {
                reset(true,offline);assert(setenv("MOZ_FORCE_DISABLE_E10S",value,1)==0);
                assert(BrowserTabsRemoteAutostart());
            }
            reset(false,offline);assert(setenv("MOZ_FORCE_DISABLE_E10S","1",1)==0);
            assert(BrowserTabsRemoteAutostart()); // child process stays remote
        }
    }
    unsetenv("MOZ_FORCE_DISABLE_E10S");
    puts("Actual pinned E10s startup policy: supported switch / exact value / caching / parent vs child / official restrictions, 32 cycles PASS");
}
