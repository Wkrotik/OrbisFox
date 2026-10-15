"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const uri=text=>{const u=new URL(text);return {spec:u.href,scheme:u.protocol.slice(0,-1),prePath:u.origin,userPass:u.username||u.password};};
(async()=>{
 let created=0,started=0,active=0,peak=0,save=0,cacheReads=0;const channels=[],timers=[];
 const png=[137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82,0,0,0,16,0,0,0,16];
 const service={getFaviconForPage:async()=>{++cacheReads;return null;},setFaviconForPage:async()=>{++save;}};
 const Cc={
  '@mozilla.org/browser/favicon-service;1':{getService:()=>service},
  '@mozilla.org/timer;1':{createInstance:()=>{const t={initWithCallback(fn,delay){assert.equal(delay,5000);this.fn=fn;},cancel(){this.cancelled=true;}};timers.push(t);return t;}},
  '@mozilla.org/binaryinputstream;1':{createInstance:()=>({setInputStream(input){this.input=input;},readByteArray(n){return this.input.slice(0,n);}})}
 };
 const Ci={nsILoadInfo:{SEC_REQUIRE_SAME_ORIGIN_INHERITS_SEC_CONTEXT:19},nsIContentPolicy:{TYPE_IMAGE:3},nsIRequest:{LOAD_ANONYMOUS:16},nsITimer:{TYPE_ONE_SHOT:0}};
 const io={newURI:uri,newChannelFromURI(icon,unused,principal,extra,flags,type){
  ++created;assert.equal(icon.prePath,principal.uri.prePath);assert.equal(principal.system,false);assert.equal(flags,19);assert.equal(type,3);
  const c={icon,loadFlags:0,contentLength:png.length,asyncOpen(listener){this.listener=listener;++started;++active;peak=Math.max(peak,active);assert(this.loadFlags&16);},cancel(){this.cancelled=true;},complete(bytes=png,status=0){--active;this.listener.onStartRequest(this);this.listener.onDataAvailable(this,bytes,0,bytes.length);this.listener.onStopRequest(this,status);}};channels.push(c);return c;
 }};
 const ssm={createContentPrincipal:u=>({uri:u,system:false})},logs=[];
 const context=vm.createContext({URL,Uint8Array,ChromeUtils:{generateQI:()=>()=>{},base64URLEncode:(bytes)=>Buffer.from(bytes).toString('base64').replace(/\+/g,'-').replace(/\//g,'_')},console});
 vm.runInContext(fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-host.js','utf8'),context);
 const cache=context.createOrbisFaviconCache(Cc,Ci,io,ssm,{log:t=>logs.push(t)},()=>true);
 const doc={nodePrincipal:{isSystemPrincipal:false},readyState:'complete',documentURI:'https://a.example/page',querySelector:()=>({href:'https://cross.example/evil.svg'})};
 const flush=()=>new Promise(resolve=>setImmediate(resolve));
 assert.equal(cache.request('chrome://orbisfox/'),null);assert.equal(cache.request('https://user:secret@a.example/'),null);
 assert.equal(cache.request('https://a.example/page',doc),null);cache.request('https://b.example/');cache.request('https://c.example/');await flush();
 assert.equal(started,2);assert.equal(channels[0].icon.spec,'https://a.example/favicon.ico');channels[0].complete();await flush();assert.equal(started,3);assert.equal(peak,2);
 assert.match(cache.request('https://a.example/page#fragment'),/^data:image\/png;base64,/);assert.equal(cache.revision,1);assert.equal(save,1);
 channels[1].complete([...png.slice(0,16),0,0,16,0,0,0,0,16]);channels[2].complete([...Buffer.from('<svg>')]);await flush();assert.equal(cache.revision,1,'oversize PNG and active SVG must be rejected');
 const before=created;cache.request('https://a.example/page');await flush();assert.equal(created,before,'no repeated network requests per UI frame');
 for(let n=0;n<140;++n)cache.request('https://bounded.example/'+n);await flush();assert.equal(cacheReads,5,'only two bounded concurrent requests start');cache.close();assert(channels.at(-1).cancelled);assert.equal(cache.request('https://later.example/'),null);
 console.log('Favicon source: same-origin anonymous web principals, concurrency2/cache128/32KiB limits, raster validation, cleanup, no system-principal fetches; explicit channel/Places doubles, not firmware proof');
})().catch(error=>{console.error(error);process.exitCode=1;});
