const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const text=fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-host.js','utf8');
const helper=text.slice(text.indexOf('function createOrbisPageNetworkObserver('),text.indexOf('function runOrbisFoxBrowserShell('));
for(let cycle=0;cycle<32;cycle++){
 const context={URL};vm.createContext(context);vm.runInContext(helper,context);
 const lines=[],host={diagnosticsEnabled:false,log:value=>lines.push(JSON.parse(value.slice(value.indexOf('{'))))};
 const tab={id:'content',closed:false};
 const observe=context.createOrbisPageNetworkObserver(host,(document,owner)=>owner===tab&&document.owned===true);
 const make=()=>{const events={};const view={URL,WebSocket:class{},fetch(){},ReadableStream:class{},navigator:{userAgent:'Gecko actual OrbisFox'},isSecureContext:true,addEventListener:(name,cb)=>events[name]=cb};view.top=view;
 return {owned:true,documentURI:'https://chat.example/live_chat?token=secret#private',nodePrincipal:{isSystemPrincipal:false},defaultView:view,events};};
 const doc=make();observe(doc,tab);assert.equal(lines.length,0);
 host.diagnosticsEnabled=true;observe(doc,tab);assert.equal(lines.length,1);assert.equal(lines[0].webSocket,true);assert.equal(lines[0].fetch,true);assert.equal(lines[0].uri,'https://chat.example/live_chat');assert(!JSON.stringify(lines).includes('secret'));
 observe(doc,tab);assert.equal(lines.length,1);
 doc.events.error({isTrusted:false,message:'fake'});assert.equal(lines.length,1);
 doc.events.error({isTrusted:true,message:'real failure',filename:'https://chat.example/script.js?token=secret',lineno:5});assert.equal(lines[1].message,'real failure');assert.equal(lines[1].file,'https://chat.example/script.js');
 doc.events.error({isTrusted:true,message:'Failed https://chat.example/script?token=hidden#fragment'});assert.equal(lines[2].message,'Failed https://chat.example/script');assert(!JSON.stringify(lines).includes('hidden'));
 host.diagnosticsEnabled=false;doc.events.error({isTrusted:true,message:'off'});assert.equal(lines.length,3);
 host.diagnosticsEnabled=true;const foreign=make();foreign.owned=false;observe(foreign,tab);
 const system=make();system.nodePrincipal.isSystemPrincipal=true;observe(system,tab);assert.equal(lines.length,3);
 for(let i=0;i<30;i++)doc.events.unhandledrejection({isTrusted:true,reason:{private:'not serialized'}});
 assert.equal(lines.length,12);assert(!JSON.stringify(lines).includes('not serialized'));
 tab.closed=true;observe(make(),tab);assert.equal(lines.length,12);
}
console.log('Network observer:32 cycles actual source; opt-in/trusted/bounded, content ownership and no network payloads/query strings. Explicit DOM doubles, not PS4 protocol proof.');
