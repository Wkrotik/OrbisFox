/* Trusted local/LAN development launcher using Firefox's own XPConnect shell.
 * Not injected into web content; no substitute DOM or layout implementation. */
"use strict";
// Bounded synchronous I/O probe of the packaged fixture, separate from the
// actual file-channel document navigation. No replacement DOM or layout.
function readTrustedFixture(Cc, Ci, file) {
  if (!file.isFile() || file.fileSize <= 0 || file.fileSize > 65536)
    throw new Error("Invalid trusted fixture size/type");
  const stream = Cc["@mozilla.org/network/file-input-stream;1"].createInstance(Ci.nsIFileInputStream);
  const converter = Cc["@mozilla.org/intl/converter-input-stream;1"].createInstance(Ci.nsIConverterInputStream);
  stream.init(file, -1, -1, 0);
  let initialized = false, text = "";
  try {
    converter.init(stream, "UTF-8", 4096, 0);
    initialized = true;
    const chunk = {};
    while (converter.readString(4096, chunk)) {
      text += chunk.value;
      if (text.length > 65536) throw new Error("Trusted fixture exceeds bound");
    }
    if (!/^<!doctype html>/i.test(text)) throw new Error("Trusted fixture doctype missing");
    return text;
  } finally {
    if (initialized) converter.close(); else stream.close();
  }
}
// XPCShell does not run Firefox's InitializeUserPrefs startup path. Saving
// prefs.js is insufficient: load it after registering ProfD and before applying
// this port's runtime policy or constructing the browser UI.
function restoreOrbisFoxPreferences(Cc,Ci,profile,host) {
  const file=profile.clone();file.append("prefs.js");
  if(!file.exists()){host.log("Gecko profile preferences: no saved prefs.js on first run");return false;}
  if(!file.isFile() || file.fileSize>4*1024*1024)throw Error("Invalid saved profile preferences file");
  Cc["@mozilla.org/preferences-service;1"].getService(Ci.nsIPrefService).readUserPrefsFromFile(file);
  host.log("Gecko profile preferences: saved prefs.js restored before browser UI");return true;
}
(() => {
  const Cc = Components.classes, Ci = Components.interfaces;
  const host = Cc["@orbisfox.local/native-host;1"].getService(Ci.nsIOrbisFoxHost);
  host.log("Gecko startup: privileged XPConnect launcher entered");
  const prefs = Cc["@mozilla.org/preferences-service;1"].getService(Ci.nsIPrefBranch);
  const io = Cc["@mozilla.org/network/io-service;1"].getService(Ci.nsIIOService);
  const tm = Cc["@mozilla.org/thread-manager;1"].getService(Ci.nsIThreadManager);
  const ssm = Cc["@mozilla.org/scriptsecuritymanager;1"].getService(Ci.nsIScriptSecurityManager);
  const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  let browser = null, running = true, previousButtons = 0;
  let webProgress = null, progressListener = null, lastDocumentState = "";
  let reported = false, warned = false, rendererReported = false;
  let fileProbeChannel = null, networkProbes = null, httpsProbes = null;
  let lastNetworkState = "", documentBeforeLoad = null;
  globalThis.load("/app0/assets/storage-probe.js");
  globalThis.load("/app0/assets/network-probe.js");
  globalThis.load("/app0/assets/https-probe.js");
  const fileProbe = { started: false, bytes: 0, stopped: false, status: null };
  let profileLifecycle = null, directories = null, provider = null;
  const started = Date.now();
  try {
    const applyRuntimePreferences=()=>{
    for (const [name, value] of Object.entries({
      "gfx.webrender.all": true,
      "gfx.webrender.software": true,
      "gfx.webrender.compositor": false,
      "layers.acceleration.disabled": true,
      "layers.gpu-process.enabled": false,
      "network.process.enabled": false,
      "browser.tabs.remote.autostart": false,
      "dom.ipc.processPrelaunch.enabled": false,
      "toolkit.telemetry.enabled": false,
      "toolkit.telemetry.unified": false,
      "datareporting.healthreport.uploadEnabled": false,
      "dom.push.enabled": false,
      // Native Gecko compatibility token, using the real engine version. The
      // OrbisFox app token remains present; no UA override or fake capabilities.
      "general.useragent.compatMode.firefox": true,
      "dom.viewTransitions.cross-document.enabled": false,
      "media.gmp-provider.enabled": false,
      "media.rdd-process.enabled": false,
      "media.utility-process.enabled": false,
      "media.allow-audio-non-utility": true,
      "full-screen-api.enabled": true,
      // Native VideoOut already owns the physical screen. Fullscreen changes
      // the real DOM and chrome viewport, not an unsupported OS window mode.
      "full-screen-api.ignore-widgets": true,
      "media.ffvpx.enabled": true,
      "media.ffmpeg.enabled": false,
      // Prefer VP9/Opus for this CPU-rendered first playback implementation.
      "media.av1.enabled": false,
      "javascript.options.baselinejit": host.nativeJitReady===true,
      "javascript.options.native_regexp": host.nativeJitReady===true,
      "javascript.options.ion": false,
      "javascript.options.wasm": false
    })) prefs.setBoolPref(name, value);
    prefs.setCharPref("layout.css.devPixelsPerPx", "1.0");
    prefs.setIntPref("dom.ipc.processCount", 1);
    // Content/chrome DOM at30Hz; independent native cursor/menu stays60Hz.
    prefs.setIntPref("layout.frame_rate", 30);
    prefs.setIntPref("layout.throttled_frame_rate", 1);
    io.manageOfflineStatus = false;
    io.offline = true;
    };
    const profile = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    profile.initWithPath("/data/orbisfox/gecko-profile");
    if (!profile.exists()) profile.create(Ci.nsIFile.DIRECTORY_TYPE, 0o700);
    directories = Cc["@mozilla.org/file/directory_service;1"].getService(Ci.nsIDirectoryService);
    provider = {
      getFile(name, persistent) {
        if (["ProfD", "ProfLD", "cachePDir", "ProfDS", "ProfLDS"].includes(name)) {
          persistent.value = true;
          return profile.clone();
        }
        // DirectoryService tries the next provider when this one returns no
        // file. Decline unknown keys; never invent paths or throw into native
        // startup callbacks for ordinary provider fall-through.
        persistent.value = false;
        return null;
      },
      QueryInterface: ChromeUtils.generateQI(["nsIDirectoryServiceProvider"])
    };
    directories.registerProvider(provider);
    restoreOrbisFoxPreferences(Cc,Ci,profile,host);
    applyRuntimePreferences();
    globalThis.load("/app0/assets/profile-lifecycle.js");
    profileLifecycle = startOrbisFoxProfile(Cc, Ci, host, ssm, io);
    const pageJavaScriptEnabled = prefs.getBoolPref("javascript.enabled", false);
    host.log("Gecko generated defaults: javascript.enabled=" + pageJavaScriptEnabled);
    if (!pageJavaScriptEnabled) throw new Error("Required Gecko defaults do not enable fixture JavaScript");
    const diagnosticMarker = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    diagnosticMarker.initWithPath("/data/orbisfox/diagnostic-only");
    if (!diagnosticMarker.exists()) {
      globalThis.load("/app0/assets/browser-shell-host.js");
      runOrbisFoxBrowserShell(Cc, Ci, host, io, tm, ssm, profileLifecycle);
      return;
    }
    host.log("Gecko: explicit diagnostic-only marker retains direct-content fixture lane");
    browser = host.createBrowser(1280, 720);
    webProgress = browser.docShell.QueryInterface(Ci.nsIWebProgress);
    let progressMessages = 0;
    const logProgress = message => { if (progressMessages++ < 32) host.log(message); };
    progressListener = {
      onStateChange(progress, request, flags, status) {
        logProgress("Gecko load state: flags=0x" + (flags >>> 0).toString(16) +
                    " status=0x" + (status >>> 0).toString(16));
      },
      onLocationChange(progress, request, location) {
        logProgress("Gecko load location: " + (location ? location.spec.slice(0, 160) : "none"));
      },
      onStatusChange(progress, request, status, message) {
        logProgress("Gecko load status: 0x" + (status >>> 0).toString(16) + " " + String(message).slice(0, 240));
      },
      onProgressChange() {}, onSecurityChange() {}, onContentBlockingEvent() {},
      QueryInterface: ChromeUtils.generateQI(["nsIWebProgressListener", "nsISupportsWeakReference"])
    };
    webProgress.addProgressListener(progressListener, Ci.nsIWebProgress.NOTIFY_STATE_DOCUMENT |
        Ci.nsIWebProgress.NOTIFY_LOCATION | Ci.nsIWebProgress.NOTIFY_STATUS);
    const fileURI = io.newURI("file:///app0/assets/offline.html");
    const fixtureFile = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    fixtureFile.initWithPath("/app0/assets/offline.html");
    host.log("Gecko fixture: synchronous packaged UTF-8 read entered");
    const html = readTrustedFixture(Cc, Ci, fixtureFile);
    host.log("Gecko fixture: synchronous read returned; bytes=" + fixtureFile.fileSize + "; characters=" + html.length);
    let uri = fileURI;
    const principal = ssm.getSystemPrincipal();
    fileProbeChannel = io.newChannelFromURI(fileURI, null, principal, principal,
        Ci.nsILoadInfo.SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL, Ci.nsIContentPolicy.TYPE_OTHER);
    fileProbeChannel.asyncOpen({
      onStartRequest() { fileProbe.started = true; host.log("Gecko async file probe: listener started"); },
      onDataAvailable(request, stream, offset, count) {
        const input = Cc["@mozilla.org/binaryinputstream;1"].createInstance(Ci.nsIBinaryInputStream);
        input.setInputStream(stream);
        input.readBytes(count);
        fileProbe.bytes += count;
      },
      onStopRequest(request, status) {
        fileProbe.stopped = true; fileProbe.status = status >>> 0;
        host.log("Gecko async file probe: " + JSON.stringify(fileProbe));
      },
      QueryInterface: ChromeUtils.generateQI(["nsIStreamListener", "nsIRequestObserver"])
    });
    host.log("Gecko async file probe: AsyncOpen returned; no completion assumed");
    const load = () => {
      documentBeforeLoad = browser.docShell.domWindow.document;
      host.log("Gecko stage: loadURI call entered");
      browser.loadURI(uri, { triggeringPrincipal: ssm.getSystemPrincipal() });
      host.log("Gecko stage: loadURI call returned");
    };
    host.log("Gecko: verified single-process visible browser; original offline file navigation; independent file-channel probe retained");
    load();
    let ticks = 0;
    let lastClicks = 0;
    host.log("Gecko stage: timer initialization entered");
    timer.initWithCallback(() => {
      try {
        ++ticks;
        if (ticks <= 16) host.log("Gecko timer callback entered: " + ticks);
        if (ticks === 1) host.log("Gecko stage: first timer callback entered");
        if (!host.pumpFrame()) { running = false; return; }
        if (ticks === 1) host.log("Gecko stage: first frame pump returned");
        const buttons = host.buttons;
        if ((buttons & 2) && !(previousButtons & 2)) {
          host.log("Gecko: Triangle reload requested");
          reported = false;
          load();
        }
        if ((buttons & 4) && !(previousButtons & 4)) {
          if (networkProbes && networkProbes.canNavigateLAN()) {
            uri = io.newURI(networkProbes.fixtureURI);
            host.log("Gecko: Square controlled LAN fixture navigation requested: " + uri.spec);
            reported = false;
            load();
          } else host.log("Gecko: LAN navigation refused until exact native HTTP probe succeeds");
        }
        previousButtons = buttons;
        const window = browser.docShell.domWindow;
        const result = window && window.wrappedJSObject.orbisfoxFixture;
        const clicks = window && window.wrappedJSObject.orbisfoxClicks;
        if (Number.isSafeInteger(clicks) && clicks !== lastClicks) {
          if (clicks <= 16) host.log("Gecko fixture real DOM button count: " + clicks);
          lastClicks = clicks;
        }
        if (window && (ticks === 1 || ticks % 60 === 0)) {
          const state = JSON.stringify({ uri: browser.currentURI && browser.currentURI.spec.slice(0, 160),
            ready: window.document.readyState, title: window.document.title,
            visibility: window.document.visibilityState, active: browser.browsingContext.isActive,
            softwareWebRender: host.softwareWebRender, fileProbe,
            progress: window.wrappedJSObject.orbisfoxProgress || null });
          if (state !== lastDocumentState) { host.log("Gecko document: " + state); lastDocumentState = state; }
        }
        if (result && !reported && window.document !== documentBeforeLoad &&
            window.document.documentURI === uri.spec) {
          host.log("Gecko fixture assertion document: " + window.document.documentURI);
          host.log("Gecko fixture DOM/CSS assertions: " + JSON.stringify(result));
          host.fixtureCheckpoint(result.passed);
          reported = true;
          if (result.ok && result.passed === 8 && !networkProbes) {
            networkProbes = startTrustedNetworkProbes(Cc, Ci, io, tm, ssm, host);
          }
        }
        if (networkProbes && window) {
          const network = networkProbes.snapshot();
          if (!httpsProbes && network.storage.ok && network.http.ok && network.dns.ok)
            httpsProbes = startTrustedHTTPSProbes(Cc, Ci, io, ssm, host, network);
          const https = httpsProbes ? httpsProbes.snapshot() : null;
          const httpsStatus = !https ? "NOT STARTED" : !https.complete ? "PENDING" : https.ok ? "PASS (valid + 3 rejects)" : "FAIL (see log)";
          const source = window.document.documentURI.startsWith("http:") ? "HTTP fixture" : "FILE fixture";
          const storageStatus = network.storage.ok ? "SQLite PASS" : "SQLite FAIL (see log)";
          const status = source + " / " + storageStatus + " / LAN HTTP " + (network.http.done ? (network.http.ok ? "PASS" : "FAIL") : "PENDING") +
            " / native DNS " + (network.dns.done ? (network.dns.ok ? "PASS" : "FAIL") : "PENDING") +
            " / HTTPS " + httpsStatus + ". Square: LAN fixture after HTTP PASS.";
          const element = window.document.getElementById("network-status");
          if (element && element.textContent !== status) element.textContent = status;
          const serialized = JSON.stringify({network, https});
          if (serialized !== lastNetworkState) {
            host.log("Gecko network state: " + serialized); lastNetworkState = serialized;
          }
        }
        if (host.framesPresented && !rendererReported) {
          host.log("Gecko VideoOut: first published frame presented; software WebRender=" + host.softwareWebRender);
          rendererReported = true;
          if (!host.softwareWebRender) host.log("ERROR: Gecko frame exists, but SWGL selection is not confirmed");
        }
        if (!warned && Date.now() - started > 30000 && (!reported || !host.framesPresented)) {
          host.log("ERROR: 30-second bring-up timeout: DOM assertions=" + reported + "; presented frames=" + host.framesPresented);
          warned = true;
        }
        if (ticks <= 16) host.log("Gecko timer callback returned: " + ticks);
        if (ticks % 60 === 0) host.log("Gecko timer heartbeat: ticks=" + ticks + "; frames=" + host.framesPresented);
      } catch (error) {
        host.log("ERROR: Gecko event loop: " + error + "\n" + error.stack);
        running = false;
      }
    }, 16, Ci.nsITimer.TYPE_REPEATING_SLACK);
    host.log("Gecko stage: timer initialization returned; event loop entered");
    tm.spinEventLoopUntil("OrbisFox trusted offline browser", () => !running);
    host.log("Gecko stage: event loop returned");
    if (httpsProbes) httpsProbes.close();
    if (networkProbes) networkProbes.close();
    timer.cancel();
  } catch (error) {
    host.log("ERROR: Gecko startup: " + error + "\n" + error.stack);
    throw error;
  } finally {
    if (httpsProbes) httpsProbes.close();
    httpsProbes = null;
    if (networkProbes) networkProbes.close();
    networkProbes = null;
    documentBeforeLoad = null;
    timer.cancel();
    if (webProgress && progressListener) {
      try { webProgress.removeProgressListener(progressListener); }
      catch (error) { host.log("ERROR: progress listener cleanup: " + error); }
    }
    progressListener = null;
    webProgress = null;
    if (fileProbeChannel && !fileProbe.stopped) {
      host.log("Gecko async file probe still pending at close; cancelling actual request");
      try { fileProbeChannel.cancel(Components.results.NS_BINDING_ABORTED); }
      catch (error) { host.log("ERROR: file probe cancellation: " + error); }
    }
    fileProbeChannel = null;
    try { host.closeBrowser(); } catch(error) {host.log("ERROR: browser close: " + error);}
    browser = null;
    if (profileLifecycle) try {profileLifecycle.close();} catch(error) {host.log("ERROR: profile close: " + error);}
    if (directories && provider) directories.unregisterProvider(provider);
  }
})();
