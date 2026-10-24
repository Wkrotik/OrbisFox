/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#ifndef ORBISFOX_LIBEVENT_CONFIG_H
#define ORBISFOX_LIBEVENT_CONFIG_H

// Retain the pinned Unix/LP64 configuration, but do not claim unsupported BSD
// kernel APIs. The core event loop uses poll/select; upstream RNG seeding uses
// device entropy, not a fabricated implementation of firmware arc4random.
#include "../../bsd/event2/event-config.h"
#undef EVENT__HAVE_ARC4RANDOM
#undef EVENT__HAVE_ARC4RANDOM_ADDRANDOM
#undef EVENT__HAVE_ARC4RANDOM_BUF
#ifdef ORBISFOX_HOMEBREW_SDK
// BSD 9 exposes pipe(), not pipe2(). Retain libevent's checked pipe/fcntl path.
#undef EVENT__HAVE_PIPE2
// Keep upstream's TCP/UDP protocol names and unknown-protocol failure path.
#undef EVENT__HAVE_GETPROTOBYNUMBER
#endif
#undef EVENT__HAVE_GETRANDOM
#undef EVENT__HAVE_SYS_RANDOM_H
#undef EVENT__HAVE_SYSCTL
#undef EVENT__HAVE_SYS_SYSCTL_H
#undef EVENT__HAVE_DECL_CTL_KERN
#undef EVENT__HAVE_DECL_KERN_ARND
#undef EVENT__HAVE_KQUEUE
#undef EVENT__HAVE_WORKING_KQUEUE
#undef EVENT__HAVE_SYS_EVENT_H

#endif
