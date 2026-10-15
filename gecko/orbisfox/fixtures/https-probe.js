/* Real Necko/NSS probes only. No certificate overrides, injected test roots,
 * credentials, validation-pref changes, redirect following or public browsing.
 * External test sites can change: outage/wrong error must be FAIL, never PASS. */
function startTrustedHTTPSProbes(Cc, Ci, io, ssm, host, prerequisites) {
  const tests = [
    {name: "valid", uri: "https://example.com/"},
    {name: "untrusted", uri: "https://self-signed.badssl.com/",
      errors: ["SEC_ERROR_UNKNOWN_ISSUER", "MOZILLA_PKIX_ERROR_SELF_SIGNED_CERT"]},
    {name: "expired", uri: "https://expired.badssl.com/", errors: ["SEC_ERROR_EXPIRED_CERTIFICATE"]},
    {name: "wrongHost", uri: "https://wrong.host.badssl.com/", errors: ["SSL_ERROR_BAD_CERT_DOMAIN"]}
  ];
  const state = {started: false, complete: false, ok: false, results: {}};
  const requests = [], timers = [];
  let closed = false;
  const report = (test, fields) => {
    if (closed || state.results[test.name]?.done) return;
    state.results[test.name] = Object.assign({done: true, ok: false}, fields);
    state.complete = tests.every(item => state.results[item.name]?.done);
    state.ok = state.complete && tests.every(item => state.results[item.name].ok);
    host.log("Gecko real HTTPS " + test.name + ": " + JSON.stringify(state.results[test.name]));
  };
  // Prerequisite object is a privileged host snapshot, never page-controlled.
  if (host.nativeNetworkReady !== true || !prerequisites?.storage?.ok ||
      !prerequisites?.dns?.ok || io.offline) {
    for (const test of tests) report(test, {error: "Required native Net / storage / DNS gates not passed"});
  } else {
    state.started = true;
    host.log("Gecko HTTPS validation probes: normal NSS trust and hostname/time checks; no certificate overrides or custom roots");
    for (const test of tests) {
      let request = null;
      try {
        const uri = io.newURI(test.uri), principal = ssm.getSystemPrincipal();
        request = io.newChannelFromURI(uri, null, principal, principal,
          Ci.nsILoadInfo.SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL, Ci.nsIContentPolicy.TYPE_OTHER);
        request.loadFlags |= Ci.nsIRequest.LOAD_ANONYMOUS | Ci.nsIRequest.LOAD_BYPASS_CACHE | Ci.nsIRequest.INHIBIT_CACHING;
        request.QueryInterface(Ci.nsIHttpChannel).redirectionLimit = 0;
        requests.push({test, request});
        let bytes = 0, body = "", response = null;
        request.asyncOpen({
          onStartRequest(channel) {
            if (closed || state.results[test.name]?.done) return;
            try { response = channel.QueryInterface(Ci.nsIHttpChannel).responseStatus; }
            catch (error) {
              // Necko still calls onStartRequest after TLS rejection. There is
              // no HTTP response then; wait for actual terminal NSS evidence.
              // This absence never counts as rejection by itself.
              if (test.name !== "valid" &&
                  (error.result >>> 0) === (Components.results.NS_ERROR_NOT_AVAILABLE >>> 0)) {
                host.log("Gecko HTTPS " + test.name + ": no HTTP response; awaiting terminal TLS evidence");
                return;
              }
              report(test, {error: "HTTP start: " + String(error).slice(0, 180)});
              channel.cancel(Components.results.NS_BINDING_ABORTED);
            }
          },
          onDataAvailable(channel, stream, offset, count) {
            if (closed || state.results[test.name]?.done) return;
            if (count > 65536 || bytes + count > 65536) {
              report(test, {error: "HTTPS probe exceeds 65536-byte bound"});
              channel.cancel(Components.results.NS_BINDING_ABORTED); return;
            }
            const input = Cc["@mozilla.org/binaryinputstream;1"].createInstance(Ci.nsIBinaryInputStream);
            input.setInputStream(stream); const chunk = input.readBytes(count);
            bytes += chunk.length; if (test.name === "valid") body += chunk;
          },
          onStopRequest(channel, status) {
            if (closed || state.results[test.name]?.done) return;
            try {
              const exactURI = channel.QueryInterface(Ci.nsIChannel).URI.spec === test.uri;
              const info = channel.securityInfo.QueryInterface(Ci.nsITransportSecurityInfo);
              const errorCode = info.errorCode, errorName = info.errorCodeString;
              const secure = (info.securityState & Ci.nsIWebProgressListener.STATE_IS_SECURE) !== 0;
              // Post-handshake getters can throw on rejected certificates.
              // They are mandatory for success, irrelevant to negative proof.
              const chainLength = test.name === "valid" ? info.succeededCertChain.length : null;
              const builtinRoot = test.name === "valid" ? info.isBuiltCertChainRootBuiltInRoot : null;
              const protocol = test.name === "valid" ? info.protocolVersion : null;
              const ok = test.name === "valid" ?
                (status >>> 0) === 0 && exactURI && response === 200 && secure && errorCode === 0 &&
                  !!info.serverCert && chainLength >= 2 && builtinRoot === true &&
                  protocol >= Ci.nsITransportSecurityInfo.TLS_VERSION_1_2 && body.includes("Example Domain") :
                (status >>> 0) !== 0 && exactURI && !secure && response === null && bytes === 0 &&
                  errorCode !== 0 && test.errors.includes(errorName);
              report(test, {ok, status: status >>> 0, response, bytes, exactURI, secure,
                errorCode, errorName, protocol, chainLength, builtinRoot});
            } catch (error) { report(test, {error: "TLS evidence unavailable: " + String(error).slice(0, 200)}); }
          },
          QueryInterface: ChromeUtils.generateQI(["nsIStreamListener", "nsIRequestObserver"])
        });
        const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer); timers.push(timer);
        timer.initWithCallback(() => {
          if (closed || state.results[test.name]?.done) return;
          report(test, {error: "20-second callback deadline; not certificate-rejection proof"});
          try { request.cancel(Components.results.NS_BINDING_ABORTED); }
          catch (error) { host.log("ERROR: HTTPS timeout cancellation: " + error); }
        }, 20000, Ci.nsITimer.TYPE_ONE_SHOT);
      } catch (error) {
        report(test, {error: String(error).slice(0, 220)});
        if (request) try { request.cancel(Components.results.NS_BINDING_ABORTED); }
        catch (failure) { host.log("ERROR: HTTPS cancellation: " + failure); }
      }
    }
  }
  return {
    snapshot() { return JSON.parse(JSON.stringify(state)); },
    close() {
      if (closed) return; closed = true;
      for (const timer of timers) timer.cancel();
      for (const {test, request} of requests) if (!state.results[test.name]?.done) {
        try { request.cancel(Components.results.NS_BINDING_ABORTED); }
        catch (error) { host.log("ERROR: HTTPS close cancellation: " + error); }
      }
    }
  };
}
