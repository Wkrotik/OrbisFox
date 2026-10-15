/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "nsIBrowserDOMWindow.h"
#include "nsGlobalWindowOuter.h"
#include "nsWindowWatcher.h"
#include "mozilla/dom/Document.h"
#include "mozilla/dom/ScriptSettings.h"

// The windowless embedding does not have AppWindow/nsContentTreeOwner. Its
// container must provide this real native chain to browserDOMWindow. Never
// fall through to unsupported native-window creation on rejection.
NS_IMETHODIMP WebBrowserChrome2Stub::ProvideWindow(
    nsIOpenWindowInfo* aOpenWindowInfo, uint32_t aChromeFlags,
    bool aCalledFromJS, nsIURI* aURI, const nsAString& aName,
    const nsACString& aFeatures,
    const mozilla::dom::UserActivation::Modifiers& aModifiers,
    bool aForceNoOpener, bool aForceNoReferrer, bool aIsPopupRequested,
    nsDocShellLoadState* aLoadState, bool* aWindowIsNew,
    dom::BrowsingContext** aReturn) {
  NS_ENSURE_ARG_POINTER(aReturn);
  NS_ENSURE_ARG_POINTER(aWindowIsNew);
  *aReturn = nullptr;
  *aWindowIsNew = false;
  printf_stderr("Orbis window provider: entered; URI-present=%d no-opener=%d no-referrer=%d\n",
                int(aURI != nullptr), int(aForceNoOpener), int(aForceNoReferrer));
  if (!aOpenWindowInfo || !mBrowser) return NS_ERROR_ABORT;
  RefPtr<dom::BrowsingContext> parent = aOpenWindowInfo->GetParent();
  if (!parent || !parent->IsContent() || aOpenWindowInfo->GetIsForPrinting())
    return NS_ERROR_ABORT;
  nsCOMPtr<mozIDOMWindowProxy> proxy;
  if (NS_FAILED(mBrowser->GetContentDOMWindow(getter_AddRefs(proxy))) || !proxy)
    return NS_ERROR_ABORT;
  auto* chrome = nsGlobalWindowOuter::Cast(proxy);
  auto* document = chrome->GetDoc();
  if (!chrome->IsChromeWindow() || !document ||
      !document->NodePrincipal()->IsSystemPrincipal()) return NS_ERROR_ABORT;
  nsAutoCString spec;
  if (!document->GetDocumentURI() ||
      NS_FAILED(document->GetDocumentURI()->GetSpec(spec)) ||
      !spec.EqualsLiteral("chrome://orbisfox/content/browser.xhtml")) return NS_ERROR_ABORT;
  nsCOMPtr<nsIBrowserDOMWindow> bridge = chrome->GetBrowserDOMWindow();
  if (!bridge) return NS_ERROR_ABORT;
  int32_t where = nsWindowWatcher::GetWindowOpenLocation(
      parent->GetDOMWindow(), aChromeFlags, aModifiers, aCalledFromJS, false);
  // OrbisFox has bounded tabs, no additional native top-level window lane.
  if (where != nsIBrowserDOMWindow::OPEN_CURRENTWINDOW &&
      where != nsIBrowserDOMWindow::OPEN_NEWTAB_BACKGROUND &&
      where != nsIBrowserDOMWindow::OPEN_NEWTAB_FOREGROUND)
    where = nsIBrowserDOMWindow::OPEN_NEWTAB;
  uint32_t flags = nsIBrowserDOMWindow::OPEN_NEW;
  if (aForceNoOpener) flags |= nsIBrowserDOMWindow::OPEN_NO_OPENER;
  if (aForceNoReferrer) flags |= nsIBrowserDOMWindow::OPEN_NO_REFERRER;
  dom::AutoNoJSAPI nojsapi;
  RefPtr<NullPrincipal> principal = NullPrincipal::CreateWithoutOriginAttributes();
  const nsresult rv = bridge->CreateContentWindow(aURI, aOpenWindowInfo, where,
      flags, principal, nullptr, aReturn);
  if (NS_FAILED(rv) || !*aReturn) {
    printf_stderr("Orbis window provider: rejected; bridge-result=0x%08x\n", unsigned(rv));
    // A bridge returning a context on error violates the out-parameter contract.
    // Release it before returning cancellation, never let WindowWatcher use it.
    NS_IF_RELEASE(*aReturn);
    return NS_ERROR_ABORT;
  }
  bool remoteTabs = true, remoteSubframes = true;
  if (!(*aReturn)->IsContent() || NS_FAILED((*aReturn)->GetUseRemoteTabs(&remoteTabs)) ||
      NS_FAILED((*aReturn)->GetUseRemoteSubframes(&remoteSubframes)) || remoteTabs || remoteSubframes) {
    NS_RELEASE(*aReturn);
    return NS_ERROR_ABORT;
  }
  *aWindowIsNew = where != nsIBrowserDOMWindow::OPEN_CURRENTWINDOW;
  printf_stderr("Orbis window provider: bounded content context returned; new=%d location=%d; WindowWatcher owns loading\n",
                int(*aWindowIsNew), int(where));
  return NS_OK;
}
