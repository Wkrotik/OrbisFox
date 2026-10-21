/* Pure UI state/policy only. Gecko owns DOM, layout, history and navigation. */
"use strict";
var OrbisFoxShellModel = (() => {
  const HOME = "file:///app0/assets/offline.html";
  const LAN = "http://10.42.0.1:8765/orbisfox/offline.html";
  const HTTPS = "https://example.com/";
  const GOOGLE = "https://www.google.com/";
  const Buttons = Object.freeze({cross:1, reload:2, address:4, menu:8, cancel:16,
    left:32, right:64, up:128, down:256, previousTab:512, nextTab:1024, forward:2048});
  function resolveAddress(text, gates = {}) {
    if (typeof text !== "string" || text.length > 2048 || /[\x00-\x1f\x7f]/.test(text))
      throw new Error("Invalid address");
    const value = text.trim();
    if (!value || value === "home" || value === HOME) return HOME;
    if (value === LAN && gates.lan === true) return LAN;
    if (gates.web !== true) throw new Error("Web navigation awaits native Net, persistent storage, quota and TLS checks");
    let address=value;
    if (!/^https?:\/\//i.test(address)) {
      if (/^[a-z][a-z0-9+.-]*:/i.test(address) && !/^(localhost|[^/:]+\.[^/:]+):[0-9]+(?:\/|$)/i.test(address))
        throw new Error("Only HTTP and HTTPS addresses are supported");
      // Local/private hosts default to plain HTTP; everything else to HTTPS.
      address=(privateHost(/^[^/?#]*/.exec(address)[0])?"http://":"https://")+address;
    }
    const authority=/^https?:\/\/([^/?#]+)(?:[/?#]|$)/i.exec(address);
    if (!authority || /[@\\\s]/.test(authority[1]) || /[\\\s]/.test(address))
      throw new Error("Invalid web address or embedded credentials");
    return address;
  }
  const SEARCH_ENGINES=Object.freeze({google:"https://www.google.com/search?q=",duckduckgo:"https://duckduckgo.com/?q=",bing:"https://www.bing.com/search?q=",
    wikipedia:"https://en.wikipedia.org/wiki/Special:Search?search=",ecosia:"https://www.ecosia.org/search?q=",startpage:"https://www.startpage.com/do/search?query="});
  // Firefox-style "@keyword terms" one-off searches.
  const SEARCH_KEYWORDS=Object.freeze({"@google":"google","@duckduckgo":"duckduckgo","@ddg":"duckduckgo","@bing":"bing","@wikipedia":"wikipedia","@wiki":"wikipedia","@ecosia":"ecosia","@startpage":"startpage"});
  function localHost(authority){
    const host=String(authority).replace(/:[0-9]{1,5}$/,"").toLowerCase();
    if(host==="localhost"||/^\[[0-9a-f:.]+\]$/.test(host))return true;
    return /^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$/.test(host)&&host.split(".").every(part=>Number(part)<=255);
  }
  // Plain HTTP is only the default for loopback, private and link-local hosts;
  // a typed public IP still tries HTTPS first.
  function privateHost(authority){
    const host=String(authority).replace(/:[0-9]{1,5}$/,"").toLowerCase();
    if(host==="localhost"||host==="[::1]"||/^\[f[cd]|^\[fe[89ab]/.test(host))return true;
    if(!localHost(host)||host.startsWith("["))return false;const [a,b]=host.split(".").map(Number);
    return a===127||a===10||(a===172&&b>=16&&b<=31)||(a===192&&b===168)||(a===169&&b===254);
  }
  // Typed text is an address only when it has a plausible host; anything else
  // (single words, "1.5", "what is: x") is a search, as in Firefox.
  // Common file names ("node.js", "notes.txt") are searches, not hosts.
  const NOT_TLDS=new Set(["js","mjs","ts","txt","htm","html","css","json","xml","csv","log","pdf","png","jpg","jpeg","gif","webp","svg","exe","dll","bat","ini","cfg","tmp","bak","doc","docx","xls","xlsx","ppt","pptx","mp3","mp4","wav","php","jsp","asp","aspx","cpp","hpp","java","yml","yaml","toml","lock","iso","bin","dmg","apk","pkg","rar","gz","tar","7z"]);
  function looksLikeAddress(value){
    if(/\s/.test(value))return false;if(/^https?:\/\//i.test(value))return true;
    const authority=/^[^/?#]*/.exec(value)[0];if(localHost(authority))return true;
    const labels=authority.replace(/:[0-9]{1,5}$/,"").replace(/\.$/,"").toLowerCase().split(".");
    return labels.length>1&&labels.every(label=>label.length>0&&label.length<=63&&/^[\p{L}\p{N}-]+$/u.test(label))&&
      /^(?:\p{L}{2,63}|xn--[a-z0-9-]{1,59})$/u.test(labels.at(-1))&&!NOT_TLDS.has(labels.at(-1));
  }
  function searchURL(terms,engine){return (Object.hasOwn(SEARCH_ENGINES,engine)?SEARCH_ENGINES[engine]:SEARCH_ENGINES.google)+encodeURIComponent(terms);}
  function homeAddress(text,engine="google"){
    if(typeof text!=="string"||!text.trim()||text.length>512||/[\x00-\x1f\x7f]/.test(text))throw new Error("Enter a search or website");
    const value=text.trim(),keyword=/^(@[a-z]+)\s+(\S[\s\S]*)$/i.exec(value);
    if(keyword&&Object.hasOwn(SEARCH_KEYWORDS,keyword[1].toLowerCase()))return searchURL(keyword[2].trim(),SEARCH_KEYWORDS[keyword[1].toLowerCase()]);
    if(value.length>1&&value[0]==="?")return searchURL(value.slice(1).trim(),engine);
    return looksLikeAddress(value)?value:searchURL(value,engine);
  }
  // Address-bar text: explicit "scheme://" or known-scheme input stays an
  // address so unsafe schemes are rejected (never silently searched).
  function navigationText(text,engine="google"){
    if(typeof text!=="string")throw new Error("Invalid address");const value=text.trim();
    if(!value||value==="home"||value===HOME)return HOME;
    if(/^[a-z][a-z0-9+.-]*:\/\//i.test(value)||/^(?:javascript|data|about|chrome|resource|file|view-source|blob|jar|moz-extension|mailto):/i.test(value))return value;
    return homeAddress(value,engine);
  }
  class Settings {
    constructor(serialized="{}",persist=null){
      this.persist=persist;this.value={searchEngine:"google",cursorSpeed:1,defaultZoom:100,colorScheme:"system",homePage:"",restoreSession:false,globalPrivacyControl:false};
      try{if(typeof serialized!=="string"||serialized.length>4096)throw Error();const parsed=JSON.parse(serialized);this.validate(parsed);this.value={searchEngine:parsed.searchEngine,cursorSpeed:parsed.cursorSpeed,defaultZoom:parsed.defaultZoom??100,colorScheme:parsed.colorScheme??"system",
        homePage:parsed.homePage??"",restoreSession:parsed.restoreSession??false,globalPrivacyControl:parsed.globalPrivacyControl??false};}catch(_error){}
    }
    validate(value){if(!value || typeof value.searchEngine!=="string" || !Object.hasOwn(SEARCH_ENGINES,value.searchEngine)||!Number.isFinite(value.cursorSpeed)||value.cursorSpeed<0.25||value.cursorSpeed>3||(value.defaultZoom!==undefined&&(!Number.isInteger(value.defaultZoom)||value.defaultZoom<50||value.defaultZoom>200||value.defaultZoom%10))||(value.colorScheme!==undefined&&!["system","light","dark"].includes(value.colorScheme))||
      (value.restoreSession!==undefined&&typeof value.restoreSession!=="boolean")||(value.globalPrivacyControl!==undefined&&typeof value.globalPrivacyControl!=="boolean"))throw Error("Invalid browser settings");
      if(value.homePage!==undefined&&value.homePage!==""&&(typeof value.homePage!=="string"||value.homePage.length>1024||!/^https?:\/\//i.test(value.homePage)||resolveAddress(value.homePage,{web:true})!==value.homePage))throw Error("Invalid home page");}
    snapshot(){return {...this.value};}
    // Only known keys are stored, and a saved record must stay loadable.
    update(changes){const next={...this.value};for(const key of Object.keys(this.value))if(Object.hasOwn(changes,key))next[key]=changes[key];this.validate(next);
      if(JSON.stringify(next).length>4096)throw Error("Settings too large");if(this.persist)this.persist(JSON.stringify(next),next);this.value=next;return this.snapshot();}
  }
  const MAX_BOOKMARKS=128;
  function bookmarkRecord(url,title){
    if(typeof url!=="string"||!/^https?:\/\//i.test(url))throw new Error("Only web pages can be bookmarked");
    const checked=resolveAddress(url,{web:true});
    return {url:checked,title:typeof title==="string"&&title.trim()?title.trim().slice(0,160):checked};
  }
  class Bookmarks {
    constructor(serialized="[]",persist=()=>{}){
      this.items=[];this.persist=persist;this.revision=0;
      let records=[];try{if(typeof serialized==="string"&&serialized.length<=524288)records=JSON.parse(serialized);}catch(error){}
      if(Array.isArray(records))for(const entry of records.slice(0,MAX_BOOKMARKS))try{
        const item=bookmarkRecord(entry?.url,entry?.title);if(!this.has(item.url))this.items.push(item);
      }catch(error){}
    }
    has(url){return this.items.some(item=>item.url===url);}
    snapshot(){return this.items.map(item=>({...item}));}
    toggle(url,title){
      const item=bookmarkRecord(url,title),exists=this.has(item.url);
      if(!exists&&this.items.length>=MAX_BOOKMARKS)throw new Error("Bookmark limit reached (128)");
      const next=exists?this.items.filter(entry=>entry.url!==item.url):[...this.items,item];
      this.persist(JSON.stringify(next));this.items=next;++this.revision;return !exists;
    }
    remove(url){if(!this.has(url))return false;const next=this.items.filter(item=>item.url!==url);this.persist(JSON.stringify(next));this.items=next;++this.revision;return true;}
  }
  const MAX_HISTORY=256;
  class History {
    constructor(serialized="[]",persist=()=>{}){
      this.items=[];this.persist=persist;this.revision=0;
      let records=[];try{if(typeof serialized==="string"&&serialized.length<=524288)records=JSON.parse(serialized);}catch(_error){}
      if(Array.isArray(records))for(const entry of records.slice(0,MAX_HISTORY))try{
        const item=bookmarkRecord(entry?.url,entry?.title);
        if(!Number.isSafeInteger(entry?.lastVisit)||entry.lastVisit<=0||entry.lastVisit>8640000000000000)continue;
        if(this.items.some(old=>old.url===item.url))continue;
        this.items.push({...item,lastVisit:entry.lastVisit,visits:Number.isSafeInteger(entry.visits)&&entry.visits>0?Math.min(entry.visits,1000000):1});
      }catch(_error){}
      this.items.sort((a,b)=>b.lastVisit-a.lastVisit);
    }
    snapshot(limit=MAX_HISTORY){return this.items.slice(0,Math.max(0,Math.min(MAX_HISTORY,limit))).map(item=>({...item}));}
    visit(url,title,when=Date.now()){
      const item=bookmarkRecord(url,title);
      if(!Number.isSafeInteger(when)||when<=0||when>8640000000000000)throw Error("Invalid visit time");
      const previous=this.items.find(old=>old.url===item.url);
      const next=[{...item,lastVisit:when,visits:previous?Math.min(previous.visits+1,1000000):1},...this.items.filter(old=>old.url!==item.url)].slice(0,MAX_HISTORY);
      let serialized=JSON.stringify(next);while(serialized.length>524288){next.pop();serialized=JSON.stringify(next);}
      this.persist(serialized);this.items=next;++this.revision;
    }
    remove(url){if(!this.items.some(item=>item.url===url))return false;const next=this.items.filter(item=>item.url!==url);this.persist(JSON.stringify(next));this.items=next;++this.revision;return true;}
    clear(){if(!this.items.length)return;this.persist("[]");this.items=[];++this.revision;}
  }
  // Session-only list, like Firefox's "Recently closed tabs".
  const MAX_CLOSED_TABS=10;
  class ClosedTabs {
    constructor(){this.items=[];this.revision=0;}
    push(url,title,when=Date.now()){let item;try{item=bookmarkRecord(url,title);}catch(_error){return false;}
      this.items=[{...item,closed:when},...this.items.filter(old=>old.url!==item.url)].slice(0,MAX_CLOSED_TABS);++this.revision;return true;}
    peek(index=0){const item=Number.isInteger(index)?this.items[index]:undefined;return item?{...item}:null;}
    remove(index){if(!Number.isInteger(index)||index<0||index>=this.items.length)return false;this.items.splice(index,1);++this.revision;return true;}
    clear(){if(this.items.length){this.items=[];++this.revision;}}
    snapshot(){return this.items.map(item=>({...item}));}
  }
  // Open web tabs for "Open previous tabs" at startup (bounded to the tab cap).
  function sessionURLs(serialized){
    let records=[];try{if(typeof serialized==="string"&&serialized.length<=8192)records=JSON.parse(serialized);}catch(_error){}
    const urls=[];if(Array.isArray(records))for(const url of records.slice(0,16))try{const item=bookmarkRecord(url,"");if(!urls.includes(item.url)&&urls.length<3)urls.push(item.url);}catch(_error){}
    return urls;
  }
  // Necko status codes from nsError.h, shown as Firefox-style messages.
  const LOAD_ERRORS=Object.freeze({0x804b000a:"The address isn’t valid",0x804b000d:"Unable to connect",0x804b000e:"The connection has timed out",0x804b0010:"Offline — check the console network connection",
    0x804b0013:"This address is restricted",0x804b0014:"The connection was reset",0x804b001b:"Content encoding error",0x804b001d:"Corrupted content error",0x804b001e:"Server not found",
    0x804b001f:"The page isn’t redirecting properly",0x804b0024:"The server sent an empty response",0x804b002a:"Proxy server not found",0x804b0047:"The connection was interrupted",0x804b0048:"The proxy server is refusing connections",
    0x804b004a:"File type not allowed",0x804b004c:"The page was only partly received",0x804b0052:"Secure connection failed",0x804b0055:"The connection has timed out",0x804b0056:"Secure site not available",0x80004004:"The load was interrupted"});
  // about:neterror?e=<code> names used by Gecko's error pages.
  const ERROR_PAGES=Object.freeze({dnsNotFound:"Server not found",connectionFailure:"Unable to connect",netTimeout:"The connection has timed out",netReset:"The connection was reset",
    netInterrupt:"The connection was interrupted",netOffline:"Offline — check the console network connection",redirectLoop:"The page isn’t redirecting properly",
    unknownSocketType:"Unable to connect",proxyConnectFailure:"The proxy server is refusing connections",proxyResolveFailure:"Proxy server not found",malformedURI:"The address isn’t valid",
    contentEncodingError:"Content encoding error",corruptedContentErrorv2:"Corrupted content error",nssFailure2:"Secure connection failed",nssBadCert:"Warning: potential security risk",
    httpErrorPage:"The server returned an error",serverError:"The server returned an error",blockedByPolicy:"Blocked page"});
  function errorPageMessage(documentURI){
    const code=/[?&]e=([A-Za-z0-9]+)/.exec(documentURI)?.[1]||"";
    return (Object.hasOwn(ERROR_PAGES,code)?ERROR_PAGES[code]:"This page couldn’t be loaded")+(code?" ("+code+")":"");
  }
  function loadError(status){
    const code=status>>>0,hex=" (0x"+code.toString(16)+")";
    if(Object.hasOwn(LOAD_ERRORS,code))return LOAD_ERRORS[code]+hex;
    if((code>>>16)===0x805a)return "Secure connection failed"+hex;
    return "Load failed"+hex;
  }
  class State {
    constructor() {
      this.location = HOME; this.title = "Home"; this.busy = false;
      this.error = ""; this.message = "Initializing content tab";
      this.canBack = this.canForward = false;
      this.requested = HOME; this.editing = false; this.security = ""; this.issuer = "";
    }
    begin(uri) {this.requested = uri; this.busy = true; this.error = ""; this.message = "Loading…"; this.issuer = "";}
    locationChanged(uri) {this.location = uri;}
    stopped(status, documentURI = "") {
      this.busy = false;
      // Docshell replaces a failed load with an error page whose own stop is
      // successful; keep the failure visible instead of reporting "Ready".
      const errorPage = /^about:(?:neterror|certerror)\?/.exec(documentURI || "");
      if ((status >>> 0) === 0 && errorPage) {this.error = errorPageMessage(documentURI); this.message = this.error;}
      else if ((status >>> 0) === 0) {this.error = ""; this.message = "Ready";}
      // NS_BINDING_ABORTED: the user pressed Stop or started another load.
      else if ((status >>> 0) === 0x804b0002) {this.error = ""; this.message = "Stopped";}
      // NS_BINDING_RETARGETED: handed to another handler (not an error).
      else if ((status >>> 0) === 0x804b0004) {this.error = ""; this.message = "Ready";}
      else {this.error = loadError(status); this.message = this.error;}
    }
    history(back, forward) {this.canBack = back === true; this.canForward = forward === true;}
    snapshot() {return {location:this.location,title:this.title,busy:this.busy,error:this.error,
      message:this.message,canBack:this.canBack,canForward:this.canForward,requested:this.requested,editing:this.editing,security:this.security,issuer:this.issuer};}
  }
  class Controller {
    constructor() {this.previous = 0; this.direction = 0; this.nextRepeat = 0; this.nextDelete = 0; this.editing = false; this.blocked = 0;}
    update(buttons, now, editing = false) {
      // Never reuse a held opener, Enter or Close as an action in the next mode.
      if(editing!==this.editing){this.editing=editing;this.blocked|=this.previous;this.direction=0;}
      this.blocked &= buttons;buttons &= ~this.blocked;
      const pressed = buttons & ~this.previous; this.previous = buttons;
      const actions = [];
      const direction = buttons & (Buttons.left | Buttons.right | Buttons.up | Buttons.down);
      const ambiguousDirection = direction && (direction & (direction - 1)) !== 0;
      for (const [name, bit] of Object.entries(Buttons))
        if ((pressed & bit) && !(ambiguousDirection && (bit & direction)) &&
            !(name === "cross" && (pressed & ~Buttons.cross))) actions.push(name);
      // Opposing/multiple directions are ignored; repeats are bounded to one
      // event per callback, never catch up with a flood after a delayed frame.
      if (direction && (direction & (direction - 1)) === 0) {
        if (direction !== this.direction) this.nextRepeat = now + 400;
        else if (now >= this.nextRepeat) {
          const name = Object.keys(Buttons).find(key => Buttons[key] === direction);
          if (!(pressed & direction)) actions.push(name);
          this.nextRepeat = now + 100;
        }
      }
      if(editing && (buttons & Buttons.address)){
        if(pressed & Buttons.address)this.nextDelete=now+400;
        else if(now>=this.nextDelete){actions.push('address');this.nextDelete=now+100;}
      }
      this.direction = direction; return actions;
    }
  }
  return Object.freeze({HOME, LAN, HTTPS, GOOGLE, MAX_TABS:3, MAX_BOOKMARKS, MAX_HISTORY, MAX_CLOSED_TABS, Bookmarks, History, ClosedTabs, Settings, SEARCH_ENGINES, SEARCH_KEYWORDS, Buttons, State, Controller,
    resolveAddress, homeAddress, navigationText, sessionURLs, loadError});
})();
