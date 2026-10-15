/* OrbisFox native widget registration. Licensed under MPL-2.0. */
#ifndef orbis_nsWidgetFactory_h
#define orbis_nsWidgetFactory_h
#include "nsID.h"
#include "nscore.h"
nsresult nsAppShellConstructor(const nsIID&, void**);
nsresult nsWidgetOrbisModuleCtor();
void nsWidgetOrbisModuleDtor();
#endif
