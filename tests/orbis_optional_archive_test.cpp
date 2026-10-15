#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <string>
using nsresult=int32_t;
constexpr nsresult NS_OK=0, NS_ERROR_FAILURE=-1;
#define NS_SUCCEEDED(rv) ((rv)>=0)
#define NS_FAILED(rv) ((rv)<0)
#define printf_stderr(...) ((void)0)
using nsCString=std::string;
template<class T> struct RefPtr {
    T* ptr; RefPtr(T* p):ptr(p){} operator T*() const{return ptr;}
    explicit operator bool() const{return ptr!=nullptr;} T* operator->() const{return ptr;}
};
template<class T> using nsCOMPtr=RefPtr<T>;
// Host-only archive/cache boundary doubles. The tested scanner body is the
// actual patched source; no XPCOM archive implementation or rendering claim.
static int finds, nexts, destroyed, appends, metadata_reads, cache_reads;
static bool last_changed;
struct nsZipFind {
    bool emitted=false;
    nsresult FindNext(const char** path,uint16_t* len) {
        ++nexts;if(emitted)return NS_ERROR_FAILURE;emitted=true;
        *path="res/fonts/fixture.ttf";*len=uint16_t(std::strlen(*path));return NS_OK;
    }
    ~nsZipFind(){++destroyed;}
};
struct nsZipArchive {
    bool fail=false;
    nsresult FindInit(const char* pattern,nsZipFind** out) {
        ++finds;assert(std::string(pattern)=="res/fonts/*.ttf$");
        *out=nullptr;if(fail)return NS_ERROR_FAILURE;*out=new nsZipFind;return NS_OK;
    }
};
struct nsIFile {
    int64_t time=5;bool fail=false;
    nsresult GetLastModifiedTime(int64_t* out){++metadata_reads;if(fail)return NS_ERROR_FAILURE;*out=time;return NS_OK;}
};
namespace Omnijar {
    enum class Type{GRE}; static nsZipArchive* reader;static nsIFile* file;
    static nsZipArchive* GetReader(Type){return reader;}
    static nsIFile* GetPath(Type){return file;}
}
namespace mozilla::scache {
    struct StartupCache {
        bool fail=false;uint32_t length=8;int64_t time=5;
        static StartupCache* instance;
        static StartupCache* GetSingleton(){return instance;}
        nsresult GetBuffer(const char*,const char** out,uint32_t* len){
            ++cache_reads;if(fail)return NS_ERROR_FAILURE;*out=reinterpret_cast<const char*>(&time);*len=length;return NS_OK;
        }
    };
    StartupCache* StartupCache::instance=nullptr;
}
namespace LittleEndian {static int64_t readInt64(const char* p){int64_t v;std::memcpy(&v,p,8);return v;}}
static const char* JAR_LAST_MODIFED_TIME="fixture-time";
struct FontNameCache{};
struct gfxFT2FontList {
    int64_t mJarModifiedTime=0;
    void FindFontsInOmnijar(FontNameCache*);
    void AppendFacesFromOmnijarEntry(nsZipArchive* reader,const nsCString& name,FontNameCache*,bool changed){
        assert(reader && name=="res/fonts/fixture.ttf");++appends;last_changed=changed;
    }
};
#include "optional-archive-function.inc"
static void reset(){finds=nexts=destroyed=appends=metadata_reads=cache_reads=0;last_changed=false;}
int main(){
    gfxFT2FontList fonts;FontNameCache names;nsZipArchive archive;nsIFile file;mozilla::scache::StartupCache cache;
    for(int cycle=0;cycle<32;++cycle){
        reset();Omnijar::reader=nullptr;Omnijar::file=nullptr;mozilla::scache::StartupCache::instance=&cache;
        fonts.FindFontsInOmnijar(&names);assert(finds==0 && cache_reads==0 && metadata_reads==0 && appends==0);
        reset();Omnijar::reader=&archive;mozilla::scache::StartupCache::instance=nullptr;
        fonts.FindFontsInOmnijar(&names);assert(finds==1 && appends==1 && nexts==2 && destroyed==1 && !last_changed);
        reset();mozilla::scache::StartupCache::instance=&cache;
        fonts.FindFontsInOmnijar(&names);assert(appends==1 && last_changed && metadata_reads==0);
        reset();Omnijar::file=&file;file.fail=true;
        fonts.FindFontsInOmnijar(&names);assert(appends==1 && last_changed && metadata_reads==1);
        reset();file.fail=false;file.time=cache.time;
        fonts.FindFontsInOmnijar(&names);assert(appends==1 && !last_changed);
        reset();file.time=cache.time+1;
        fonts.FindFontsInOmnijar(&names);assert(appends==1 && last_changed);
        reset();cache.length=4;
        fonts.FindFontsInOmnijar(&names);assert(appends==1 && !last_changed && metadata_reads==0);cache.length=8;
        reset();archive.fail=true;
        fonts.FindFontsInOmnijar(&names);assert(finds==1 && appends==0 && destroyed==0);archive.fail=false;
    }
    puts("Actual optional font-archive scanner: absent / valid / metadata absent or failed / cache changed / bad cache / enumeration failure / cleanup, 32 cycles PASS");
}
