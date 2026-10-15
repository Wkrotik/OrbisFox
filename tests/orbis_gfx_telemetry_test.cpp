#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
struct nsCString : std::string { using std::string::string; const char* get() const{return c_str();} };
using nsString=std::string;
static std::string NS_ConvertUTF16toUTF8(const nsString& text){return text;}
static bool XRE_IsParentProcess(){return true;}
#define MOZ_RELEASE_ASSERT(condition, ...) assert(condition)
static int fallback_logs;
static std::string fallback_message;
#define printf_stderr(format, message) do { ++fallback_logs; fallback_message=message; } while(0)
template<class T> struct nsCOMPtr {
    T* ptr;nsCOMPtr(T* p):ptr(p){}explicit operator bool() const{return ptr!=nullptr;}T* operator->() const{return ptr;}
};
template<class T> using RefPtr=nsCOMPtr<T>;
struct LayoutDeviceIntRect {int Width() const{return 1280;}int Height() const{return 720;}};
namespace widget {
    struct Screen {LayoutDeviceIntRect GetRect(){return {};}bool GetIsHDR(){return false;}};
    struct ScreenList : std::vector<Screen*> {uint32_t Length() const{return size();}};
    struct ScreenManager {
        Screen screen;ScreenList screens;
        ScreenManager(){screens.push_back(&screen);}
        static ScreenManager& GetSingleton(){static ScreenManager instance;return instance;}
        ScreenList& CurrentScreenList(){return screens;}
        Screen* GetPrimaryScreen(){return &screen;}
    };
}
// Host-only metric/screen/service doubles: tested production bodies below are
// extracted verbatim. These fixed test values are not console GPU evidence.
struct Metric {
    int writes=0;int64_t number=-1;
    void Set(int64_t value){++writes;number=value;}
    void Set(const std::string&){++writes;}
};
namespace mozilla::glean {
    namespace gfx_display {static Metric count,primary_height,primary_width;}
    namespace gfx {static Metric supports_hdr;}
    namespace gfx_status {static Metric headless;}
    namespace gfx_adapter_primary {
        static Metric description,vendor_id,device_id,subsystem_id,ram,driver_files,driver_vendor,driver_version,driver_date;
    }
}
namespace glean=mozilla::glean;
struct nsIGfxInfo {
    int queries=0,logs=0;std::string logged;
    void GetAdapterDescription(nsString& out){++queries;out="test adapter";}
    void GetAdapterVendorID(nsString& out){++queries;out="test vendor";}
    void GetAdapterDeviceID(nsString& out){++queries;out="test device";}
    void GetAdapterSubsysID(nsString& out){++queries;out="test subsystem";}
    void GetAdapterRAM(uint32_t* out){++queries;*out=123;}
    void GetAdapterDriver(nsString& out){++queries;out="test driver files";}
    void GetAdapterDriverVendor(nsString& out){++queries;out="test driver vendor";}
    void GetAdapterDriverVersion(nsString& out){++queries;out="test version";}
    void GetAdapterDriverDate(nsString& out){++queries;out="test date";}
    void LogFailure(const nsCString& text){++logs;logged=text;}
};
static nsIGfxInfo* service;
#define ORBISFOX_GFXINFO_SERVICE() service
#define do_GetService(contract) service
struct gfxPlatform {static bool IsHeadless(){return true;}static void ReportTelemetry();};
#include "gfx-telemetry-functions.inc"
int main(){
    for(int cycle=0;cycle<32;++cycle){
        namespace display=mozilla::glean::gfx_display;
        namespace adapter=mozilla::glean::gfx_adapter_primary;
        service=nullptr;auto count=display::count.writes;auto gpu=adapter::description.writes;
        auto headless=mozilla::glean::gfx_status::headless.writes;
        gfxPlatform::ReportTelemetry();
        assert(display::count.writes==count+1 && display::count.number==1);
        assert(display::primary_width.number==1280 && display::primary_height.number==720);
        assert(adapter::description.writes==gpu && adapter::vendor_id.writes==gpu);
        assert(mozilla::glean::gfx_status::headless.writes==headless+1);
        int old=fallback_logs;LogFailure(nsCString("real diagnostic fixture"));
        assert(fallback_logs==old+1 && fallback_message=="real diagnostic fixture");
        nsIGfxInfo info;service=&info;
        gfxPlatform::ReportTelemetry();assert(info.queries==9 && adapter::description.writes==gpu+1);
        assert(mozilla::glean::gfx_status::headless.writes==headless+2);
        LogFailure(nsCString("service diagnostic fixture"));assert(info.logs==1 && fallback_logs==old+1);
        service=nullptr;
    }
    puts("Actual graphics telemetry/logging: missing / present service, retained screen/headless metrics, no fabricated adapter metrics, preserved failures; 32 cycles PASS");
}
