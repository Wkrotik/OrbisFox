"use strict";
// Actual lifecycle source; explicit observer/IndexedDB/sandbox/timer doubles.
// Host tests do not establish real QuotaManager or disk persistence.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('gecko/orbisfox/fixtures/profile-lifecycle.js','utf8');
function setup(fault='') {
  const calls=[],queue=[],timers=[],records=new Map();let opens=0,dbs=[];
  const later=fn=>queue.push(fn);
  const makeDB=()=>{
    const db={closed:false,objectStoreNames:{contains(){return true;}},createObjectStore(){calls.push('create-store');},close(){this.closed=true;calls.push('close-db');},
      transaction(name,mode){assert.equal(name,'records');const tx={error:'transaction failed',abort(){calls.push('abort');later(()=>tx.onabort?.());},
        objectStore(){return {put(value,key){calls.push('put');records.set(key,value);later(()=>fault==='write'?tx.onabort?.():tx.oncomplete?.());},
          get(key){calls.push('get');const r={result:fault==='mismatch'?'wrong':records.get(key)};later(()=>{r.onsuccess?.();tx.oncomplete?.();});return r;}};}};return tx;}};
    dbs.push(db);return db;
  };
  const factory={open(name,version){assert.equal(name,'orbisfox-durable-probe');assert.equal(version,1);const index=++opens;
    const req={error:'open failed'};later(()=>{
      if(fault==='timeout')return;
      if(fault==='open'||fault==='reopen'&&index===2){req.onerror?.();return;}
      if(fault==='blocked'){req.onblocked?.();return;}
      req.result=makeDB();if(index===1)req.onupgradeneeded?.();req.onsuccess?.();
    });return req;}};
  const Cc={
    '@mozilla.org/observer-service;1':{getService(){return {notifyObservers(subject,topic,data){calls.push(topic);if(fault==='shutdown'&&topic==='profile-before-change')throw Error('one failed observer');}};}},
    '@mozilla.org/dom/quota-manager-service;1':{getService(){calls.push('quota-service');return {};}},
    '@mozilla.org/timer;1':{createInstance(){const t={cancel(){calls.push('cancel-timer');},initWithCallback(fn,delay){assert.equal(delay,20000);this.callback=fn;}};timers.push(t);return t;}}
  };
  const context=vm.createContext({Components:{utils:{Sandbox(principal,options){assert.equal(principal,'content');assert.deepEqual(Array.from(options.wantGlobalProperties),['indexedDB']);calls.push('sandbox');return {};},evalInSandbox(code){assert.equal(code,'indexedDB');return factory;}}}});
  vm.runInContext(source,context);
  const host={log(text){calls.push(['log',text]);}};
  const probe=context.startOrbisFoxProfile(Cc,{nsITimer:{TYPE_ONE_SHOT:0}},host,{createContentPrincipal(uri){assert.equal(uri.spec,'https://orbisfox-storage.invalid/');return 'content';}},{newURI:spec=>({spec})});
  const drain=()=>{for(let n=0;queue.length&&n<30;++n)queue.shift()();assert.equal(queue.length,0);};
  return {probe,calls,queue,timers,dbs,drain};
}
for(let cycle=0;cycle<32;++cycle){
  const good=setup();assert(!good.probe.snapshot().done);good.drain();assert(good.probe.snapshot().ok);assert.equal(good.dbs.length,2);assert(good.dbs.every(db=>db.closed));
  assert(good.calls.indexOf('quota-service')<good.calls.indexOf('profile-do-change'));assert(good.calls.indexOf('profile-do-change')<good.calls.indexOf('put'));
  const copy=good.probe.snapshot();copy.ok=false;assert(good.probe.snapshot().ok);
  good.probe.close();good.probe.close();
  const topics=good.calls.filter(c=>typeof c==='string'&&c.startsWith('profile-'));
  assert.deepEqual(topics,['profile-do-change','profile-change-net-teardown','profile-change-teardown','profile-before-change','profile-before-change-qm']);
  for(const fault of ['open','reopen','blocked','mismatch','write']){const bad=setup(fault);bad.drain();assert(bad.probe.snapshot().done&&!bad.probe.snapshot().ok);bad.probe.close();bad.drain();assert(bad.dbs.every(db=>db.closed));}
  const timeout=setup('timeout');timeout.drain();timeout.timers[0].callback();assert(timeout.probe.snapshot().done&&!timeout.probe.snapshot().ok);timeout.probe.close();
  const early=setup();early.probe.close();early.drain();assert(!early.probe.snapshot().done);assert(early.dbs.every(db=>db.closed));
  const shutdown=setup('shutdown');shutdown.drain();assert.throws(()=>shutdown.probe.close());assert(shutdown.calls.includes('profile-before-change-qm'));
}
console.log('Profile lifecycle:32 cycles actual source, explicit observer/IndexedDB/sandbox doubles; commit-close-reopen/deadline/late callback/shutdown ordering; not disk/firmware proof');
