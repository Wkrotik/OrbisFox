#include "orbisfox/native_chrome.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#ifdef ORBISFOX_FULL_GECKO
#define STB_TRUETYPE_IMPLEMENTATION
#include <stb/stb_truetype.h>
#endif
namespace orbisfox {
namespace {
#ifdef ORBISFOX_FULL_GECKO
unsigned char fontPixels[512*512]{};stbtt_bakedchar fontChars[96]{};bool fontReady=false;
#endif
void chromeText(Surface s,int x,int y,const char* value,int scale,Color c){
#ifdef ORBISFOX_FULL_GECKO
 if(fontReady){
  float pen=float(x),baseline=float(y+18);
  for(const unsigned char* p=reinterpret_cast<const unsigned char*>(value);*p;++p){
   const unsigned ch=*p>=32&&*p<128?*p:'?';stbtt_aligned_quad q{};stbtt_GetBakedQuad(fontChars,512,512,int(ch-32),&pen,&baseline,&q,1);
   for(int yy=int(q.y0);yy<int(q.y1);++yy)for(int xx=int(q.x0);xx<int(q.x1);++xx){
    if(xx<0||yy<0||xx>=s.width||yy>=s.height)continue;
    const int tx=int(q.s0*512)+xx-int(q.x0),ty=int(q.t0*512)+yy-int(q.y0);
    if(tx<0||ty<0||tx>=512||ty>=512)continue;
    const unsigned a=fontPixels[ty*512+tx];auto* pixel=s.pixels+size_t(yy)*s.stride+size_t(xx)*4;
    pixel[0]=uint8_t((c.r*a+pixel[0]*(255-a))/255);pixel[1]=uint8_t((c.g*a+pixel[1]*(255-a))/255);pixel[2]=uint8_t((c.b*a+pixel[2]*(255-a))/255);pixel[3]=255;
   }
  }return;
 }
#endif
 text(s,x,y,value,scale,c);
}
struct Lock {pthread_mutex_t& m;explicit Lock(pthread_mutex_t& value):m(value){if(pthread_mutex_lock(&m))__builtin_trap();}~Lock(){if(pthread_mutex_unlock(&m))__builtin_trap();}};
bool id(const char* text,size_t length){if(!length||length>=32)return false;for(size_t i=0;i<length;++i)if(!((text[i]>='a'&&text[i]<='z')||(text[i]>='0'&&text[i]<='9')||text[i]=='-'))return false;return true;}
bool field(const char*& p,char* out,size_t capacity){const char* end=strchr(p,'|');if(!end)return false;size_t n=size_t(end-p);if(n>=capacity)return false;memcpy(out,p,n);out[n]=0;p=end+1;return true;}
bool integer(const char*& p,int& result,char delimiter){if(!*p)return false;char* end=nullptr;const long value=strtol(p,&end,10);if(end==p||*end!=delimiter||value<0||value>4096)return false;result=int(value);p=end+1;return true;}
bool contains(const ChromeControl& c,int x,int y){return x>=c.x&&x<c.x+c.width&&y>=c.y&&y<c.y+c.height;}
constexpr int menuX=900,menuY=105,menuWidth=365,rowHeight=42,menuRows=10,menuPadding=8,zoomRow=6;
constexpr const char* menuLabels[]={"New Tab","Home","Fullscreen","Bookmarks","History","Find in Page","","Close Current Tab","Settings","Quit"};
constexpr int menuCommands[]={8,4,30,32,33,38,41,35,34,36};
}
bool prepare_native_chrome_font(const char* path){
#ifdef ORBISFOX_FULL_GECKO
 if(fontReady)return true;
 FILE* file=fopen(path,"rb");if(!file)return false;
 if(fseek(file,0,SEEK_END)){fclose(file);return false;}long bytes=ftell(file);
 if(bytes<=0||bytes>4*1024*1024||fseek(file,0,SEEK_SET)){fclose(file);return false;}
 auto* data=static_cast<unsigned char*>(malloc(size_t(bytes)));if(!data){fclose(file);return false;}
 bool loaded=fread(data,1,size_t(bytes),file)==size_t(bytes);fclose(file);
 fontReady=loaded&&stbtt_BakeFontBitmap(data,0,20,fontPixels,512,512,32,96,fontChars)>0;free(data);return fontReady;
#else
 (void)path;return true;
#endif
}
bool parse_chrome_scene(const char* wire,ChromeScene& result){
 if(!wire||strnlen(wire,4097)>4096)return false;
 ChromeScene next{};const char* p=wire;int version=0,fullscreen=0,web=0;
 if(!integer(p,version,'|')||(version!=1&&version!=2)||!integer(p,fullscreen,'|')||fullscreen>1||!integer(p,web,'|')||web>1)return false;
 if(!field(p,next.active,sizeof(next.active))||!id(next.active,strlen(next.active)))return false;
 for(auto& tab:next.tabs)if(!field(p,tab,sizeof(tab))||(*tab&&!id(tab,strlen(tab))))return false;
 if(version==2){int zoom=0;if(!integer(p,zoom,'|')||zoom<50||zoom>200||zoom%10)return false;next.zoom=unsigned(zoom);}
 bool active=false;for(auto& tab:next.tabs)if(*tab&&!strcmp(tab,next.active))active=true;if(!active)return false;
 while(*p){
  if(next.count==20)return false;
  ChromeControl c{};int enabled=0;
  if(!integer(p,c.command,',')||!integer(p,c.x,',')||!integer(p,c.y,',')||!integer(p,c.width,',')||!integer(p,c.height,',')||!integer(p,enabled,';'))return false;
  if(c.command<1||c.command>46||enabled>1||c.x+c.width>1280||c.y+c.height>720||!c.width||!c.height)return false;
  if(!((c.command>=1&&c.command<=8)||(c.command>=10&&c.command<=12)||(c.command>=20&&c.command<=22)||(c.command>=43&&c.command<=46)))return false;
  if(c.command<43 ? c.y+c.height>104 : c.y<650)return false;
  for(unsigned i=0;i<next.count;++i)if(next.controls[i].command==c.command)return false;
  c.enabled=enabled;next.controls[next.count++]=c;
 }
 next.enabled=true;next.fullscreen=fullscreen;next.web=web;result=next;return true;
}
NativeChrome::~NativeChrome(){if(pthread_mutex_destroy(&mutex_))__builtin_trap();}
void NativeChrome::update(const ChromeScene& scene){Lock lock(mutex_);bool changed=strcmp(scene_.active,scene.active)||scene_.count!=scene.count;for(unsigned i=0;i<scene.count&&!changed;++i){const auto& a=scene_.controls[i];const auto& b=scene.controls[i];changed=a.command!=b.command||a.x!=b.x||a.y!=b.y||a.width!=b.width||a.height!=b.height||a.enabled!=b.enabled;}if(changed&&!menu_)pressed_=-1;scene_=scene;if(!scene.enabled){head_=count_=0;menu_=swallowPrimary_=swallowMiddle_=overflow_=false;pressed_=-1;*desiredTab_=0;}if(*desiredTab_&&!strcmp(desiredTab_,scene.active))*desiredTab_=0;++revision_;}
bool NativeChrome::push(int command,const char* target){
 if(count_==16){overflow_=true;return false;}
 snprintf(actions_[(head_+count_)%16],48,"%d:%s",command,target?target:"");++count_;return true;
}
void NativeChrome::activate(int command){
 if(command==6){menu_=!menu_;menuFocus_=0;keyboardMenu_=false;pressed_=-1;return;}
 if(command==31&&!scene_.web)return;
 const char* target=nullptr;
 if(command>=10&&command<=12){target=scene_.tabs[command-10];if(!*target)return;}
 else if(command>=20&&command<=22){target=scene_.tabs[command-20];if(!*target)return;}
 else if(command==35)target=*desiredTab_?desiredTab_:scene_.active;
 if(push(command,target)&&command>=10&&command<=12)snprintf(desiredTab_,sizeof(desiredTab_),"%s",target);
 if(command<39||command>41){menu_=false;pressed_=-1;}
}
uint32_t NativeChrome::input(uint32_t buttons,int x,int y){
 Lock lock(mutex_);if(!scene_.enabled){previous_=buttons;return 0;}
 const uint32_t pressed=buttons&~previous_,released=previous_&~buttons;previous_=buttons;
 if(x!=menuPointerX_||y!=menuPointerY_)keyboardMenu_=false;
 menuPointerX_=x;menuPointerY_=y;
 const int oldHover=hover_;const bool oldMenu=menu_;const unsigned oldFocus=menuFocus_;uint32_t mask=8|512|1024|2048|4096|16|16384;hover_=-1;
 if(pressed&16){if(menu_){menu_=false;pressed_=-1;}else activate(scene_.fullscreen?30:42);}
 if(pressed&2048)activate(2); // R2: Forward.
 if(pressed&4096)activate(1); // L2: Back.
 if(pressed&16384)activate(38); // L3: Find in page.
 if(pressed&8){if(scene_.fullscreen)activate(30);else{activate(6);if(menu_)keyboardMenu_=true;}mask|=8;}
 if(menu_){
  mask=32767;
  if(pressed&16)menu_=false;
  if(pressed&128){menuFocus_=(menuFocus_+menuRows-1)%menuRows;keyboardMenu_=true;}
  if(pressed&256){menuFocus_=(menuFocus_+1)%menuRows;keyboardMenu_=true;}
  if(!keyboardMenu_&&x>=menuX&&x<menuX+menuWidth&&y>=menuY+menuPadding&&y<menuY+menuPadding+menuRows*rowHeight)hover_=int((y-menuY-menuPadding)/rowHeight);
  if((keyboardMenu_?int(menuFocus_):hover_)==zoomRow&&(pressed&(32|64)))activate(pressed&32?39:40);
  if(pressed&1){swallowPrimary_=true;pressed_=keyboardMenu_?int(menuFocus_):hover_;if(pressed_<0)menu_=false;}
  if((released&1)&&swallowPrimary_&&pressed_>=0){const int row=pressed_;pressed_=-1;if(keyboardMenu_||row==hover_){const int command=row!=zoomRow?menuCommands[row]:keyboardMenu_?41:x<menuX+menuWidth/3?39:x>=menuX+menuWidth*2/3?40:41;activate(command);}}
 }else{
  for(unsigned i=0;i<scene_.count;++i)if(contains(scene_.controls[i],x,y)){hover_=int(i);break;}
  if((pressed&8192)&&hover_>=0){const auto& c=scene_.controls[hover_];if(c.command>=10&&c.command<=12){swallowMiddle_=true;activate(c.command+10);}}
  if((pressed&1)&&hover_>=0){swallowPrimary_=true;pressed_=hover_;}
  if((released&1)&&swallowPrimary_&&pressed_>=0){const int which=pressed_;pressed_=-1;if(which==hover_&&unsigned(which)<scene_.count&&scene_.controls[which].enabled)activate(scene_.controls[which].command);}
  if(pressed&(512|1024)){
   unsigned index=0,total=0;for(auto& tab:scene_.tabs)if(*tab){if(!strcmp(tab,*desiredTab_?desiredTab_:scene_.active))index=total;++total;}
   if(total){const unsigned next=(index+((pressed&512)?total-1:1))%total;activate(10+int(next));}mask|=512|1024;
  }
 }
 if(*desiredTab_&&hover_<0)mask|=1|8192;
 if(swallowMiddle_){mask|=8192;if(!(buttons&8192))swallowMiddle_=false;}
 if(swallowPrimary_){mask|=1;if(!(buttons&1))swallowPrimary_=false;}
 if(pressed||released||oldHover!=hover_||oldMenu!=menu_||oldFocus!=menuFocus_)++revision_;
 return mask;
}
void NativeChrome::render(Surface surface){
 ChromeScene scene;bool menu,overflow,pending,keyboard;int hover,pressed;unsigned focus;char desired[32];
 {Lock lock(mutex_);scene=scene_;menu=menu_;overflow=overflow_;pending=count_!=0;hover=hover_;pressed=pressed_;focus=menuFocus_;keyboard=keyboardMenu_;memcpy(desired,desiredTab_,sizeof(desired));}
 if(!scene.enabled)return;
 // Existing Gecko pixels preserve real text/favicons. Interaction decoration
 // and menu draw independently using immutable baked Noto pixels; no
 // Gecko widget/DOM/font object is touched here.
 if(!menu&&hover>=0&&unsigned(hover)<scene.count){const auto& c=scene.controls[hover];if(c.enabled){fill_rect(surface,c.x,c.y,c.width,2,{255,172,100,255});fill_rect(surface,c.x,c.y+c.height-2,c.width,2,{255,172,100,255});}}
 if(*desired)for(unsigned i=0;i<scene.count;++i){const auto& c=scene.controls[i];if(c.command>=10&&c.command<=12&&!strcmp(scene.tabs[c.command-10],desired))fill_rect(surface,c.x,c.y+c.height-4,c.width,4,{255,150,60,255});}
 if(menu){
  fill_rect(surface,menuX-2,menuY-2,menuWidth+4,menuRows*rowHeight+menuPadding*2+4,{64,64,76,255});fill_rect(surface,menuX,menuY,menuWidth,menuRows*rowHeight+menuPadding*2,{43,42,51,255});
  for(int i=0;i<menuRows;++i){int yy=menuY+menuPadding+i*rowHeight;bool selected=i==(hover>=0?hover:keyboard?int(focus):-1);if(selected)fill_rect(surface,menuX+8,yy,menuWidth-16,rowHeight-2,{66,65,77,255});if(i==1||i==8)fill_rect(surface,menuX+12,yy-2,menuWidth-24,1,{90,89,100,255});if(i==zoomRow){char zoom[12];snprintf(zoom,sizeof(zoom),"%u%%",scene.zoom);chromeText(surface,menuX+35,yy+9,"-",2,{251,251,254,255});chromeText(surface,menuX+menuWidth/2-22,yy+9,zoom,2,{251,251,254,255});chromeText(surface,menuX+menuWidth-45,yy+9,"+",2,{251,251,254,255});}else chromeText(surface,menuX+18,yy+9,menuLabels[i],2,{251,251,254,255});}
 }
 if(pending||*desired||overflow){fill_rect(surface,0,surface.height-32,485,32,{43,42,51,255});chromeText(surface,12,surface.height-27,overflow?"Command queue full - wait for Gecko":"Waiting for the page to respond...",2,{251,251,254,255});}
 (void)pressed;
}
bool NativeChrome::modal(){Lock lock(mutex_);return scene_.enabled&&menu_;}
bool NativeChrome::take(char* destination,size_t capacity){Lock lock(mutex_);if(!destination||capacity<48||!count_)return false;memcpy(destination,actions_[head_],48);head_=(head_+1)%16;--count_;if(!count_)overflow_=false;++revision_;return true;}
}
