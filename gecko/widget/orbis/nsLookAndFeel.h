/* OrbisFox stand-in native theme. Licensed under MPL-2.0. */
#ifndef orbis_nsLookAndFeel_h
#define orbis_nsLookAndFeel_h

#include "HeadlessLookAndFeel.h"

// A real class matches nsXPLookAndFeel's forward declaration. The portable
// upstream headless implementation provides colors, metrics and fonts without
// GTK or desktop-theme services.
class nsLookAndFeel final : public mozilla::widget::HeadlessLookAndFeel {
 public:
  nsLookAndFeel() = default;
  ~nsLookAndFeel() override = default;
};

#endif
