"use strict";
// Explicit minimal DOM double for actual packaged chrome UI source.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(id,document){this.id=id;this.document=document;this.children=[];this.parent=null;this.dataset={};this.events={};this.attributes={};this.style={values:{},getPropertyValue(name){return this.values[name]||'';},setProperty(name,value){this.values[name]=value;}};this.hidden=false;this.disabled=false;this.value='';this.selectionStart=0;this.selectionEnd=0;this.textContent='';}
  addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
  appendChild(e){e.parent=this;this.children.push(e);if(!this.document.all.includes(e))this.document.all.push(e);return e;}
  remove(){this.parent?.children.splice(this.parent.children.indexOf(this),1);this.document.all=this.document.all.filter(e=>!this.contains(e));this.parent=null;}
  contains(e){return this===e||this.children.some(c=>c.contains(e));}
  getClientRects(){for(let e=this;e;e=e.parent)if(e.hidden)return [];return [{}];}
  getBoundingClientRect(){return {left:0,top:0,right:1280,bottom:720};}
  scrollBy(x,y){this.scrollDelta=[x,y];}
  querySelectorAll(){return this.document.all.filter(e=>e!==this&&this.contains(e)&&e.dataset.control);}
  get hidden(){return this._hidden??false;}
  set hidden(value){this._hidden=!!value;this.propertyWrites=(this.propertyWrites||0)+1;}
  get disabled(){return this._disabled??false;}
  set disabled(value){this._disabled=!!value;this.propertyWrites=(this.propertyWrites||0)+1;}
  get value(){return this._value??'';}
  set value(value){this._value=value;this.propertyWrites=(this.propertyWrites||0)+1;}
  get title(){return this._title??'';}
  set title(value){this._title=value;this.propertyWrites=(this.propertyWrites||0)+1;}
  get textContent(){return this._text??'';}
  set textContent(value){this._text=value;this.textWrites=(this.textWrites||0)+1;}
  getAttribute(name){return this.attributes[name]??null;}
  setAttribute(name,value){this.attributes[name]=String(value);if(name==='data-focused')this.dataset.focused=value;}
  removeAttribute(name){delete this.attributes[name];if(name==='data-focused')delete this.dataset.focused;}
  focus(){this.document.activeElement=this;}
  click(){if(!this.disabled)for(const fn of this.events.click||[])fn({});}
  select(){this.selectionStart=0;this.selectionEnd=this.value.length;}
  setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;}
}
const source=fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-ui.js','utf8');
for(let cycle=0;cycle<32;++cycle){
  const document={all:[],activeElement:null,readyState:cycle%2?'complete':'loading',events:{},
    addEventListener(type,fn,options){if(type==='DOMContentLoaded')assert(options.once);this.events[type]=fn;},createElement:()=>new Element('',document),createElementNS:()=>new Element('',document),
    getElementById(id){return this.all.find(e=>e.id===id);},querySelectorAll(selector){return this.all.filter(e=>selector==='[data-control]'?e.dataset.control:e.dataset.command);}};
  document.body=new Element('body',document);
  const $=id=>document.getElementById(id);
  for(const id of ['tabs','tab-buttons','first-tab','tab','tab-title','tab-dot','first-close-tab','new-tab','close-tab','back','forward','reload','home','go','menu-button','address','content','content-deck',
    'browser-header','browser-footer','fullscreen-notice','fullscreen-button','color-system','color-light','color-dark','bookmark-button','home-screen','home-search','home-go','bookmark-list','recent-list','recent-empty','library-panel','library-title','library-bookmarks','library-history','clear-history','library-list','library-status','library-more','settings-panel','settings-general','settings-controls','settings-general-tab','settings-controls-tab','diagnostics-toggle','diagnostics-clear','engine-google','engine-duckduckgo','engine-bing','engine-wikipedia','engine-ecosia','engine-startpage','home-page-value','home-current','home-default','restore-session','gpc-toggle','clear-site-data','site-identity','site-panel','site-host','site-connection','site-issuer','library-closed','cursor-speed','cursor-speed-label','cursor-speed-shell','default-zoom','default-zoom-label','default-zoom-shell','zoom-value','settings-status','find-bar','find-text','find-status','find-next','find-previous','find-close','menu-panel','diagnostic-panel','security','status','focus-hint','diagnostic-text','keyboard-panel','keyboard-title','keyboard-note','keyboard-draft','keyboard-password','keyboard-keys'])document.all.push(new Element(id,document));
  $('cursor-speed').min='25';$('cursor-speed').max='300';$('default-zoom').min='50';$('default-zoom').max='200';
  $('find-bar').hidden=true;$('keyboard-panel').hidden=true;$('keyboard-password').type='password';
  for(const name of ['find-next','find-previous','find-close']){$(name).dataset.command=name;$(name).dataset.control=name;$('find-bar').appendChild($(name));}
  $('tab-buttons').appendChild($('first-tab'));$('first-tab').appendChild($('tab'));$('tab').appendChild($('tab-title'));$('tab').appendChild($('tab-dot'));$('first-tab').appendChild($('first-close-tab'));
  $('content-deck').appendChild($('content'));$('content').frameLoader={browsingContext:{isActive:true}};
  for(const id of ['tab','first-close-tab','new-tab','back','forward','reload','home','go','menu-button','address'])$(id).dataset.control=id;
  for(const panel of ['menu-panel','diagnostic-panel','settings-panel','library-panel','site-panel'])$(panel).hidden=true;
  $('site-identity').dataset.control='site-identity';$('site-identity').dataset.command='site-info';
  const siteClose=new Element('site-close',document);siteClose.dataset.control='site-close';siteClose.dataset.command='page';$('site-panel').appendChild(siteClose);
  for(const name of ['settings-general-tab','settings-controls-tab']){const e=$(name);e.dataset.command=name.replace('-tab','');e.dataset.control=e.dataset.command;$('settings-panel').appendChild(e);}
  for(const name of ['settings-general','settings-controls'])$('settings-panel').appendChild($(name));$('settings-controls').hidden=true;
  for(const name of ['diagnostics-toggle','diagnostics-clear']){const e=$(name);e.dataset.command=name;e.dataset.control=name;$('settings-general').appendChild(e);}
  for(const name of ['engine-google','engine-duckduckgo','engine-bing','engine-wikipedia','engine-ecosia','engine-startpage','home-current','home-default','restore-session','gpc-toggle','clear-site-data','color-system','color-light','color-dark']){const e=$(name);e.dataset.command=name;e.dataset.control=name;$('settings-general').appendChild(e);}
  $('cursor-speed').dataset.control='cursor-speed';$('settings-general').appendChild($('cursor-speed'));
  for(const name of ['library-bookmarks','library-history','library-closed','clear-history','library-more']){const e=$(name);e.dataset.command=name.replace('library-bookmarks','bookmarks').replace('library-history','history').replace('library-closed','closed-tabs');e.dataset.control=name;$('library-panel').appendChild(e);}
  $('content-deck').appendChild($('library-panel'));$('library-panel').appendChild($('library-list'));
  for(const name of ['home','fullscreen','bookmark','bookmarks','history','settings','diagnostics','page','exit','close-tab']){
    const e=name==='close-tab'?$(name):new Element('menu-'+name,document);
    e.dataset.control='menu-'+name;e.dataset.command=name;$('menu-panel').appendChild(e);
  }
  const close=new Element('close',document);close.dataset.control='diagnostic-close';close.dataset.command='dismiss-diagnostics';$('diagnostic-panel').appendChild(close);
  let settings={searchEngine:'google',cursorSpeed:1};
  let bookmarkRevision=0,historyRevision=0,bookmarkReads=0,historyReads=0,pendingClear=null,closedRevision=0,closedItems=[{url:'https://closed.example/',title:'Closed page',closed:1}];
  let bookmarkItems=[{url:'https://saved.example/',title:'<not markup>'}],historyItems=Array.from({length:80},(_,i)=>({url:'https://recent.example/'+i,title:'Page '+i,lastVisit:1000000-i}));
  const calls=[],window={},context=vm.createContext({document,window,URL});vm.runInContext(fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-model.js','utf8'),context);vm.runInContext(source,context);
  if(document.readyState==='loading'){assert.equal(window.OrbisFoxShell,undefined);document.readyState='complete';document.events.DOMContentLoaded();}
  const ui=window.OrbisFoxShell;
  const actions={exitContentFullscreen:()=>{calls.push(['exit-content-fullscreen']);return true;},openKeyboard:()=>assert.fail('custom keyboard must not launch native IME'),openTextKeyboard:()=>assert.fail('custom keyboard must not launch native IME'),
    keyboardActive:value=>calls.push(['keyboard-active',value]),enterText:()=>{calls.push(['enter-text']);return true;},
    updateText:(value,start,end)=>{calls.push(['live-text',value,start,end]);return value==='refused'?false:{value,start,end};},
    setDiagnostics:value=>{settings={...settings,diagnostics:value};calls.push(['diagnostics',value]);return true;},clearDiagnosticLogs:()=>{settings={...settings,diagnostics:false};calls.push(['clear-logs']);return {removed:3,retained:1};},
    search:text=>{calls.push(['search',text]);return true;},settings:()=>settings,saveSettings:changes=>{settings={...settings,...changes};calls.push(['settings',changes]);return true;},
    bookmarkRevision:()=>bookmarkRevision,bookmarks:()=>{++bookmarkReads;return bookmarkItems;},
    historyRevision:()=>historyRevision,history:()=>{++historyReads;return historyItems;},historyAvailable:()=>true,
    clearHistory:()=>{historyItems=[];++historyRevision;calls.push(['clear-history']);return true;},
    removeBookmark:url=>{bookmarkItems=bookmarkItems.filter(item=>item.url!==url);++bookmarkRevision;calls.push(['remove-bookmark',url]);return true;},toggleBookmark:()=>{calls.push(['bookmark']);return true;},
    commitText:text=>{calls.push(['text',text]);return text!=='refused';},cancelText:()=>calls.push(['cancel-text']),pointer:value=>calls.push(['pointer',value]),navigate:uri=>{calls.push(['navigate',uri]);return uri!=='refused';},
    find:(text,backwards)=>{calls.push(['find',text,backwards]);return text!=='missing';},escape:()=>calls.push(['escape']),zoom:delta=>calls.push(['zoom',delta]),
    back:()=>calls.push(['back']),forward:()=>calls.push(['forward']),reload:()=>calls.push(['reload']),exit:()=>calls.push(['exit']),newTab:()=>{calls.push(['new-tab']);return true;},selectTab:id=>calls.push(['select-tab',id]),closeTab:id=>calls.push(['close-tab',id]),relativeTab:d=>calls.push(['relative',d]),
    closedTabsRevision:()=>closedRevision,closedTabs:()=>closedItems,reopenClosedTab:index=>{calls.push(['reopen',index]);closedItems=closedItems.filter((_,i)=>i!==index);++closedRevision;return true;},
    removeHistory:url=>{historyItems=historyItems.filter(item=>item.url!==url);++historyRevision;calls.push(['remove-history',url]);return true;},
    clearSiteData:done=>{calls.push(['clear-site-data']);pendingClear=done;return true;}};ui.bind(actions);
  assert.throws(()=>ui.bind({}));
  const home={title:'Home',location:context.OrbisFoxShellModel.HOME,message:'Ready',error:'',busy:false,canBack:false,canForward:true};
  ui.renderTabs([{id:'content',...home}],'content');ui.update(home,'diagnostics',{lan:false,web:false});
  assert(!fs.readFileSync('gecko/orbisfox/fixtures/browser.xhtml','utf8').includes('data-command="google"'));assert.equal($('back').disabled,true);assert.equal($('tab-title').textContent,'Home');assert.equal($('first-close-tab').disabled,true);
  assert(!$('home-screen').hidden);assert(!ui.canScroll());
  const unchanged=['tab-title','security','status','diagnostic-text','bookmark-button'].map(id=>[$(id),$(id).textWrites]);
  const unchangedProperties=document.all.map(e=>[e,e.propertyWrites||0]);
  for(let repeat=0;repeat<20;++repeat){ui.renderTabs([{id:'content',...home}],'content');ui.update(home,'diagnostics',{lan:false,web:false});}
  for(const [element,writes] of unchanged)assert.equal(element.textWrites,writes,'unchanged chrome must not recreate text nodes');
  for(const [element,writes] of unchangedProperties)assert.equal(element.propertyWrites||0,writes,'unchanged reflected properties must not dirty chrome: '+element.id);
  assert.equal($('bookmark-list').children[0].children[0].children[1].textContent,'<not markup>');
  assert.equal($('bookmark-list').children[0].children[0].children[0].className,'site-icon');
  assert.equal($('tab-dot').className,undefined);assert.match($('tab-dot').getAttribute('src'),/^data:image\/svg\+xml,/);
  const badIcon='data:image/png;base64,AAAA';ui.renderTabs([{id:'content',...home,favicon:badIcon}],'content');
  for(const error of $('tab-dot').events.error)error();const safeIcon=$('tab-dot').getAttribute('src');
  for(let repeat=0;repeat<10;++repeat)ui.renderTabs([{id:'content',...home,favicon:badIcon}],'content');
  assert.equal($('tab-dot').getAttribute('src'),safeIcon,'a corrupt raster must not restart image decoding every frame');
  assert.equal(bookmarkReads,1);assert.equal(historyReads,1);assert.equal($('recent-list').children.length,1,'recents deduplicate site paths');assert.equal($('recent-list').children[0].children[0].children[1].textContent,'recent.example');
  const savedHistory=historyItems;historyItems=Array.from({length:30},(_,i)=>({url:'https://site'+Math.floor(i/2)+'.example/path'+i,title:'Path title',lastVisit:1000000-i}));++historyRevision;ui.update(home,'diagnostics',{web:false});assert.equal($('recent-list').children.length,9);assert.equal($('recent-list').children[0].children[0].title,'https://site0.example/');historyItems=savedHistory;++historyRevision;ui.update(home,'diagnostics',{web:false});
  $('home-search').value='cats';for(const fn of $('home-search').events.keydown)fn({key:'Enter',preventDefault(){}});
  assert(calls.some(c=>c[0]==='search'&&c[1]==='cats'));
  ui.update({...home,location:'https://example.com/'},'diagnostics',{lan:false,web:true});
  ui.control('menu');$('menu-fullscreen').click();assert($('browser-header').hidden&&$('browser-footer').hidden);assert($('menu-panel').hidden);
  ui.control('menu');assert(!$('browser-header').hidden&&!$('browser-footer').hidden);assert($('menu-panel').hidden);
  const navigationCount=calls.filter(c=>c[0]==='navigate').length;
  ui.control('menu');$('menu-bookmarks').click();assert(!$('library-panel').hidden);assert.equal($('library-title').textContent,'Bookmarks');assert.equal(calls.filter(c=>c[0]==='navigate').length,navigationCount,'bookmarks must not navigate home');
  assert.equal($('library-list').children.length,1);document.all.find(e=>e.dataset.control==='library-remove-0').click();assert.equal($('library-list').children.length,0);
  $('library-history').click();assert.equal($('library-title').textContent,'Browsing history');assert.equal($('library-list').children.length,64);assert(!$('library-more').hidden);$('library-more').click();assert.equal($('library-list').children.length,80);
  assert(ui.scrollShell(0,24,100,100));assert.deepEqual($('library-panel').scrollDelta,[0,24]);
  $('clear-history').click();assert.equal($('library-list').children.length,0);assert.equal($('recent-list').children.length,0);ui.control('cancel');assert($('library-panel').hidden);
  // Recently closed tabs reopen via the library; history rows can be deleted with local dates.
  ui.control('menu');$('menu-history').click();$('library-closed').click();assert.equal($('library-title').textContent,'Recently closed tabs');assert.equal($('library-list').children.length,1);
  document.all.find(e=>e.dataset.control==='library-reopen-0').click();assert(calls.some(c=>c[0]==='reopen'&&c[1]===0));assert($('library-panel').hidden);
  historyItems=[{url:'https://kept.example/',title:'Kept',lastVisit:Date.UTC(2026,0,2,3,4)},{url:'https://gone.example/',title:'Gone',lastVisit:Date.UTC(2026,0,1)}];++historyRevision;
  ui.control('menu');$('menu-history').click();assert.equal($('library-list').children.length,2);assert(!/UTC$/.test($('library-list').children[0].children[1].textContent));
  for(let step=0;step<10&&document.activeElement?.dataset.control!=='library-delete-1';++step)ui.control('down');assert.equal(document.activeElement.dataset.control,'library-delete-1');
  document.all.find(e=>e.dataset.control==='library-delete-1').click();assert.equal(document.activeElement.dataset.control,'library-delete-0','focus moves to the nearest row, not the top');assert(calls.some(c=>c[0]==='remove-history'&&c[1]==='https://gone.example/'));assert.equal($('library-list').children.length,1);ui.control('cancel');
  // Site identity: lock for HTTPS, "Not Secure" for HTTP, details panel with issuer.
  ui.update({...home,location:'http://plain.example/',security:'insecure'},'diagnostics',{web:true});assert.equal($('site-identity').getAttribute('data-security'),'insecure');assert.equal($('security').textContent,'Not Secure');
  ui.update({...home,location:'https://mixed.example/',security:'broken'},'diagnostics',{web:true});assert.equal($('security').textContent,'Not fully secure');
  ui.update({...home,location:'https://unknown.example/',security:''},'diagnostics',{web:true});assert.equal($('site-identity').getAttribute('data-security'),'');assert.equal($('security').textContent,'');
  ui.update({...home,location:'https://example.com/',security:'secure',issuer:'Example CA'},'diagnostics',{web:true});assert.equal($('security').textContent,'');
  $('site-identity').click();assert(!$('site-panel').hidden);assert.equal($('site-host').textContent,'example.com');assert.match($('site-connection').textContent,/secure/);assert.equal($('site-issuer').textContent,'Verified by: Example CA');
  ui.update({...home,location:'http://redirected.example/',security:'insecure'},'diagnostics',{web:true});assert.equal($('site-host').textContent,'redirected.example','open panel follows navigation');assert.equal($('site-issuer').textContent,'');
  document.events.mousedown({target:$('content')});assert($('site-panel').hidden,'clicking the page dismisses site information');assert.equal($('site-identity').getAttribute('aria-expanded'),'false');
  ui.update({...home,location:'https://example.com/',security:'secure',issuer:'Example CA'},'diagnostics',{web:true});
  ui.control('menu');$('menu-settings').click();assert(!$('settings-panel').hidden);
  // Home page, session restore, GPC and two-step site-data clearing.
  $('home-current').click();assert.equal(settings.homePage,'https://example.com/');assert.equal($('home-page-value').textContent,'https://example.com/');assert($('home-current').disabled);
  $('home-default').click();assert.equal(settings.homePage,'');assert.equal($('home-page-value').textContent,'OrbisFox Home');
  $('restore-session').click();assert.equal(settings.restoreSession,true);assert.equal($('restore-session').getAttribute('aria-checked'),'true');
  $('gpc-toggle').click();assert.equal(settings.globalPrivacyControl,true);assert.match($('gpc-toggle').textContent,/On$/);
  $('clear-site-data').click();assert(!calls.some(c=>c[0]==='clear-site-data'),'first press only arms the confirmation');assert.equal($('clear-site-data').getAttribute('data-confirm'),'true');
  $('clear-site-data').click();assert(calls.some(c=>c[0]==='clear-site-data'));assert.equal($('settings-status').textContent,'Clearing cookies and site data…');
  pendingClear(false);assert.equal($('settings-status').textContent,'Some site data could not be cleared.');
  // An armed confirmation expires after five seconds and is not kept across reopening Settings.
  const ContextDate=vm.runInContext('Date',context),realNow=ContextDate.now;try{$('clear-site-data').click();assert.equal($('clear-site-data').getAttribute('data-confirm'),'true');const armed=realNow();ContextDate.now=()=>armed+5001;
    ui.update({...home,location:'https://example.com/'},'diagnostics',{web:true});assert.equal($('clear-site-data').getAttribute('data-confirm'),'false');assert.equal($('settings-status').textContent,'Changes are saved automatically.');
    ContextDate.now=realNow;$('clear-site-data').click();ui.control('cancel');ui.control('menu');$('menu-settings').click();const clears=calls.filter(c=>c[0]==='clear-site-data').length;
    $('clear-site-data').click();assert.equal(calls.filter(c=>c[0]==='clear-site-data').length,clears,'reopened Settings needs a fresh confirmation');}finally{ContextDate.now=realNow;}
  // D-pad focus survives a home-page button disabling itself.
  for(let step=0;step<40&&document.activeElement!==$('home-current');++step)ui.control('down');assert.equal(document.activeElement,$('home-current'));
  $('home-current').click();assert($('home-current').disabled);assert(!$('home-current').dataset.focused);assert($('settings-panel').contains(document.activeElement));assert.notEqual(document.activeElement,$('settings-general-tab'));
  $('engine-wikipedia').click();assert.equal(settings.searchEngine,'wikipedia');assert.equal($('engine-wikipedia').getAttribute('aria-pressed'),'true');
  assert.equal($('diagnostics-toggle').getAttribute('aria-checked'),'false');
  $('settings-controls-tab').click();assert($('settings-general').hidden&&!$('settings-controls').hidden);assert.equal($('settings-controls-tab').getAttribute('aria-selected'),'true');
  $('settings-general-tab').click();assert(!$('settings-general').hidden&&$('settings-controls').hidden);
  $('diagnostics-toggle').click();assert.equal(settings.diagnostics,true);assert.equal($('diagnostics-toggle').getAttribute('aria-checked'),'true');
  $('diagnostics-clear').click();assert.equal(settings.diagnostics,false);assert.match($('settings-status').textContent,/Removed 3/);assert(calls.some(c=>c[0]==='clear-logs'));
  $('engine-duckduckgo').click();assert.equal(settings.searchEngine,'duckduckgo');
  $('cursor-speed').value='150';for(const fn of $('cursor-speed').events.input)fn();assert.equal(settings.cursorSpeed,1);assert.equal($('cursor-speed-label').textContent,'1.5×');assert.equal($('cursor-speed-shell').style.getPropertyValue('--fill'),((150-25)*100/275)+'%');for(const fn of $('cursor-speed').events.change)fn();assert.equal(settings.cursorSpeed,1.5);
  for(let step=0;step<24&&document.activeElement!==$('cursor-speed');++step)ui.control('down');
  assert.equal(document.activeElement,$('cursor-speed'));ui.control('right');assert.equal(settings.cursorSpeed,1.75);ui.control('cancel');assert($('settings-panel').hidden);
  for(const colorScheme of ['dark','light','system']){$('color-'+colorScheme).click();assert.equal(settings.colorScheme,colorScheme);assert.equal($('color-'+colorScheme).getAttribute('aria-pressed'),'true');}
  $('default-zoom').value='110';for(const fn of $('default-zoom').events.input)fn();assert.equal($('default-zoom-shell').style.getPropertyValue('--fill'),'40%');for(const fn of $('default-zoom').events.change)fn();assert.equal(settings.defaultZoom,110);
  const originalNewTab=actions.newTab;actions.newTab=()=>false;assert.equal(ui.nativeCommand('8:'),false);actions.newTab=originalNewTab;assert.equal(ui.nativeCommand('8:'),true);
  $('new-tab').click();assert(calls.some(c=>c[0]==='new-tab'));
  const second=ui.createContent('content-1');assert(second.hidden,'new tab must be hidden until selected');assert.equal(second.attributes.type,'content');assert.equal(second.attributes.remote,undefined);
  ui.createContent('content-2');assert.throws(()=>ui.createContent('content-3'));assert.throws(()=>ui.createContent('content-2'));
  ui.selectContent('content-1');assert($('content').hidden);assert(!second.hidden);
  ui.renderTabs([{id:'content',...home},{id:'content-1',title:'Google'},{id:'content-2',title:'Third'}],'content-1');assert($('new-tab').disabled);
  const button=document.all.find(e=>e.dataset.control==='tab-content-2');button.click();assert(calls.some(c=>c[0]==='select-tab'&&c[1]==='content-2'));
  ui.removeContent('content-2');ui.renderTabs([{id:'content',...home},{id:'content-1',title:'Google'}],'content-1');assert(!$('new-tab').disabled);
  const key=label=>{const button=$('keyboard-keys').children.flatMap(row=>row.children).find(button=>button.textContent===label);assert(button,'missing key '+label);button.click();};
  const type=value=>{const draft=$('keyboard-password').hidden?$('keyboard-draft'):$('keyboard-password');draft.value=value;draft.setSelectionRange(value.length,value.length);for(const input of draft.events.input)input();};
  const physical=(name,shiftKey=false)=>document.events.keydown({key:name,shiftKey,preventDefault(){}});
  ui.control('address');assert(ui.isEditing());assert(!$('keyboard-panel').hidden);assert(!ui.canScroll());assert.equal(ui.nativeChromeScene(),'');assert(!ui.nativeCommand('8:'));
  const before=calls.length;ui.pointerMoved();assert.equal(calls.length,before);ui.finishAddressKeyboard(2,'ignored');assert(ui.isEditing());
  ui.control('cross');assert.equal($('keyboard-draft').value,'q');ui.control('reload');assert.equal($('keyboard-draft').value,'q ');ui.control('address');assert.equal($('keyboard-draft').value,'q');
  key('Shift');key('A');assert.equal($('keyboard-draft').value,'qA');key('Symbols');key('\\');assert.equal($('keyboard-draft').value,'qA\\');key('ABC');
  key('Clear');ui.control('left');ui.control('cross');assert.equal($('keyboard-draft').value,'P');
  key('Clear');$('keyboard-draft').focus();physical('Tab');physical('Enter');assert.equal($('keyboard-draft').value,'1');
  type('home');ui.control('forward');assert(!ui.isEditing());assert(ui.canScroll());assert(calls.some(c=>c[0]==='navigate'&&c[1]==='home'));
  assert.equal($('keyboard-draft').value,'');assert.deepEqual(calls.filter(c=>c[0]==='keyboard-active').slice(-2),[['keyboard-active',true],['keyboard-active',false]]);
  ui.control('address');type('refused');ui.control('forward');assert(ui.isEditing(),'failed R2 navigation keeps draft');physical('Escape');assert(!ui.isEditing());
  ui.control('menu');$('menu-diagnostics').click();assert(!$('diagnostic-panel').hidden);close.click();
  ui.control('previousTab');assert(calls.some(c=>c[0]==='relative'&&c[1]===-1));
  $('home-search').value='original';$('home-search').click();type('live search');ui.control('cancel');assert.equal($('home-search').value,'original');
  $('home-search').click();type('fox search');ui.control('forward');assert(calls.some(c=>c[0]==='search'&&c[1]==='fox search'));
  ui.editText('abc',{start:1,end:2});ui.control('cross');assert.equal($('keyboard-draft').value,'aqc');assert.deepEqual(calls.at(-1),['live-text','aqc',2,2]);
  ui.control('previousTab');ui.control('address');assert.equal($('keyboard-draft').value,'qc');ui.control('cancel');assert(!ui.isEditing());assert.equal($('keyboard-draft').value,'');
  assert(calls.some(c=>c[0]==='cancel-text'));assert(!calls.some(c=>c[0]==='text'),'live edits are not committed twice');
  ui.editText('secret',{password:true,start:6,end:6});assert($('keyboard-draft').hidden);assert(!$('keyboard-password').hidden);assert.equal($('keyboard-password').type,'password');
  ui.control('address');assert.equal($('keyboard-password').value,'secre');key('Done');assert.equal($('keyboard-password').value,'');
  const enters=calls.filter(c=>c[0]==='enter-text').length;
  ui.editText('fox');ui.control('forward');assert(!ui.isEditing());assert.equal(calls.filter(c=>c[0]==='enter-text').length,enters+1,'R2 sends Enter to the page, not browser Forward');
  ui.editText('fox');key('Done');assert.equal(calls.filter(c=>c[0]==='enter-text').length,enters+1,'Done closes without submitting');
  ui.editText('a',{multiline:true,start:1,end:1});ui.control('forward');assert(ui.isEditing());assert.equal($('keyboard-draft').value,'a\n');physical('Enter');assert.equal($('keyboard-draft').value,'a\n\n');physical('Escape');
  ui.editText('x',{maxLength:1,start:1,end:1});ui.control('cross');assert.equal($('keyboard-draft').value,'x');key('Clear');key('q');assert.equal($('keyboard-draft').value,'q');ui.control('cancel');
  ui.editText('😀',{start:2,end:2});ui.control('address');assert.equal($('keyboard-draft').value,'');ui.control('cancel');
  ui.editText('old');type('refused');assert(!ui.isEditing());assert.equal($('keyboard-draft').value,'');
  const forwards=calls.filter(c=>c[0]==='forward').length;assert(ui.nativeCommand('2:'));assert.equal(calls.filter(c=>c[0]==='forward').length,forwards+1,'native chrome still handles Forward outside typing');
  // Find remains visible after R2 submits its draft.
  assert(ui.nativeCommand('38:'));assert(!$('find-bar').hidden&&ui.isEditing());type('fox');ui.control('forward');assert(!$('find-bar').hidden&&!ui.isEditing());assert.equal($('find-text').value,'fox');
  $('find-next').click();$('find-previous').click();assert(calls.some(c=>c[0]==='find'&&c[1]==='fox'&&c[2]===true));assert.equal($('find-status').textContent,'Match found');
  $('find-text').value='missing';for(const input of $('find-text').events.input)input();assert.equal($('find-status').textContent,'No match found');
  ui.control('cancel');assert($('find-bar').hidden);const escapeBefore=calls.filter(c=>c[0]==='escape').length;ui.control('cancel');assert.equal(calls.filter(c=>c[0]==='escape').length,escapeBefore+1);
  assert(ui.nativeCommand('41:'));assert(calls.some(c=>c[0]==='zoom'&&c[1]===0));assert(!ui.nativeCommand('47:'));
  assert(ui.nativeCommand('37:'));assert(!$('library-panel').hidden);assert.equal($('library-title').textContent,'Recently closed tabs');ui.control('cancel');
  ui.setContentFullscreen(true,'https://video.example');assert.equal(document.body.getAttribute('data-fullscreen'),'true');assert.equal($('browser-header').hidden,true);assert.equal($('fullscreen-notice').hidden,false);assert($('fullscreen-notice').textContent.includes('https://video.example'));
  ui.control('menu');assert.equal(document.body.getAttribute('data-fullscreen'),'false');assert(calls.some(call=>call[0]==='exit-content-fullscreen'));
  ui.setContentFullscreen(false);assert.equal(document.body.getAttribute('data-fullscreen'),'false');assert.equal($('fullscreen-notice').hidden,true);
  ui.control('menu');document.events.mousedown({target:$('content')});assert($('menu-panel').hidden);
  for(const fn of $('tab').events.auxclick)fn({button:1,preventDefault(){}});assert(calls.some(c=>c[0]==='close-tab'&&c[1]==='content'));
  ui.editText('private',{password:true});ui.destroy();assert.equal($('keyboard-password').value,'');assert($('keyboard-panel').hidden);$('menu-exit').click();assert(!calls.some(c=>c[0]==='exit'));
}
console.log('Chrome UI:32 cycles explicit DOM/action doubles; real-tab element creation/select/removal/limit, custom keyboard/R2 Enter/drafts/live edits/password masking; no layout or firmware proof');
