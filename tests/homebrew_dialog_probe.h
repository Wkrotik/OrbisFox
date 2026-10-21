// SPDX-License-Identifier: MIT
// Standalone firmware calls; no Gecko, SDK mutation, scanout or text logging.
#include <stddef.h>
#include <orbis/CommonDialog.h>
#include <orbis/ImeDialog.h>
#include <orbis/Sysmodule.h>
#include <orbis/SystemService.h>
#include <orbis/UserService.h>
#include <orbis/libkernel.h>

_Static_assert(sizeof(OrbisImeDialogSetting) == 96 &&
               offsetof(OrbisImeDialogSetting, inputTextBuffer) == 40 &&
               offsetof(OrbisImeDialogSetting, title) == 72 &&
               sizeof(OrbisDialogResult) == 16, "Native IME ABI drift");

static int dialog_module(const char *name, uint32_t id, int32_t *handle) {
  *handle = -1;
  int32_t rc = (id & UINT32_C(0x80000000)) ?
      (int32_t)sceSysmoduleLoadModuleInternal((OrbisSysModuleInternal)id) :
      (int32_t)sceSysmoduleLoadModule((OrbisSysModule)id);
  fprintf(output, "MODULE %s load=0x%08x\n", name, (unsigned)rc); fflush(output);
  if (!check(rc >= 0, "module-load", rc)) return 0;
  OrbisKernelModule modules[256]; size_t count = 0;
  rc = sceKernelGetModuleList(modules, 256, &count);
  if (!check(rc == 0 && count <= 256, "module-list", rc)) return 0;
  for (size_t i = 0; i < count; ++i) {
    OrbisKernelModuleInfo info = {0}; info.size = sizeof(info);
    rc = sceKernelGetModuleInfo(modules[i], &info);
    if (rc == 0 && memchr(info.name, 0, sizeof(info.name)) && strcmp(info.name, name) == 0) {
      *handle = (int32_t)modules[i];
      return check(*handle >= 0, "module-handle", *handle);
    }
  }
  return check(0, "module-name-not-found", -1);
}

static int dialog_symbol(int32_t handle, const char *name, void **address) {
  *address = NULL;
  int32_t rc = sceKernelDlsym(handle, name, address);
  fprintf(output, "SYMBOL %s rc=0x%08x\n", name, (unsigned)rc); fflush(output);
  if (!check(rc == 0 && *address, "symbol-resolve", rc)) return 0;
  void *low = NULL, *high = NULL; int32_t protection = 0;
  rc = sceKernelQueryMemoryProtection(*address, &low, &high, &protection);
  return check(rc == 0 && (protection & ORBIS_KERNEL_PROT_CPU_EXEC) &&
               (uintptr_t)*address >= (uintptr_t)low && (uintptr_t)*address < (uintptr_t)high,
               "symbol-executable", rc);
}

static int dialog_now(struct timespec *now) {
  int rc = clock_gettime(CLOCK_MONOTONIC, now);
  return rc == 0 || check(0, "dialog-monotonic-clock", rc);
}

static void dialog_checks(void) {
  // Match the browser's dynamic service binding without linking old SDK code.
  __typeof__(&sceUserServiceInitialize) user_init = NULL;
  __typeof__(&sceUserServiceGetInitialUser) initial_user = NULL;
  __typeof__(&sceCommonDialogInitialize) common_init = NULL;
  __typeof__(&sceImeDialogInit) ime_init = NULL;
  __typeof__(&sceImeDialogGetStatus) ime_status = NULL;
  __typeof__(&sceImeDialogGetResult) ime_result = NULL;
  __typeof__(&sceImeDialogTerm) ime_term = NULL;
  __typeof__(&sceSystemServiceHideSplashScreen) hide_splash = NULL;
  int32_t module;
#define DIALOG_BIND(variable, symbol) do { \
  void *address; \
  if (!dialog_symbol(module, #symbol, &address)) return; \
  _Static_assert(sizeof(variable) == sizeof(address), "Native function-pointer ABI"); \
  memcpy(&(variable), &address, sizeof(variable)); \
} while (0)
  if (!dialog_module("libSceSystemService.sprx", ORBIS_SYSMODULE_INTERNAL_SYSTEM_SERVICE, &module)) return;
  DIALOG_BIND(hide_splash, sceSystemServiceHideSplashScreen);
  int32_t rc = hide_splash();
  if (!check(rc == 0, "hide-splash", rc)) return;
  if (!dialog_module("libSceUserService.sprx", ORBIS_SYSMODULE_INTERNAL_USER_SERVICE, &module)) return;
  DIALOG_BIND(user_init, sceUserServiceInitialize);
  DIALOG_BIND(initial_user, sceUserServiceGetInitialUser);
  OrbisUserServiceInitializeParams user_params = {0};
  user_params.priority = ORBIS_KERNEL_PRIO_FIFO_LOWEST;
  rc = user_init(&user_params);
  fprintf(output, "UserServiceInitialize rc=0x%08x\n", (unsigned)rc); fflush(output);
  if (!check(rc == 0 || (uint32_t)rc == ORBIS_USER_SERVICE_ERROR_ALREADY_INITIALIZED,
             "user-initialize", rc)) return;
  int32_t user = -1; rc = initial_user(&user);
  if (!check(rc == 0 && user >= 0, "active-user", rc)) return;
  if (!dialog_module("libSceCommonDialog.sprx", ORBIS_SYSMODULE_INTERNAL_COMMON_DIALOG, &module)) return;
  DIALOG_BIND(common_init, sceCommonDialogInitialize);
  if (!dialog_module("libSceImeDialog.sprx", ORBIS_SYSMODULE_IME_DIALOG, &module)) return;
  DIALOG_BIND(ime_init, sceImeDialogInit);
  DIALOG_BIND(ime_status, sceImeDialogGetStatus);
  DIALOG_BIND(ime_result, sceImeDialogGetResult);
  DIALOG_BIND(ime_term, sceImeDialogTerm);
#undef DIALOG_BIND
  rc = common_init();
  fprintf(output, "CommonDialogInitialize rc=0x%08x\n", (unsigned)rc); fflush(output);
  if (!check(rc == 0, "CommonDialog-initialize", rc)) return;

  // Static UTF-16 storage stays alive even if firmware refuses termination.
  static uint16_t text[65];
  static OrbisImeDialogSetting settings;
  static const uint16_t confirm_title[] = {'S','D','K',' ','1','/','2',':',' ','t','y','p','e',' ','O','K',' ','a','n','d',' ','c','o','n','f','i','r','m',0};
  static const uint16_t cancel_title[] = {'S','D','K',' ','2','/','2',':',' ','c','a','n','c','e','l',' ','t','h','i','s',' ','d','i','a','l','o','g',0};
  for (unsigned attempt = 0; attempt < 2; ++attempt) {
    memset(text, 0, sizeof(text)); memset(&settings, 0, sizeof(settings));
    settings.userId = (uint32_t)user; settings.type = ORBIS_TYPE_DEFAULT;
    settings.maxTextLength = 64; settings.enterLabel = ORBIS_BUTTON_LABEL_DEFAULT;
    settings.inputTextBuffer = (wchar_t *)text;
    settings.title = (const wchar_t *)(attempt ? cancel_title : confirm_title);
    settings.posx = 960; settings.posy = 540;
    settings.horizontalAlignment = ORBIS_H_CENTER; settings.verticalAlignment = ORBIS_V_CENTER;
    struct timespec start, now;
    if (!dialog_now(&start)) return;
    rc = ime_init(&settings, NULL);
    fprintf(output, "IME attempt=%u init=0x%08x\n", attempt + 1, (unsigned)rc); fflush(output);
    if (!check(rc == 0, "IME-init", rc)) return;
    int stopped = 0, last_status = -1;
    for (unsigned poll = 0; poll < 3000; ++poll) {
      int status = (int)ime_status();
      if (status != last_status) {
        fprintf(output, "IME status=%d\n", status); fflush(output); last_status = status;
      }
      if (status == ORBIS_DIALOG_STATUS_STOPPED) { stopped = 1; break; }
      if (status != ORBIS_DIALOG_STATUS_RUNNING || !dialog_now(&now)) break;
      if (now.tv_sec < start.tv_sec || (now.tv_sec == start.tv_sec && now.tv_nsec < start.tv_nsec) ||
          now.tv_sec - start.tv_sec >= 45) break;
      const struct timespec tick = {0, 20000000};
      if (nanosleep(&tick, NULL) && errno != EINTR) break;
    }
    int ok = check(stopped, "IME-terminal-before-deadline", stopped ? 0 : -1);
    if (stopped) {
      OrbisDialogResult result = {0}; rc = ime_result(&result);
      fprintf(output, "IME attempt=%u result=0x%08x action=%d\n", attempt + 1, (unsigned)rc, result.endstatus);
      fflush(output);
      ok &= check(rc == 0, "IME-result", rc);
      if (rc == 0) {
        ok &= check(result.endstatus == (attempt ? ORBIS_DIALOG_CANCEL : ORBIS_DIALOG_OK),
                    "IME-expected-action", result.endstatus);
        if (!attempt) ok &= check(text[0] == 'O' && text[1] == 'K' && text[2] == 0,
                                  "IME-confirmed-OK", 0);
      }
    }
    rc = ime_term();
    ok &= check(rc == 0, "IME-terminate", rc);
    if (!ok) return;
  }
}
