/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "mozilla/widget/MediaKeysEventSourceFactory.h"
namespace mozilla::widget {
mozilla::dom::MediaControlKeySource* CreateMediaControlKeySource() {
  // Native controller input remains application-owned; no OS media-key source.
  return nullptr;
}
}  // namespace mozilla::widget
