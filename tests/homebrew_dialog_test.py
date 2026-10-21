import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class HomebrewDialogTest(unittest.TestCase):
    def test_actual_dialog_body_with_firmware_doubles(self):
        headers = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))
        headers['fetch']()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'dialog.c'
            source.write_text(r'''
#include <assert.h>
#define clock_gettime probe_clock_gettime
#define nanosleep probe_nanosleep
#define ORBISFOX_SDK_PROBE_DIALOG
#define main unused_runtime_probe_main
#include "''' + str(ROOT / 'tests/homebrew_sdk_probe.c') + r'''"
#undef main
static int mode, common_calls, init_calls, result_calls, term_calls, status_calls, ticks;
static OrbisImeDialogSetting saved;
static const char *names[] = {"libSceSystemService.sprx", "libSceUserService.sprx",
                            "libSceCommonDialog.sprx", "libSceImeDialog.sprx"};
int probe_clock_gettime(clockid_t id, struct timespec *now) {
  assert(id == CLOCK_MONOTONIC);
  if (mode == 11) return -1;
  now->tv_sec = mode == 12 ? 100 - ticks++ : ticks++; now->tv_nsec = 0;
  return 0;
}
int probe_nanosleep(const struct timespec *delay, struct timespec *remaining) {
  assert(delay->tv_nsec == 20000000 && remaining == NULL); return 0;
}
int32_t sceSysmoduleLoadModule(enum OrbisSysModule id) {
  assert(id == ORBIS_SYSMODULE_IME_DIALOG); return 0;
}
uint32_t sceSysmoduleLoadModuleInternal(enum OrbisSysModuleInternal id) {
  assert(id == ORBIS_SYSMODULE_INTERNAL_SYSTEM_SERVICE ||
         id == ORBIS_SYSMODULE_INTERNAL_USER_SERVICE ||
         id == ORBIS_SYSMODULE_INTERNAL_COMMON_DIALOG); return mode == 14 ? 0x80020002 : 0;
}
int32_t sceKernelGetModuleList(OrbisKernelModule *handles, size_t capacity, size_t *count) {
  assert(capacity == 256); *count = 4;
  for (unsigned i = 0; i < 4; ++i) handles[i] = i + 1;
  return 0;
}
int32_t sceKernelGetModuleInfo(OrbisKernelModule handle, OrbisKernelModuleInfo *info) {
  assert(handle >= 1 && handle <= 4 && info->size == sizeof(*info));
  strcpy(info->name, names[handle - 1]); return 0;
}
int32_t sceSystemServiceHideSplashScreen(void) { return 0; }
int32_t sceUserServiceInitialize(void *params) {
  assert(((OrbisUserServiceInitializeParams *)params)->priority == ORBIS_KERNEL_PRIO_FIFO_LOWEST);
  return 0;
}
int32_t sceUserServiceGetInitialUser(int32_t *user) { *user = mode == 13 ? -1 : 7; return 0; }
int32_t sceCommonDialogInitialize(void) {
  ++common_calls; return mode == 1 ? (int32_t)0x80b8000e : 0;
}
int32_t sceImeDialogInit(const OrbisImeDialogSetting *settings, OrbisImeSettingsExtended *extended) {
  assert(!extended && settings->userId == 7 && settings->maxTextLength == 64);
  assert(settings->posx == 960 && settings->posy == 540);
  assert(settings->horizontalAlignment == ORBIS_H_CENTER && settings->verticalAlignment == ORBIS_V_CENTER);
  const uint16_t *title = (const uint16_t *)settings->title;
  assert(title[4] == (init_calls ? '2' : '1'));
  assert(((uint16_t *)settings->inputTextBuffer)[0] == 0);
  saved = *settings; ++init_calls; status_calls = 0;
  return mode == 4 ? -4 : 0;
}
OrbisDialogStatus sceImeDialogGetStatus(void) {
  if (mode == 5) return ORBIS_DIALOG_STATUS_NONE;
  if (mode == 8 || mode == 12) return ORBIS_DIALOG_STATUS_RUNNING;
  return status_calls++ ? ORBIS_DIALOG_STATUS_STOPPED : ORBIS_DIALOG_STATUS_RUNNING;
}
int32_t sceImeDialogGetResult(OrbisDialogResult *result) {
  ++result_calls;
  result->endstatus = init_calls == 2 || mode == 9 ? ORBIS_DIALOG_CANCEL : ORBIS_DIALOG_OK;
  uint16_t *text = (uint16_t *)saved.inputTextBuffer;
  text[0] = mode == 10 ? 'N' : 'O'; text[1] = 'K'; text[2] = 0;
  return mode == 6 ? -6 : 0;
}
int32_t sceImeDialogTerm(void) { ++term_calls; return mode == 7 ? -7 : 0; }
int32_t sceKernelDlsym(int32_t handle, const char *name, void **address) {
  assert(handle >= 1 && handle <= 4);
  if (mode == 2) return -2;
#define SYMBOL(function) if (!strcmp(name, #function)) { \
  __typeof__(&function) target = &function; memcpy(address, &target, sizeof(target)); return 0; }
  SYMBOL(sceSystemServiceHideSplashScreen)
  SYMBOL(sceUserServiceInitialize) SYMBOL(sceUserServiceGetInitialUser)
  SYMBOL(sceCommonDialogInitialize) SYMBOL(sceImeDialogInit) SYMBOL(sceImeDialogGetStatus)
  SYMBOL(sceImeDialogGetResult) SYMBOL(sceImeDialogTerm)
#undef SYMBOL
  assert(0); return -1;
}
int32_t sceKernelQueryMemoryProtection(void *address, void **low, void **high, int32_t *protection) {
  assert(address); *low = (void *)1; *high = (void *)UINTPTR_MAX;
  *protection = mode == 3 ? 0 : ORBIS_KERNEL_PROT_CPU_EXEC; return 0;
}
int main(void) {
  for (unsigned cycle = 0; cycle < 16; ++cycle) for (mode = 0; mode <= 14; ++mode) {
    checks = failures = 0;
    common_calls = init_calls = result_calls = term_calls = status_calls = ticks = 0;
    output = tmpfile(); assert(output); dialog_checks();
    assert((failures == 0) == (mode == 0));
    if (mode == 0) assert(common_calls == 1 && init_calls == 2 && result_calls == 2 && term_calls == 2);
    if (mode == 1) {
      assert(common_calls == 1 && init_calls == 0);
      rewind(output); char log[8192]; size_t n = fread(log, 1, sizeof(log) - 1, output); log[n] = 0;
      assert(strstr(log, "CommonDialogInitialize rc=0x80b8000e"));
      assert(!strstr(log, "PASS CommonDialog-initialize"));
    }
    if (mode == 4) assert(init_calls == 1 && term_calls == 0);
    if (mode >= 5 && mode <= 10) assert(init_calls == 1 && term_calls == 1);
    if (mode == 8 || mode == 12) assert(result_calls == 0);
    if (mode == 11 || mode == 13) assert(init_calls == 0);
    if (mode == 12) assert(init_calls == 1 && term_calls == 1);
    assert(fclose(output) == 0);
  }
}
''')
            binary = Path(tmp) / 'dialog'
            subprocess.run(['clang', '-std=c11', '-D_GNU_SOURCE', '-O1', '-g', '-pthread',
                            '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-I', headers['DESTINATION'] / 'include', source, '-o', binary], check=True)
            subprocess.run([binary], check=True, timeout=20)

    def test_dialog_builder_keeps_native_sdk_pin_and_bindings(self):
        builder = (ROOT / 'scripts/build-homebrew-sdk-probe.py').read_text()
        self.assertIn("FETCH['fetch']()", builder)
        self.assertIn("declarations['verify']()", builder)
        self.assertIn("'tests/homebrew_dialog_probe.h'", builder)
        self.assertIn("'probe_mode': 'dialog' if args.dialog else 'runtime'", builder)
        self.assertIn("report['service_declarations']", builder)
        pin = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-sdk.py'))
        self.assertEqual(pin['REVISION'], 'ecc8347aa20d7b3423405a5e94d7ab119485160d')
        self.assertEqual(pin['VERSION'], 'v0.2.1')


if __name__ == '__main__':
    unittest.main()
