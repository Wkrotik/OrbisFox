/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#ifndef ORBISFOX_NSPR_NETDB_H
#define ORBISFOX_NSPR_NETDB_H

#include <errno.h>
#include <netdb.h>
#include <sys/socket.h>

/* Private adapters, not replacements for exported libc functions. The pinned
 * native SDK resolver implements IPv4 only. Let NSPR's existing V4MAPPED path
 * perform any requested conversion; never label an IPv4 result as native IPv6.
 * NSPR holds its DNS lock while using the SDK's static hostent storage. */
static struct hostent* OrbisNsprGetHostByName2(const char* name, int family) {
  if (family != AF_INET) {
    errno = EAFNOSUPPORT;
    h_errno = NO_RECOVERY;
    return NULL;
  }
  return gethostbyname(name);
}

/* Query the real SDK protocol database by name, then verify the returned
 * number. These are the five records in SDK v0.2.1, not fabricated results or
 * a claim about available transports. NSPR holds _getproto_lock for the copy. */
static struct protoent* OrbisNsprGetProtoByNumber(int number) {
  static const char* const names[] = {"ip", "icmp", "tcp", "udp", "ipv6"};
  for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
    struct protoent* record = getprotobyname(names[i]);
    if (record && record->p_proto == number) {
      return record;
    }
  }
  errno = ENOENT;
  return NULL;
}

#endif
