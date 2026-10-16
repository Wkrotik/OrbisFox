"use strict";
// Actual supervisor with explicit XPConnect/docshell/controller/editor doubles.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-host.js','utf8');
function run({principal=true,failLoad=false,early=false,profileOkay=true,nativeReady=true,tabsTest=false,textTest=false,stale=false,scroll=false,tabFault=false,reenterTabs=false,bookmarksTest=false,historyTest=false,mediaTest=false,saveFails=false,settingsTest=false,cursorFails=false,initialSettings='{}',initialSession='[]',featuresTest=false,clearData=null,ticks=7,tlsState=null,secureUI=undefined,blankTitle=false,delayWeb=-1,siteDataFlag=false,script=null,cursorX=40,cursorY=150,pixelRatio=1,rect={left:0,top:104,width:1280,height:584}}={}) {
  const calls=[],snapshots=[],elements=new Map();let tick,actions,exit=false,listenerCount=0,selected='content',editing=false;
  const Ci={nsIDOMWindowUtils:{WHEEL_EVENT_CAUSED_BY_NO_LINE_OR_PAGE_DELTA_DEVICE:1,WHEEL_EVENT_ASYNC_ENABLED:8},nsITimer:{TYPE_REPEATING_SLACK:1},
    nsIWebProgress:{NOTIFY_STATE_DOCUMENT:1,NOTIFY_LOCATION:2},nsIWebProgressListener:{STATE_IS_BROKEN:1,STATE_IS_SECURE:2,STATE_IS_DOCUMENT:4,STATE_START:8,STATE_STOP:16,LOCATION_CHANGE_SAME_DOCUMENT:32},nsIChannel:{},nsITransportSecurityInfo:{},
    nsIWebNavigation:{STOP_ALL:1,LOAD_FLAGS_NONE:0},nsIBrowserDOMWindow:{OPEN_CURRENTWINDOW:1,OPEN_NEWTAB:3,OPEN_PRINT_BROWSER:4,OPEN_NEWTAB_BACKGROUND:5,OPEN_NEWTAB_FOREGROUND:6,OPEN_NO_REFERRER:8}};
  const uri=spec=>({spec,scheme:spec.split(':')[0],host:/^https?:/.test(spec)?new URL(spec).hostname:'',userPass:/^https?:/.test(spec)?new URL(spec).username:''});
  function element(id){
    const win={innerWidth:1280,innerHeight:584,windowUtils:{sendWheelEvent(...args){calls.push(['wheel',id,...args]);},sendContentCommandEvent(...args){calls.push(['text',id,...args]);return true;}}};
    const nav={document:{documentURI:'about:blank'},canGoBack:false,canGoForward:false,
      loadURI(target,options){calls.push(['load',id,target.spec,options.triggeringPrincipal,options]);if(failLoad)throw Error('Load refused');
        this.document={documentURI:target.spec,nodePrincipal:{isSystemPrincipal:false},title:blankTitle?'  ':target.spec,defaultView:{wrappedJSObject:{orbisfoxFixture:{ok:true,passed:8}}},activeElement:null,elementFromPoint(){return this.activeElement;}};
        // TLS evidence double for https stops: secure/broken certificate state with an issuer.
        const tlsInfo=tlsState&&target.spec.startsWith('https:')?{QueryInterface:()=>({securityState:tlsState==='secure'?2:1,errorCode:0,errorCodeString:'',protocolVersion:4,succeededCertChain:[],isBuiltCertChainRootBuiltInRoot:true,serverCert:{issuerOrganization:'Trusted CA'}})}:null;
        const request=tlsInfo?{QueryInterface:()=>({securityInfo:tlsInfo,URI:{spec:target.spec}})}:null;
        this.listener.onLocationChange({DOMWindow:win},null,target);this.listener.onStateChange({DOMWindow:win},null,12,0);
        if(!target.spec.includes('slow'))this.listener.onStateChange({DOMWindow:win},request,20,0);},
      stop(){calls.push(['stop',id]);},reload(){calls.push(['reload',id]);},goBack(){calls.push(['back',id]);},goForward(){calls.push(['forward',id]);}};
    const progress={addProgressListener(l){nav.listener=l;++listenerCount;},removeProgressListener(){--listenerCount;calls.push(['remove-listener',id]);}};
    const e={id,nav,contentWindow:win,docShell:{QueryInterface:iface=>iface===Ci.nsIWebProgress?progress:nav},frameLoader:{browsingContext:{isContent:true,useRemoteTabs:false,useRemoteSubframes:false,get secureBrowserUI(){if(secureUI==='throw')throw Error('no secure UI');return secureUI===undefined?undefined:{state:secureUI};}}},
      getAttribute:name=>name==='type'?'content':null,hasAttribute:()=>false,getBoundingClientRect:()=>rect};
    elements.set(id,e);return e;
  }
  element('content');
  const ui={ready:true,bind(value){actions=value;calls.push(['bind']);},contentElement:()=>elements.get(selected),createContent(id,info){const e=element(id);e.openWindowInfo=info;if(tabFault)e.hasAttribute=name=>name==='remote';return e;},selectContent(id){selected=id;calls.push(['select',id]);},
    removeContent(id){elements.delete(id);calls.push(['remove',id]);},renderTabs(tabs,active){calls.push(['tabs',tabs.map(t=>t.id),active]);},isEditing:()=>editing,
    canScroll:()=>!editing,pointerMoved(){},control(){},editText(value){editing=true;assert(actions.openTextKeyboard(value));calls.push(['edit-text',value]);},
    finishAddressKeyboard(status,text){editing=false;calls.push(['keyboard-finish',status,text]);if(textTest)calls.push(['commit-result',actions.commitText(text)]);},
    update(state,diagnostic,gates){snapshots.push({state,gates});},destroy(){calls.push(['destroy']);}};
  const win={addEventListener(){},removeEventListener(){},devicePixelRatio:pixelRatio,document:{documentURI:'chrome://orbisfox/content/browser.xhtml',readyState:'complete',nodePrincipal:{isSystemPrincipal:principal}},wrappedJSObject:{OrbisFoxShell:ui}};
  const chrome={docShell:{domWindow:win},loadURI(){}};
  const host={cursorX,cursorY,buttons:0,nativeNetworkReady:nativeReady&&delayWeb<0,framesPresented:0,scrollX:scroll?4:0,scrollY:scroll?-7:0,keyboardStatus:1,keyboardText:'fox',keyboardConfirmButton:1,
    openAddressKeyboard(){return true;},openTextKeyboard(){calls.push(['open-text']);return true;},cancelAddressKeyboard(){calls.push(['cancel-keyboard']);},
    createChromeBrowser:()=>chrome,pumpFrame:()=>!early,log:text=>calls.push(['log',text]),fixtureCheckpoint:value=>calls.push(['checkpoint',value]),setPointerInputEnabled(enabled){if(!enabled&&reenterTabs&&actions)assert.equal(actions.newTab(),false);},requestExit(){exit=true;},closeBrowser(){calls.push(['close']);}};
  host.setCursorSpeed=value=>{if(cursorFails&&value!==1)throw Error('cursor failed');calls.push(['cursor-speed',value]);};
  const timer={initWithCallback(fn){tick=fn;},cancel(){calls.push(['cancel-timer']);}};
  let bookmarkPrefs='[]',historyPrefs='[]',settingsPrefs=initialSettings,sessionPrefs=initialSession,contentColorScheme=2;const boolPrefs={};let prefSaves=0;
  // Full pref names (branch prefix + name) catch prefs written on the wrong branch.
  const preferenceService={getBranch:(prefix='')=>({setIntPref:(name,value)=>{assert.equal(prefix+name,'layout.css.prefers-color-scheme.content-override');contentColorScheme=value;},
    setBoolPref:(name,value)=>{assert(['privacy.globalprivacycontrol.enabled','privacy.globalprivacycontrol.functionality.enabled'].includes(prefix+name),prefix+name);assert.equal(typeof value,'boolean');boolPrefs[prefix+name]=value;},
    getStringPref:name=>{const full=prefix+name;assert(full.startsWith('orbisfox.browser.'),full);return name==='settings'?settingsPrefs:name==='history'?historyPrefs:name==='session'?sessionPrefs:name==='bookmarks'?bookmarkPrefs:assert.fail('unknown pref '+full);},
    setStringPref:(name,value)=>{const full=prefix+name;assert(full.startsWith('orbisfox.browser.'),full);if(name==='settings')settingsPrefs=value;else if(name==='history')historyPrefs=value;else if(name==='session')sessionPrefs=value;else if(name==='bookmarks')bookmarkPrefs=value;else assert.fail('unknown pref '+full);}}),
    savePrefFile(file){assert(file&&file.leaf==='prefs.js','explicit blocking preference destination required');++prefSaves;if(saveFails)throw Error('save failed');}};
  const Cc={'@mozilla.org/file/directory_service;1':{getService:()=>({get:key=>{assert.equal(key,'ProfD');return {clone:()=>({append(name){this.leaf=name;}})};}})},'@mozilla.org/preferences-service;1':{getService:()=>preferenceService},'@mozilla.org/timer;1':{createInstance:()=>timer},'@mozilla.org/referrer-info;1':{createInstance:()=>({init(policy,send,uri){this.policy=policy;this.send=send;this.uri=uri;}})}};
  // Asynchronous like Gecko: the callback runs after deleteData returns.
  if(clearData)Cc['@mozilla.org/clear-data-service;1']={getService:()=>({deleteData(flags,callback){calls.push(['clear-data',flags]);queueMicrotask(()=>callback.onDataDeleted(clearData.failed));}})};
  Ci.nsIClearDataService=siteDataFlag?{CLEAR_COOKIES:1,CLEAR_DOM_STORAGES:0x40280,CLEAR_ALL_CACHES:0xc1000e,CLEAR_COOKIES_AND_SITE_DATA:0x70073aa1}:{CLEAR_COOKIES:1,CLEAR_DOM_STORAGES:4,CLEAR_ALL_CACHES:2};
  const network={snapshot:()=>({storage:{ok:true},http:{ok:false},dns:{ok:true}}),canNavigateLAN:()=>false,close(){calls.push(['network-close']);}};
  const tls={snapshot:()=>({ok:true}),close(){calls.push(['TLS-close']);}};
  const context=vm.createContext({Cc,Ci,host,io:{newURI:uri},ssm:{getSystemPrincipal:()=> 'system',createContentPrincipal:()=> 'file',createNullPrincipal:()=> 'null'},
    ChromeUtils:{generateQI:()=>()=>{}},startTrustedNetworkProbes:()=>network,startTrustedHTTPSProbes:()=>tls});
  context.load=path=>vm.runInContext(fs.readFileSync('gecko/orbisfox/fixtures/'+path.split('/').at(-1),'utf8'),context);
  const tm={spinEventLoopUntil(name,done){
    for(let i=0;i<ticks&&!done();++i){if(i===delayWeb)host.nativeNetworkReady=true;tick();if(!actions)continue;
      if(script){script(i,{actions,calls,elements,snapshots,win,uri,boolPrefs,host,get sessionPrefs(){return sessionPrefs;},get prefSaves(){return prefSaves;},get selected(){return selected;}});if(i===ticks-2)actions.exit();continue;}
      if(i===0){if(tabFault){assert.equal(actions.newTab(),false);assert.equal(elements.size,1);}
        assert.equal(actions.navigate('chrome://global/'),false);assert.equal(actions.navigate('https://arbitrary.example/path'),profileOkay&&nativeReady&&!failLoad);
        if(settingsTest){
          assert.equal(actions.saveSettings({searchEngine:'duckduckgo',cursorSpeed:1.5,defaultZoom:110,colorScheme:'dark'}),!saveFails&&!cursorFails);
          assert.equal(contentColorScheme,saveFails||cursorFails?2:0);
          assert.equal(actions.settings().colorScheme,saveFails||cursorFails?'system':'dark');
          assert.equal(actions.settings().cursorSpeed,saveFails||cursorFails?1:1.5);
          assert(actions.navigate('cats dogs'));assert.equal(calls.filter(c=>c[0]==='load').at(-1)[2],(saveFails||cursorFails?'https://www.google.com/search?q=':'https://duckduckgo.com/?q=')+'cats%20dogs');
          assert.equal(settingsPrefs==='{}',saveFails||cursorFails);
          assert(actions.zoom(10));assert(actions.zoom(0));
          assert.equal(actions.zoomValue(),saveFails||cursorFails?100:110);
          assert.equal(elements.get('content').frameLoader.browsingContext.fullZoom,saveFails||cursorFails?1:1.1);
        }
        if(bookmarksTest){
          assert.equal(actions.toggleBookmark(),!saveFails);
          assert.equal(actions.bookmarks().length,saveFails?0:1);
          assert.equal(JSON.parse(bookmarkPrefs).length,saveFails?0:1);
          if(!saveFails){assert(actions.toggleBookmark());assert.equal(actions.bookmarks().length,0);}
        }
        if(mediaTest){
          const document=elements.get('content').nav.document;let played=0,paused=0,scopes=0,destroyed=0;
          const media={paused:true,ended:false,currentTime:0,play(){++played;this.paused=false;return Promise.resolve();},pause(){++paused;this.paused=true;}};
          document.querySelectorAll=()=>[media];document.defaultView={windowUtils:{setHandlingUserInput(value){assert.equal(value,true);++scopes;return {destruct(){++destroyed;}};}}};
          assert(actions.toggleMedia());assert.equal(played,1);assert(actions.toggleMedia());assert.equal(paused,1);assert.equal(scopes,2);assert.equal(destroyed,2);
          document.nodePrincipal.isSystemPrincipal=true;assert.equal(actions.toggleMedia(),false);assert.equal(scopes,2);
        }
        if(historyTest){
          assert.equal(actions.history().length,saveFails?0:1);assert.equal(JSON.parse(historyPrefs).length,saveFails?0:1);
          if(!saveFails){
            const e=elements.get('content'),web={DOMWindow:e.contentWindow};
            const visited=actions.history()[0].url;assert.equal(visited,'https://arbitrary.example/path');
            e.nav.document.documentURI='about:neterror';e.nav.listener.onStateChange(web,null,20,0);assert.equal(actions.history().length,1);
            e.nav.document.documentURI='https://failed.example/';e.nav.listener.onStateChange(web,null,20,0x80004005);assert.equal(actions.history().length,1);
            e.nav.document.documentURI='https://system.example/';e.nav.document.nodePrincipal.isSystemPrincipal=true;e.nav.listener.onStateChange(web,null,20,0);assert.equal(actions.history().length,1);
            e.nav.document.nodePrincipal.isSystemPrincipal=false;e.nav.document.documentURI='https://spa.example/video';
            e.nav.listener.onLocationChange(web,null,uri(e.nav.document.documentURI),32);assert.equal(actions.history().length,2);assert.equal(JSON.parse(historyPrefs)[0].url,'https://spa.example/video');
            const historyRevision=actions.historyRevision();e.nav.listener.onStateChange(web,null,20,0);
            e.nav.document.documentURI='https://spa.example/video#t=3';e.nav.listener.onLocationChange(web,null,uri(e.nav.document.documentURI),32);
            assert.equal(actions.historyRevision(),historyRevision,'repeated/fragment notifications must not rewrite history prefs');
            assert(actions.clearHistory());assert.equal(actions.history().length,0);assert.equal(historyPrefs,'[]');
          }
        }
        if(tabsTest){assert(actions.newTab());assert(actions.newTab());assert.equal(actions.newTab(),false);}
        if(textTest){const doc=elements.get('content').nav.document;doc.defaultView=elements.get('content').contentWindow;
          const field={isConnected:true,ownerDocument:doc,localName:'textarea',value:'old',disabled:false,readOnly:false,focus(){doc.activeElement=this;},select(){calls.push(['select-text']);}};
          doc.activeElement=field;host.buttons=1;}
      }
      if(i===1&&textTest)host.buttons=0;
      if(i===2&&textTest){if(stale)elements.get('content').nav.document.activeElement.value='changed';host.keyboardStatus=2;}
      if(i===2&&tabsTest){assert(actions.selectTab('content'));assert(actions.closeTab('content-1'));assert(actions.relativeTab(1));assert(actions.closeTab());assert.equal(actions.closeTab(),false);
        assert.throws(()=>win.browserDOMWindow.openURI(uri('https://popup.example/'),null,4,0,{isSystemPrincipal:false}));
        assert.throws(()=>win.browserDOMWindow.openURI(uri('https://popup.example/'),null,2,0,{isSystemPrincipal:false}));
        assert.throws(()=>win.browserDOMWindow.openURI(null,null,3,0,{isSystemPrincipal:false}));
        const policy={policy:'owned'},referrer={referrer:'owned'},opener={opener:'owned'};
        const before=elements.size;
        const bc=win.browserDOMWindow.openURI(uri('https://popup.example/'),opener,5,8,{isSystemPrincipal:false},policy,referrer);assert(bc.isContent);
        assert.equal(selected,'content');assert.equal(elements.size,before+1);
        const popup=Array.from(elements.values()).find(e=>e.openWindowInfo===opener);assert(popup);
        const popupLoad=calls.filter(c=>c[0]==='load'&&c[1]===popup.id).at(-1);assert.equal(popupLoad[4].policyContainer,policy);assert.equal(popupLoad[4].referrerInfo.send,false);
        assert(win.browserDOMWindow.openURIInFrame(uri('https://current.example/'),{openWindowInfo:null,triggeringPrincipal:{isSystemPrincipal:false},policyContainer:policy,referrerInfo:referrer},1,0,'').frameLoader.browsingContext.isContent);assert.equal(elements.size,before+1);
        const currentLoad=calls.filter(c=>c[0]==='load'&&c[2]==='https://current.example/').at(-1);assert.equal(currentLoad[4].referrerInfo,referrer);
        const third=win.browserDOMWindow.createContentWindow(null,{opener:'create-only'},6,0,{isSystemPrincipal:false});assert(third.isContent);assert.equal(elements.size,3);
        const loadCount=calls.filter(c=>c[0]==='load').length;
        assert.throws(()=>win.browserDOMWindow.createContentWindow(null,null,3,0,{isSystemPrincipal:false}));assert.equal(elements.size,3);assert.equal(calls.filter(c=>c[0]==='load').length,loadCount);
        assert(win.browserDOMWindow.openURI(uri('https://full-current.example/'),null,1,0,{isSystemPrincipal:false}).isContent);assert.equal(elements.size,3);
        // At the cap, new-tab link loads fail; they never retarget an existing tab.
        const capLoads=calls.filter(c=>c[0]==='load').length;
        for(const where of [3,5,6])assert.throws(()=>win.browserDOMWindow.openURI(uri('https://capped.example/'),null,where,0,{isSystemPrincipal:false}));
        assert.throws(()=>win.browserDOMWindow.openURIInFrame(uri('https://capped.example/'),{openWindowInfo:null,triggeringPrincipal:{isSystemPrincipal:false}},3,0,''));
        assert.equal(elements.size,3);assert.equal(calls.filter(c=>c[0]==='load').length,capLoads);
        editing=true;assert.throws(()=>win.browserDOMWindow.createContentWindow(null,null,3,0,{isSystemPrincipal:false}));editing=false;
      }
      if(i===3&&featuresTest){
        // Recently closed tabs reopen in a new tab, newest first.
        assert(actions.navigate('https://first.example/'));assert(actions.newTab());assert(actions.navigate('https://second.example/'));
        assert(actions.closeTab());assert.equal(actions.closedTabs()[0].url,'https://second.example/');const closedRevision=actions.closedTabsRevision();
        assert(actions.reopenClosedTab(0));assert.equal(actions.closedTabs().length,0);assert(actions.closedTabsRevision()>closedRevision);
        assert(calls.some(c=>c[0]==='load'&&c[2]==='https://second.example/'&&c[1]!=='content'));assert.equal(actions.reopenClosedTab(0),false);
        // Address text: unknown "scheme:" searches; unsafe schemes are refused, not searched.
        assert(actions.navigate('define:fox'));assert.equal(calls.filter(c=>c[0]==='load').at(-1)[2],'https://www.google.com/search?q=define%3Afox');
        const loads=calls.filter(c=>c[0]==='load').length;assert.equal(actions.navigate('javascript:alert(1)'),false);assert.equal(calls.filter(c=>c[0]==='load').length,loads);
        assert(actions.navigate('localhost:8080'));assert.equal(calls.filter(c=>c[0]==='load').at(-1)[2],'http://localhost:8080');
        // Custom home page and Global Privacy Control.
        assert(actions.saveSettings({homePage:'https://start.example/',globalPrivacyControl:true}));assert.equal(boolPrefs['privacy.globalprivacycontrol.enabled'],true);
        assert(actions.navigate('home'));assert.equal(calls.filter(c=>c[0]==='load').at(-1)[2],'https://start.example/');
        assert.equal(actions.saveSettings({homePage:'chrome://global/'}),false);assert.equal(actions.settings().homePage,'https://start.example/');
        // Single history entries can be deleted.
        const visited=actions.history().length;assert(actions.removeHistory('https://start.example/'));assert.equal(actions.history().length,visited-1);
        // Clear-data reports asynchronously; results are checked after all runs.
        assert.equal(actions.clearSiteData(ok=>clearResults.push(ok)),!!clearData);
        if(clearData)assert.equal(calls.find(c=>c[0]==='clear-data')[1],siteDataFlag?0x70c73aaf:7);
      }
      if(i===ticks-2)actions.exit();
    }
  }};
  vm.runInContext(source,context);context.runOrbisFoxBrowserShell(Cc,Ci,host,context.io,tm,context.ssm,{snapshot:()=>({ok:profileOkay})});
  assert.equal(listenerCount,0);return {calls,snapshots,exit,settingsPrefs,sessionPrefs,boolPrefs,prefSaves};
}
const clearResults=[];
for(let cycle=0;cycle<32;++cycle){
  const good=run();assert(good.exit);assert(good.calls.some(c=>c[0]==='checkpoint'&&c[1]===8));
  assert(good.calls.some(c=>c[0]==='load'&&c[2]==='https://arbitrary.example/path'&&c[3]==='null'));
  const scroll=run({scroll:true});assert.deepEqual(scroll.calls.find(c=>c[0]==='wheel'),['wheel','content',40,46,4,-7,0,0,0,0,0,9]);
  const movedScroll=run({scroll:true,cursorX:950,cursorY:470});assert.deepEqual(movedScroll.calls.find(c=>c[0]==='wheel').slice(2,4),[950,366]);
  const scaledScroll=run({scroll:true,cursorX:400,cursorY:500,pixelRatio:2,rect:{left:20,top:100,width:640,height:292}});
  assert.deepEqual(scaledScroll.calls.find(c=>c[0]==='wheel').slice(2,4),[360,300]);
  for(const point of [{cursorY:50},{cursorY:719},{cursorX:1280},{rect:{left:0,top:104,width:0,height:584}}])
    assert(!run({scroll:true,...point}).calls.some(c=>c[0]==='wheel'));
  run({bookmarksTest:true});run({bookmarksTest:true,saveFails:true});run({historyTest:true});run({historyTest:true,saveFails:true});run({mediaTest:true});
  run({settingsTest:true});run({settingsTest:true,saveFails:true});run({settingsTest:true,cursorFails:true});
  run({featuresTest:true});run({featuresTest:true,clearData:{failed:0}});run({featuresTest:true,clearData:{failed:4}});
  // Session restore: previous web tabs reopen once web navigation is ready.
  const restored=run({initialSettings:JSON.stringify({searchEngine:'google',cursorSpeed:1,restoreSession:true}),initialSession:JSON.stringify(['https://one.example/','https://two.example/','javascript:alert(1)'])});
  assert(restored.calls.some(c=>c[0]==='load'&&c[1]==='content'&&c[2]==='https://one.example/'));assert(restored.calls.some(c=>c[0]==='load'&&c[1]!=='content'&&c[2]==='https://two.example/'));
  const homePage=run({initialSettings:JSON.stringify({searchEngine:'google',cursorSpeed:1,homePage:'https://start.example/'})});assert(homePage.calls.some(c=>c[0]==='load'&&c[1]==='content'&&c[2]==='https://start.example/'));
  run({tabsTest:true});const text=run({textTest:true});assert(text.calls.some(c=>c[0]==='text'&&c[2]==='insertText'&&c[4]==='fox'));assert(text.calls.some(c=>c[0]==='commit-result'&&c[1]));
  const stale=run({textTest:true,stale:true});assert(!stale.calls.some(c=>c[0]==='text'));assert(stale.calls.some(c=>c[0]==='commit-result'&&!c[1]));
  for(const settings of [{profileOkay:false},{nativeReady:false},{failLoad:true},{principal:false},{early:true},{tabFault:true},{reenterTabs:true,tabsTest:true}])run(settings);
}
console.log('Browser supervisor:32 cycles actual source; explicit docshell/XPConnect/editor doubles; real tab ownership limits/switch/close/popup routing, gates/principals/stale editor cleanup. No firmware/render proof');

// Scenario scripts: each callback runs after tick i with live actions/doubles.
const loadsOf=(r,tab)=>r.calls.filter(c=>c[0]==='load'&&(tab===undefined||c[1]===tab)).map(c=>c[2]);
const restoreOn=JSON.stringify({searchEngine:'google',cursorSpeed:1,restoreSession:true});
for(let cycle=0;cycle<4;++cycle){
  // Session saving: loading tabs saved by requested URL, unchanged sets not rewritten, "[]" at once when disabled.
  let saved=null;
  const session=run({ticks:70,initialSettings:restoreOn,script(i,t){
    if(i===0){assert(t.actions.navigate('https://one.example/'));assert(t.actions.newTab());assert(t.actions.navigate('https://slow.example/'));}
    if(i===31)assert.deepEqual(JSON.parse(t.sessionPrefs),['https://one.example/','https://slow.example/']);
    if(i===32)assert(t.actions.navigate('https://two.example/'));
    if(i===61){assert.deepEqual(JSON.parse(t.sessionPrefs),['https://one.example/','https://two.example/']);saved=t.prefSaves;}
    if(i===66){assert.equal(t.prefSaves,saved,'unchanged session is not rewritten');assert(t.actions.saveSettings({restoreSession:false}));assert.equal(t.sessionPrefs,'[]','disabling clears the saved session at once');}
  }});
  assert.equal(session.sessionPrefs,'[]');
  // Oversized URLs are left out instead of voiding the whole saved session.
  const long='https://long.example/'+'a'.repeat(2100);
  const bounded=run({initialSettings:restoreOn,script(i,t){if(i===0){assert(t.actions.navigate('https://short.example/'));assert(t.actions.newTab());t.elements.get(t.selected).nav.loadURI(t.uri(long),{triggeringPrincipal:'null'});}}});
  assert.deepEqual(JSON.parse(bounded.sessionPrefs),['https://short.example/']);
  // Shutdown saves the final tab set even between periodic saves.
  const shutdown=run({initialSettings:restoreOn,script(i,t){if(i===1)assert(t.actions.navigate('https://last.example/'));}});
  assert.deepEqual(JSON.parse(shutdown.sessionPrefs),['https://last.example/']);
  // A failed prefs.js write rolls the session pref back.
  assert.equal(run({saveFails:true,initialSettings:restoreOn,initialSession:'["https://kept.example/"]',script(i,t){if(i===1)t.actions.navigate('https://new.example/');}}).sessionPrefs,'["https://kept.example/"]');
  // Clearing history forgets recently closed tabs and the saved session.
  const cleared=run({initialSettings:restoreOn,script(i,t){
    if(i===1){assert(t.actions.newTab());assert(t.actions.navigate('https://gone.example/'));assert(t.actions.closeTab());assert.equal(t.actions.closedTabs().length,1);
      assert(t.actions.clearHistory());assert.equal(t.actions.closedTabs().length,0);}
  }});
  assert(!cleared.sessionPrefs.includes('gone.example'));
  // Restore waits for the web gate, respects the tab cap, skips invalid/duplicate entries.
  const delayed=run({ticks:8,delayWeb:3,initialSettings:restoreOn,initialSession:JSON.stringify(['https://a.example/','javascript:alert(1)','https://a.example/','https://b.example/','https://c.example/','https://d.example/']),
    script(i,t){if(i<3)assert(!loadsOf({calls:t.calls}).some(u=>u.startsWith('https:')),'no web restore before the gate opens');if(i===3)assert.equal(t.elements.size,3);}});
  assert.deepEqual(loadsOf(delayed).filter(u=>u.startsWith('https:')),['https://a.example/','https://b.example/','https://c.example/']);
  // A tab the user already changed is kept; the first stored URL then opens in a new tab.
  const kept=run({ticks:8,delayWeb:3,initialSettings:restoreOn,initialSession:'["https://a.example/"]',script(i,t){if(i===1)t.elements.get('content').nav.loadURI(t.uri('http://10.42.0.1:8765/orbisfox/offline.html'),{triggeringPrincipal:'null'});}});
  assert(!loadsOf(kept,'content').includes('https://a.example/'));assert(loadsOf(kept).includes('https://a.example/'));
  const keptHome=run({ticks:8,delayWeb:3,initialSettings:JSON.stringify({searchEngine:'google',cursorSpeed:1,homePage:'https://start.example/'}),script(i,t){if(i===1)t.elements.get('content').nav.loadURI(t.uri('http://10.42.0.1:8765/orbisfox/offline.html'),{triggeringPrincipal:'null'});}});
  assert(!loadsOf(keptHome).includes('https://start.example/'));
  // Lock state: Gecko secure-UI flags first, verified TLS evidence as fallback, unknown otherwise.
  const state=(options,url='https://site.example/')=>{let value=null;run({...options,script(i,t){if(i===0)assert(t.actions.navigate(url));if(i===1)value=t.snapshots.at(-1).state;}});return value;};
  assert.equal(state({secureUI:2}).security,'secure');assert.equal(state({secureUI:3}).security,'broken');assert.equal(state({secureUI:4}).security,'insecure');
  assert.equal(state({secureUI:0,tlsState:'secure'}).security,'secure','uncomputed secure UI falls back to TLS evidence');
  assert.equal(state({secureUI:'throw',tlsState:'secure'}).security,'secure');assert.equal(state({tlsState:'secure'}).issuer,'Trusted CA');
  assert.equal(state({tlsState:'broken'}).security,'');assert.equal(state({tlsState:'broken'}).issuer,'','no identity from an unverified connection');
  assert.equal(state({}).security,'','no lock without evidence');assert.equal(state({secureUI:2},'http://plain.example/').security,'insecure');
  // Titles fall back to the host (www. stripped, IPv6 kept whole) for blank titles.
  assert.equal(state({blankTitle:true},'https://www.titled.example/x').title,'titled.example');
  assert.equal(state({blankTitle:true},'http://[::1]:8080/').title,'[::1]');
  // A new default zoom applies to tabs at the old default and new tabs, not to manually zoomed tabs.
  run({script(i,t){
    if(i!==0)return;const zoomOf=id=>t.elements.get(id).frameLoader.browsingContext.fullZoom;
    assert(t.actions.newTab());assert(t.actions.zoom(10));const manual=t.selected;assert(t.actions.newTab());const third=t.selected;
    assert(t.actions.saveSettings({defaultZoom:120}));assert.equal(zoomOf('content'),1.2);assert.equal(zoomOf(manual),1.1);assert.equal(zoomOf(third),1.2);
  }});
  // Reopen at the three-tab cap loads into the current tab; nothing reopens before the web gate.
  run({script(i,t){
    if(i!==0)return;assert(t.actions.newTab());assert(t.actions.navigate('https://closed.example/'));assert(t.actions.closeTab());assert(t.actions.newTab());assert(t.actions.newTab());
    assert.equal(t.elements.size,3);assert(t.actions.reopenClosedTab(0));assert.equal(t.elements.size,3);
    const last=t.calls.filter(c=>c[0]==='load').at(-1);assert.equal(last[1],t.selected);assert.equal(last[2],'https://closed.example/');assert.equal(t.actions.closedTabs().length,0);
  }});
  run({ticks:8,delayWeb:5,script(i,t){if(i===1){assert(t.actions.newTab());t.actions.closeTab();assert.equal(t.actions.reopenClosedTab(0),false);}}});
  // Global Privacy Control is applied on the root branch at startup and rolled back on save failure.
  const gpc=run({initialSettings:JSON.stringify({searchEngine:'google',cursorSpeed:1,globalPrivacyControl:true})});
  assert.equal(gpc.boolPrefs['privacy.globalprivacycontrol.enabled'],true);assert(!('privacy.globalprivacycontrol.functionality.enabled' in gpc.boolPrefs),'no dead pref is written');
  assert.equal(run().boolPrefs['privacy.globalprivacycontrol.enabled'],false);
  const gpcFail=run({saveFails:true,script(i,t){if(i===0)assert.equal(t.actions.saveSettings({globalPrivacyControl:true}),false);}});assert.equal(gpcFail.boolPrefs['privacy.globalprivacycontrol.enabled'],false);
  // Clear-data prefers CLEAR_COOKIES_AND_SITE_DATA (real Gecko flag values) and waits for the web gate.
  run({ticks:6,delayWeb:4,clearData:{failed:0},script(i,t){if(i===1)assert.equal(t.actions.clearSiteData(()=>assert.fail('must not clear before the gate')),false);}});
  // A failed load replaced by Gecko's error page keeps a readable message.
  run({script(i,t){const e=t.elements.get('content');if(i===0){const web={DOMWindow:e.contentWindow};e.nav.document={...e.nav.document,documentURI:'about:neterror?e=dnsNotFound&u=https%3A//x.invalid/'};e.nav.listener.onStateChange(web,null,20,0);}    if(i===1)assert.equal(t.snapshots.at(-1).state.error,'Server not found (dnsNotFound)');}});
  run({featuresTest:true,clearData:{failed:0},siteDataFlag:true});
}
setImmediate(()=>{assert.equal(clearResults.filter(ok=>ok===false).length,32,'failed flags are reported as failure');assert.equal(clearResults.filter(ok=>ok===true).length,36);
  console.log('Browser features: session save/bounds/rollback/shutdown/clear, gated/capped/non-destructive restore, lock evidence, title fallback, zoom defaults, reopen at cap, GPC root prefs, async clear-data');});
// Issue #3: diagnostics media evidence carries Gecko's per-stage frame counters.
const mediaRun=diagnostics=>run({script(i,t){
  if(i!==0)return;t.host.diagnosticsEnabled=diagnostics;const e=t.elements.get('content'),web={DOMWindow:e.contentWindow};
  const video={localName:'video',readyState:4,networkState:2,currentTime:1,paused:false,ended:false,error:null,videoWidth:640,videoHeight:360,addEventListener(){},
    getVideoPlaybackQuality:()=>({totalVideoFrames:30,droppedVideoFrames:2}),mozParsedFrames:40,mozDecodedFrames:32,mozPresentedFrames:30,mozPaintedFrames:28,mozFrameDelay:0.05};
  const audio={localName:'audio',readyState:4,networkState:2,currentTime:1,paused:false,ended:false,error:null,addEventListener(){}};
  e.nav.document={documentURI:'https://media.example/',nodePrincipal:{isSystemPrincipal:false},title:'m',querySelectorAll:s=>s==='video,audio'?[video,audio]:[],defaultView:{}};
  e.nav.listener.onStateChange(web,null,20,0);}});
const evidence=mediaRun(true).calls.filter(c=>c[0]==='log'&&c[1].startsWith('Browser media evidence: ')).map(c=>JSON.parse(c[1].slice('Browser media evidence: '.length)));
assert.deepEqual([evidence[0].parsed,evidence[0].decoded,evidence[0].presented,evidence[0].painted,evidence[0].lateSeconds],[40,32,30,28,0.05]);
assert.deepEqual([evidence[1].type,evidence[1].parsed,evidence[1].painted],['audio',null,null],'audio elements report null stage counters');
assert(!mediaRun(false).calls.some(c=>c[0]==='log'&&c[1].startsWith('Browser media evidence')),'same media page logs nothing while diagnostics are off');
console.log('Media evidence: parsed/decoded/presented/painted/lateSeconds stage counters, diagnostics-gated');
