"use strict";
// Actual supervisor with explicit XPConnect/docshell/controller/editor doubles.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-host.js','utf8');
function run({principal=true,failLoad=false,early=false,profileOkay=true,nativeReady=true,tabsTest=false,textTest=false,stale=false,scroll=false,tabFault=false,reenterTabs=false,bookmarksTest=false,historyTest=false,mediaTest=false,saveFails=false,settingsTest=false,cursorFails=false,cursorX=40,cursorY=150,pixelRatio=1,rect={left:0,top:104,width:1280,height:584}}={}) {
  const calls=[],snapshots=[],elements=new Map();let tick,actions,exit=false,listenerCount=0,selected='content',editing=false;
  const Ci={nsIDOMWindowUtils:{WHEEL_EVENT_CAUSED_BY_NO_LINE_OR_PAGE_DELTA_DEVICE:1,WHEEL_EVENT_ASYNC_ENABLED:8},nsITimer:{TYPE_REPEATING_SLACK:1},
    nsIWebProgress:{NOTIFY_STATE_DOCUMENT:1,NOTIFY_LOCATION:2},nsIWebProgressListener:{STATE_IS_DOCUMENT:4,STATE_START:8,STATE_STOP:16,LOCATION_CHANGE_SAME_DOCUMENT:32},
    nsIWebNavigation:{STOP_ALL:1,LOAD_FLAGS_NONE:0},nsIBrowserDOMWindow:{OPEN_CURRENTWINDOW:1,OPEN_NEWTAB:3,OPEN_PRINT_BROWSER:4,OPEN_NEWTAB_BACKGROUND:5,OPEN_NEWTAB_FOREGROUND:6,OPEN_NO_REFERRER:8}};
  const uri=spec=>({spec,scheme:spec.split(':')[0],host:/^https?:/.test(spec)?new URL(spec).hostname:'',userPass:/^https?:/.test(spec)?new URL(spec).username:''});
  function element(id){
    const win={innerWidth:1280,innerHeight:584,windowUtils:{sendWheelEvent(...args){calls.push(['wheel',id,...args]);},sendContentCommandEvent(...args){calls.push(['text',id,...args]);return true;}}};
    const nav={document:{documentURI:'about:blank'},canGoBack:false,canGoForward:false,
      loadURI(target,options){calls.push(['load',id,target.spec,options.triggeringPrincipal,options]);if(failLoad)throw Error('Load refused');
        this.document={documentURI:target.spec,nodePrincipal:{isSystemPrincipal:false},title:target.spec,defaultView:{wrappedJSObject:{orbisfoxFixture:{ok:true,passed:8}}},activeElement:null,elementFromPoint(){return this.activeElement;}};
        this.listener.onLocationChange({DOMWindow:win},null,target);this.listener.onStateChange({DOMWindow:win},null,20,0);},
      stop(){calls.push(['stop',id]);},reload(){calls.push(['reload',id]);},goBack(){calls.push(['back',id]);},goForward(){calls.push(['forward',id]);}};
    const progress={addProgressListener(l){nav.listener=l;++listenerCount;},removeProgressListener(){--listenerCount;calls.push(['remove-listener',id]);}};
    const e={id,nav,contentWindow:win,docShell:{QueryInterface:iface=>iface===Ci.nsIWebProgress?progress:nav},frameLoader:{browsingContext:{isContent:true,useRemoteTabs:false,useRemoteSubframes:false}},
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
  const host={cursorX,cursorY,buttons:0,nativeNetworkReady:nativeReady,framesPresented:0,scrollX:scroll?4:0,scrollY:scroll?-7:0,keyboardStatus:1,keyboardText:'fox',keyboardConfirmButton:1,
    openAddressKeyboard(){return true;},openTextKeyboard(){calls.push(['open-text']);return true;},cancelAddressKeyboard(){calls.push(['cancel-keyboard']);},
    createChromeBrowser:()=>chrome,pumpFrame:()=>!early,log:text=>calls.push(['log',text]),fixtureCheckpoint:value=>calls.push(['checkpoint',value]),setPointerInputEnabled(enabled){if(!enabled&&reenterTabs&&actions)assert.equal(actions.newTab(),false);},requestExit(){exit=true;},closeBrowser(){calls.push(['close']);}};
  host.setCursorSpeed=value=>{if(cursorFails&&value!==1)throw Error('cursor failed');calls.push(['cursor-speed',value]);};
  const timer={initWithCallback(fn){tick=fn;},cancel(){calls.push(['cancel-timer']);}};
  let bookmarkPrefs='[]',historyPrefs='[]',settingsPrefs='{}',contentColorScheme=2;
  const preferenceService={getBranch:()=>({setIntPref:(name,value)=>{assert.equal(name,'layout.css.prefers-color-scheme.content-override');contentColorScheme=value;},getStringPref:name=>name==='settings'?settingsPrefs:name==='history'?historyPrefs:bookmarkPrefs,setStringPref:(name,value)=>{if(name==='settings')settingsPrefs=value;else if(name==='history')historyPrefs=value;else bookmarkPrefs=value;}}),savePrefFile(file){assert(file&&file.leaf==='prefs.js','explicit blocking preference destination required');if(saveFails)throw Error('save failed');}};
  const Cc={'@mozilla.org/file/directory_service;1':{getService:()=>({get:key=>{assert.equal(key,'ProfD');return {clone:()=>({append(name){this.leaf=name;}})};}})},'@mozilla.org/preferences-service;1':{getService:()=>preferenceService},'@mozilla.org/timer;1':{createInstance:()=>timer},'@mozilla.org/referrer-info;1':{createInstance:()=>({init(policy,send,uri){this.policy=policy;this.send=send;this.uri=uri;}})}};
  const network={snapshot:()=>({storage:{ok:true},http:{ok:false},dns:{ok:true}}),canNavigateLAN:()=>false,close(){calls.push(['network-close']);}};
  const tls={snapshot:()=>({ok:true}),close(){calls.push(['TLS-close']);}};
  const context=vm.createContext({Cc,Ci,host,io:{newURI:uri},ssm:{getSystemPrincipal:()=> 'system',createContentPrincipal:()=> 'file',createNullPrincipal:()=> 'null'},
    ChromeUtils:{generateQI:()=>()=>{}},startTrustedNetworkProbes:()=>network,startTrustedHTTPSProbes:()=>tls});
  context.load=path=>vm.runInContext(fs.readFileSync('gecko/orbisfox/fixtures/'+path.split('/').at(-1),'utf8'),context);
  const tm={spinEventLoopUntil(name,done){
    for(let i=0;i<7&&!done();++i){tick();if(!actions)continue;
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
        editing=true;assert.throws(()=>win.browserDOMWindow.createContentWindow(null,null,3,0,{isSystemPrincipal:false}));editing=false;
      }
      if(i===5)actions.exit();
    }
  }};
  vm.runInContext(source,context);context.runOrbisFoxBrowserShell(Cc,Ci,host,context.io,tm,context.ssm,{snapshot:()=>({ok:profileOkay})});
  assert.equal(listenerCount,0);return {calls,snapshots,exit};
}
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
  run({tabsTest:true});const text=run({textTest:true});assert(text.calls.some(c=>c[0]==='text'&&c[2]==='insertText'&&c[4]==='fox'));assert(text.calls.some(c=>c[0]==='commit-result'&&c[1]));
  const stale=run({textTest:true,stale:true});assert(!stale.calls.some(c=>c[0]==='text'));assert(stale.calls.some(c=>c[0]==='commit-result'&&!c[1]));
  for(const settings of [{profileOkay:false},{nativeReady:false},{failLoad:true},{principal:false},{early:true},{tabFault:true},{reenterTabs:true,tabsTest:true}])run(settings);
}
console.log('Browser supervisor:32 cycles actual source; explicit docshell/XPConnect/editor doubles; real tab ownership limits/switch/close/popup routing, gates/principals/stale editor cleanup. No firmware/render proof');
