// Execute actual Necko probe helper with explicit XPCOM channel/DNS/timer doubles.
// Not an HTTP/DNS/TLS/firmware or native Gecko integration certification.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('gecko/orbisfox/fixtures/network-probe.js', 'utf8');
function setup(failure = '') {
  const timers = [], messages = [];
  const state = {httpCancels: 0, dnsCancels: 0};
  const io = {offline: true, manageOfflineStatus: true, newURI(spec) {return {spec};},
    newChannelFromURI(uri, context, principal, loading, flags, type) {
      assert.equal(principal, loading); assert.equal(context, null);
      http.URI = uri; return http;
    }};
  const http = {loadFlags: 0, responseStatus: 200, redirectionLimit: 20,
    QueryInterface() {return this;},
    asyncOpen(listener) {state.httpListener = listener; if (failure === 'http') throw Error('HTTP unavailable');},
    cancel() {++state.httpCancels;}};
  const dns = {cancel() {++state.dnsCancels;}};
  const Cc = {
    '@mozilla.org/timer;1': {createInstance() {
      const timer = {initWithCallback(callback, delay) {assert.equal(delay, 12000); timer.callback = callback;},
                     cancel() {timer.cancelled = true;}};
      timers.push(timer); return timer;
    }},
    '@mozilla.org/binaryinputstream;1': {createInstance() {return {
      setInputStream(stream) {this.stream = stream;}, readBytes(count) {return this.stream.slice(0, count);}
    };}},
    '@mozilla.org/network/dns-service;1': {getService() {return {
      asyncResolve(host, type, flags, extra, listener, target, attributes) {
        assert.equal(host, 'example.com'); assert.equal(extra, null); assert.equal(flags, 544);
        state.dnsListener = listener; if (failure === 'dns') throw Error('DNS unavailable');
        return dns;
      }
    };}}
  };
  const Ci = {nsIRequest: {LOAD_ANONYMOUS: 1, LOAD_BYPASS_CACHE: 2, INHIBIT_CACHING: 4},
    nsITimer: {TYPE_ONE_SHOT: 0}, nsILoadInfo: {SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL: 1},
    nsIContentPolicy: {TYPE_OTHER: 1}, nsIDNSService: {RESOLVE_TYPE_DEFAULT: 0, RESOLVE_DISABLE_TRR: 512, RESOLVE_DISABLE_IPV6: 32}};
  const context = {verifyTrustedPersistentStorage() {
      if (failure === 'storage') throw Error('Required storage unavailable');
      return true; // Explicit storage gate double; actual helper tested separately.
    }, Components: {results: {NS_BINDING_ABORTED: 0x804b0002}},
    ChromeUtils: {generateQI() {return function() {return this;};}}};
  vm.runInNewContext(source, context);
  const probe = context.startTrustedNetworkProbes(Cc, Ci, io, {mainThread: {}},
    {getSystemPrincipal() {return 'explicit system principal double';}}, {nativeNetworkReady: failure !== 'native-net', log(message) {messages.push(message);}});
  if (failure === 'storage' || failure === 'native-net') {
    assert.equal(io.offline, true); assert.equal(http.redirectionLimit, 20);
    assert.equal(state.httpListener, undefined); assert.equal(state.dnsListener, undefined);
  } else {
    assert.equal(io.offline, false); assert.equal(http.redirectionLimit, 0);
    assert.equal(http.loadFlags, 7);
  }
  const expected = 'OrbisFox native Necko probe ' + source.match(/const token = "([a-f0-9]{32})"/)[1] + '\n';
  function finishHTTP(body = expected, status = 0, response = 200) {
    http.responseStatus = response; state.httpListener.onStartRequest(http);
    state.httpListener.onDataAvailable(http, body, 0, body.length);
    state.httpListener.onStopRequest(http, status);
  }
  function finishDNS(addresses = ['93.184.215.14'], status = 0) {
    let index = 0;
    const record = {QueryInterface() {return this;}, hasMore() {return index < addresses.length;},
                    getNextAddrAsString() {return addresses[index++];}};
    state.dnsListener.onLookupComplete(dns, record, status);
  }
  return {probe, state, timers, messages, io, http, finishHTTP, finishDNS};
}
for (let cycle = 0; cycle < 32; ++cycle) {
  let s = setup(); assert(!s.probe.canNavigateLAN());
  s.finishHTTP(); s.finishDNS(); assert(s.probe.canNavigateLAN());
  assert(s.probe.snapshot().storage.ok); assert(s.probe.snapshot().http.ok); assert(s.probe.snapshot().dns.ok);
  const snapshot = s.probe.snapshot(); snapshot.http.ok = false; assert(s.probe.snapshot().http.ok);
  s.probe.close(); s.probe.close(); assert.equal(s.io.offline, true); assert(s.timers.every(t => t.cancelled));
  assert(!s.probe.canNavigateLAN()); assert.equal(s.state.httpCancels, 0);
  s = setup(); s.finishHTTP('wrong'); assert(!s.probe.canNavigateLAN()); s.probe.close(); assert.equal(s.state.dnsCancels, 1);
  s = setup(); s.finishHTTP(undefined, 0x804b0002); assert(!s.probe.canNavigateLAN()); s.probe.close();
  s = setup(); s.finishHTTP(undefined, 0, 302); assert(!s.probe.canNavigateLAN()); s.probe.close();
  s = setup(); s.http.URI = {spec: s.http.URI.spec + '/redirect'}; s.finishHTTP(); assert(!s.probe.canNavigateLAN()); s.probe.close();
  s = setup(); s.finishHTTP('x'.repeat(4097)); assert(!s.probe.canNavigateLAN()); assert.equal(s.state.httpCancels, 1); s.probe.close();
  s = setup(); s.finishDNS([], 0x804b001e); assert(!s.probe.snapshot().dns.ok); s.probe.close();
  s = setup(); s.finishDNS(['999.1.1.1']); assert(!s.probe.snapshot().dns.ok); s.probe.close();
  s = setup(); s.finishDNS([]); assert(!s.probe.snapshot().dns.ok); s.probe.close();
  s = setup(); s.timers.forEach(t => t.callback()); assert(!s.probe.canNavigateLAN());
  assert.equal(s.state.httpCancels, 1); assert.equal(s.state.dnsCancels, 1);
  s.finishHTTP(); s.finishDNS(); assert(!s.probe.snapshot().http.ok); assert(!s.probe.snapshot().dns.ok); s.probe.close();
  s = setup(); s.probe.close(); assert.equal(s.state.httpCancels, 1); assert.equal(s.state.dnsCancels, 1);
  s.finishHTTP(); s.finishDNS(); assert(!s.probe.snapshot().http.ok);
  s = setup('http'); assert(!s.probe.snapshot().http.ok); s.probe.close();
  s = setup('dns'); assert(!s.probe.snapshot().dns.ok); s.probe.close();
  s = setup('storage'); assert(!s.probe.snapshot().storage.ok); assert(!s.probe.snapshot().http.ok); assert(!s.probe.snapshot().dns.ok);
  assert(!s.probe.canNavigateLAN()); assert.equal(s.timers.length, 0); s.probe.close();
  s = setup('native-net'); assert(!s.probe.snapshot().http.ok); assert(!s.probe.snapshot().dns.ok);
  assert.equal(s.state.httpListener, undefined); assert.equal(s.state.dnsListener, undefined);
  assert.equal(s.timers.length, 0); s.probe.close();
}
console.log('Actual Necko probe helper: exact body/URI/status gate, no redirects/credentials/cache, byte bounds, DNS errors, deadlines/cancellation/late callbacks/close, 32 cycles PASS (XPCOM doubles)');
