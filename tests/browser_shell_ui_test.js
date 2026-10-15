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
    'browser-header','browser-footer','fullscreen-notice','fullscreen-button','color-system','color-light','color-dark','bookmark-button','home-screen','home-search','home-go','bookmark-list','recent-list','recent-empty','library-panel','library-title','library-bookmarks','library-history','clear-history','library-list','library-status','library-more','settings-panel','settings-general','settings-controls','settings-general-tab','settings-controls-tab','diagnostics-toggle','diagnostics-clear','engine-google','engine-duckduckgo','engine-bing','cursor-speed','cursor-speed-label','cursor-speed-shell','default-zoom','default-zoom-label','default-zoom-shell','zoom-value','settings-status','find-bar','find-text','find-status','find-next','find-previous','find-close','menu-panel','diagnostic-panel','security','status','focus-hint','diagnostic-text'])document.all.push(new Element(id,document));
  $('cursor-speed').min='25';$('cursor-speed').max='300';$('default-zoom').min='50';$('default-zoom').max='200';
  $('find-bar').hidden=true;
  for(const name of ['find-next','find-previous','find-close']){$(name).dataset.command=name;$(name).dataset.control=name;$('find-bar').appendChild($(name));}
  $('tab-buttons').appendChild($('first-tab'));$('first-tab').appendChild($('tab'));$('tab').appendChild($('tab-title'));$('tab').appendChild($('tab-dot'));$('first-tab').appendChild($('first-close-tab'));
  $('content-deck').appendChild($('content'));$('content').frameLoader={browsingContext:{isActive:true}};
  for(const id of ['tab','first-close-tab','new-tab','back','forward','reload','home','go','menu-button','address'])$(id).dataset.control=id;
  for(const panel of ['menu-panel','diagnostic-panel','settings-panel','library-panel'])$(panel).hidden=true;
  for(const name of ['settings-general-tab','settings-controls-tab']){const e=$(name);e.dataset.command=name.replace('-tab','');e.dataset.control=e.dataset.command;$('settings-panel').appendChild(e);}
  for(const name of ['settings-general','settings-controls'])$('settings-panel').appendChild($(name));$('settings-controls').hidden=true;
  for(const name of ['diagnostics-toggle','diagnostics-clear']){const e=$(name);e.dataset.command=name;e.dataset.control=name;$('settings-general').appendChild(e);}
  for(const name of ['engine-google','engine-duckduckgo','engine-bing','color-system','color-light','color-dark']){const e=$(name);e.dataset.command=name;e.dataset.control=name;$('settings-general').appendChild(e);}
  $('cursor-speed').dataset.control='cursor-speed';$('settings-general').appendChild($('cursor-speed'));
  for(const name of ['library-bookmarks','library-history','clear-history','library-more']){const e=$(name);e.dataset.command=name.replace('library-bookmarks','bookmarks').replace('library-history','history');e.dataset.control=name;$('library-panel').appendChild(e);}
  $('content-deck').appendChild($('library-panel'));$('library-panel').appendChild($('library-list'));
  for(const name of ['home','fullscreen','bookmark','bookmarks','history','settings','diagnostics','page','exit','close-tab']){
    const e=name==='close-tab'?$(name):new Element('menu-'+name,document);
    e.dataset.control='menu-'+name;e.dataset.command=name;$('menu-panel').appendChild(e);
  }
  const close=new Element('close',document);close.dataset.control='diagnostic-close';close.dataset.command='dismiss-diagnostics';$('diagnostic-panel').appendChild(close);
  let nativeOpen=false,confirm=1,settings={searchEngine:'google',cursorSpeed:1};
  let bookmarkRevision=0,historyRevision=0,bookmarkReads=0,historyReads=0;
  let bookmarkItems=[{url:'https://saved.example/',title:'<not markup>'}],historyItems=Array.from({length:80},(_,i)=>({url:'https://recent.example/'+i,title:'Page '+i,lastVisit:1000000-i}));
  const calls=[],window={},context=vm.createContext({document,window,URL});vm.runInContext(fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-model.js','utf8'),context);vm.runInContext(source,context);
  if(document.readyState==='loading'){assert.equal(window.OrbisFoxShell,undefined);document.readyState='complete';document.events.DOMContentLoaded();}
  const ui=window.OrbisFoxShell;
  const actions={exitContentFullscreen:()=>{calls.push(['exit-content-fullscreen']);return true;},openKeyboard:draft=>{calls.push(['keyboard',draft]);return nativeOpen;},openTextKeyboard:draft=>{calls.push(['text-keyboard',draft]);return nativeOpen;},keyboardConfirm:()=>confirm,
    setDiagnostics:value=>{settings={...settings,diagnostics:value};calls.push(['diagnostics',value]);return true;},clearDiagnosticLogs:()=>{settings={...settings,diagnostics:false};calls.push(['clear-logs']);return {removed:3,retained:1};},
    search:text=>{calls.push(['search',text]);return true;},settings:()=>settings,saveSettings:changes=>{settings={...settings,...changes};calls.push(['settings',changes]);return true;},
    bookmarkRevision:()=>bookmarkRevision,bookmarks:()=>{++bookmarkReads;return bookmarkItems;},
    historyRevision:()=>historyRevision,history:()=>{++historyReads;return historyItems;},historyAvailable:()=>true,
    clearHistory:()=>{historyItems=[];++historyRevision;calls.push(['clear-history']);return true;},
    removeBookmark:url=>{bookmarkItems=bookmarkItems.filter(item=>item.url!==url);++bookmarkRevision;calls.push(['remove-bookmark',url]);return true;},toggleBookmark:()=>{calls.push(['bookmark']);return true;},
    commitText:text=>{calls.push(['text',text]);return text!=='refused';},cancelText:()=>calls.push(['cancel-text']),pointer:value=>calls.push(['pointer',value]),navigate:uri=>{calls.push(['navigate',uri]);return uri!=='refused';},
    find:(text,backwards)=>{calls.push(['find',text,backwards]);return text!=='missing';},escape:()=>calls.push(['escape']),zoom:delta=>calls.push(['zoom',delta]),
    back:()=>calls.push(['back']),forward:()=>calls.push(['forward']),reload:()=>calls.push(['reload']),exit:()=>calls.push(['exit']),newTab:()=>{calls.push(['new-tab']);return true;},selectTab:id=>calls.push(['select-tab',id]),closeTab:id=>calls.push(['close-tab',id]),relativeTab:d=>calls.push(['relative',d])};ui.bind(actions);
  assert.throws(()=>ui.bind({}));
  const home={title:'Home',location:context.OrbisFoxShellModel.HOME,message:'Ready',error:'',busy:false,canBack:false,canForward:true};
  ui.renderTabs([{id:'content',...home}],'content');ui.update(home,'diagnostics',{lan:false,web:false});
  assert(!fs.readFileSync('gecko/orbisfox/fixtures/browser.xhtml','utf8').includes('data-command="google"'));assert.equal($('back').disabled,true);assert.equal($('tab-title').textContent,'Home');assert.equal($('first-close-tab').disabled,true);
  assert(!$('home-screen').hidden);assert(!ui.canScroll());
  const unchanged=['tab-title','security','status','diagnostic-text','bookmark-button'].map(id=>[$(id),$(id).textWrites]);
  for(let repeat=0;repeat<20;++repeat){ui.renderTabs([{id:'content',...home}],'content');ui.update(home,'diagnostics',{lan:false,web:false});}
  for(const [element,writes] of unchanged)assert.equal(element.textWrites,writes,'unchanged chrome must not recreate text nodes');
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
  ui.control('menu');$('menu-settings').click();assert(!$('settings-panel').hidden);
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
  assert(!source.includes('keyValues')&&!fs.readFileSync('gecko/orbisfox/fixtures/browser.xhtml','utf8').includes('id="keyboard"'));
  ui.control('address');assert(!ui.isEditing());assert.match($('status').textContent,/PS4 keyboard unavailable/);
  ui.control('menu');$('menu-diagnostics').click();assert(!$('diagnostic-panel').hidden);close.click();
  ui.control('previousTab');assert(calls.some(c=>c[0]==='relative'&&c[1]===-1));
  nativeOpen=true;ui.control('address');assert(!ui.canScroll());const before=calls.length;ui.control('menu');ui.pointerMoved();assert.equal(calls.length,before);
  ui.finishAddressKeyboard(2,'home');assert(ui.canScroll());assert(calls.some(c=>c[0]==='navigate'&&c[1]==='home'));
  ui.editText('fox');assert(!ui.canScroll());ui.finishAddressKeyboard(2,'fox revised');assert(calls.some(c=>c[0]==='text'&&c[1]==='fox revised'));
  ui.editText('fox');ui.finishAddressKeyboard(3,'');assert(!ui.isEditing());assert(calls.some(c=>c[0]==='cancel-text'));
  confirm=2;const nativeCount=calls.filter(c=>c[0]==='keyboard').length;ui.control('address');assert.match($('focus-hint').textContent,/Circle selects/);assert.equal(calls.filter(c=>c[0]==='keyboard').length,nativeCount+1);ui.finishAddressKeyboard(2,'home');assert(ui.canScroll()); // Native remains usable on Circle-confirm systems.
  confirm=1;ui.control('address');confirm=2;ui.finishAddressKeyboard(3,'');assert(!ui.isEditing());
  ui.editText('ab');ui.finishAddressKeyboard(2,'F');assert(calls.some(c=>c[0]==='text'&&c[1]==='F'));
  // Firefox-shaped find bar remains after native text entry; repeat both directions.
  assert(ui.nativeCommand('38:'));assert(!$('find-bar').hidden&&ui.isEditing());ui.finishAddressKeyboard(2,'fox');assert(!$('find-bar').hidden&&!ui.isEditing());assert.equal($('find-text').value,'fox');
  $('find-next').click();$('find-previous').click();assert(calls.some(c=>c[0]==='find'&&c[1]==='fox'&&c[2]===true));assert.equal($('find-status').textContent,'Match found');
  $('find-text').value='missing';for(const input of $('find-text').events.input)input();assert.equal($('find-status').textContent,'No match found');
  ui.control('cancel');assert($('find-bar').hidden);const escapeBefore=calls.filter(c=>c[0]==='escape').length;ui.control('cancel');assert.equal(calls.filter(c=>c[0]==='escape').length,escapeBefore+1);
  assert(ui.nativeCommand('41:'));assert(calls.some(c=>c[0]==='zoom'&&c[1]===0));assert(!ui.nativeCommand('37:'));
  ui.setContentFullscreen(true,'https://video.example');assert.equal(document.body.getAttribute('data-fullscreen'),'true');assert.equal($('browser-header').hidden,true);assert.equal($('fullscreen-notice').hidden,false);assert($('fullscreen-notice').textContent.includes('https://video.example'));
  ui.control('menu');assert.equal(document.body.getAttribute('data-fullscreen'),'false');assert(calls.some(call=>call[0]==='exit-content-fullscreen'));
  ui.setContentFullscreen(false);assert.equal(document.body.getAttribute('data-fullscreen'),'false');assert.equal($('fullscreen-notice').hidden,true);
  ui.control('menu');document.events.mousedown({target:$('content')});assert($('menu-panel').hidden);
  for(const fn of $('tab').events.auxclick)fn({button:1,preventDefault(){}});assert(calls.some(c=>c[0]==='close-tab'&&c[1]==='content'));
  ui.destroy();$('menu-exit').click();assert(!calls.some(c=>c[0]==='exit'));
}
console.log('Chrome UI:32 cycles explicit DOM/action doubles; real-tab element creation/select/removal/limit, native keyboard/cancel/confirm labels; no built-in keyboard; no layout or firmware proof');
