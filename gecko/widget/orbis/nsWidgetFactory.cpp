/* OrbisFox native widget registration. Licensed under MPL-2.0. */
#include "nsWidgetFactory.h"
#include "nsAppShellSingleton.h"
#include "nsIWidget.h"
#include "mozilla/widget/HeadlessWidget.h"

nsresult nsWidgetOrbisModuleCtor() { return nsAppShellInit(); }
void nsWidgetOrbisModuleDtor() { nsAppShellShutdown(); }

already_AddRefed<nsIWidget> nsIWidget::CreateTopLevelWindow() {
  return CreateHeadlessWidget();
}
already_AddRefed<nsIWidget> nsIWidget::CreateChildWindow() {
  return CreateHeadlessWidget();
}
