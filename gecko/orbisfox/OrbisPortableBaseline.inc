/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
// Included inside js::pbl; one atomic bit, no JS objects or per-opcode logging.
static mozilla::Atomic<bool, mozilla::Relaxed> sOrbisPortableBaselineEntered{false};
extern "C" bool OrbisPortableBaselineEntered() {
  return sOrbisPortableBaselineEntered;
}
