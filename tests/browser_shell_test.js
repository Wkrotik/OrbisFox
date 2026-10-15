"use strict";
const assert = require("node:assert/strict"), vm = require("node:vm"), fs = require("node:fs");
const source = fs.readFileSync("gecko/orbisfox/fixtures/browser-shell-model.js","utf8");
for(let cycle=0;cycle<32;cycle++) {
  const context=vm.createContext({});vm.runInContext(source,context);const M=context.OrbisFoxShellModel;
  let serialized='';const settings=new M.Settings('{}',text=>{serialized=text;});
  settings.update({searchEngine:'duckduckgo',cursorSpeed:0.25});assert.equal(JSON.parse(serialized).cursorSpeed,0.25);
  assert.equal(new M.Settings(serialized).snapshot().searchEngine,'duckduckgo');
  assert.equal(new M.Settings('{"cursorSpeed":1,"searchEngine":"google"}').snapshot().colorScheme,'system');
  for(const colorScheme of ['dark','light','system']){settings.update({colorScheme});assert.equal(new M.Settings(serialized).snapshot().colorScheme,colorScheme);}
  for(const colorScheme of ['Dark',0,null,'constructor',{}])assert.throws(()=>settings.update({colorScheme}));
  assert.equal(M.homeAddress('cats dogs',settings.snapshot().searchEngine),'https://duckduckgo.com/?q=cats%20dogs');
  assert.equal(M.homeAddress('cats dogs','constructor'),'https://www.google.com/search?q=cats%20dogs');
  for(const changes of [{searchEngine:'constructor'},{cursorSpeed:0},{cursorSpeed:Infinity},{cursorSpeed:'1'},{cursorSpeed:3.25}])assert.throws(()=>settings.update(changes));
  const failing=new M.Settings('{}',()=>{throw Error('disk failed');});assert.throws(()=>failing.update({cursorSpeed:2}));assert.equal(failing.snapshot().cursorSpeed,1);
  for(const text of ["", "home", M.HOME]) assert.equal(M.resolveAddress(text),M.HOME);
  for(const bad of ["javascript:alert(1)","data:text/html,hi","chrome://global/", "file:///data/secrets", "https://example.com@evil/",
    "ftp://example.com/", "about:config", "https://user:pass@example.com/", "https://", "https://bad host/", "https://example.com\\evil", "\0home", "home\n", "a".repeat(2049), null, 9])
    assert.throws(()=>M.resolveAddress(bad,{lan:true,web:true}));
  assert.throws(()=>M.resolveAddress(M.LAN));assert.throws(()=>M.resolveAddress(M.HTTPS));
  assert.throws(()=>M.resolveAddress(M.LAN,{lan:1}));
  assert.equal(M.resolveAddress(M.LAN,{lan:true}),M.LAN);
  assert.equal(M.resolveAddress("example.com",{web:true}),"https://example.com");
  for(const url of [M.GOOGLE,"google.com","www.google.com","https://google.com/","https://www.google.com","https://wikipedia.org/wiki/Fox","http://10.42.0.1:8765/page","https://example.com.evil/"]) {
    assert.throws(()=>M.resolveAddress(url));assert.throws(()=>M.resolveAddress(url,{web:1}));
    assert.equal(M.resolveAddress(url,{web:true}),/^https?:/.test(url)?url:"https://"+url);
  }
  assert.equal(M.MAX_TABS,3);
  const state=new M.State();state.begin(M.LAN);assert.equal(state.busy,true);assert.equal(state.location,M.HOME);
  state.locationChanged(M.LAN);assert.equal(state.busy,true);state.stopped(0x804b0002);
  assert.equal(state.busy,false);assert.match(state.error,/804b0002/);
  state.begin(M.HOME);assert.equal(state.error,"");state.stopped(0);assert.equal(state.message,"Ready");
  state.history(true,false);assert.equal(state.canBack,true);assert.equal(state.canForward,false);
  const copy=state.snapshot();copy.location="fake";assert.equal(state.location,M.LAN);
  const ctrl=new M.Controller(), array = value => Array.from(value);
  assert.deepEqual(array(ctrl.update(M.Buttons.address|M.Buttons.cross,0)),["address"]);
  assert.deepEqual(array(ctrl.update(M.Buttons.address|M.Buttons.cross,16)),[]);
  ctrl.update(0,32);assert.deepEqual(array(ctrl.update(M.Buttons.down,40)),["down"]);
  assert.deepEqual(array(ctrl.update(M.Buttons.down,439)),[]);
  assert.deepEqual(array(ctrl.update(M.Buttons.down,440)),["down"]);
  assert.deepEqual(array(ctrl.update(M.Buttons.down,100000)),["down"]);
  assert.deepEqual(array(ctrl.update(M.Buttons.left|M.Buttons.right,100001)),[]);
  ctrl.update(0,100002);assert.deepEqual(array(ctrl.update(M.Buttons.menu,100003)),["menu"]);
}
const featureContext=vm.createContext({});vm.runInContext(source,featureContext);const model=featureContext.OrbisFoxShellModel;
const saved=[];const bookmarks=new model.Bookmarks('[]',text=>saved.push(text));
assert(bookmarks.toggle('https://example.com/','Example'));assert.equal(bookmarks.snapshot().length,1);
const restored=new model.Bookmarks(saved.at(-1));assert(restored.has('https://example.com/'));
assert.equal(restored.toggle('https://example.com/','Example'),false);assert.equal(restored.snapshot().length,0);
assert.throws(()=>bookmarks.toggle('javascript:alert(1)','bad'));
assert.throws(()=>bookmarks.toggle('https://user:pass@example.com/','bad'));
const unavailable=new model.Bookmarks('[]',()=>{throw Error('disk failure');});
assert.throws(()=>unavailable.toggle('https://example.com/','Example'));assert.equal(unavailable.snapshot().length,0);
assert.equal(model.homeAddress('cats and dogs'),'https://www.google.com/search?q=cats%20and%20dogs');
assert.equal(model.homeAddress('fmhy.net'),'fmhy.net');
const visitSaved=[];const history=new model.History('[]',text=>visitSaved.push(text));
history.visit('https://one.example/','One',100);history.visit('https://two.example/','Two',200);history.visit('https://one.example/','Renamed',300);
assert.equal(history.snapshot().length,2);assert.equal(history.snapshot()[0].title,'Renamed');assert.equal(history.snapshot()[0].visits,2);assert.equal(history.revision,3);
const visitReloaded=new model.History(visitSaved.at(-1));assert.equal(visitReloaded.snapshot()[0].url,'https://one.example/');
const visitCopy=history.snapshot();visitCopy[0].url='fake';assert.equal(history.snapshot()[0].url,'https://one.example/');
for(const bad of ['file:///app0/assets/offline.html','about:neterror','javascript:alert(1)','https://user:pass@example.com/'])assert.throws(()=>history.visit(bad,'Bad',400));
for(const badTime of [0,-1,NaN,Infinity,8640000000000001])assert.throws(()=>history.visit('https://example.com/','Bad',badTime));
const failingHistory=new model.History(visitSaved.at(-1),()=>{throw Error('disk failure');});
const beforeHistory=JSON.stringify(failingHistory.snapshot());assert.throws(()=>failingHistory.visit('https://three.example/','Three',400));assert.throws(()=>failingHistory.clear());assert.equal(JSON.stringify(failingHistory.snapshot()),beforeHistory);assert.equal(failingHistory.revision,0);
for(let i=0;i<300;++i)history.visit('https://bounded.example/'+i,'Bounded',1000+i);assert.equal(history.snapshot().length,model.MAX_HISTORY);assert.equal(history.snapshot()[0].url,'https://bounded.example/299');
history.clear();assert.equal(history.snapshot().length,0);assert.equal(visitSaved.at(-1),'[]');
assert(bookmarks.remove('https://example.com/'));assert.equal(bookmarks.snapshot().length,0);assert(!bookmarks.remove('https://missing.example/'));
console.log("Browser shell:32 cycles actual policy/state/controller source; no Gecko rendering or PS4 claims");
