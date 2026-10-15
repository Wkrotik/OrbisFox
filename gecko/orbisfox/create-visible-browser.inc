/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
// Included inside nsAppShellService.cpp to reuse its real browser lifetime
// container. The visible HeadlessWidget is independent of the BrowsingContext
// windowless flag, which describes the absence of a <browser> embedder and
// prevents unsupported process switching. Never create a PuppetWidget.
#include "nsIXULRuntime.h"
#include "nsFocusManager.h"
nsresult OrbisCreateVisibleBrowser(uint32_t aWidth, uint32_t aHeight,
                                  nsIWindowlessBrowser** aResult,
                                  nsIWidget** aNativeWidget,
                                  bool aChrome = false) {
  NS_ENSURE_ARG_POINTER(aResult);
  NS_ENSURE_ARG_POINTER(aNativeWidget);
  *aResult = nullptr;
  *aNativeWidget = nullptr;
  if (!aWidth || !aHeight || aWidth > 1280 || aHeight > 720) {
    return NS_ERROR_INVALID_ARG;
  }
  const bool globalRemote = mozilla::BrowserTabsRemoteAutostart();
  printf_stderr("Orbis browser: global remote-autostart=%d e10s-parent=%d\n",
                int(globalRemote), int(XRE_IsE10sParentProcess()));
  // A nonremote context alone is insufficient: parent document loading still
  // enforces E10s restrictions if the process-wide mode was initialized true.
  NS_ENSURE_FALSE(globalRemote || XRE_IsE10sParentProcess(), NS_ERROR_NOT_AVAILABLE);
  RefPtr<WebBrowserChrome2Stub> container = new WebBrowserChrome2Stub();
  nsCOMPtr<nsIWidget> nativeWidget = nsIWidget::CreateTopLevelWindow();
  NS_ENSURE_TRUE(nativeWidget, NS_ERROR_NOT_AVAILABLE);
  MOZ_TRY(nativeWidget->Create(nullptr,
      LayoutDeviceIntRect(0, 0, aWidth, aHeight), widget::InitData()));
  // The legacy content diagnostic remains independent/windowless. The UI
  // uses a genuine chrome docshell, with a separate nonremote content browser.
  const auto contextType = aChrome ? BrowsingContext::Type::Chrome : BrowsingContext::Type::Content;
  RefPtr<BrowsingContext> context = BrowsingContext::CreateIndependent(contextType, true);
  NS_ENSURE_TRUE(context->Windowless(), NS_ERROR_NOT_AVAILABLE);
  // CreateIndependent attaches this content context immediately. Its default
  // remote flags are false: validate them, but never invoke configuration
  // setters after attachment (CanSetOriginAttributes deliberately crashes).
  bool remoteTabs = true, remoteSubframes = true;
  MOZ_TRY(context->GetUseRemoteTabs(&remoteTabs));
  MOZ_TRY(context->GetUseRemoteSubframes(&remoteSubframes));
  NS_ENSURE_FALSE(remoteTabs || remoteSubframes, NS_ERROR_NOT_AVAILABLE);
  RefPtr<nsOpenWindowInfo> info = new nsOpenWindowInfo();
  if (aChrome) info->mPrincipalToInheritForAboutBlank = nsContentUtils::GetSystemPrincipal();
  else info->mPrincipalToInheritForAboutBlank = NullPrincipal::CreateWithoutOriginAttributes();
  RefPtr<nsWebBrowser> browser;
  MOZ_TRY(nsWebBrowser::Create(container, nativeWidget, context, nullptr,
                               info, getter_AddRefs(browser)));
  container->SetBrowser(browser);
  // This standalone content context has no active chrome parent to inherit
  // from. Visibility alone does not set activeness or enable refresh drivers.
  printf_stderr("Orbis browser: independent context active before=%d\n", int(context->IsActive()));
  MOZ_TRY(context->SetExplicitActive(mozilla::dom::ExplicitActiveStatus::Active));
  NS_ENSURE_TRUE(context->IsActive(), NS_ERROR_NOT_AVAILABLE);
  printf_stderr("Orbis browser: independent context active after=%d\n", int(context->IsActive()));
  MOZ_TRY(browser->SetPositionAndSize(0, 0, aWidth, aHeight, 0));
  MOZ_TRY(browser->SetVisibility(true));
  nativeWidget->Show(true);
  NS_ENSURE_TRUE(nativeWidget->IsVisible(), NS_ERROR_NOT_AVAILABLE);
  if (aChrome) {
    // Visibility/ExplicitActive don't raise the window in nsFocusManager.
    // There is no OS window manager for this fixed-screen embedding. Use the
    // same genuine embedding activation path as BrowserChild, so web content
    // can pass the normal focused-tab Fullscreen API checks.
    browser->FocusActivate(nsFocusManager::GenerateFocusActionId());
  }
  printf_stderr("Orbis browser: standalone context windowless=%d native-widget-visible=%d\n",
                int(context->Windowless()), int(nativeWidget->IsVisible()));
  nsISupports* owner = NS_ISUPPORTS_CAST(nsIWebBrowserChrome*, container);
  RefPtr<nsIWindowlessBrowser> result = new WindowlessBrowser(browser, owner);
  result.forget(aResult);
  nativeWidget.forget(aNativeWidget);
  return NS_OK;
}
