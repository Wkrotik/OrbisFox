'use strict';
// Actual frontend handler; explicit Gecko DOM/security/referrer doubles.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={};vm.createContext(context);vm.runInContext(fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-host.js','utf8'),context);
for(let cycle=0;cycle<32;++cycle){
 const principal={isSystemPrincipal:false},policy={csp:'real-doc-policy'},document={nodePrincipal:principal,policyContainer:policy};
 const node={ownerDocument:document},referrer={initWithElement:n=>assert.equal(n,node),initWithDocument:d=>assert.equal(d,document)};
 let security=0,opened=0,referrers=0,prevented=0,deny=false,failOpen=false,source=true,linkNode=node,href='https://example.test/path';
 const handler=context.createOrbisMiddleLinkHandler({sourceTab:d=>source&&d===document,linkData:()=>[href,linkNode,principal],
  checkedURI:text=>({scheme:text.split(':')[0],spec:text}),ssm:{checkLoadURIStrWithPrincipal(p,url,flags){assert.equal(flags,0);assert.equal(p,principal);assert.equal(url,href);++security;if(deny)throw Error('denied');}},
  Cc:{'@mozilla.org/referrer-info;1':{createInstance(){++referrers;return referrer;}}},Ci:{nsIScriptSecurityManager:{STANDARD:0},nsIReferrerInfo:{},nsIBrowserDOMWindow:{OPEN_NEWTAB_BACKGROUND:4}},
  popup(uri,info,where,flags,p,csp,load,ref){assert.equal(uri.spec,href);assert.equal(info,null);assert.equal(where,4);assert.equal(flags,0);assert.equal(p,principal);assert.equal(csp,policy);assert.equal(load,true);assert.equal(ref,referrer);if(failOpen)throw Error('tab limit');++opened;},log(){}});
 const event={isTrusted:true,button:1,defaultPrevented:false,composedTarget:node,preventDefault(){++prevented;}};
 const wrapper={isTrusted:true,sourceEvent:event,preventDefault(){++prevented;}};
 assert.equal(handler(wrapper),true);assert.equal(opened,1);assert.equal(security,1);assert.equal(referrers,1);assert.equal(prevented,2);
 for(const field of ['isTrusted','defaultPrevented']){const original=event[field];event[field]=field==='isTrusted'?false:true;assert.equal(handler(wrapper),false);event[field]=original;}
 wrapper.isTrusted=false;assert.equal(handler(wrapper),false);wrapper.isTrusted=true;
 for(const button of [0,2]){event.button=button;assert.equal(handler(wrapper),false);}event.button=1;
 source=false;assert.equal(handler(wrapper),false);source=true;
 document.nodePrincipal={isSystemPrincipal:true};assert.equal(handler(wrapper),false);document.nodePrincipal=principal;
 for(const url of ['file:///app0/eboot.bin','chrome://privileged','javascript:alert(1)']){href=url;assert.equal(handler(wrapper),false);}href='https://example.test/path';
 deny=true;assert.equal(handler(wrapper),false);deny=false;assert.equal(opened,1);
 failOpen=true;assert.equal(handler(wrapper),false);failOpen=false;assert.equal(prevented,2);
 linkNode=null;assert.equal(handler(wrapper),true);assert.equal(opened,2);assert.equal(prevented,4);
 principal.isSystemPrincipal=true;assert.equal(handler(wrapper),false);
}
console.log('Middle-link handler:32 cycles actual source; trusted source/SSM/referrer/policy/background/limits preserved; no synthetic clicks. Host-only, no firmware proof.');
