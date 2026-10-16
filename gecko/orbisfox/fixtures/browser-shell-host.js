/* Privileged supervisor. Real bounded docshell tabs, no injected content host. */
// Passive icon data only. Same-origin anonymous channels use a web principal,
// never the shell principal; chrome CSP stays chrome:/data: images only.
function createOrbisLogCleaner(Cc,Ci) {
  const runID=/^run-(?:[0-9a-f]{16}-){3}[0-9a-f]{16}$/;
  const known=/^(?:startup-layout\.log|platform-layout\.log|gecko-heartbeat\.log|stdio-lock-probe\.log|heap-audit\.log|heap-diagnostics\.bin|gecko-(?:first|fixture)-frame\.bgra|gecko-load\.log(?:[._-][A-Za-z0-9._-]+)?)$/;
  return ()=>{
    const root=Cc['@mozilla.org/file/local;1'].createInstance(Ci.nsIFile);root.initWithPath('/data/orbisfox');
    let removed=0,retained=0,visited=0;
    const safeDirectory=file=>file.exists()&&!file.isSymlink()&&file.isDirectory();
    if(!root.exists())return {removed,retained};
    if(!safeDirectory(root))throw Error('Unsafe diagnostic directory');
    const erase=(file,metadata=false)=>{
      if(++visited>8192)throw Error('Diagnostic cleanup limit reached; run cleanup again');
      if(file.isSymlink()||!file.isFile()||!(known.test(file.leafName)||(metadata&&file.leafName==='run-meta.json'))){++retained;return;}
      file.remove(false);++removed;
    };
    for(const entry of root.directoryEntries){const file=entry.QueryInterface(Ci.nsIFile);
      if(known.test(file.leafName))erase(file);
      else if(file.leafName==='runs'){
        if(!safeDirectory(file)){++retained;continue;}
        for(const item of file.directoryEntries){const run=item.QueryInterface(Ci.nsIFile);
          if(!runID.test(run.leafName)||!safeDirectory(run)){++retained;continue;}
          for(const child of run.directoryEntries)erase(child.QueryInterface(Ci.nsIFile),true);
          try{run.remove(false);}catch(_error){++retained;}
        }
      }
    }
    return {removed,retained};
  };
}
function createOrbisFaviconCache(Cc,Ci,io,ssm,host,allowed) {
  const entries=new Map(),waiting=[],requests=new Set();let revision=0,closed=false,running=0;
  let store=null;try{store=Cc['@mozilla.org/browser/favicon-service;1'].getService(Ci.nsIFaviconService);}catch(_){}
  const page=text=>{const uri=io.newURI(text);if(!['http','https'].includes(uri.scheme)||uri.userPass||uri.spec.length>2048)throw Error('Invalid favicon page');return uri;};
  const raster=bytes=>{
    if(bytes.length>=24&&bytes.slice(0,8).join(',')==='137,80,78,71,13,10,26,10'){
      const n=i=>bytes[i]*16777216+bytes[i+1]*65536+bytes[i+2]*256+bytes[i+3];
      return n(16)>0&&n(16)<=128&&n(20)>0&&n(20)<=128?'image/png':null;
    }
    if(bytes.length>=22&&bytes[0]===0&&bytes[1]===0&&bytes[2]===1&&bytes[3]===0){
      const count=bytes[4]+bytes[5]*256,n=i=>bytes[i]+bytes[i+1]*256+bytes[i+2]*65536+bytes[i+3]*16777216;
      if(!count||count>16||bytes.length<6+count*16)return null;let pixels=0;
      for(let i=0;i<count;++i){const at=6+i*16,w=bytes[at]||256,h=bytes[at+1]||256,size=n(at+8),offset=n(at+12);
        if(w>128||h>128||(pixels+=w*h)>65536||size<24||offset<6+count*16||offset+size>bytes.length)return null;
        const payload=bytes.slice(offset,offset+size);
        if(payload[0]===137&&raster(payload)==='image/png')continue;
        const header=n(offset);if(![40,108,124].includes(header)||size<header||n(offset+4)!==w||n(offset+8)!==h*2||n(offset+16)!==0)return null;
      }return 'image/x-icon';
    }
    return null;
  };
  const publish=(entry,data)=>{if(closed||typeof data!=='string'||data.length>50000||!/^data:image\/(png|x-icon|vnd\.microsoft\.icon);base64,[A-Za-z0-9+/=]+$/.test(data))return;entry.data=data;++revision;};
  const pump=()=>{
    if(closed)return;
    while(running<2&&waiting.length){const entry=waiting.shift();++running;
      (async()=>{
        try{const cached=await store?.getFaviconForPage(entry.page,16);if(cached?.dataURI?.spec){publish(entry,cached.dataURI.spec);if(entry.data)return;}}catch(_){}
        if(closed||!allowed())return;
        await new Promise(resolve=>{
          let channel=null,timer=null,bytes=[],done=false;
          const finish=()=>{if(done)return;done=true;timer?.cancel();if(channel)requests.delete(channel);resolve();};
          try{
            const principal=ssm.createContentPrincipal(entry.page,{});
            channel=io.newChannelFromURI(entry.icon,null,principal,null,Ci.nsILoadInfo.SEC_REQUIRE_SAME_ORIGIN_INHERITS_SEC_CONTEXT,Ci.nsIContentPolicy.TYPE_IMAGE);
            channel.loadFlags|=Ci.nsIRequest.LOAD_ANONYMOUS;requests.add(channel);
            timer=Cc['@mozilla.org/timer;1'].createInstance(Ci.nsITimer);timer.initWithCallback(()=>{channel.cancel(0x804b0002);finish();},5000,Ci.nsITimer.TYPE_ONE_SHOT);
            channel.asyncOpen({
              onStartRequest(request){if(channel.contentLength>32768)request.cancel(0x804b0002);},
              onDataAvailable(request,input,offset,count){if(bytes.length+count>32768){request.cancel(0x804b0002);return;}
                const stream=Cc['@mozilla.org/binaryinputstream;1'].createInstance(Ci.nsIBinaryInputStream);stream.setInputStream(input);bytes.push(...stream.readByteArray(count));},
              onStopRequest(request,status){try{if(!done&&!closed&&(status>>>0)===0){const mime=raster(bytes);if(mime){
                const base64=ChromeUtils.base64URLEncode(Uint8Array.from(bytes),{pad:true}).replace(/-/g,'+').replace(/_/g,'/');
                const data='data:'+mime+';base64,'+base64;publish(entry,data);
                store?.setFaviconForPage(entry.page,entry.icon,io.newURI(data)).catch(()=>{});
              }}}catch(error){host.log('Favicon decode/cache: '+String(error).slice(0,100));}finally{finish();}},
              QueryInterface:ChromeUtils.generateQI(['nsIStreamListener','nsIRequestObserver'])});
          }catch(_){finish();}
        });
      })().catch(()=>{}).finally(()=>{--running;pump();});
    }
  };
  const request=(text,document=null)=>{
    if(closed||!allowed())return null;
    try{const uri=page(text),key=uri.spec.replace(/#.*$/,'');
      if(document&&(document.nodePrincipal?.isSystemPrincipal!==false||document.readyState==='loading'||document.documentURI?.replace(/#.*$/,'')!==key))return null;let entry=entries.get(key);if(entry)return entry.data||null;
      if(entries.size>=128)return null;
      let icon=io.newURI(uri.prePath+'/favicon.ico');
      if(document?.nodePrincipal?.isSystemPrincipal===false)try{const link=document.querySelector('link[rel~="icon"]');if(link?.href){const candidate=page(link.href);if(candidate.prePath===uri.prePath)icon=candidate;}}catch(_){}
      entry={page:io.newURI(key),icon,data:null};entries.set(key,entry);waiting.push(entry);pump();return null;
    }catch(_){return null;}
  };
  return {request,get revision(){return revision;},close(){closed=true;waiting.length=0;for(const request of requests)request.cancel(0x804b0002);requests.clear();entries.clear();}};
}
// Gecko dispatches this chrome-only event for auxiliary link navigation. The
// original trusted native mouse event stays intact; no synthetic page clicks.
function createOrbisMiddleLinkHandler({sourceTab,linkData,checkedURI,ssm,Cc,Ci,popup,log}) {
  let failures=0;
  return wrapper=>{
    const event=wrapper?.sourceEvent;
    if(wrapper?.isTrusted!==true||event?.isTrusted!==true||event.button!==1||event.defaultPrevented)return false;
    try{
      const document=event.composedTarget?.ownerDocument;
      if(document?.nodePrincipal?.isSystemPrincipal!==false||!sourceTab(document))return false;
      const data=linkData(event);if(!data?.[0]||data[2]?.isSystemPrincipal!==false)return false;
      const [href,node,principal]=data,uri=checkedURI(href);
      if(!['http','https'].includes(uri.scheme))return false;
      ssm.checkLoadURIStrWithPrincipal(principal,uri.spec,Ci.nsIScriptSecurityManager.STANDARD);
      const referrer=Cc['@mozilla.org/referrer-info;1'].createInstance(Ci.nsIReferrerInfo);
      if(node)referrer.initWithElement(node);else referrer.initWithDocument(document);
      popup(uri,null,Ci.nsIBrowserDOMWindow.OPEN_NEWTAB_BACKGROUND,0,principal,document.policyContainer,true,referrer);
      event.preventMultipleActions?.();event.preventDefault();wrapper.preventDefault();
      log('Browser link: trusted middle-click opened bounded background tab');return true;
    }catch(error){if(failures++<8)log('Browser middle-link: '+String(error).slice(0,180));return false;}
  };
}
// Opt-in, bounded observations only. No page patching, network interception,
// message contents, query strings, or privileged objects exposed to content.
function createOrbisPageNetworkObserver(host,owns) {
  const seen=new WeakSet();let documents=0;
  return (document,tab)=>{
    if(host.diagnosticsEnabled!==true||tab.closed||!document||seen.has(document)||documents>=64)return;
    try{
      if(document.nodePrincipal?.isSystemPrincipal!==false||!owns(document,tab))return;
      const view=document.defaultView;if(!view||typeof view.URL!=='function')return;
      const parseURL=view.URL,uri=new parseURL(document.documentURI);if(!['http:','https:'].includes(uri.protocol))return;
      seen.add(document);++documents;
      const address=(uri.origin+uri.pathname).slice(0,320);let reports=0;
      const emit=(kind,details)=>{if(host.diagnosticsEnabled!==true||tab.closed||reports++>=12)return;host.log('Browser frame networking: '+JSON.stringify({tab:tab.id,uri:address,kind,...details}));};
      emit('capabilities',{top:view===view.top,webSocket:typeof view.WebSocket==='function',fetch:typeof view.fetch==='function',readableStream:typeof view.ReadableStream==='function',webAssembly:typeof view.WebAssembly==='object',worker:typeof view.Worker==='function',textDecoder:typeof view.TextDecoder==='function',secure:view.isSecureContext===true,userAgent:String(view.navigator?.userAgent||'').slice(0,240)});
      view.addEventListener?.('error',event=>{if(event.isTrusted!==true)return;let file='';try{const url=new parseURL(event.filename);file=(url.origin+url.pathname).slice(0,240);}catch(_){}
        const message=typeof event.message==='string'?event.message.slice(0,1000).replace(/https?:\/\/[^\s"'<>()]+/g,value=>{try{const url=new parseURL(value);return url.origin+url.pathname;}catch(_){return '[URL]';}}).slice(0,240):'';
        emit('script-error',{message,file,line:event.lineno||0});},true);
      view.addEventListener?.('unhandledrejection',event=>{if(event.isTrusted===true)emit('unhandled-rejection',{reasonType:typeof event.reason});},true);
    }catch(_){}
  };
}
function createOrbisFullscreenController(win,active,ui,io) {
  const handle=event=>{if(event.isTrusted!==true)return;
    try{const tab=active(),document=tab?.nav?.document,target=event.originalTarget||event.target;
      const source=target?.nodeType===9?target:target?.ownerDocument;
      if(!tab||tab.closed||!source||!(source===win.document||source.defaultView?.top===tab.element.contentWindow))return;
      if(event.type==='MozDOMFullscreen:Entered'){
        if(document?.nodePrincipal?.isSystemPrincipal!==false||!document.fullscreenElement)return;
        // The fullscreen element may be a cross-origin iframe. Show the
        // innermost requesting document's origin, not the embedding site's.
        let leaf=document;
        for(let depth=0;depth<16;++depth){const child=leaf.fullscreenElement?.contentDocument;
          if(!child||child===leaf||!child.fullscreenElement)break;
          if(child.nodePrincipal?.isSystemPrincipal!==false||child.defaultView?.top!==tab.element.contentWindow)return;
          leaf=child;
        }
        if(leaf.fullscreenElement?.contentDocument?.fullscreenElement){ui.setContentFullscreen(true,'Embedded website');return;}
        const uri=leaf.nodePrincipal.URI||io.newURI(leaf.documentURI);if(!['http','https'].includes(uri.scheme))return;
        ui.setContentFullscreen(true,uri.scheme+'://'+uri.asciiHostPort);
      }else if(!document?.fullscreenElement)ui.setContentFullscreen(false);
    }catch(_){}
  };
  for(const type of ['MozDOMFullscreen:Entered','MozDOMFullscreen:Exited'])win.addEventListener(type,handle,true);
  return ()=>{for(const type of ['MozDOMFullscreen:Entered','MozDOMFullscreen:Exited'])win.removeEventListener(type,handle,true);};
}
function runOrbisFoxBrowserShell(Cc,Ci,host,io,tm,ssm,profile) {
  const CHROME="chrome://orbisfox/content/browser.xhtml",timer=Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  let chrome=null,ui=null,alive=true,network=null,https=null,ticks=0,serial=0,active=null,controls=null,middleLink=null,removeFullscreen=null;
  let keyboardPending=null,textTarget=null,scrollFailures=0,lastScroll="",scrollReports=0;
  let lastX=host.cursorX,lastY=host.cursorY,lastButtons=0,lastDiagnostics="",diagnosticText="",lastNativeScene="";
  const tabs=[],started=Date.now();let tabMutation=false,bookmarks=null,history=null,settings=null,settingsAvailable=false;
  let closedTabs=null,lastSecurity=null,pendingSession=null,webWasReady=false,lastSession=null,sessionFailures=0;
  const browserPrefs=()=>Cc["@mozilla.org/preferences-service;1"].getService(Ci.nsIPrefService);
  // Remember identity, not the old document/window graph. WeakMap keys do not
  // keep previous pages alive after Gecko releases their history/cache owners.
  const documentIDs=new WeakMap(),resourcesObserved=new WeakSet();let documentSerial=0;
  const documentID=document=>{if(!document)return 0;let id=documentIDs.get(document);if(!id){id=++documentSerial;documentIDs.set(document,id);}return id;};
  // Explicit destination makes nsIPrefService save synchronously (null queues
  // an asynchronous save and can even succeed without an initialized file).
  const savePreferences=service=>{
    if(profile?.snapshot().ok!==true)throw Error("Preferences require a persistent profile");
    const directory=Cc["@mozilla.org/file/directory_service;1"].getService(Ci.nsIProperties).get("ProfD",Ci.nsIFile);
    const file=directory.clone();file.append("prefs.js");service.savePrefFile(file);
  };
  const initializeSettings=()=>{
    settings=new OrbisFoxShellModel.Settings();
    try{
      const service=Cc["@mozilla.org/preferences-service;1"].getService(Ci.nsIPrefService),branch=service.getBranch("orbisfox.browser."),root=service.getBranch("");
      // Gecko's content-only override updates real prefers-color-scheme media
      // queries (including existing documents), without recoloring chrome or
      // injecting page CSS. Keep the profile transaction/rollback intact.
      // Global Privacy Control sends Sec-GPC and navigator.globalPrivacyControl
      // through Gecko's own implementation; nothing is injected into pages.
      const apply=next=>{root.setIntPref("layout.css.prefers-color-scheme.content-override",{dark:0,light:1,system:2}[next.colorScheme]);
        root.setBoolPref("privacy.globalprivacycontrol.enabled",next.globalPrivacyControl===true);
        host.setCursorSpeed(next.cursorSpeed);};
      settings=new OrbisFoxShellModel.Settings(branch.getStringPref("settings","{}"),(serialized,next)=>{
        if(profile?.snapshot().ok!==true)throw Error("Settings require a persistent profile");
        const previous=branch.getStringPref("settings","{}"),oldSettings=settings.snapshot();
        try{branch.setStringPref("settings",serialized);apply(next);savePreferences(service);}
        catch(error){branch.setStringPref("settings",previous);try{apply(oldSettings);savePreferences(service);}catch(_rollbackError){}throw error;}
      });
      apply(settings.snapshot());settingsAvailable=true;
      if(settings.snapshot().restoreSession)pendingSession=OrbisFoxShellModel.sessionURLs(branch.getStringPref("session","[]"));
    }catch(error){host.log("Browser UI: settings unavailable: "+String(error).slice(0,160));}
  };
  // "Open previous tabs": persist open web tabs only while the option is on,
  // and only once loads settle (not on every progress notification).
  const saveSession=(force=false)=>{
    if(!settingsAvailable||(!force&&sessionFailures>=4))return;
    // A loading tab is saved by the address it is loading. Entries stay
    // within the limits sessionURLs accepts so one long URL cannot void all.
    const urls=[];if(settings.snapshot().restoreSession)for(const tab of tabs){
      const url=tab.model.busy?tab.model.requested:tab.model.location;
      if(/^https?:\/\//i.test(url)&&url.length<=2048&&!urls.includes(url)&&JSON.stringify([...urls,url]).length<=8192)urls.push(url);}
    const serialized=JSON.stringify(urls);if(serialized===lastSession)return;
    let service=null,branch=null,previous=null;
    try{service=browserPrefs();branch=service.getBranch("orbisfox.browser.");previous=branch.getStringPref("session","[]");
      branch.setStringPref("session",serialized);savePreferences(service);lastSession=serialized;}
    catch(error){if(branch&&previous!==null)try{branch.setStringPref("session",previous);}catch(_){}
      ++sessionFailures;host.log("Browser UI: session save failed: "+String(error).slice(0,160));}
  };
  const homeTarget=()=>{const page=settings.snapshot().homePage;return page&&gates().web?page:"home";};
  // Web navigation opens only after the packaged Home fixture and trusted
  // network/TLS probes pass. Restore tabs or the custom home page then.
  const webBecameReady=()=>{
    const first=tabs[0],untouched=first&&!first.closed&&first.model.requested===OrbisFoxShellModel.HOME&&!first.model.busy;
    const urls=pendingSession||[];pendingSession=null;
    if(urls.length){let opened=0;
      for(const [index,url] of urls.entries()){
        if(index===0&&untouched){if(load(url,first))++opened;}
        else if(tabs.length<OrbisFoxShellModel.MAX_TABS&&tabAction(()=>newTab(url,null,true)))++opened;}
      host.log("Browser UI: restored "+opened+" of "+urls.length+" previous web tabs");}
    else if(untouched&&settings.snapshot().homePage)load(settings.snapshot().homePage,first);
  };
  const initializeBookmarks=()=>{
    try{
      const service=Cc["@mozilla.org/preferences-service;1"].getService(Ci.nsIPrefService),branch=service.getBranch("orbisfox.browser.");
      bookmarks=new OrbisFoxShellModel.Bookmarks(branch.getStringPref("bookmarks","[]"),serialized=>{
        const previous=branch.getStringPref("bookmarks","[]");
        try{branch.setStringPref("bookmarks",serialized);savePreferences(service);}
        catch(error){branch.setStringPref("bookmarks",previous);throw error;}
      });
    }catch(error){host.log("Browser UI: bookmark storage unavailable: "+String(error).slice(0,160));}
  };
  const initializeHistory=()=>{
    try{
      const service=Cc["@mozilla.org/preferences-service;1"].getService(Ci.nsIPrefService),branch=service.getBranch("orbisfox.browser.");
      history=new OrbisFoxShellModel.History(branch.getStringPref("history","[]"),serialized=>{
        const previous=branch.getStringPref("history","[]");
        try{branch.setStringPref("history",serialized);savePreferences(service);}
        catch(error){branch.setStringPref("history",previous);throw error;}
      });
    }catch(error){host.log("Browser UI: history storage unavailable: "+String(error).slice(0,160));}
  };
  const recordVisit=tab=>{
    if(!history||!gates().web||tab.closed)return;
    try{
      const document=tab.nav?.document,uri=document?.documentURI;
      if(!/^https?:\/\//i.test(uri||"")||document.nodePrincipal?.isSystemPrincipal!==false)return;
      // Repeated notifications/fragment updates are not new page visits and
      // must not synchronously rewrite prefs on every SPA refresh.
      const key=documentID(document)+":"+uri.replace(/#.*$/,"");
      if(tab.lastHistoryKey===key)return;
      history.visit(uri,document.title||tab.model.title);tab.lastHistoryKey=key;
    }catch(error){host.log("Browser UI: history save failed: "+String(error).slice(0,160));}
  };
  const icons=createOrbisFaviconCache(Cc,Ci,io,ssm,host,()=>gates().web);
  const tabAction=callback=>{
    if(tabMutation){host.log("Browser UI: overlapping tab operation rejected");return false;}
    tabMutation=true;try{return action(callback);}finally{tabMutation=false;}
  };
  const gates=()=>({lan:!!network?.canNavigateLAN(),web:host.nativeNetworkReady===true&&
    profile?.snapshot().ok===true&&network?.snapshot().storage.ok===true&&!!https?.snapshot().ok});
  const fail=error=>{if(active){active.model.busy=false;active.model.error=String(error).slice(0,240);active.model.message=active.model.error;}host.log("Browser UI: "+String(error).slice(0,240));};
  const action=callback=>{try{return callback();}catch(error){fail(error);return false;}};
  const checkedURI=text=>{
    const uri=io.newURI(OrbisFoxShellModel.resolveAddress(text,gates()));
    if(uri.scheme!=="file"&&(!["http","https"].includes(uri.scheme)||!uri.host||uri.userPass))throw new Error("Invalid or privileged web URI");
    if(uri.scheme==="file"&&uri.spec!==OrbisFoxShellModel.HOME)throw new Error("Only packaged Home file is permitted");return uri;
  };
  const siteName=spec=>{const match=/^https?:\/\/(\[[^\]/]+\]|[^/?#:]+)/i.exec(spec||"");return match?match[1].replace(/^www\./i,""):"";};
  // Lock state from Gecko's own secure-browser UI when available; otherwise
  // the verified TLS state recorded at document stop. Unknown stays "".
  const pageSecurity=tab=>{
    const location=tab.model.location;if(location===OrbisFoxShellModel.HOME||location.startsWith("file:"))return "local";
    if(location.startsWith("http:"))return "insecure";if(!location.startsWith("https:"))return "";
    try{const state=tab.element?.frameLoader?.browsingContext?.secureBrowserUI?.state,flags=Ci.nsIWebProgressListener;
      if(Number.isInteger(state)){if(state&(flags.STATE_IS_BROKEN??1))return "broken";if(state&(flags.STATE_IS_SECURE??2))return "secure";if(state&(flags.STATE_IS_INSECURE??4))return "insecure";}}catch(_){}
    const document=tab.nav?.document;
    return tab.tlsSecure===true&&document?.nodePrincipal?.isSystemPrincipal===false&&/^https:\/\//i.test(document.documentURI||"")?"secure":"";
  };
  const load=(text,tab=active,options={})=>action(()=>{
    if(!tab||tab.closed||!tab.nav)throw new Error("Content tab not ready");const uri=checkedURI(text);
    tab.beforeLoad=documentID(tab.nav.document);tab.reported=false;tab.model.begin(uri.spec);
    const principal=options.triggeringPrincipal?.isSystemPrincipal===false?options.triggeringPrincipal:
      uri.scheme==="file"?ssm.createContentPrincipal(uri,{}):ssm.createNullPrincipal({});
    try{tab.nav.loadURI(uri,{...options,triggeringPrincipal:principal});}catch(error){tab.model.busy=false;throw error;}
    host.log("Browser UI: tab="+tab.id+" accepted content navigation "+uri.spec+"; completion not assumed");return true;
  });
  const observeNetworking=createOrbisPageNetworkObserver(host,(document,tab)=>document.defaultView?.top===tab.element.contentWindow);
  const reportPageResources=tab=>{
    if(host.diagnosticsEnabled!==true)return;
    observeNetworking(tab.nav?.document,tab);
    const document=tab.nav?.document;if(!document||resourcesObserved.has(document))return;resourcesObserved.add(document);
    try{
      const performance=document.defaultView?.performance,navigation=performance?.getEntriesByType?.("navigation")?.[0];
      if(navigation){
        const delta=(end,start)=>Number.isFinite(navigation[end])&&Number.isFinite(navigation[start])?Math.max(0,Math.round(navigation[end]-navigation[start])):null;
        host.log("Browser page timings: "+JSON.stringify({tab:tab.id,uri:document.documentURI,durationMs:Math.round(navigation.duration),
          dnsMs:delta("domainLookupEnd","domainLookupStart"),connectMs:delta("connectEnd","connectStart"),
          firstByteMs:delta("responseStart","requestStart"),responseMs:delta("responseEnd","responseStart"),
          interactiveMs:Math.round(navigation.domInteractive),DOMContentLoadedMs:Math.round(navigation.domContentLoadedEventEnd),
          loadEventMs:Math.round(navigation.loadEventEnd),transferBytes:navigation.transferSize,decodedBytes:navigation.decodedBodySize}));
      }
      const mse=document.defaultView?.MediaSource;
      const types={vp9:'video/webm; codecs="vp9"',opus:'audio/webm; codecs="opus"',avc:'video/mp4; codecs="avc1.42E01E"',aac:'audio/mp4; codecs="mp4a.40.2"',vp9mp4:'video/mp4; codecs="vp09.00.10.08"'};
      const support={};for(const [name,mime] of Object.entries(types))support[name]=mse?.isTypeSupported?.(mime)===true;
      host.log('Browser actual MSE support: '+JSON.stringify({uri:document.documentURI,mse:!!mse,support}));
      // Observe real media state without injecting a privileged bridge or
      // polling timeupdate every frame. Bound both elements and event reports.
      let clicks=0;
      document.addEventListener?.('click',event=>{if(host.diagnosticsEnabled!==true||tab.closed||clicks++>=16)return;try{const target=event.target?.closest?.('video,button,a,[role="button"]')||event.target;
        host.log('Browser trusted click: '+JSON.stringify({tab:tab.id,trusted:event.isTrusted,x:event.clientX,y:event.clientY,tag:target?.localName,role:target?.getAttribute?.('role'),label:target?.getAttribute?.('aria-label')?.slice(0,64)}));
      }catch(_){}},true);
      let mediaReports=0,mediaIndex=0;
      for(const media of document.querySelectorAll?.("video,audio")||[]){
        if(mediaIndex===8)break;const index=mediaIndex++;
        const reportMedia=reason=>{if(host.diagnosticsEnabled!==true||tab.closed||mediaReports++>=32)return;try{
          const quality=media.getVideoPlaybackQuality?.();
          host.log("Browser media evidence: "+JSON.stringify({tab:tab.id,index,reason,type:media.localName,
            ready:media.readyState,network:media.networkState,time:media.currentTime,paused:media.paused,ended:media.ended,
            error:media.error?.code??null,width:media.videoWidth,height:media.videoHeight,
            frames:quality?.totalVideoFrames,dropped:quality?.droppedVideoFrames,
            // Gecko's per-stage counters (issue #3): demuxed -> decoded ->
            // presented -> painted. A gap shows which stage falls behind.
            parsed:media.mozParsedFrames??null,decoded:media.mozDecodedFrames??null,presented:media.mozPresentedFrames??null,
            painted:media.mozPaintedFrames??null,lateSeconds:media.mozFrameDelay??null}));
        }catch(error){host.log("Browser media evidence unavailable: "+String(error).slice(0,160));}};
        reportMedia("document-stop");
        for(const event of ["loadedmetadata","play","pause","playing","waiting","stalled","ended","error"])
          media.addEventListener(event,()=>reportMedia(event));
      }
      const fonts=document.fonts;if(!fonts)return;let reports=0;
      const report=reason=>{if(host.diagnosticsEnabled!==true||tab.closed||reports++>=4)return;try{
        const faces=[];for(const face of fonts){if(faces.length===32)break;faces.push({family:String(face.family).slice(0,80),status:face.status,unicodeRange:String(face.unicodeRange).slice(0,80)});}
        host.log("Browser webfont evidence: "+JSON.stringify({tab:tab.id,reason,status:fonts.status,faces}).slice(0,3900));
      }catch(error){host.log("Browser webfont evidence unavailable: "+String(error).slice(0,160));}};
      report("document-stop");fonts.addEventListener("loadingdone",()=>report("loadingdone"));fonts.addEventListener("loadingerror",()=>report("loadingerror"));
    }catch(error){host.log("Browser page-resource evidence unavailable: "+String(error).slice(0,160));}
  };
  const bindTab=tab=>{
    if(tab.nav)return true;const e=tab.element;if(!e.docShell)return false;
    if(e.getAttribute("type")!=="content"||e.hasAttribute("remote")||e.hasAttribute("maychangeremoteness"))throw new Error("Content remoteness attribute forbidden");
    const bc=e.frameLoader?.browsingContext;
    if(!bc||bc.isContent!==true||bc.useRemoteTabs||bc.useRemoteSubframes)throw new Error("Separate nonremote content context required");
    tab.nav=e.docShell.QueryInterface(Ci.nsIWebNavigation);tab.progress=e.docShell.QueryInterface(Ci.nsIWebProgress);
    e.addEventListener?.('DOMContentLoaded',event=>observeNetworking(event.originalTarget||event.target,tab),true);
    tab.listener={
      onStateChange(web,request,flags,status){
        if(tab.closed||web.DOMWindow!==e.contentWindow||!(flags&Ci.nsIWebProgressListener.STATE_IS_DOCUMENT))return;
        if(flags&Ci.nsIWebProgressListener.STATE_START){tab.model.busy=true;tab.model.message="Loading…";tab.model.issuer="";tab.tlsSecure=false;}
        if(flags&Ci.nsIWebProgressListener.STATE_STOP){
          tab.model.stopped(status,tab.nav?.document?.documentURI);host.log("Browser UI: tab="+tab.id+" content document stop status=0x"+(status>>>0).toString(16));
          tab.securityDirty=true;reportPageResources(tab);
          if((status>>>0)===0)recordVisit(tab);
          if(request&&/^https:\/\//.test(tab.model.requested))try{
            const channel=request.QueryInterface(Ci.nsIChannel),info=channel.securityInfo;
            if(info){const tls=info.QueryInterface(Ci.nsITransportSecurityInfo);
              // Identity details only from a verified connection for this document.
              try{tab.tlsSecure=!!(tls.securityState&Ci.nsIWebProgressListener.STATE_IS_SECURE)&&(status>>>0)===0;const cert=tab.tlsSecure?tls.serverCert:null;
                tab.model.issuer=String(cert?.issuerOrganization||cert?.issuerCommonName||"").slice(0,120);}catch(_){tab.tlsSecure=false;tab.model.issuer="";}
              host.log("Browser UI: actual HTTPS document evidence "+JSON.stringify({tab:tab.id,uri:channel.URI.spec,status:status>>>0,
                secure:!!(tls.securityState&Ci.nsIWebProgressListener.STATE_IS_SECURE),errorCode:tls.errorCode,errorName:tls.errorCodeString,
                protocol:tls.protocolVersion,chainLength:tls.succeededCertChain.length,builtinRoot:tls.isBuiltCertChainRootBuiltInRoot,serverCertificate:!!tls.serverCert}));}
            else host.log("Browser UI: HTTPS stop has no transport security info; status=0x"+(status>>>0).toString(16));
          }catch(error){host.log("Browser UI: HTTPS evidence unavailable: "+error);}
        }
      },
      onLocationChange(web,request,location,flags=0){if(!tab.closed&&web.DOMWindow===e.contentWindow&&location){tab.securityDirty=true;
        tab.model.locationChanged(location.spec);tab.model.requested=location.spec;
        if(flags&Ci.nsIWebProgressListener.LOCATION_CHANGE_SAME_DOCUMENT)recordVisit(tab);
      }},
      onStatusChange(){},onProgressChange(){},onSecurityChange(){},onContentBlockingEvent(){},
      QueryInterface:ChromeUtils.generateQI(["nsIWebProgressListener","nsISupportsWeakReference"])
    };
    tab.progress.addProgressListener(tab.listener,Ci.nsIWebProgress.NOTIFY_STATE_DOCUMENT|Ci.nsIWebProgress.NOTIFY_LOCATION);
    bc.isActive=tab===active;
    // nsSecureBrowserUI is created lazily; create it before the first commit
    // so its state is computed for this tab's documents.
    try{void bc.secureBrowserUI;}catch(_){}
    host.log("Browser UI: tab="+tab.id+" genuine separate nonremote context bound");
    if(tab.pending!==null){const pending=tab.pending;tab.pending=null;load(pending,tab);}return true;
  };
  const selectTab=id=>action(()=>{
    if(ui.isEditing())throw new Error("Finish editing before switching tabs");const tab=tabs.find(t=>t.id===id&&!t.closed);
    if(!tab)throw new Error("Unknown tab");host.setPointerInputEnabled(false);textTarget=null;active=tab;lastScroll="";
    ui.selectContent(id);host.setPointerInputEnabled(true);host.log("Browser UI: selected real tab "+id);return true;
  });
  const newTab=(initial="home",openWindowInfo=null,background=false)=>{
    if(tabs.length>=OrbisFoxShellModel.MAX_TABS)throw new Error("Three real-tab limit reached; close a tab first");
    const id=tabs.length===0?"content":"content-"+(++serial),element=tabs.length===0?ui.contentElement():ui.createContent(id,openWindowInfo);
    const tab={id,element,model:new OrbisFoxShellModel.State(),nav:null,progress:null,listener:null,pending:initial,beforeLoad:null,reported:false,closed:false,created:Date.now(),zoom:settings.snapshot().defaultZoom||100};
    const previous=active;tabs.push(tab);
    try {if(background&&previous)ui.selectContent(previous.id);else if(!selectTab(id))throw new Error("Unable to select new tab");bindTab(tab);const context=element.frameLoader?.browsingContext;if(context)context.fullZoom=tab.zoom/100;return tab;}
    catch(error){tabs.splice(tabs.indexOf(tab),1);dispose(tab);active=previous;if(previous)ui.selectContent(previous.id);throw error;}
  };
  const dispose=tab=>{
    if(tab.disposed)return;tab.disposed=true;tab.closed=true;
    if(tab.progress&&tab.listener)try{tab.progress.removeProgressListener(tab.listener);}catch(error){host.log("ERROR: tab listener cleanup: "+error);}
    if(tab.nav)try{tab.nav.stop(Ci.nsIWebNavigation.STOP_ALL);}catch(error){host.log("ERROR: tab stop: "+error);}
    ui.removeContent(tab.id);tab.nav=tab.progress=tab.listener=tab.element=tab.beforeLoad=null;
  };
  const closeTab=(id=active?.id)=>action(()=>{
    if(ui.isEditing())throw new Error("Finish editing before closing a tab");if(tabs.length<=1)throw new Error("Keep one real tab; use Exit to close browser");
    const index=tabs.findIndex(t=>t.id===id);if(index<0)throw new Error("Unknown tab");const tab=tabs[index];
    const selected=tab===active;closedTabs.push(tab.model.location,tab.model.title);tab.closed=true;tabs.splice(index,1);
    if(selected)selectTab(tabs[Math.min(index,tabs.length-1)].id);
    dispose(tab);host.log("Browser UI: real tab closed "+id);return true;
  });
  const validField=field=>field?.isConnected&&field.ownerDocument?.nodePrincipal.isSystemPrincipal===false&&!field.disabled&&!field.readOnly&&
    (field.localName==="textarea"||field.localName==="input"&&["text","search","email","url","tel"].includes(field.type));
  const editClickedField=()=>action(()=>{
    if(!active?.nav||!ui.canScroll()||ui.isEditing())return false;
    const rect=active.element.getBoundingClientRect();let doc=active.nav.document;
    let x=host.cursorX-rect.left,y=host.cursorY-rect.top,hit=doc.elementFromPoint(x,y);
    for(let depth=0;depth<8&&hit&&["iframe","frame"].includes(hit.localName);++depth){const r=hit.getBoundingClientRect();x-=r.left;y-=r.top;doc=hit.contentDocument;if(!doc)return false;hit=doc.elementFromPoint(x,y);}
    const field=doc.activeElement;
    if(!validField(field)||hit!==field||field.value.length>512)return false;
    textTarget={tab:active,field,document:doc,draft:field.value};ui.editText(field.value);return true;
  });
  const commitText=text=>action(()=>{
    const target=textTarget;
    if(!target||target.tab!==active||!validField(target.field)||target.field.ownerDocument!==target.document||target.field.value!==target.draft||typeof text!=="string"||text.length>512)
      throw new Error("Page text target changed; text not applied");
    target.field.focus();target.field.select();
    const enabled=target.document.defaultView.windowUtils.sendContentCommandEvent("insertText",null,text);
    if(!enabled)throw new Error("Real content editor rejected text input");
    textTarget=null;host.log("Browser UI: trusted content-editor text command applied; no text logged");return true;
  });
  const popup=(uri,info,where,flags,principal,policy,loadNow=false,referrer=null)=>{
    if(tabMutation)throw new Error("Tab operation already in progress");tabMutation=true;
    try {
    host.log("Browser UI: popup bridge entered location="+where+" load-now="+loadNow+"; no URI or user text logged");
    const locations=Ci.nsIBrowserDOMWindow;
    if(ui.isEditing())throw new Error("Finish editing before opening a popup");
    if(where===locations.OPEN_PRINT_BROWSER)throw new Error("Printing window unavailable");
    if(![locations.OPEN_CURRENTWINDOW,locations.OPEN_NEWTAB,locations.OPEN_NEWTAB_BACKGROUND,locations.OPEN_NEWTAB_FOREGROUND].includes(where))
      throw new Error("Unsupported popup location");
    if(loadNow&&!uri)throw new Error("openURI requires a URI");
    if(uri&&uri.spec!=="about:blank")checkedURI(uri.spec);if(principal?.isSystemPrincipal===true)throw new Error("System-principal popup rejected");
    if(flags&locations.OPEN_NO_REFERRER){referrer=Cc["@mozilla.org/referrer-info;1"].createInstance(Ci.nsIReferrerInfo);referrer.init(0,false,null);}
    const created=where!==locations.OPEN_CURRENTWINDOW;
    const tab=created?newTab(null,info,where===locations.OPEN_NEWTAB_BACKGROUND):active;
    if(!tab||!bindTab(tab)){if(created&&tab)closeTab(tab.id);throw new Error("Popup docshell not synchronously ready");}
    if(loadNow&&!load(uri.spec,tab,{triggeringPrincipal:principal,policyContainer:policy,referrerInfo:referrer})) {if(created)closeTab(tab.id);throw new Error("Popup navigation rejected");}
    host.log("Browser UI: popup bridge returned bounded context tab="+tab.id+" created="+created);
    return tab;
    } finally {tabMutation=false;}
  };
  try {
    globalThis.load("/app0/assets/browser-shell-model.js");closedTabs=new OrbisFoxShellModel.ClosedTabs();initializeBookmarks();initializeHistory();initializeSettings();
    host.setDiagnosticsEnabled?.(host.diagnosticsEnabled===true);
    controls=new OrbisFoxShellModel.Controller();chrome=host.createChromeBrowser(1280,720);
    chrome.loadURI(io.newURI(CHROME),{triggeringPrincipal:ssm.getSystemPrincipal()});
    timer.initWithCallback(()=>{
      try {
        ++ticks;
        if(ui&&host.takeNativeChromeAction)for(let i=0;i<16;++i){const command=host.takeNativeChromeAction();if(!command)break;
          host.log('Native chrome: dequeued '+command+' handled='+ui.nativeCommand(command));lastNativeScene='';if(!alive)break;}
        if(!alive||!host.pumpFrame()){alive=false;return;}
        if(!ui){
          const win=chrome.docShell.domWindow,doc=win.document;
          if(doc.documentURI!==CHROME||doc.readyState==="loading"){if(Date.now()-started>15000)throw new Error("Chrome document readiness timeout");return;}
          if(doc.nodePrincipal.isSystemPrincipal!==true)throw new Error("Shell must be system-principal chrome");
          const candidate=win.wrappedJSObject.OrbisFoxShell;
          if(!candidate?.ready||!candidate.contentElement()?.docShell){if(Date.now()-started>15000)throw new Error("Chrome/content readiness timeout");return;}
          ui=candidate;
          ui.bind({navigate:text=>action(()=>load(text==="home"?homeTarget():OrbisFoxShellModel.navigationText(text,settings.snapshot().searchEngine))),search:text=>action(()=>load(OrbisFoxShellModel.homeAddress(text,settings.snapshot().searchEngine))),
            settings:()=>({...settings.snapshot(),diagnostics:host.diagnosticsEnabled===true}),
            setDiagnostics:value=>action(()=>{host.setDiagnosticsEnabled(value===true);return true;}),
            clearDiagnosticLogs:()=>{host.setDiagnosticsEnabled(false);return createOrbisLogCleaner(Cc,Ci)();},
            saveSettings:changes=>action(()=>{if(!settingsAvailable)throw Error("Settings storage unavailable");const oldZoom=settings.snapshot().defaultZoom;settings.update(changes);
              // Like Firefox, a new default zoom applies to every tab still at
              // the old default (and the current tab); manual zooms are kept.
              if(changes.defaultZoom!==undefined)for(const tab of tabs){const context=tab.element?.frameLoader?.browsingContext;
                if(context&&(tab===active||tab.zoom===oldZoom)){tab.zoom=changes.defaultZoom;context.fullZoom=tab.zoom/100;}}
              if(changes.restoreSession!==undefined){lastSession=null;if(!changes.restoreSession)saveSession(true);}return true;}),
            closedTabs:()=>closedTabs.snapshot(),closedTabsRevision:()=>closedTabs.revision,
            reopenClosedTab:(index=0)=>tabAction(()=>{
              const item=closedTabs.peek(index);if(!item)throw Error("No recently closed tab");if(!gates().web)throw Error("Web navigation is not ready yet");
              // Firefox reopens in a new tab; at the three-tab cap use this one.
              if(tabs.length<OrbisFoxShellModel.MAX_TABS){const tab=newTab(item.url);if(tab.pending!==item.url&&tab.model.requested!==item.url)return false;}
              else if(!load(item.url))return false;
              closedTabs.remove(index);return true;}),
            removeHistory:url=>action(()=>{if(!history)throw Error("History storage unavailable");return history.remove(url);}),
            clearSiteData:done=>action(()=>{
              // Gecko's own ClearDataService; the shell never touches cookie files.
              // Clearing auth tokens cancels every connection, so never run it
              // while the one-shot startup network/TLS probes still decide the web gate.
              if(!gates().web)throw Error("Wait until web browsing is ready before clearing site data");
              const service=Cc["@mozilla.org/clear-data-service;1"].getService(Ci.nsIClearDataService),flags=Ci.nsIClearDataService;
              const mask=(flags.CLEAR_COOKIES_AND_SITE_DATA||((flags.CLEAR_COOKIES|0)|(flags.CLEAR_DOM_STORAGES|0)))|(flags.CLEAR_ALL_CACHES|0);
              if(!mask)throw Error("Site data clearing unavailable");
              service.deleteData(mask,{onDataDeleted(failed){host.log("Browser UI: cookies/site data cleared failedFlags="+(failed>>>0));try{done?.((failed>>>0)===0);}catch(_){}}});
              return true;}),
            zoomValue:()=>active?.zoom||100,zoom:delta=>action(()=>{if(!active||![-10,0,10].includes(delta))throw Error('Invalid zoom action');const zoom=Math.max(50,Math.min(200,delta===0?settings.snapshot().defaultZoom:active.zoom+delta));const context=active.element.frameLoader?.browsingContext;if(!context)throw Error('Page zoom unavailable');context.fullZoom=zoom/100;active.zoom=zoom;return true;}),
            find:(text,backwards=false)=>action(()=>{if(typeof text!=='string'||!text.trim()||text.length>512)throw Error('Enter text to find');const finder=active.nav.QueryInterface(Ci.nsIInterfaceRequestor).getInterface(Ci.nsIWebBrowserFind);finder.searchString=text;finder.wrapFind=true;finder.findBackwards=!!backwards;const found=finder.findNext();active.model.message=found?'Match found':'No match found';return found;}),
            exitContentFullscreen:()=>action(()=>{chrome.docShell.domWindow.windowUtils.exitFullscreen();return true;}),
            escape:()=>action(()=>{host.sendEscape();return true;}),pointer:value=>host.setPointerInputEnabled(value),
            bookmarks:()=>bookmarks?.snapshot()||[],bookmarkRevision:()=>bookmarks?.revision??-1,
            history:limit=>history?.snapshot(limit)||[],historyRevision:()=>history?.revision??-1,
            historyAvailable:()=>!!history,favicon:url=>icons.request(url),faviconRevision:()=>icons.revision,
            removeBookmark:url=>action(()=>{if(!bookmarks)throw Error("Bookmark storage unavailable");bookmarks.remove(url);return true;}),
            clearHistory:()=>action(()=>{if(!history)throw Error("History storage unavailable");history.clear();
              // Clearing history also forgets closed tabs and the saved session list.
              closedTabs.clear();lastSession=null;saveSession(true);return true;}),
            toggleMedia:()=>action(()=>{
              const document=active?.nav?.document;if(!gates().web||document?.nodePrincipal?.isSystemPrincipal!==false)throw Error('No active web media');
              const media=[...(document.querySelectorAll('video,audio')||[])].slice(0,8).find(element=>!element.ended)||document.querySelector('video,audio');
              if(!media)throw Error('No media element on this page');
              // Explicit physical-controller command, not autoplay or a decoder bypass.
              const handling=document.defaultView.windowUtils.setHandlingUserInput(true);
              try{if(media.paused){host.log('Browser media command: play requested; awaiting actual result');media.play().then(()=>host.log('Browser media command: play resolved paused='+media.paused+' time='+media.currentTime),error=>host.log('Browser media command: play rejected '+String(error).slice(0,180)));}
                else{media.pause();host.log('Browser media command: pause requested paused='+media.paused);}return true;
              }finally{handling.destruct();}
            }),
            toggleBookmark:()=>action(()=>{
              if(!bookmarks||!gates().web||!active)throw new Error("Bookmark storage not ready");
              const added=bookmarks.toggle(active.model.location,active.nav.document?.title||active.model.title);
              active.model.message=added?"Bookmark saved":"Bookmark removed";return true;
            }),
            openKeyboard:draft=>{const opened=host.openAddressKeyboard(draft);if(opened)keyboardPending="address";return opened;},
            openTextKeyboard:draft=>{const opened=host.openTextKeyboard(draft);if(opened)keyboardPending="text";return opened;},
            keyboardConfirm:()=>host.keyboardConfirmButton,commitText,cancelText:()=>{textTarget=null;},
            newTab:()=>tabAction(()=>newTab()),selectTab:id=>tabAction(()=>selectTab(id)),closeTab:id=>tabAction(()=>closeTab(id)),
            relativeTab:delta=>tabAction(()=>selectTab(tabs[(tabs.indexOf(active)+delta+tabs.length)%tabs.length].id)),
            back:()=>action(()=>{if(active.nav.canGoBack){active.beforeLoad=documentID(active.nav.document);active.reported=false;active.nav.goBack(false,true);}}),
            forward:()=>action(()=>{if(active.nav.canGoForward){active.beforeLoad=documentID(active.nav.document);active.reported=false;active.nav.goForward();}}),
            reload:()=>action(()=>{if(active.model.busy)active.nav.stop(Ci.nsIWebNavigation.STOP_ALL);else{active.beforeLoad=documentID(active.nav.document);active.reported=false;active.model.begin(active.model.location);active.nav.reload(Ci.nsIWebNavigation.LOAD_FLAGS_NONE);}}),
            exit:()=>{host.requestExit();alive=false;}});
          win.browserDOMWindow={
            createContentWindow:(uri,info,where,flags,principal,policy)=>popup(uri,info,where,flags,principal,policy).element.frameLoader.browsingContext,
            createContentWindowInFrame:(uri,params,where,flags,name)=>popup(uri,params.openWindowInfo,where,flags,params.triggeringPrincipal,params.policyContainer).element,
            openURI:(uri,info,where,flags,principal,policy)=>popup(uri,info,where,flags,principal,policy,true).element.frameLoader.browsingContext,
            openURIInFrame:(uri,params,where,flags,name)=>popup(uri,params.openWindowInfo,where,flags,params.triggeringPrincipal,params.policyContainer,true,params.referrerInfo).element,
            canClose:()=>true,get tabCount(){return tabs.length;},QueryInterface:ChromeUtils.generateQI(["nsIBrowserDOMWindow"])};
          middleLink=createOrbisMiddleLinkHandler({sourceTab:document=>tabs.find(tab=>!tab.closed&&document.defaultView?.top===tab.element.contentWindow),
            linkData:event=>ChromeUtils.importESModule('resource://gre/modules/BrowserUtils.sys.mjs').BrowserUtils.hrefAndLinkNodeForClickEvent(event),
            checkedURI,ssm,Cc,Ci,popup,log:message=>host.log(message)});
          win.addEventListener('chromelinkclick',middleLink,true);
          removeFullscreen=createOrbisFullscreenController(win,()=>active,ui,io);
          if(!tabAction(()=>newTab()))throw new Error("Initial real tab creation failed");
          host.log("Browser UI: privileged shell / real bounded tabs / content separation verified");
        }
        for(const tab of tabs)if(!bindTab(tab)&&Date.now()-tab.created>5000)throw new Error("New content tab readiness timeout");
        if(!active.nav)return;
        if(host.cursorX!==lastX||host.cursorY!==lastY)ui.pointerMoved();lastX=host.cursorX;lastY=host.cursorY;
        const releasedCross=(lastButtons&1)&&!(host.buttons&1)&&!(lastButtons&8190);lastButtons=host.buttons;
        // Controller edge history belongs to the shell, not to a switched tab.
        for(const name of controls.update(host.buttons,Date.now()))ui.control(name);
        if(releasedCross)editClickedField();
        if(keyboardPending&&host.keyboardStatus!==1){keyboardPending=null;ui.finishAddressKeyboard(host.keyboardStatus,host.keyboardText);}
        const dx=host.scrollX||0,dy=host.scrollY||0;
        if(dx||dy)try{
          if(!Number.isInteger(dx)||!Number.isInteger(dy)||Math.abs(dx)>64||Math.abs(dy)>64)throw new Error("Invalid scroll delta");
          const chromeScale=chrome.docShell.domWindow.devicePixelRatio||1;
          if(!ui.canScroll())ui.scrollShell?.(dx*24,dy*24,host.cursorX/chromeScale,host.cursorY/chromeScale);
          else{
          const win=active.element.contentWindow;if(active.nav.document.nodePrincipal.isSystemPrincipal!==false)throw new Error("System scroll target rejected");
          const flags=Ci.nsIDOMWindowUtils.WHEEL_EVENT_CAUSED_BY_NO_LINE_OR_PAGE_DELTA_DEVICE|Ci.nsIDOMWindowUtils.WHEEL_EVENT_ASYNC_ENABLED;
          const rect=active.element.getBoundingClientRect(),scale=chrome.docShell.domWindow.devicePixelRatio||1;
          const x=host.cursorX/scale-rect.left,y=host.cursorY/scale-rect.top;
          // Hit-test the real cursor in this content viewport, not its center.
          // Ignore chrome/outside/temporarily hidden targets; Gecko handles
          // nested scroll containers and cross-frame event propagation.
          if(rect.width>0&&rect.height>0&&Number.isFinite(x)&&Number.isFinite(y)&&
             x>=0&&x<rect.width&&y>=0&&y<rect.height)
            win.windowUtils.sendWheelEvent(x*win.innerWidth/rect.width,y*win.innerHeight/rect.height,dx,dy,0,0,0,0,0,flags);
          }
        }catch(error){if(scrollFailures++<8)host.log('Browser wheel: dispatch skipped; will retry: '+String(error).slice(0,180));}
        for(const tab of tabs){
          if(!tab.nav)continue;const document=tab.nav.document;tab.model.history(tab.nav.canGoBack,tab.nav.canGoForward);
          // Like Firefox, an untitled or still-loading page shows its host.
          tab.model.title=document?.documentURI===OrbisFoxShellModel.HOME?"Home":document?.title?.trim().slice(0,160)||siteName(tab.model.busy?tab.model.requested:tab.model.location)||"Untitled";
          // Lock state changes with loads; recheck it then (and the active tab once
          // a second for late mixed content) instead of on every 33 ms tick.
          if(tab.securityDirty!==false||(tab===active&&ticks%30===0)){tab.model.security=pageSecurity(tab);tab.securityDirty=false;}
          if(tab===active&&document&&[OrbisFoxShellModel.HOME,OrbisFoxShellModel.LAN].includes(document.documentURI)){
            const pos=(document.defaultView?.scrollX||0)+","+(document.defaultView?.scrollY||0);
            if(pos!=="0,0"&&pos!==lastScroll&&scrollReports<12){host.log("Browser UI: actual content scroll position "+pos);++scrollReports;}lastScroll=pos;
          }
          if(document&&documentID(document)!==tab.beforeLoad&&document.documentURI===tab.model.requested&&
             [OrbisFoxShellModel.HOME,OrbisFoxShellModel.LAN].includes(document.documentURI)&&document.nodePrincipal.isSystemPrincipal===false&&!tab.reported){
            const result=document.defaultView?.wrappedJSObject.orbisfoxFixture;
            if(result){host.log("Browser UI: fresh content fixture assertions "+JSON.stringify(result));host.fixtureCheckpoint(result.passed);tab.reported=true;
              if(result.ok&&result.passed===8&&!network)network=startTrustedNetworkProbes(Cc,Ci,io,tm,ssm,host);}
          }
        }
        const snapshot=network?.snapshot();if(!https&&snapshot?.storage.ok&&snapshot.dns.ok)https=startTrustedHTTPSProbes(Cc,Ci,io,ssm,host,snapshot);
        if(!webWasReady&&gates().web){webWasReady=true;webBecameReady();}
        if(webWasReady&&ticks%30===0)saveSession();
        // Static probe transcripts do not need serialization every UI frame.
        if(host.diagnosticsEnabled!==true)diagnosticText='';
        else if(!diagnosticText||ticks%30===0)diagnosticText=JSON.stringify({nativeNetReady:host.nativeNetworkReady,nativeJitReady:host.nativeJitReady,nativeAudioReady:host.nativeAudioReady,profile:profile?.snapshot(),network:snapshot||"Awaiting8 checks",https:https?.snapshot()||"Awaiting DNS/storage",
          tabs:tabs.length,maxTabs:OrbisFoxShellModel.MAX_TABS,scope:"General HTTP/HTTPS after storage/quota/TLS gates. Unsafe schemes/credentials denied. No production sandbox/security certification."},null,2);
        const diagnostic=diagnosticText;
        ui.renderTabs(tabs.map(tab=>({id:tab.id,...tab.model.snapshot(),favicon:icons.request(tab.model.location,tab.nav?.document)})),active.id);ui.update(active.model.snapshot(),diagnostic,{...gates(),bookmarksAvailable:!!bookmarks});
        if(active.model.security!==lastSecurity){lastSecurity=active.model.security;lastNativeScene="";}
        if(host.setNativeChromeState&&ui.nativeChromeScene&&(ticks%30===0||!lastNativeScene)){
          const scene=ui.nativeChromeScene();if(scene&&scene!==lastNativeScene){host.setNativeChromeState(scene);lastNativeScene=scene;}}
        if(diagnostic!==lastDiagnostics){host.log("Browser UI diagnostics: "+diagnostic.slice(0,3900));lastDiagnostics=diagnostic;}
        if(ticks%120===0)host.log("Browser UI heartbeat: ticks="+ticks+" frames="+host.framesPresented+" tabs="+tabs.length);
      }catch(error){host.log("ERROR: browser shell: "+error+"\n"+error.stack);alive=false;}
    },33,Ci.nsITimer.TYPE_REPEATING_SLACK);
    tm.spinEventLoopUntil("OrbisFox bounded real-tab shell",()=>!alive);
  }finally{
    try{removeFullscreen?.();}catch(_){}
    if(middleLink)chrome?.docShell.domWindow.removeEventListener('chromelinkclick',middleLink,true);
    const cleanup=(name,callback)=>{try{callback();}catch(error){host.log("ERROR: shell cleanup "+name+": "+error);}};
    if(webWasReady)cleanup("session",()=>saveSession(true));
    cleanup("favicon channels",()=>icons.close());
    cleanup("native chrome",()=>host.setNativeChromeState?.(''));
    cleanup("timer",()=>timer.cancel());cleanup("native keyboard",()=>host.cancelAddressKeyboard());textTarget=null;keyboardPending=null;
    if(chrome)cleanup("popup host",()=>{chrome.docShell.domWindow.browserDOMWindow=null;});
    for(const tab of tabs)cleanup("tab "+tab.id,()=>dispose(tab));tabs.length=0;
    if(https)cleanup("HTTPS",()=>https.close());if(network)cleanup("network",()=>network.close());
    if(ui)cleanup("UI",()=>ui.destroy());cleanup("pointer",()=>host.setPointerInputEnabled(true));cleanup("browser",()=>host.closeBrowser());
    chrome=ui=active=null;
  }
}
