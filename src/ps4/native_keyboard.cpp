// OpenOrbis declarations; public Apollo PS4 dialog example informed lifecycle.
// Reference: https://github.com/bucanero/apollo-ps4/blob/645bd8fb/source/dialog.c
// This is a bounded nonblocking OrbisFox implementation, not Apollo's UI loop.
// No wchar_t conversion: firmware dialog buffers are explicitly UTF-16.
#include "orbisfox/native_keyboard.h"
#include "orbisfox/presenter.h"
#include <orbis/Sysmodule.h>
#include <orbis/libkernel.h>
#include <stddef.h>
namespace orbisfox {
static_assert(sizeof(OrbisImeDialogSetting)==96 &&
  offsetof(OrbisImeDialogSetting,inputTextBuffer)==40 &&
  offsetof(OrbisImeDialogSetting,title)==72 && sizeof(OrbisDialogResult)==16,
  "IME dialog ABI drift");
static_assert(sizeof(char16_t)==2,"Firmware IME needs 16-bit units");
bool NativeKeyboard::prepare(void* opaque,int32_t* user) {
  auto& self=*static_cast<NativeKeyboard*>(opaque);
  if(!self.ready_) {
    const auto backend=ps4_module_backend();
    if(!self.common_.open(backend,"libSceCommonDialog",ORBIS_SYSMODULE_INTERNAL_COMMON_DIALOG) ||
       !self.common_.bind("sceCommonDialogInitialize",self.commonInit_) ||
       !self.ime_.open(backend,"libSceImeDialog",ORBIS_SYSMODULE_IME_DIALOG) ||
       !self.ime_.bind("sceImeDialogInit",self.init_) ||
       !self.ime_.bind("sceImeDialogGetStatus",self.status_) ||
       !self.ime_.bind("sceImeDialogGetResult",self.result_) ||
       !self.ime_.bind("sceImeDialogTerm",self.term_) ||
       !self.user_.open(backend,"libSceUserService",ORBIS_SYSMODULE_INTERNAL_USER_SERVICE) ||
       !self.user_.bind("sceUserServiceGetInitialUser",self.initialUser_)) {
      log("Native IME: module/executable-symbol gate failed; HTML keyboard retained");return false;
    }
    const int32_t result=self.commonInit_();
    log("Native IME: genuine CommonDialog initialization rc=0x%x",result);
    if(result!=0) return false; // No guessed already-initialized success code.
    self.ready_=true;
  }
  if(!self.paramGetInt_) {
    if(self.system_.open(ps4_module_backend(),"libSceSystemService",ORBIS_SYSMODULE_INTERNAL_SYSTEM_SERVICE))
      self.system_.bind("sceSystemServiceParamGetInt",self.paramGetInt_);
  }
  int32_t assignment=-1;
  const int32_t assignmentResult=self.paramGetInt_?self.paramGetInt_(ORBIS_SYSTEM_SERVICE_PARAM_ID_ENTER_BUTTON_ASSIGN,&assignment):-1;
  self.confirm_=assignmentResult==0?(assignment==ORBIS_SYSTEM_PARAM_ENTER_BUTTON_ASSIGN_CROSS?1:assignment==ORBIS_SYSTEM_PARAM_ENTER_BUTTON_ASSIGN_CIRCLE?2:0):0;
  log("Native IME: real system confirm assignment rc=0x%x value=%d; %s",assignmentResult,assignment,
      self.confirm_==1?"Cross confirm / Circle cancel":self.confirm_==2?"Circle confirm / Cross cancel":"unknown - follow system dialog labels");
  const int32_t rc=self.initialUser_(user);
  log("Native IME: initial user rc=0x%x user=%d",rc,*user);
  return rc==0;
}
int32_t NativeKeyboard::init(void* opaque,int32_t user,char16_t* text,uint32_t limit) {
  auto& self=*static_cast<NativeKeyboard*>(opaque);
  self.setting_={};auto& param=self.setting_;
  static constexpr char16_t addressTitle[]=u"OrbisFox address",textTitle[]=u"OrbisFox page text";
  const char16_t* title=self.addressMode_?addressTitle:textTitle;
  param.userId=static_cast<uint32_t>(user);param.type=self.addressMode_?ORBIS_TYPE_TYPE_URL:ORBIS_TYPE_DEFAULT;
  param.maxTextLength=limit;param.enterLabel=ORBIS_BUTTON_LABEL_GO;
  // The SDK spells these pointer fields wchar_t*, but the native buffer ABI is
  // uint16_t. Never dereference them through this SDK/private-C++ wchar type.
  param.inputTextBuffer=reinterpret_cast<wchar_t*>(text);
  param.title=reinterpret_cast<const wchar_t*>(title);
  param.posx=960;param.posy=540;param.horizontalAlignment=ORBIS_H_CENTER;param.verticalAlignment=ORBIS_V_CENTER;
  self.lastStatus_=-1;
  const int32_t rc=self.init_(&param,nullptr);
  log("Native IME: %s dialog init rc=0x%x UTF16-limit=%u",self.addressMode_?"URL":"text",rc,limit);return rc;
}
int32_t NativeKeyboard::status(void* opaque) {
  auto& self=*static_cast<NativeKeyboard*>(opaque);const int32_t result=self.status_();
  if(result!=self.lastStatus_){log("Native IME: real status transition %d -> %d",self.lastStatus_,result);self.lastStatus_=result;}
  return result;
}
int32_t NativeKeyboard::result(void* opaque,int32_t* end) {
  OrbisDialogResult result{};
  const int32_t rc=static_cast<NativeKeyboard*>(opaque)->result_(&result);
  if(rc==0)*end=result.endstatus;
  log("Native IME: terminal result rc=0x%x action=%d",rc,*end);return rc;
}
int32_t NativeKeyboard::term(void* opaque) {
  const int32_t rc=static_cast<NativeKeyboard*>(opaque)->term_();
  log("Native IME: terminate rc=0x%x",rc);return rc;
}
uint64_t NativeKeyboard::now(void*) {return sceKernelGetProcessTime();}
}
