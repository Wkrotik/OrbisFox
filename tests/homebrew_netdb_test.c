/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <string.h>
#include "../gecko/orbisfox/OrbisNsprNetdb.h"

static unsigned dns_calls;
static struct hostent host;
static struct protoent proto;
static int wrong_number;

struct hostent* __wrap_gethostbyname(const char* name) {
  ++dns_calls;
  if (!strcmp(name, "present.test")) return &host;
  errno = EHOSTUNREACH;
  h_errno = HOST_NOT_FOUND;
  return NULL;
}
struct protoent* __wrap_getprotobyname(const char* name) {
  if (!strcmp(name, "tcp")) {
    proto.p_proto = wrong_number ? 99 : 6;
    return &proto;
  }
  return NULL;
}
int main(void) {
  assert(OrbisNsprGetHostByName2("present.test", AF_INET) == &host);
  assert(dns_calls == 1);
  assert(!OrbisNsprGetHostByName2("missing.test", AF_INET));
  assert(dns_calls == 2 && errno == EHOSTUNREACH && h_errno == HOST_NOT_FOUND);
  assert(!OrbisNsprGetHostByName2("present.test", AF_INET6));
  assert(dns_calls == 2 && errno == EAFNOSUPPORT && h_errno == NO_RECOVERY);
  assert(!OrbisNsprGetHostByName2("present.test", -1));
  assert(dns_calls == 2 && errno == EAFNOSUPPORT);
  assert(OrbisNsprGetProtoByNumber(6) == &proto);
  assert(!OrbisNsprGetProtoByNumber(17) && errno == ENOENT);
  assert(!OrbisNsprGetProtoByNumber(-1) && errno == ENOENT);
  wrong_number = 1;
  assert(!OrbisNsprGetProtoByNumber(6) && errno == ENOENT);
  return 0;
}
