"use strict";
// Actual chrome event controller; explicit DOM doubles, not firmware proof.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-host.js','utf8');
for(let cycle=0;cycle<32;++cycle){
  const context=vm.createContext({});vm.runInContext(source,context);
  const events=new Map(),calls=[],top={},foreign={},document={nodeType:9,documentURI:'https://video.example/watch?private=1',nodePrincipal:{isSystemPrincipal:false},fullscreenElement:{},defaultView:{top}};
  const win={document:{nodeType:9},addEventListener(type,fn){events.set(type,fn);},removeEventListener(type,fn){assert.equal(events.get(type),fn);events.delete(type);}};
  const tab={closed:false,nav:{document},element:{contentWindow:top}};
  const ui={setContentFullscreen(...args){calls.push(args);}};
  const io={newURI(value){const url=new URL(value);return {scheme:url.protocol.slice(0,-1),asciiHostPort:url.host};}};
  const remove=context.createOrbisFullscreenController(win,()=>tab,ui,io);
  const send=(type,target=document,trusted=true)=>events.get(type)({type,isTrusted:trusted,originalTarget:target});
  send('MozDOMFullscreen:Entered',document,false);assert.equal(calls.length,0);
  send('MozDOMFullscreen:Entered',{nodeType:9,defaultView:{top:foreign}});assert.equal(calls.length,0);
  document.nodePrincipal.isSystemPrincipal=true;send('MozDOMFullscreen:Entered');assert.equal(calls.length,0);
  document.nodePrincipal.isSystemPrincipal=false;send('MozDOMFullscreen:Entered');assert.deepEqual(calls.pop(),[true,'https://video.example']);
  send('MozDOMFullscreen:Entered',{ownerDocument:document});assert.deepEqual(calls.pop(),[true,'https://video.example']);
  const child={nodeType:9,documentURI:'https://user:password@player.example/embed?token=secret',nodePrincipal:{isSystemPrincipal:false},fullscreenElement:{},defaultView:{top}};
  document.fullscreenElement={contentDocument:child};send('MozDOMFullscreen:Entered');assert.deepEqual(calls.pop(),[true,'https://player.example']);
  child.nodePrincipal.isSystemPrincipal=true;send('MozDOMFullscreen:Entered');assert.equal(calls.length,0);
  document.fullscreenElement=null;send('MozDOMFullscreen:Entered');assert.equal(calls.length,0);
  send('MozDOMFullscreen:Exited');assert.deepEqual(calls.pop(),[false]);
  send('MozDOMFullscreen:Exited',win.document);assert.deepEqual(calls.pop(),[false]);
  tab.closed=true;send('MozDOMFullscreen:Exited');assert.equal(calls.length,0);
  remove();assert.equal(events.size,0);
}
console.log('Fullscreen controller:32 cycles actual source, trusted owned active documents, origin-only notice and listener cleanup; no firmware proof.');
