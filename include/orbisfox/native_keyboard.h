#pragma once
#include "orbisfox/keyboard_session.h"
#include "orbisfox/module_binding.h"
#include <orbis/CommonDialog.h>
#include <orbis/ImeDialog.h>
#include <orbis/UserService.h>
#include <orbis/SystemService.h>
namespace orbisfox {
class NativeKeyboard {
  ModuleBinding common_,ime_,user_,system_;
  decltype(&::sceSystemServiceParamGetInt) paramGetInt_=nullptr;
  bool addressMode_=true;
  uint32_t confirm_=0;
  int32_t lastStatus_=-1;
  decltype(&::sceCommonDialogInitialize) commonInit_=nullptr;
  decltype(&::sceImeDialogInit) init_=nullptr;
  decltype(&::sceImeDialogGetStatus) status_=nullptr;
  decltype(&::sceImeDialogGetResult) result_=nullptr;
  decltype(&::sceImeDialogTerm) term_=nullptr;
  decltype(&::sceUserServiceGetInitialUser) initialUser_=nullptr;
  bool ready_=false;
  OrbisImeDialogSetting setting_{};
  static bool prepare(void*,int32_t*);
  static int32_t init(void*,int32_t,char16_t*,uint32_t);
  static int32_t status(void*);
  static int32_t result(void*,int32_t*);
  static int32_t term(void*);
  static uint64_t now(void*);
public:
  KeyboardSession session;
  NativeKeyboard():session({this,prepare,init,status,result,term,now}) {}
  bool setAddressMode(bool value) {if(session.active())return false;addressMode_=value;return true;}
  uint32_t confirmButton() const {return confirm_;} //0 unknown,1 Cross,2 Circle
};
}
