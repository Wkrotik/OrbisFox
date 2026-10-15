/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "nspr_link_probe.h"
#include "prinit.h"
#include "prlink.h"
#include "prerror.h"

namespace {
int static_probe_function() { return 0x4f524253; }
const PRStaticLinkTable probe_table[] = {
    {"orbisfox_static_probe_function", reinterpret_cast<PRFuncPtr>(static_probe_function)},
    {nullptr, nullptr},
};
}

bool probe_orbisfox_static_nspr(void (*message)(const char*)) {
  message("NSPR: real native initialization begin; desktop dlopen is disabled");
  PR_Init(PR_USER_THREAD, PR_PRIORITY_NORMAL, 0);
  if (!PR_Initialized()) {
    message("ERROR: NSPR initialization did not complete");
    return false;
  }
  message("NSPR: initialization completed");
  PRLibrary* registered = PR_LoadStaticLibrary("orbisfox-static-probe", probe_table);
  if (!registered) {
    message("ERROR: NSPR static-table registration failed");
    return false;
  }
  auto function = reinterpret_cast<int (*)()>(
      PR_FindFunctionSymbol(registered, "orbisfox_static_probe_function"));
  bool ok = function && function() == 0x4f524253;
  ok = (PR_FindSymbol(registered, "not_a_registered_symbol") == nullptr &&
        PR_GetError() == PR_FIND_SYMBOL_ERROR) && ok;
  PRLibrary* cached = PR_LoadLibrary("/not-a-real-directory/orbisfox-static-probe");
  ok = (cached == registered) && ok;
  PRLibrary* unsupported = PR_LoadLibrary("orbisfox-unsupported-dynamic-library.so");
  ok = (unsupported == nullptr && PR_GetError() == PR_LOAD_LIBRARY_ERROR) && ok;
  if (unsupported) PR_UnloadLibrary(unsupported);
  if (cached) ok = (PR_UnloadLibrary(cached) == PR_SUCCESS) && ok;
  ok = (PR_UnloadLibrary(registered) == PR_SUCCESS) && ok;
  message(ok ? "NSPR: static symbols / cached load / missing-symbol and unknown-DLL rejection OK"
             : "ERROR: NSPR static-linker behavior probe failed");
  return ok;
}
