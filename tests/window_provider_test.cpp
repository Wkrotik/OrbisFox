// Explicit Gecko/XPConnect type and lifetime doubles, not a real DOM host.
#include <cassert>
#include <cstdint>
#include <string>
#include <cstdio>
using nsresult=int;constexpr nsresult NS_OK=0,NS_ERROR_ABORT=1,NS_ERROR_INVALID_ARG=2;
#define NS_IMETHODIMP nsresult
#define NS_ENSURE_ARG_POINTER(x) if(!(x))return NS_ERROR_INVALID_ARG
#define NS_FAILED(x) ((x)!=NS_OK)
#define NS_IF_RELEASE(x) do{if(x){(x)->Release();(x)=nullptr;}}while(0)
#define NS_RELEASE(x) NS_IF_RELEASE(x)
void printf_stderr(const char*,...){}
using nsAString=std::string;using nsACString=std::string;
struct nsAutoCString:std::string{bool EqualsLiteral(const char* s)const{return *this==s;}};
struct nsIURI{std::string spec="chrome://orbisfox/content/browser.xhtml";nsresult GetSpec(nsAutoCString& out){out.assign(spec);return NS_OK;}};
struct nsDocShellLoadState{};
namespace mozilla::dom {struct UserActivation{struct Modifiers{};};}
namespace dom {
struct AutoNoJSAPI{AutoNoJSAPI(){}~AutoNoJSAPI(){}};
struct BrowsingContext{
 bool content=true,remote=false,subframes=false;int refs=1;
 bool IsContent(){return content;}void* GetDOMWindow(){return this;}
 nsresult GetUseRemoteTabs(bool* out){*out=remote;return NS_OK;}
 nsresult GetUseRemoteSubframes(bool* out){*out=subframes;return NS_OK;}
 void Release(){assert(refs>1);--refs;}
};}
struct nsIOpenWindowInfo{dom::BrowsingContext* parent=nullptr;bool print=false;dom::BrowsingContext* GetParent(){return parent;}bool GetIsForPrinting(){return print;}};
template<class T>struct RefPtr{T* p;RefPtr(T* value):p(value){}T* operator->(){return p;}operator bool(){return p;}operator T*(){return p;}};
template<class T>struct nsCOMPtr{T* p=nullptr;nsCOMPtr()=default;nsCOMPtr(T* value):p(value){}T* operator->(){return p;}operator bool(){return p;}operator T*(){return p;}};
template<class T>T** getter_AddRefs(nsCOMPtr<T>& p){return &p.p;}
struct NullPrincipal{static NullPrincipal* CreateWithoutOriginAttributes(){static NullPrincipal p;return &p;}};
struct Principal{bool system=true;bool IsSystemPrincipal(){return system;}};
struct Document{Principal principal;nsIURI uri;Principal* NodePrincipal(){return &principal;}nsIURI* GetDocumentURI(){return &uri;}};
struct nsIBrowserDOMWindow{
 static constexpr int OPEN_CURRENTWINDOW=1,OPEN_NEWTAB=3,OPEN_NEWTAB_BACKGROUND=5,OPEN_NEWTAB_FOREGROUND=6;
 static constexpr unsigned OPEN_NEW=0,OPEN_NO_OPENER=4,OPEN_NO_REFERRER=8;
 unsigned calls=0,lastFlags=0;int lastWhere=0;nsresult status=NS_OK;bool returnNull=false;
 nsIURI* lastURI=nullptr;nsIOpenWindowInfo* lastInfo=nullptr;dom::BrowsingContext result;
 nsresult CreateContentWindow(nsIURI* uri,nsIOpenWindowInfo* info,int where,unsigned flags,
     NullPrincipal* principal,void* policy,dom::BrowsingContext** out){
  assert(principal&&policy==nullptr);++calls;lastURI=uri;lastInfo=info;lastWhere=where;lastFlags=flags;
  if(!returnNull){++result.refs;*out=&result;}return status;
 }
};
struct mozIDOMWindowProxy{bool chrome=true,bridgeReady=true;Document document;nsIBrowserDOMWindow bridge;};
struct nsGlobalWindowOuter:mozIDOMWindowProxy{
 static nsGlobalWindowOuter* Cast(mozIDOMWindowProxy* p){return static_cast<nsGlobalWindowOuter*>(p);}
 bool IsChromeWindow(){return chrome;}Document* GetDoc(){return &document;}
 nsIBrowserDOMWindow* GetBrowserDOMWindow(){return bridgeReady?&bridge:nullptr;}
};
struct nsIWebBrowser{nsGlobalWindowOuter window;bool failed=false;nsresult GetContentDOMWindow(mozIDOMWindowProxy** out){if(failed)return NS_ERROR_ABORT;*out=&window;return NS_OK;}};
struct nsWindowWatcher{static inline int where=3;static int GetWindowOpenLocation(void*,unsigned,const mozilla::dom::UserActivation::Modifiers&,bool,bool){return where;}};
struct WebBrowserChrome2Stub{nsIWebBrowser* mBrowser=nullptr;
 nsresult ProvideWindow(nsIOpenWindowInfo*,uint32_t,bool,nsIURI*,const nsAString&,const nsACString&,
 const mozilla::dom::UserActivation::Modifiers&,bool,bool,bool,nsDocShellLoadState*,bool*,dom::BrowsingContext**);
};
// ACTUAL_PROVIDER_METHOD
int main(){
 for(unsigned cycle=0;cycle<32;++cycle){
  nsIWebBrowser browser;WebBrowserChrome2Stub provider;provider.mBrowser=&browser;
  dom::BrowsingContext parent;nsIOpenWindowInfo info{&parent,false};nsIURI uri;uri.spec="https://example.com/";
  bool fresh=true;dom::BrowsingContext* context=nullptr;
  auto call=[&](bool noOpener=false,bool noReferrer=false){context=nullptr;fresh=true;return provider.ProvideWindow(&info,0,true,&uri,"","",{},noOpener,noReferrer,false,nullptr,&fresh,&context);};
  for(int location:{0,1,2,3,5,6,7}){
   nsWindowWatcher::where=location;assert(call(true,true)==NS_OK);assert(context&&fresh==(location!=1));
   assert(browser.window.bridge.lastFlags==12&&browser.window.bridge.lastInfo==&info&&browser.window.bridge.lastURI==&uri);
   assert(browser.window.bridge.lastWhere==((location==1||location==5||location==6)?location:3));
   NS_RELEASE(context);
  }
  auto reject=[&]{assert(call()==NS_ERROR_ABORT&&context==nullptr&&!fresh);assert(browser.window.bridge.result.refs==1);};
  browser.window.chrome=false;reject();browser.window.chrome=true;
  browser.window.document.principal.system=false;reject();browser.window.document.principal.system=true;
  browser.window.document.uri.spec="https://example.com/";reject();browser.window.document.uri.spec="chrome://orbisfox/content/browser.xhtml";
  browser.window.bridgeReady=false;reject();browser.window.bridgeReady=true;
  browser.failed=true;reject();browser.failed=false;
  info.print=true;reject();info.print=false;
  parent.content=false;reject();parent.content=true;
  browser.window.bridge.status=NS_ERROR_ABORT;reject();browser.window.bridge.status=NS_OK;
  browser.window.bridge.returnNull=true;reject();browser.window.bridge.returnNull=false;
  browser.window.bridge.result.remote=true;reject();browser.window.bridge.result.remote=false;
  browser.window.bridge.result.subframes=true;reject();browser.window.bridge.result.subframes=false;
  browser.window.bridge.result.content=false;reject();browser.window.bridge.result.content=true;
  provider.mBrowser=nullptr;reject();provider.mBrowser=&browser;
 }
 puts("Actual extracted native window-provider:32 cycles, chrome/principal/URI/content/remoteness guards, opener/referrer flags, cancellation ownership, window-location routing PASS; explicit Gecko doubles, not full WindowWatcher/firmware proof");
}
