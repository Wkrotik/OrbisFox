/* Pure UI state/policy only. Gecko owns DOM, layout, history and navigation. */
"use strict";
var OrbisFoxShellModel = (() => {
  const HOME = "file:///app0/assets/offline.html";
  const LAN = "http://10.42.0.1:8765/orbisfox/offline.html";
  const HTTPS = "https://example.com/";
  const GOOGLE = "https://www.google.com/";
  const Buttons = Object.freeze({cross:1, reload:2, address:4, menu:8, cancel:16,
    left:32, right:64, up:128, down:256, previousTab:512, nextTab:1024});
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
      address="https://"+address;
    }
    const authority=/^https?:\/\/([^/?#]+)(?:[/?#]|$)/i.exec(address);
    if (!authority || /[@\\\s]/.test(authority[1]) || /[\\\s]/.test(address))
      throw new Error("Invalid web address or embedded credentials");
    return address;
  }
  const SEARCH_ENGINES=Object.freeze({google:"https://www.google.com/search?q=",duckduckgo:"https://duckduckgo.com/?q=",bing:"https://www.bing.com/search?q="});
  function homeAddress(text,engine="google"){
    if(typeof text!=="string"||!text.trim()||text.length>512||/[\x00-\x1f\x7f]/.test(text))throw new Error("Enter a search or website");
    const value=text.trim();return /^https?:\/\//i.test(value)||(!/\s/.test(value)&&value.includes("."))?value:(Object.hasOwn(SEARCH_ENGINES,engine)?SEARCH_ENGINES[engine]:SEARCH_ENGINES.google)+encodeURIComponent(value);
  }
  class Settings {
    constructor(serialized="{}",persist=null){
      this.persist=persist;this.value={searchEngine:"google",cursorSpeed:1,defaultZoom:100,colorScheme:"system"};
      try{if(typeof serialized!=="string"||serialized.length>2048)throw Error();const parsed=JSON.parse(serialized);this.validate(parsed);this.value={searchEngine:parsed.searchEngine,cursorSpeed:parsed.cursorSpeed,defaultZoom:parsed.defaultZoom??100,colorScheme:parsed.colorScheme??"system"};}catch(_error){}
    }
    validate(value){if(!value || typeof value.searchEngine!=="string" || !Object.hasOwn(SEARCH_ENGINES,value.searchEngine)||!Number.isFinite(value.cursorSpeed)||value.cursorSpeed<0.25||value.cursorSpeed>3||(value.defaultZoom!==undefined&&(!Number.isInteger(value.defaultZoom)||value.defaultZoom<50||value.defaultZoom>200||value.defaultZoom%10))||(value.colorScheme!==undefined&&!["system","light","dark"].includes(value.colorScheme)))throw Error("Invalid browser settings");}
    snapshot(){return {...this.value};}
    update(changes){const next={...this.value,...changes};this.validate(next);if(this.persist)this.persist(JSON.stringify(next),next);this.value=next;return this.snapshot();}
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
    clear(){if(!this.items.length)return;this.persist("[]");this.items=[];++this.revision;}
  }
  class State {
    constructor() {
      this.location = HOME; this.title = "Home"; this.busy = false;
      this.error = ""; this.message = "Initializing content tab";
      this.canBack = this.canForward = false;
      this.requested = HOME; this.editing = false;
    }
    begin(uri) {this.requested = uri; this.busy = true; this.error = ""; this.message = "Loading…";}
    locationChanged(uri) {this.location = uri;}
    stopped(status) {
      this.busy = false;
      if ((status >>> 0) === 0) {this.error = ""; this.message = "Ready";}
      else {this.error = "Load failed: 0x" + (status >>> 0).toString(16); this.message = this.error;}
    }
    history(back, forward) {this.canBack = back === true; this.canForward = forward === true;}
    snapshot() {return {location:this.location,title:this.title,busy:this.busy,error:this.error,
      message:this.message,canBack:this.canBack,canForward:this.canForward,requested:this.requested,editing:this.editing};}
  }
  class Controller {
    constructor() {this.previous = 0; this.direction = 0; this.nextRepeat = 0;}
    update(buttons, now) {
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
      this.direction = direction; return actions;
    }
  }
  return Object.freeze({HOME, LAN, HTTPS, GOOGLE, MAX_TABS:3, MAX_BOOKMARKS, MAX_HISTORY, Bookmarks, History, Settings, SEARCH_ENGINES, Buttons, State, Controller, resolveAddress, homeAddress});
})();
