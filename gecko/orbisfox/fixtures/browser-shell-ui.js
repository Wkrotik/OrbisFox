/* Packaged system-principal chrome only. Content receives no host bridge. */
"use strict";
function initializeOrbisFoxShell() {
  const $=id=>document.getElementById(id);
  // textContent recreates text nodes even when the string is unchanged. Avoid
  // dirtying chrome/layout/compositor on every16ms supervisory timer tick.
  const text=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
  const attribute=(element,name,value)=>{if(element.getAttribute(name)!==value)element.setAttribute(name,value);};
  const fallbackIcon='data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20"%3E%3Ccircle cx="10" cy="10" r="8" fill="none" stroke="%2396a3ba"/%3E%3Cpath d="M2 10h16M10 2c-5 4-5 12 0 16 5-4 5-12 0-16" fill="none" stroke="%2396a3ba"/%3E%3C/svg%3E';
  const setIcon=(img,url,data=null)=>{
    if(!img.dataset.iconBound){img.dataset.iconBound='true';img.addEventListener('error',()=>{const failed=img.getAttribute('src');if(failed!==fallbackIcon){img.dataset.failedIcon=failed;img.setAttribute('src',fallbackIcon);}});}
    if(img.dataset.site!==(url||''))img.dataset.site=url||'';
    let source=data||actions?.favicon?.(url)||fallbackIcon;if(source===img.dataset.failedIcon)source=fallbackIcon;
    if(img.getAttribute('src')!==source)img.setAttribute('src',source);
  };
  const icon=url=>{const img=document.createElement('img');img.className='site-icon';img.alt='';img.setAttribute('aria-hidden','true');img.decoding='async';img.loading='lazy';setIcon(img,url);return img;};
  let lastIconRevision=-1;
  const contents=new Map([["content",$("content")]]), labels=new Map();
  let actions=null,focused=null,pointer=true,latest=null,nativeEditing=false;
  let editing="address",fullscreen=false,homeVisible=true,bookmarkSignature=null,historySignature=null,lastStatusMessage='',statusUntil=0;
  let bookmarkItems=[],historyItems=[],libraryMode="bookmarks",libraryLimit=64,librarySignature=null,webReady=false,fullscreenNoticeUntil=0;
  const setFullscreen=enabled=>{
    if(!enabled){actions?.exitContentFullscreen?.();$("fullscreen-notice").hidePopover?.();$("fullscreen-notice").hidden=true;}
    fullscreen=enabled;document.body.setAttribute("data-fullscreen",String(enabled));
    $("browser-header").hidden=enabled;$("browser-footer").hidden=enabled;
    $("fullscreen-button").textContent=enabled?"Exit fullscreen":"Fullscreen · Options to exit";
  };
  const empty=list=>{while(list.children.length)list.children[0].remove();};
  const siteButton=(item,id)=>{
    const button=document.createElement("button");button.appendChild(icon(item.url));const title=document.createElement('span');title.textContent=item.title||item.url;button.appendChild(title);button.title=item.url;button.dataset.control=id;button.disabled=!webReady;
    button.addEventListener("click",()=>{if(actions?.navigate(item.url))page();});return button;
  };
  const renderBookmarks=()=>{
    const revision=actions?.bookmarkRevision?.(),entries=revision===undefined?actions?.bookmarks?.()||[]:null;
    const signature=revision===undefined?JSON.stringify(entries):revision;if(signature===bookmarkSignature)return;bookmarkSignature=signature;
    bookmarkItems=entries||actions?.bookmarks?.()||[];const list=$("bookmark-list");empty(list);
    for(const [index,item] of bookmarkItems.slice(0,12).entries()){
      const row=document.createElement("div");row.className="bookmark-row";row.appendChild(siteButton(item,"bookmark-"+index));list.appendChild(row);
    }
  };
  const renderHistory=()=>{
    const revision=actions?.historyRevision?.(),entries=revision===undefined?actions?.history?.()||[]:null;
    const signature=revision===undefined?JSON.stringify(entries):revision;if(signature===historySignature)return;historySignature=signature;
    historyItems=entries||actions?.history?.()||[];const list=$("recent-list");empty(list);$("recent-empty").hidden=historyItems.length>0;
    const seen=new Set(),recents=[];
    for(const item of historyItems){try{const url=new URL(item.url),site=url.hostname.replace(/^www\./,'');if(seen.has(site))continue;seen.add(site);recents.push({url:url.origin+'/',title:site});if(recents.length===9)break;}catch(_error){}}
    for(const [index,item] of recents.entries()){
      const row=document.createElement("div");row.className="bookmark-row";row.appendChild(siteButton(item,"recent-"+index));list.appendChild(row);
    }
  };
  const renderLibrary=()=>{
    if($("library-panel").hidden)return;
    const signature=libraryMode+":"+libraryLimit+":"+String(bookmarkSignature)+":"+String(historySignature)+":"+webReady;
    if(signature===librarySignature)return;librarySignature=signature;
    const isHistory=libraryMode==="history",items=isHistory?historyItems:bookmarkItems;
    text($("library-title"),isHistory?"Browsing history":"Bookmarks");
    attribute($("library-history"),"aria-pressed",String(isHistory));attribute($("library-bookmarks"),"aria-pressed",String(!isHistory));
    $("clear-history").hidden=!isHistory;$("clear-history").disabled=!items.length||actions?.historyAvailable?.()===false;
    text($("library-status"),items.length?(isHistory?items.length+" recently visited pages":"Saved websites"):
      isHistory?(actions?.historyAvailable?.()===false?"History storage unavailable.":"No browsing history yet."):"No bookmarks yet. Use the star in the address bar.");
    const list=$("library-list");empty(list);
    for(const [index,item] of items.slice(0,libraryLimit).entries()){
      const row=document.createElement("div");row.className="library-row";
      const link=siteButton(item,"library-site-"+index);link.className="library-link";link.textContent="";
      const title=document.createElement("span"),url=document.createElement("span");title.textContent=item.title||item.url;url.textContent=item.url;url.className="library-url";
      link.appendChild(icon(item.url));link.appendChild(title);link.appendChild(url);row.appendChild(link);
      if(isHistory){const date=document.createElement("span");date.className="library-date";date.textContent=new Date(item.lastVisit).toISOString().slice(0,16).replace("T"," ")+" UTC";row.appendChild(date);}
      else{const remove=document.createElement("button");remove.textContent="Remove";remove.dataset.control="library-remove-"+index;remove.addEventListener("click",()=>{actions?.removeBookmark?.(item.url);renderBookmarks();librarySignature=null;renderLibrary();});row.appendChild(remove);}
      list.appendChild(row);
    }
    $("library-more").hidden=items.length<=libraryLimit;
  };
  const showLibrary=kind=>{
    if(fullscreen)setFullscreen(false);closePanels();libraryMode=kind;libraryLimit=64;librarySignature=null;
    $("library-panel").hidden=false;renderBookmarks();renderHistory();renderLibrary();focus(visibleControls()[0]);
  };
  const rangeVisual=(id,value)=>{const input=$(id),min=Number(input.min||input.getAttribute('min')),max=Number(input.max||input.getAttribute('max'));
    const percent=Math.max(0,Math.min(100,(value-min)*100/(max-min))),style=$(id+'-shell').style;
    // CSSOM property writes keep the chrome CSP intact (no inline style attr).
    if(Number.isFinite(percent)&&style.getPropertyValue('--fill')!==percent+'%')style.setProperty('--fill',percent+'%');};
  const settingsTab=kind=>{
    const controls=kind==='controls';$('settings-general').hidden=controls;$('settings-controls').hidden=!controls;
    attribute($('settings-general-tab'),'aria-selected',String(!controls));attribute($('settings-controls-tab'),'aria-selected',String(controls));
  };
  const renderSettings=()=>{
    const settings=actions?.settings?.()||{searchEngine:"google",cursorSpeed:1};
    for(const engine of ["google","duckduckgo","bing"])$("engine-"+engine).setAttribute("aria-pressed",String(settings.searchEngine===engine));
    for(const scheme of ['system','light','dark'])attribute($('color-'+scheme),'aria-pressed',String((settings.colorScheme||'system')===scheme));
    $("cursor-speed").value=String(settings.cursorSpeed*100);$("cursor-speed-label").textContent=settings.cursorSpeed+"×";
    $("default-zoom").value=String(settings.defaultZoom||100);text($("default-zoom-label"),(settings.defaultZoom||100)+'%');
    rangeVisual('cursor-speed',settings.cursorSpeed*100);rangeVisual('default-zoom',settings.defaultZoom||100);
    attribute($('diagnostics-toggle'),'aria-checked',String(settings.diagnostics===true));
    text($('diagnostics-toggle'),'Save diagnostic logs: '+(settings.diagnostics===true?'On':'Off'));
  };
  const saveSettings=changes=>{const saved=actions?.saveSettings?.(changes)===true;renderSettings();$("settings-status").textContent=saved?"Saved to your profile.":"Unable to save settings.";};
  const panels=["menu-panel","diagnostic-panel","settings-panel","library-panel"];
  const visibleControls=()=>[...document.querySelectorAll("[data-control]")].filter(e=>!e.disabled&&e.getClientRects().length&&
    (!$("menu-panel").hidden?$("menu-panel").contains(e):
      !$("diagnostic-panel").hidden?$("diagnostic-panel").contains(e):!$("settings-panel").hidden?$("settings-panel").contains(e):!$("library-panel").hidden?$("library-panel").contains(e):true));
  const setPointer=enabled=>{pointer=enabled;actions?.pointer(enabled);$("focus-hint").textContent=enabled?
    "Cross click/type · R3 middle-click · Right stick scroll · Square address · L1/R1 tabs · R2/L2 back/forward · Circle Escape · Options menu":"D-pad focus · Cross activate · Circle page · Options + Circle exit";};
  const focus=e=>{focused?.removeAttribute("data-focused");focused=e;if(e){setPointer(false);e.setAttribute("data-focused","true");e.focus();}};
  const closePanels=()=>{for(const id of panels)$(id).hidden=true;};
  const page=()=>{closePanels();if(latest)$("address").value=latest.location===OrbisFoxShellModel.HOME?"":latest.location;focused?.removeAttribute("data-focused");focused=null;setPointer(true);api.contentElement().focus();};
  const keyboardHint=()=>actions?.keyboardConfirm?.()===2?"PS4 keyboard: Circle selects/confirms · Cross cancels":
    actions?.keyboardConfirm?.()===1?"PS4 keyboard: Cross selects/confirms · Circle cancels":"PS4 keyboard: follow the dialog's confirm/cancel labels";
  const edit=(kind="address",text=$("address").value)=>{
    if(nativeEditing)return;if(fullscreen)setFullscreen(false);closePanels();editing=kind;
    if(kind==="text"?actions?.openTextKeyboard?.(text):actions?.openKeyboard?.(text)){
      nativeEditing=true;setPointer(false);$("focus-hint").textContent=keyboardHint();return;
    }
    if(kind==="text")actions?.cancelText();page();$("status").textContent="PS4 keyboard unavailable.";
  };
  const find=(backwards=false)=>{const value=$("find-text").value;if(!value.trim()){text($("find-status"),'Enter text to find');return;}const found=actions?.find?.(value,backwards)===true;text($("find-status"),found?'Match found':'No match found');};
  const showFind=()=>{if(fullscreen)setFullscreen(false);page();$("find-bar").hidden=false;edit('find',$("find-text").value);};
  const closeFind=()=>{$("find-bar").hidden=true;page();};
  const go=value=>{if(!actions)return;if(editing==='find'){$("find-text").value=value;page();find();return;}const okay=editing==="text"?actions.commitText(value):editing==="search"?actions.search(value):actions.navigate(value);if(okay)page();};
  const cancel=()=>{if(editing==="text")actions?.cancelText();page();};
  const escape=()=>{if(fullscreen){setFullscreen(false);page();}else if(panels.some(id=>!$(id).hidden))cancel();else if(!$("find-bar").hidden)closeFind();else{page();actions?.escape?.();}};
  const menu=()=>{if(fullscreen){setFullscreen(false);page();return;}const open=!$("menu-panel").hidden;closePanels();if(open){page();return;}$("menu-panel").hidden=false;focus(visibleControls()[0]);};
  const command=name=>{
    if(!actions||nativeEditing)return;
    if(name==="fullscreen"){closePanels();setFullscreen(!fullscreen);page();}
    else if(name==="bookmark"){actions.toggleBookmark?.();renderBookmarks();}
    else if(name==="bookmarks"||name==="history")showLibrary(name);
    else if(name==="clear-history"){if(actions?.clearHistory?.()){libraryLimit=64;renderHistory();renderLibrary();}}
    else if(name==="library-more"){libraryLimit+=64;renderLibrary();}
    else if(name==='find')showFind();
    else if(name==='find-edit')edit('find',$("find-text").value);
    else if(name==='find-next'||name==='find-previous')find(name==='find-previous');
    else if(name==='find-close')closeFind();
    else if(name==='zoom-out'||name==='zoom-in'||name==='zoom-reset')actions.zoom?.(name==='zoom-reset'?0:name==='zoom-out'?-10:10);
    else if(name==="settings"){closePanels();settingsTab('general');renderSettings();$("settings-status").textContent="Changes are saved automatically.";$("settings-panel").hidden=false;focus(visibleControls()[0]);}
    else if(name==='settings-general'||name==='settings-controls'){settingsTab(name==='settings-controls'?'controls':'general');focus($(name+'-tab'));}
    else if(name==='diagnostics-toggle'){
      const next=actions.settings().diagnostics!==true,okay=actions?.setDiagnostics?.(next)===true;renderSettings();
      text($('settings-status'),okay?(next?'Diagnostics enabled. Logs may contain visited addresses.':'Diagnostics off. Existing logs are kept until cleared.'):'Unable to change diagnostics.');
    }
    else if(name==='diagnostics-clear'){
      try{const result=actions.clearDiagnosticLogs();renderSettings();text($('settings-status'),'Removed '+result.removed+' diagnostic files. Diagnostics off.'+(result.retained?' Other files were kept.':''));}
      catch(_error){renderSettings();text($('settings-status'),'Unable to clear all logs. Your profile was not changed.');}
    }
    else if(name.startsWith("engine-"))saveSettings({searchEngine:name.slice(7)});
    else if(['color-system','color-light','color-dark'].includes(name))saveSettings({colorScheme:name.slice(6)});
    else if(name==="home-address")edit();
    else if(name==="home-go"){
      const value=$("home-search").value.trim();if(!value)return;
      if(actions.search(value))page();
    }
    else if(name==="page"||name==="dismiss-diagnostics")page();
    else if(name==="diagnostics"){closePanels();$("diagnostic-panel").hidden=false;focus(visibleControls()[0]);}
    else if(name==="exit")actions.exit();
    else if(name==="new-tab"){if(actions.newTab())page();}
    else if(name==="close-tab"){actions.closeTab();page();}
    else if(name==="home"&&actions.navigate("home"))page();
  };
  $("find-text").addEventListener('click',()=>command('find-edit'));
  $("find-text").addEventListener('input',()=>find());
  $("find-text").addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();find(!!event.shiftKey);}else if(event.key==='Escape'){event.preventDefault();closeFind();}});
  document.addEventListener('mousedown',event=>{if(!$("menu-panel").hidden&&!$("menu-panel").contains(event.target)&&!$("menu-button").contains(event.target))page();});
  $("cursor-speed").addEventListener("input",()=>{const value=Number($("cursor-speed").value);$("cursor-speed-label").textContent=(value/100)+"×";rangeVisual('cursor-speed',value);});
  $("cursor-speed").addEventListener("change",()=>saveSettings({cursorSpeed:Number($("cursor-speed").value)/100}));
  $("default-zoom").addEventListener("input",()=>{const value=Number($("default-zoom").value);text($("default-zoom-label"),value+'%');rangeVisual('default-zoom',value);});
  $("default-zoom").addEventListener("change",()=>saveSettings({defaultZoom:Number($("default-zoom").value)}));
  $("back").addEventListener("click",()=>actions?.back());$("forward").addEventListener("click",()=>actions?.forward());
  $("reload").addEventListener("click",()=>actions?.reload());$("home").addEventListener("click",()=>command("home"));
  $("menu-button").addEventListener("click",menu);
  $("address").addEventListener("click",()=>edit());
  $("home-search").addEventListener("click",()=>edit("search",$("home-search").value));
  $("home-search").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();command("home-go");}});
  $("tab").addEventListener("click",()=>{actions?.selectTab("content");page();});
  $("tab").addEventListener('auxclick',event=>{if(event.button===1&&!nativeEditing){event.preventDefault();actions?.closeTab('content');page();}});
  $("new-tab").addEventListener("click",()=>command("new-tab"));
  $("first-close-tab").addEventListener("click",()=>{if(!nativeEditing){actions?.closeTab("content");page();}});
  $("address").addEventListener("keydown",event=>{
    if(event.key==="Enter"){event.preventDefault();editing="address";go($("address").value);}if(event.key==="Escape"){event.preventDefault();cancel();}});
  for(const button of document.querySelectorAll("[data-command]"))button.addEventListener("click",()=>command(button.dataset.command));
  let selected="content";
  const api=Object.freeze({ready:true,
    bind(callbacks){if(actions)throw new Error("Shell already bound");actions=callbacks;},
    setContentFullscreen(enabled,origin=''){
      if(enabled){closePanels();setFullscreen(true);page();fullscreenNoticeUntil=Date.now()+5000;
        text($('fullscreen-notice'),String(origin).slice(0,240)+' — Fullscreen · Options or Circle to exit');$('fullscreen-notice').hidden=false;$('fullscreen-notice').showPopover?.();
      }else setFullscreen(false);
    },
    contentElement(){return contents.get(selected);},
    createContent(id,openWindowInfo=null){
      if(contents.has(id))throw new Error("Duplicate content tab ID");
      if(contents.size>=OrbisFoxShellModel.MAX_TABS)throw new Error("Three real-tab limit reached; close a tab first");
      const e=document.createElementNS("http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul","browser");
      e.id=id;e.hidden=true;e.setAttribute("type","content");e.setAttribute("flex","1");if(openWindowInfo)e.openWindowInfo=openWindowInfo;
      $("content-deck").appendChild(e);contents.set(id,e);return e;
    },
    selectContent(id){
      if(!contents.has(id))throw new Error("Unknown real content tab");if(selected===id)return;selected=id;
      for(const [key,e] of contents){if(e.hidden!==(key!==id))e.hidden=key!==id;const bc=e.frameLoader?.browsingContext;if(bc)bc.isActive=key===id;}
    },
    removeContent(id){if(!contents.has(id))return;const e=contents.get(id);e.remove();contents.delete(id);},
    renderTabs(tabs,active){
      selected=active;const alive=new Set(tabs.map(t=>t.id));
      for(const [id,label] of labels)if(!alive.has(id)){label.container.remove();labels.delete(id);}
      for(const tab of tabs){
        let label=labels.get(tab.id);
        if(!label){
          if(tab.id==="content")label={container:$("first-tab"),button:$("tab"),title:$("tab-title"),dot:$("tab-dot"),close:$("first-close-tab")};
          else{
            const container=document.createElement("div");container.className="tab-item";
            const button=document.createElement("button");button.className="tab-button";button.dataset.control="tab-"+tab.id;button.setAttribute("role","tab");
            const dot=icon(tab.location),title=document.createElement("span");title.className="tab-title";button.appendChild(dot);button.appendChild(title);
            const close=document.createElement("button");close.className="tab-close";close.dataset.control="close-"+tab.id;close.setAttribute("aria-label","Close tab");
            const svg=document.createElementNS("http://www.w3.org/2000/svg","svg"),path=document.createElementNS("http://www.w3.org/2000/svg","path");
            svg.setAttribute("class","icon");svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");path.setAttribute("d","M6 6l12 12M18 6L6 18");svg.appendChild(path);close.appendChild(svg);
            button.addEventListener("click",()=>{if(!nativeEditing){actions.selectTab(tab.id);page();}});
            button.addEventListener('auxclick',event=>{if(event.button===1&&!nativeEditing){event.preventDefault();actions.closeTab(tab.id);page();}});
            close.addEventListener("click",()=>{if(!nativeEditing){actions.closeTab(tab.id);page();}});
            container.appendChild(button);container.appendChild(close);$("tab-buttons").appendChild(container);label={container,button,title,dot,close};
          }labels.set(tab.id,label);
        }
        label.close.disabled=tabs.length<=1;setIcon(label.dot,tab.location,tab.favicon);text(label.title,tab.title||"Untitled");if(label.dot.dataset.busy!==String(!!tab.busy))label.dot.dataset.busy=String(!!tab.busy);attribute(label.button,"aria-selected",String(tab.id===active));
      }
      $("new-tab").disabled=tabs.length>=OrbisFoxShellModel.MAX_TABS;
      $("close-tab").disabled=tabs.length<=1;
    },
    nativeChromeScene(){
      if(!actions||!labels.has(selected))return null;
      const ids=[...labels.keys()],controls=[];
      const add=(element,code)=>{if(!element?.getBoundingClientRect)return;const r=element.getBoundingClientRect();
        const x=Math.round(r.left),y=Math.round(r.top),w=Math.round(r.width),h=Math.round(r.height);
        if(!element.hidden&&element.getClientRects().length&&x>=0&&y>=0&&w>0&&h>0&&x+w<=1280&&(code>=43?y>=650&&y+h<=720:y+h<=104))controls.push([code,x,y,w,h,element.disabled?0:1].join(',')+';');};
      if(!fullscreen){for(const [name,code] of [['back',1],['forward',2],['reload',3],['home',4],['address',5],['menu-button',6],['bookmark-button',7],['new-tab',8]])add($(name),code);
        for(const [i,id] of ids.entries()){add(labels.get(id).button,10+i);add(labels.get(id).close,20+i);}}
      if(!$("find-bar").hidden)for(const [name,code] of [['find-text',43],['find-previous',44],['find-next',45],['find-close',46]])add($(name),code);
      return [2,fullscreen?1:0,webReady?1:0,selected,...Array.from({length:3},(_,i)=>ids[i]||''),actions.zoomValue?.()||100].join('|')+'|'+controls.join('');
    },
    nativeCommand(wire){
      if(typeof wire!=='string'||nativeEditing)return false;const match=/^(\d{1,2}):([a-z0-9-]*)$/.exec(wire);if(!match)return false;
      const code=Number(match[1]),target=match[2];
      if(code>=10&&code<=12){if(!contents.has(target))return false;actions.selectTab(target);page();}
      else if(code>=20&&code<=22||code===35){if(!contents.has(target))return false;actions.closeTab(target);page();}
      else if(code===1)actions.back();else if(code===2)actions.forward();else if(code===3)actions.reload();
      else if(code===4){actions.navigate('home');page();}else if(code===5)edit();else if(code===7)command('bookmark');else if(code===8){if(!actions.newTab())return false;page();}
      else if(code>=30&&code<=34)command(['fullscreen','bookmark','bookmarks','history','settings'][code-30]);else if(code===36)command('exit');else if(code===38)command('find');else if(code===39)command('zoom-out');else if(code===40)command('zoom-in');else if(code===41)command('zoom-reset');else if(code===42)escape();else if(code>=43&&code<=46)command(['find-edit','find-previous','find-next','find-close'][code-43]);else return false;
      return true;
    },
    canScroll(){return !homeVisible&&!nativeEditing&&panels.every(id=>$(id).hidden);},
    scrollShell(dx,dy,x,y){
      const id=panels.find(id=>!$(id).hidden)||(homeVisible?"home-screen":null);if(!id||nativeEditing)return false;
      const target=$(id),rect=target.getBoundingClientRect();if(x<rect.left||x>=rect.right||y<rect.top||y>=rect.bottom)return false;
      target.scrollBy(dx,dy);return true;
    },
    isEditing(){return nativeEditing;},
    editText(text){edit("text",text);},
    finishAddressKeyboard(status,text){
      if(!nativeEditing)return;nativeEditing=false;
      if(status===2&&typeof text==="string"&&text.length<=512)go(text);
      else cancel();
    },
    pointerMoved(){if(nativeEditing||pointer)return;setPointer(true);focused?.removeAttribute("data-focused");focused=null;},
    control(name){
      if(nativeEditing)return;
      if(["left","right","up","down"].includes(name)){
        if(focused===$("default-zoom")&&(name==="left"||name==="right")){saveSettings({defaultZoom:Math.max(50,Math.min(200,Number(focused.value)+(name==='left'?-10:10)))});return;}
        if(focused===$("cursor-speed")&&(name==="left"||name==="right")){
          const value=Math.max(25,Math.min(300,Number(focused.value)+(name==="left"?-25:25)));saveSettings({cursorSpeed:value/100});return;
        }
        const controls=visibleControls();if(!controls.length)return;const index=controls.indexOf(focused);
        const delta=name==="left"||name==="up"?-1:1;
        focus(controls[index<0?0:(index+delta+controls.length)%controls.length]);
      }else if(name==="cross"&&!pointer&&focused)focused.click();
      else if(name==="address")edit();else if(name==="cancel")escape();else if(name==="menu")menu();else if(name==="reload")actions?.reload();
      else if(name==="previousTab"||name==="nextTab"){if(!api.isEditing()){actions?.relativeTab(name==="previousTab"?-1:1);page();}}
    },
    update(state,diagnostics,gates){
      latest=state;homeVisible=state.location===OrbisFoxShellModel.HOME;$("home-screen").hidden=!homeVisible;
      $("home-go").disabled=!gates.web;$("home-search").disabled=!gates.web;
      $("bookmark-button").disabled=!gates.bookmarksAvailable||!/^https?:\/\//i.test(state.location);
      if(webReady!==!!gates.web){webReady=!!gates.web;for(const list of [$("bookmark-list"),$("recent-list")])for(const button of list.querySelectorAll("button"))button.disabled=!webReady;}
      renderBookmarks();renderHistory();renderLibrary();
      const revision=actions?.faviconRevision?.()??0;if(revision!==lastIconRevision){lastIconRevision=revision;for(const image of document.querySelectorAll('.site-icon'))setIcon(image,image.dataset.site);}
      const bookmarked=bookmarkItems.some(item=>item.url===state.location);attribute($("bookmark-button"),'aria-pressed',String(bookmarked));attribute($("bookmark-button"),'aria-label',bookmarked?'Remove this bookmark':'Bookmark this page');$("bookmark-button").title=bookmarked?'Remove this bookmark':'Bookmark this page';
      text($("zoom-value"),(actions.zoomValue?.()||100)+'%');
      $("back").disabled=!state.canBack;$("forward").disabled=!state.canForward;
      if($("reload").dataset.busy!==String(!!state.busy))$("reload").dataset.busy=String(!!state.busy);$("reload").title=state.busy?"Stop":"Reload";attribute($("reload"),"aria-label",state.busy?"Stop":"Reload");
      if(!api.isEditing()&&document.activeElement!==$("address"))$("address").value=homeVisible?"":state.location;
      text($("security"),homeVisible?"HOME":state.location.startsWith("file:")?"LOCAL":state.location.startsWith("https:")?"HTTPS":"HTTP");
      if(lastStatusMessage!==state.message){lastStatusMessage=state.message;if(/^(Found:|Not found:)/.test(state.message))statusUntil=Date.now()+3000;}
      if(!$("fullscreen-notice").hidden&&Date.now()>=fullscreenNoticeUntil){$("fullscreen-notice").hidePopover?.();$("fullscreen-notice").hidden=true;}
      $("browser-footer").hidden=fullscreen||!(state.busy||state.error||Date.now()<statusUntil);text($("status"),state.message);if($("status").dataset.error!==String(!!state.error))$("status").dataset.error=String(!!state.error);
      text($("diagnostic-text"),diagnostics);
    },
    destroy(){$("find-bar").hidden=true;setFullscreen(false);actions=null;nativeEditing=false;closePanels();focused=null;labels.clear();contents.clear();}
  });
  window.OrbisFoxShell=api;
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initializeOrbisFoxShell,{once:true});
else initializeOrbisFoxShell();
