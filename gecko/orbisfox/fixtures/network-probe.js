/* Privileged, bounded Necko bring-up. No injected web privileges, TLS bypass,
 * socket replacement, remote rendering, or production website-security claim. */
function startTrustedNetworkProbes(Cc, Ci, io, tm, ssm, host) {
  const origin = "http://10.42.0.1:8765";
  const token = "e639f704a0814bef91854c0d69bab865";
  const expected = "OrbisFox native Necko probe " + token + "\n";
  const state = { storage: { done: false, ok: false, error: null },
                  http: { done: false, ok: false, bytes: 0, status: null },
                  dns: { done: false, ok: false, addresses: [], status: null } };
  let http = null, dns = null, closed = false;
  const timers = [];
  const report = (part, fields) => {
    if (closed || state[part].done) return;
    Object.assign(state[part], fields, {done: true});
    host.log("Gecko real network " + part + ": " + JSON.stringify(state[part]));
  };
  const deadline = (part, request) => {
    const timer = Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
    timers.push(timer);
    timer.initWithCallback(() => {
      if (closed || state[part].done) return;
      report(part, {ok: false, error: "12-second callback deadline; cancellation requested"});
      try { request.cancel(Components.results.NS_BINDING_ABORTED); }
      catch (error) { host.log("ERROR: network " + part + " timeout cancellation: " + error); }
    }, 12000, Ci.nsITimer.TYPE_ONE_SHOT);
  };
  try {
    if (!verifyTrustedPersistentStorage(Cc, Ci, host)) throw new Error("Persistent storage gate returned false");
    Object.assign(state.storage, {done: true, ok: true});
  } catch (error) {
    const failure = "Persistent storage gate: " + String(error).slice(0, 220);
    Object.assign(state.storage, {done: true, ok: false, error: failure});
    host.log("ERROR: " + failure + "; networking not started");
    report("http", {ok: false, error: failure});
    report("dns", {ok: false, error: failure});
  }
  if (!state.http.done) try {
    if (host.nativeNetworkReady !== true)
      throw new Error("Native Net module/init/resolver-symbol gate failed; no Necko requests permitted");
    io.manageOfflineStatus = false;
    io.offline = false;
    if (io.offline) throw new Error("Necko remained offline");
    host.log("Gecko network bring-up: LAN HTTP and native DNS only; HTTPS NOT TESTED; browser remains on trusted fixture");
  } catch (error) {
    report("http", {ok: false, error: "Online transition: " + String(error).slice(0, 240)});
    report("dns", {ok: false, error: "Online transition: " + String(error).slice(0, 240)});
  }
  if (!state.http.done) try {
    const principal = ssm.getSystemPrincipal();
    const uri = io.newURI(origin + "/orbisfox/probe/" + token);
    http = io.newChannelFromURI(uri, null, principal, principal,
      Ci.nsILoadInfo.SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL, Ci.nsIContentPolicy.TYPE_OTHER);
    http.loadFlags |= Ci.nsIRequest.LOAD_ANONYMOUS | Ci.nsIRequest.LOAD_BYPASS_CACHE |
                      Ci.nsIRequest.INHIBIT_CACHING;
    const httpChannel = http.QueryInterface(Ci.nsIHttpChannel);
    httpChannel.redirectionLimit = 0;
    let body = "", response = null;
    http.asyncOpen({
      onStartRequest(request) {
        if (closed || state.http.done) return;
        try {
          response = request.QueryInterface(Ci.nsIHttpChannel).responseStatus;
          host.log("Gecko real network HTTP started: response=" + response);
        } catch (error) {
          report("http", {ok: false, error: "HTTP start: " + String(error).slice(0, 240)});
          request.cancel(Components.results.NS_BINDING_ABORTED);
        }
      },
      onDataAvailable(request, stream, offset, count) {
        if (closed || state.http.done) return;
        if (count > 4096 || body.length + count > 4096) {
          report("http", {ok: false, error: "Response exceeds 4096-byte probe bound"});
          request.cancel(Components.results.NS_BINDING_ABORTED); return;
        }
        const input = Cc["@mozilla.org/binaryinputstream;1"].createInstance(Ci.nsIBinaryInputStream);
        input.setInputStream(stream);
        body += input.readBytes(count);
        state.http.bytes = body.length;
      },
      onStopRequest(request, status) {
        if (closed || state.http.done) return;
        const exactURI = request.QueryInterface(Ci.nsIChannel).URI.spec === uri.spec;
        report("http", {status: status >>> 0, response, exactURI,
          bodyMatches: body === expected,
          ok: (status >>> 0) === 0 && response === 200 && exactURI && body === expected});
      },
      QueryInterface: ChromeUtils.generateQI(["nsIStreamListener", "nsIRequestObserver"])
    });
    deadline("http", http);
    host.log("Gecko real network HTTP AsyncOpen returned; no success assumed");
  } catch (error) {
    report("http", {ok: false, error: String(error).slice(0, 240)});
    if (http) {
      try { http.cancel(Components.results.NS_BINDING_ABORTED); }
      catch (failure) { host.log("ERROR: failed HTTP probe cancellation: " + failure); }
    }
  }
  if (!state.dns.done) try {
    const service = Cc["@mozilla.org/network/dns-service;1"].getService(Ci.nsIDNSService);
    const listener = {
      onLookupComplete(request, record, status) {
        if (closed || state.dns.done) return;
        const addresses = [];
        let error = null;
        if ((status >>> 0) === 0) {
          try {
            const result = record.QueryInterface(Ci.nsIDNSAddrRecord);
            while (addresses.length < 8 && result.hasMore()) {
              const address = result.getNextAddrAsString();
              if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(address) ||
                  address.split(".").some(value => Number(value) > 255))
                throw new Error("Unexpected native IPv4 DNS result");
              addresses.push(address);
            }
          } catch (failure) { error = String(failure).slice(0, 240); }
        }
        report("dns", {host: "example.com", status: status >>> 0, addresses, error,
          ok: (status >>> 0) === 0 && !error && addresses.length > 0});
      },
      QueryInterface: ChromeUtils.generateQI(["nsIDNSListener"])
    };
    dns = service.asyncResolve("example.com", Ci.nsIDNSService.RESOLVE_TYPE_DEFAULT,
      Ci.nsIDNSService.RESOLVE_DISABLE_TRR | Ci.nsIDNSService.RESOLVE_DISABLE_IPV6,
      null, listener, tm.mainThread, {});
    deadline("dns", dns);
    host.log("Gecko real network DNS AsyncResolve returned; native resolver, no success assumed");
  } catch (error) {
    report("dns", {ok: false, error: String(error).slice(0, 240)});
    if (dns) {
      try { dns.cancel(Components.results.NS_BINDING_ABORTED); }
      catch (failure) { host.log("ERROR: failed DNS probe cancellation: " + failure); }
    }
  }
  return {
    snapshot() { return JSON.parse(JSON.stringify(state)); },
    canNavigateLAN() { return !closed && state.http.done && state.http.ok; },
    fixtureURI: origin + "/orbisfox/offline.html",
    close() {
      if (closed) return;
      closed = true;
      for (const timer of timers) timer.cancel();
      for (const [part, request] of [["http", http], ["dns", dns]]) {
        if (request && !state[part].done) {
          try { request.cancel(Components.results.NS_BINDING_ABORTED); }
          catch (error) { host.log("ERROR: network " + part + " close cancellation: " + error); }
        }
      }
      http = dns = null;
      io.offline = true;
    }
  };
}
