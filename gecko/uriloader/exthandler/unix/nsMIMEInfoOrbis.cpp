/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "nsMIMEInfoUnix.h"

nsresult nsMIMEInfoUnix::LoadUriInternal(nsIURI*) {
  return NS_ERROR_NOT_IMPLEMENTED;
}
NS_IMETHODIMP nsMIMEInfoUnix::GetDefaultExecutable(nsIFile** aExecutable) {
  NS_ENSURE_ARG_POINTER(aExecutable);
  *aExecutable = nullptr;
  return NS_ERROR_NOT_IMPLEMENTED;
}
NS_IMETHODIMP nsMIMEInfoUnix::GetHasDefaultHandler(bool* aResult) {
  NS_ENSURE_ARG_POINTER(aResult);
  *aResult = false;
  return NS_OK;
}
nsresult nsMIMEInfoUnix::LaunchDefaultWithFile(nsIFile*) {
  return NS_ERROR_NOT_IMPLEMENTED;
}
