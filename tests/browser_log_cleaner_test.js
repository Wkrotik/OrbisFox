'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('gecko/orbisfox/fixtures/browser-shell-host.js','utf8');
const helper=source.slice(source.indexOf('function createOrbisLogCleaner('),source.indexOf('function createOrbisFaviconCache('));
for(let cycle=0;cycle<32;++cycle){
  const nodes=new Map(),removed=[];
  const add=(path,kind='file')=>nodes.set(path,{path,kind});
  const root='/data/orbisfox',run=root+'/runs/run-0000000000000001-0000000000000002-0000000000000003-0000000000000004';
  add(root,'directory');add(root+'/runs','directory');add(run,'directory');
  for(const name of ['run-meta.json','gecko-load.log','gecko-load.log.child-22','gecko-heartbeat.log','heap-audit.log','gecko-first-frame.bgra'])add(run+'/'+name);
  add(run+'/user-notes.txt');add(run+'/platform-layout.log','symlink');
  add(root+'/startup-layout.log');add(root+'/profile','directory');add(root+'/profile/prefs.js');
  add(root+'/cache','directory');add(root+'/cache/user-file.log');add(root+'/diagnostics.enabled');add(root+'/heap-debug');
  add(root+'/runs/not-a-run','directory');add(root+'/runs/not-a-run/gecko-load.log');
  const symlinkRun=root+'/runs/run-0000000000000009-0000000000000002-0000000000000003-0000000000000004';add(symlinkRun,'symlink');
  class File {
    constructor(path){this.path=path;}
    initWithPath(path){this.path=path;}
    QueryInterface(){return this;}
    get leafName(){return this.path.split('/').at(-1);}
    exists(){return nodes.has(this.path);}
    isSymlink(){return nodes.get(this.path)?.kind==='symlink';}
    isDirectory(){return nodes.get(this.path)?.kind==='directory';}
    isFile(){return nodes.get(this.path)?.kind==='file';}
    get directoryEntries(){assert(this.isDirectory()&&!this.isSymlink());return [...nodes.keys()].filter(p=>p!==this.path&&p.slice(0,p.lastIndexOf('/'))===this.path).map(p=>new File(p));}
    remove(recursive){assert.equal(recursive,false);assert(!this.isSymlink());if(this.isDirectory())assert.equal(this.directoryEntries.length,0);assert(nodes.delete(this.path));removed.push(this.path);}
  }
  const Cc={'@mozilla.org/file/local;1':{createInstance:()=>new File()}},context=vm.createContext({Cc,Ci:{nsIFile:{}}});
  vm.runInContext(helper,context);const clean=context.createOrbisLogCleaner(Cc,context.Ci);
  const result=clean();assert.equal(result.removed,7);assert(result.retained>=3);
  assert(nodes.has(root+'/profile/prefs.js')&&nodes.has(root+'/cache/user-file.log'));
  for(const p of [run+'/user-notes.txt',run+'/platform-layout.log',symlinkRun,root+'/diagnostics.enabled',root+'/heap-debug',root+'/runs/not-a-run/gecko-load.log'])assert(nodes.has(p));
  assert.equal(clean().removed,0);
  nodes.get(root).kind='symlink';assert.throws(()=>clean(),/Unsafe/);
}
assert(source.includes('host.setDiagnosticsEnabled(false);return createOrbisLogCleaner(Cc,Ci)();'));
console.log('Diagnostic cleanup:32 cycles actual helper, strict app/run/name scope, no recursive removal/symlink traversal/profile/cache/marker deletion');
