#include "nspr_link_probe.h"
#include "prinit.h"
#include "prlink.h"
#include "prerror.h"
#include <cassert>
#include <cstdio>
#include <cstring>

static void message(const char* text) { std::puts(text); }
int main() {
  for (int i = 0; i < 32; ++i) assert(probe_orbisfox_static_nspr(message));
  assert(PR_LoadLibrary("/not-real/missing-library.so") == nullptr);
  assert(PR_GetError() == PR_LOAD_LIBRARY_ERROR);
  char error[256] = {};
  assert(PR_GetErrorTextLength() > 0 && PR_GetErrorTextLength() < int(sizeof(error)));
  PR_GetErrorText(error);
  assert(std::strstr(error, "registered static libraries") != nullptr);
  assert(PR_Cleanup() == PR_SUCCESS);
  std::puts("Real patched NSPR: initialization, static dispatch, cache/refcount/unload, unknown DLL rejection, cleanup OK");
}
