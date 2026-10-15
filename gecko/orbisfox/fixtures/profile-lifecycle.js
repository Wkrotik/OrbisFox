/* Standard XPCShell profile-do-change lifecycle plus a genuine quota-backed
 * IndexedDB commit/close/reopen probe. No testing pref, storage disable or
 * assertion suppression. The sandbox is owned by chrome, never web content. */
function startOrbisFoxProfile(Cc, Ci, host, ssm, io) {
  const observers=Cc["@mozilla.org/observer-service;1"].getService(Ci.nsIObserverService);
  const quota=Cc["@mozilla.org/dom/quota-manager-service;1"].getService(Ci.nsIQuotaManagerService);
  const state={done:false,ok:false,error:null};
  let closed=false,db=null,transaction=null,sandbox=null;
  const timer=Cc["@mozilla.org/timer;1"].createInstance(Ci.nsITimer);
  const finish=(okay,error=null)=>{
    if(closed || state.done)return;
    state.done=true;state.ok=okay;state.error=error===null?null:String(error).slice(0,240);
    timer.cancel();if(db){db.close();db=null;}
    host.log("Gecko real profile / quota IndexedDB commit-close-reopen: "+JSON.stringify(state));
  };
  // The pinned XPCShell do_get_profile performs this after its provider is
  // registered. The QuotaManager observer must exist before notification.
  observers.notifyObservers(null,"profile-do-change","orbisfox-profile");
  host.log("Gecko standard profile-do-change delivered with real directory provider and quota service");
  try {
    const principal=ssm.createContentPrincipal(io.newURI("https://orbisfox-storage.invalid/"),{});
    sandbox=Components.utils.Sandbox(principal,{wantGlobalProperties:["indexedDB"],sandboxName:"OrbisFox owned persistent storage probe"});
    const factory=Components.utils.evalInSandbox("indexedDB",sandbox);
    const value="OrbisFox IndexedDB durable probe 🦊";
    const open=factory.open("orbisfox-durable-probe",1);
    open.onupgradeneeded=()=>{if(!open.result.objectStoreNames.contains("records"))open.result.createObjectStore("records");};
    open.onerror=()=>finish(false,open.error);
    open.onblocked=()=>finish(false,"Owned IndexedDB probe blocked");
    open.onsuccess=()=>{
      if(closed || state.done){open.result.close();return;}
      db=open.result;transaction=db.transaction("records","readwrite");
      transaction.objectStore("records").put(value,"message");
      transaction.onerror=()=>finish(false,transaction.error);
      transaction.onabort=()=>finish(false,transaction.error || "IndexedDB transaction aborted");
      transaction.oncomplete=()=>{
        transaction=null;db.close();db=null;
        if(closed || state.done)return;
        const reopen=factory.open("orbisfox-durable-probe",1);
        reopen.onerror=()=>finish(false,reopen.error);
        reopen.onblocked=()=>finish(false,"IndexedDB reopen blocked");
        reopen.onsuccess=()=>{
          if(closed || state.done){reopen.result.close();return;}
          db=reopen.result;transaction=db.transaction("records","readonly");
          const read=transaction.objectStore("records").get("message");let matches=false;
          read.onsuccess=()=>{matches=read.result===value;};
          transaction.onerror=()=>finish(false,transaction.error);
          transaction.onabort=()=>finish(false,transaction.error || "IndexedDB read aborted");
          transaction.oncomplete=()=>{transaction=null;finish(matches,matches?null:"IndexedDB durable value mismatch");};
        };
      };
    };
    timer.initWithCallback(()=>{if(transaction)try{transaction.abort();}catch(_){}finish(false,"20-second IndexedDB callback deadline");},20000,Ci.nsITimer.TYPE_ONE_SHOT);
  } catch(error){finish(false,error);}
  return {snapshot(){return {...state};},close(){
    if(closed)return;closed=true;timer.cancel();
    if(transaction)try{transaction.abort();}catch(_){}
    if(db){db.close();db=null;}
    // Caller closes all browser actors first, retaining the provider until
    // QuotaManager's real synchronous background shutdown acknowledges.
    let first=null;
    for(const topic of ["profile-change-net-teardown","profile-change-teardown","profile-before-change","profile-before-change-qm"])
      try{observers.notifyObservers(null,topic,"shutdown-persist");host.log("Gecko profile shutdown: "+topic);}
      catch(error){if(!first)first=error;host.log("ERROR: profile shutdown "+topic+": "+error);}
    sandbox=null;void quota;if(first)throw first;
  }};
}
