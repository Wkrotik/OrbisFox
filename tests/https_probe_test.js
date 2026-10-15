// Actual helper with explicit Necko/TransportSecurityInfo/timer doubles.
// State/error/evidence gate tests only: not TLS, roots, NSS or firmware proof.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('gecko/orbisfox/fixtures/https-probe.js', 'utf8');
function setup(gate = '') {
  const requests = [], timers = [], logs = [];
  const io = {offline: gate === 'offline', newURI(spec) {return {spec};},
    newChannelFromURI(uri) {
      const request = {URI: uri, loadFlags: 0, redirectionLimit: 10, responseStatus: 200, cancelled: 0,
        QueryInterface() {return this;}, asyncOpen(listener) {this.listener = listener;}, cancel() {++this.cancelled;}};
      requests.push(request); return request;
    }};
  const Ci = {nsIRequest: {LOAD_ANONYMOUS:1, LOAD_BYPASS_CACHE:2, INHIBIT_CACHING:4},
    nsILoadInfo:{SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL:1},nsIContentPolicy:{TYPE_OTHER:1},nsITimer:{TYPE_ONE_SHOT:0},
    nsIWebProgressListener:{STATE_IS_SECURE:2},nsITransportSecurityInfo:{TLS_VERSION_1_2:3}};
  const Cc = {'@mozilla.org/timer;1': {createInstance() {
    const timer = {initWithCallback(callback, delay) {assert.equal(delay,20000);this.callback=callback;},cancel(){this.cancelled=true;}};
    timers.push(timer);return timer;
  }},'@mozilla.org/binaryinputstream;1':{createInstance(){return {setInputStream(stream){this.stream=stream;},readBytes(count){return this.stream.slice(0,count);}};}}};
  const prerequisites={storage:{ok:gate!=='storage'},http:{ok:gate!=='http'},dns:{ok:gate!=='dns'}};
  const context={Components:{results:{NS_BINDING_ABORTED:0x804b0002,NS_ERROR_NOT_AVAILABLE:0x80040111}},ChromeUtils:{generateQI(){return function(){return this;};}}};
  vm.runInNewContext(source,context);
  const probe=context.startTrustedHTTPSProbes(Cc,Ci,io,{getSystemPrincipal(){return 'explicit principal double';}},
    {nativeNetworkReady:gate!=='native-net',log(message){logs.push(message);}},prerequisites);
  function finish(index, changes={}) {
    const request=requests[index];assert(request);
    const valid=index===0;
    const names=['','SEC_ERROR_UNKNOWN_ISSUER','SEC_ERROR_EXPIRED_CERTIFICATE','SSL_ERROR_BAD_CERT_DOMAIN'];
    const info={errorCode:valid?0:-8181,errorCodeString:names[index],securityState:valid?2:0,
      serverCert:valid?{}:null,succeededCertChain:valid?[{},{}]:[],isBuiltCertChainRootBuiltInRoot:valid,protocolVersion:3,
      QueryInterface(){return this;},...changes.info};
    request.securityInfo=info;
    if(!valid) for(const property of ['protocolVersion','succeededCertChain','isBuiltCertChainRootBuiltInRoot'])
      Object.defineProperty(info,property,{get(){throw Error('Not available after failed handshake');}});
    if(changes.uri)request.URI={spec:changes.uri};
    if(!valid && !changes.accepted) {
      Object.defineProperty(request,'responseStatus',{get(){throw Object.assign(Error('No HTTP response before TLS rejection'),{result:0x80040111});}});
      const cancellations=request.cancelled,before=JSON.stringify(probe.snapshot());
      request.listener.onStartRequest(request);
      assert.equal(request.cancelled,cancellations);assert.equal(JSON.stringify(probe.snapshot()),before);
    }
    if(valid || changes.accepted){request.listener.onStartRequest(request);const body=changes.body ?? 'Example Domain';
      request.listener.onDataAvailable(request,body,0,body.length);}
    if(changes.noInfo)request.securityInfo=null;
    request.listener.onStopRequest(request,changes.status ?? (valid?0:0x805a1ff3));
  }
  return {probe,requests,timers,logs,finish};
}
for(let cycle=0;cycle<32;++cycle){
  let s=setup();assert.equal(s.requests.length,4);assert(!s.probe.snapshot().ok);
  for(const request of s.requests){assert.equal(request.redirectionLimit,0);assert.equal(request.loadFlags,7);}
  for(let i=0;i<4;++i)s.finish(i);assert(s.probe.snapshot().ok);assert(s.probe.snapshot().complete);
  const snapshot=s.probe.snapshot();snapshot.ok=false;assert(s.probe.snapshot().ok);
  s.probe.close();s.probe.close();assert(s.timers.every(t=>t.cancelled));
  for(const gate of ['storage','dns','native-net','offline']){
    s=setup(gate);assert.equal(s.requests.length,0);assert(!s.probe.snapshot().started);assert(!s.probe.snapshot().ok);s.probe.close();
  }
  s=setup('http');assert.equal(s.requests.length,4);s.probe.close(); // LAN server not required for public browsing.
  for(const info of [{errorCode:-8181},{securityState:0},{serverCert:null},{succeededCertChain:[]},
      {isBuiltCertChainRootBuiltInRoot:false},{protocolVersion:2}]){
    s=setup();s.finish(0,{info});assert(!s.probe.snapshot().results.valid.ok);s.probe.close();
  }
  for(const changes of [{status:0x804b0002},{uri:'https://other.example/'},{body:'wrong document'},{noInfo:true},{body:'x'.repeat(65537)}]){
    s=setup();s.finish(0,changes);assert(!s.probe.snapshot().results.valid.ok);s.probe.close();
  }
  for(let i=1;i<4;++i){
    for(const changes of [{info:{errorCodeString:'NS_ERROR_UNKNOWN_HOST'}},{status:0},{info:{errorCode:0}},
        {accepted:true},{noInfo:true},{info:{securityState:2}}]){
      s=setup();s.finish(i,changes);const name=['valid','untrusted','expired','wrongHost'][i];
      assert(!s.probe.snapshot().results[name].ok);s.probe.close();
    }
  }
  for(let i=0;i<4;++i) {
    s=setup();const r=s.requests[i];
    Object.defineProperty(r,'responseStatus',{get(){throw Object.assign(Error('Bad HTTP getter'),{result:i===0?0x80040111:0x80004005});}});
    r.listener.onStartRequest(r);assert.equal(r.cancelled,1);
    assert(!s.probe.snapshot().results[['valid','untrusted','expired','wrongHost'][i]].ok);s.probe.close();
  }
  s=setup();s.timers.forEach(t=>t.callback());assert(!s.probe.snapshot().ok);assert(s.requests.every(r=>r.cancelled===1));
  for(let i=0;i<4;++i)s.finish(i);assert(!s.probe.snapshot().ok);s.probe.close();
  s=setup();s.probe.close();assert(s.requests.every(r=>r.cancelled===1));
  for(let i=0;i<4;++i)s.finish(i);assert(!s.probe.snapshot().complete);
}
console.log('Actual HTTPS helper: native/storage/DNS prerequisite gates (no required LAN server), verified builtin chain/TLS/body evidence, exact trust/time/domain rejections, no outage-as-rejection, limits/deadlines/late callbacks/cleanup, 32 cycles PASS (Necko/TLS evidence doubles)');
