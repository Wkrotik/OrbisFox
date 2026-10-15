/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "OSPreferences.h"

namespace mozilla::intl {

OSPreferences::OSPreferences() {}

bool OSPreferences::ReadSystemLocales(nsTArray<nsCString>&) {
  // No validated console locale API yet. Use LocaleService's application
  // fallback, not a fabricated console language preference.
  return false;
}

bool OSPreferences::ReadRegionalPrefsLocales(nsTArray<nsCString>&) {
  return false;
}

bool OSPreferences::ReadDateTimePattern(DateTimeFormatStyle, DateTimeFormatStyle,
                                      const nsACString&, nsACString&) {
  // The shared implementation falls back to genuine in-tree ICU data.
  return false;
}

void OSPreferences::RemoveObservers() {}

}  // namespace mozilla::intl
