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
  assert.equal(state.busy,false);assert.equal(state.error,"");assert.equal(state.message,"Stopped");
  state.begin(M.LAN);state.stopped(0x804b001e);assert.equal(state.error,"Server not found (0x804b001e)");
  state.begin(M.LAN);state.stopped(0x805a2ff0);assert.match(state.error,/^Secure connection failed \(0x805a2ff0\)$/);
  state.begin(M.LAN);state.stopped(0x80004005);assert.equal(state.error,"Load failed (0x80004005)");
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
  const keyboard=new M.Controller();
  assert.deepEqual(array(keyboard.update(M.Buttons.address,0)),['address']);
  assert.deepEqual(array(keyboard.update(M.Buttons.address,1000,true)),[],'held opener is quarantined');
  keyboard.update(0,1010,true);assert.deepEqual(array(keyboard.update(M.Buttons.address,1020,true)),['address']);
  assert.deepEqual(array(keyboard.update(M.Buttons.address,1419,true)),[]);
  assert.deepEqual(array(keyboard.update(M.Buttons.address,1420,true)),['address']);
  assert.deepEqual(array(keyboard.update(M.Buttons.address,100000,true)),['address'],'repeat once, never burst');
  assert.deepEqual(array(keyboard.update(M.Buttons.address,100001,false)),[],'held Delete cannot reopen');
  keyboard.update(0,100002,true);assert.deepEqual(array(keyboard.update(M.Buttons.forward,100003,true)),['forward']);
  assert.deepEqual(array(keyboard.update(M.Buttons.forward,200003,true)),[],'held R2 never repeats Enter');
  assert.deepEqual(array(keyboard.update(M.Buttons.forward,200004,false)),[],'held Enter cannot navigate Forward');
  keyboard.update(0,200005);assert.deepEqual(array(keyboard.update(M.Buttons.forward,200006)),['forward']);
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
// Firefox-style address bar: plausible hosts navigate, everything else searches.
for(const [typed,expected] of [['fmhy.net','fmhy.net'],['example.com/path?x=1','example.com/path?x=1'],['localhost','localhost'],['localhost:3000/app','localhost:3000/app'],
  ['192.168.1.20:8080','192.168.1.20:8080'],['münchen.de','münchen.de'],['xn--mnchen-3ya.de','xn--mnchen-3ya.de'],
  ['1.5','https://www.google.com/search?q=1.5'],['node','https://www.google.com/search?q=node'],['what is: love','https://www.google.com/search?q=what%20is%3A%20love'],
  ['999.1.1.1','https://www.google.com/search?q=999.1.1.1'],['@ddg red fox','https://duckduckgo.com/?q=red%20fox'],['@Wiki Vulpes','https://en.wikipedia.org/wiki/Special:Search?search=Vulpes'],
  ['@unknown fox','https://www.google.com/search?q=%40unknown%20fox'],['?example.com','https://www.google.com/search?q=example.com']])
  assert.equal(model.homeAddress(typed),expected,typed);
assert.equal(model.homeAddress('fox','ecosia'),'https://www.ecosia.org/search?q=fox');
for(const typed of ['chrome://global/','javascript:alert(1)','about:config','file:///etc/passwd','data:text/html,x'])assert.equal(model.navigationText(typed),typed,'unsafe schemes are rejected later, never searched');
assert.equal(model.navigationText('define:fox'),'https://www.google.com/search?q=define%3Afox');assert.equal(model.navigationText('  '),model.HOME);assert.equal(model.navigationText('localhost:3000'),'localhost:3000');
assert.equal(model.resolveAddress('localhost:3000/x',{web:true}),'http://localhost:3000/x');assert.equal(model.resolveAddress('10.0.0.2',{web:true}),'http://10.0.0.2');
// Plain HTTP only for loopback/private/link-local; typed public IPs still try HTTPS.
for(const [typed,expected] of [['192.168.1.20:8080','http://192.168.1.20:8080'],['172.16.0.1','http://172.16.0.1'],['169.254.1.1','http://169.254.1.1'],['127.0.0.1','http://127.0.0.1'],['[::1]:8080/x','http://[::1]:8080/x'],
  ['8.8.8.8','https://8.8.8.8'],['172.32.0.1','https://172.32.0.1'],['[2001:db8::1]','https://[2001:db8::1]']])assert.equal(model.resolveAddress(typed,{web:true}),expected,typed);assert.equal(model.resolveAddress('example.com:8443',{web:true}),'https://example.com:8443');
// Settings: home page, session restore and Global Privacy Control are validated.
let stored='';const extended=new model.Settings('{}',text=>{stored=text;});
assert.deepEqual([extended.snapshot().homePage,extended.snapshot().restoreSession,extended.snapshot().globalPrivacyControl],['',false,false]);
extended.update({homePage:'https://start.example/',restoreSession:true,globalPrivacyControl:true,searchEngine:'wikipedia'});
assert.deepEqual(JSON.parse(JSON.stringify(new model.Settings(stored).snapshot())),{searchEngine:'wikipedia',cursorSpeed:1,defaultZoom:100,colorScheme:'system',homePage:'https://start.example/',restoreSession:true,globalPrivacyControl:true});
for(const changes of [{homePage:'javascript:alert(1)'},{homePage:'https://user:pw@x.example/'},{homePage:'example.com'},{homePage:'https://'+'a'.repeat(1100)+'.example/'},{restoreSession:1},{globalPrivacyControl:'yes'}])
  assert.throws(()=>extended.update(changes),JSON.stringify(changes));
assert.equal(extended.snapshot().homePage,'https://start.example/');
// History entries can be deleted one at a time.
history.visit('https://one.example/','One',100);history.visit('https://two.example/','Two',200);
assert(history.remove('https://two.example/'));assert.deepEqual(JSON.parse(visitSaved.at(-1)).map(item=>item.url),['https://one.example/']);assert.equal(history.snapshot().length,1);assert.equal(history.remove('https://two.example/'),false);
// Recently closed tabs: newest first, deduplicated, bounded, web pages only.
const closed=new model.ClosedTabs();assert.equal(closed.push(model.HOME,'Home'),false);assert.equal(closed.push('javascript:alert(1)','x'),false);
for(let n=0;n<14;++n)closed.push('https://closed.example/'+n,'Closed '+n,n+1);closed.push('https://closed.example/12','Again',99);
assert.equal(closed.snapshot().length,model.MAX_CLOSED_TABS);assert.equal(closed.peek().title,'Again');assert.equal(closed.peek(1).url,'https://closed.example/13');
assert(closed.remove(0));assert.equal(closed.peek().url,'https://closed.example/13');assert.equal(closed.remove(99),false);assert.equal(closed.peek(42),null);
// Session restore keeps at most three distinct, valid web tabs.
assert.deepEqual(Array.from(model.sessionURLs(JSON.stringify(['https://a.example/','https://a.example/','chrome://global/','https://b.example/','https://c.example/','https://d.example/']))),['https://a.example/','https://b.example/','https://c.example/']);
assert.deepEqual(Array.from(model.sessionURLs('not json')),[]);
console.log('Browser shell features: address/search heuristics, @keywords, home page/session/GPC settings, history delete, closed tabs, friendly load errors');

// File names search; trailing-dot hosts navigate; non-letter Unicode does not form a TLD.
for(const typed of ['node.js','notes.txt','report.pdf','can’t.stop'])assert.equal(model.homeAddress(typed),'https://www.google.com/search?q='+encodeURIComponent(typed),typed);
for(const typed of ['example.com.','sub.example.co.uk','music.zip.example.org'])assert.equal(model.homeAddress(typed),typed,typed);
// Settings: legacy records gain defaults; size bounds hold on load and save; unknown keys are not stored.
const legacy=new model.Settings('{"searchEngine":"bing","cursorSpeed":2}').snapshot();
assert.equal(legacy.searchEngine,'bing');assert.strictEqual(legacy.homePage,'');assert.strictEqual(legacy.restoreSession,false);assert.strictEqual(legacy.globalPrivacyControl,false);
const mid=JSON.stringify({searchEngine:'bing',cursorSpeed:1,homePage:'https://x.example/'+'a'.repeat(1000)});assert(mid.length>1024);assert.equal(new model.Settings(mid).snapshot().searchEngine,'bing');
assert.equal(new model.Settings(JSON.stringify({searchEngine:'bing',cursorSpeed:1,pad:'a'.repeat(5000)})).snapshot().searchEngine,'google','oversized records reset to defaults');
let bounded='';const boundedSettings=new model.Settings('{}',text=>{bounded=text;});
assert.throws(()=>boundedSettings.update({homePage:'https://example.com/'+'\uD800'.repeat(1000)}));assert.equal(boundedSettings.snapshot().homePage,'');
boundedSettings.update({searchEngine:'bing',extra:'ignored'});assert.equal(JSON.parse(bounded).extra,undefined);
console.log('Browser shell fixes: private-only HTTP default, file-name searches, settings bounds/legacy defaults');
