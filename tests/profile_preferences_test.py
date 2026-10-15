import subprocess
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ProfilePreferencesTests(unittest.TestCase):
    def test_explicit_restore_first_run_and_file_errors(self):
        code=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('gecko/orbisfox/fixtures/gecko-startup.js','utf8');
const context={};vm.createContext(context);vm.runInContext(source.slice(0,source.indexOf('(() => {\n  const Cc')),context);
let exists=true,isFile=true,size=100,reads=0,saved={bookmarks:'[{"url":"https://example.com/","title":"saved"}]',settings:'{"searchEngine":"bing","cursorSpeed":1.5}'},loaded={};
const file={exists:()=>exists,isFile:()=>isFile,get fileSize(){return size;},append(name){assert.equal(name,'prefs.js');this.leaf=name;}};
const profile={clone:()=>file},Ci={nsIPrefService:1},Cc={'@mozilla.org/preferences-service;1':{getService:()=>({readUserPrefsFromFile(value){assert.equal(value,file);++reads;loaded={...saved};}})}},host={log(){}};
assert.equal(context.restoreOrbisFoxPreferences(Cc,Ci,profile,host),true);assert.deepEqual(loaded,saved);assert.equal(reads,1);
loaded={};assert.equal(context.restoreOrbisFoxPreferences(Cc,Ci,profile,host),true);assert.deepEqual(loaded,saved);assert.equal(reads,2);
exists=false;assert.equal(context.restoreOrbisFoxPreferences(Cc,Ci,profile,host),false);assert.equal(reads,2);
exists=true;isFile=false;assert.throws(()=>context.restoreOrbisFoxPreferences(Cc,Ci,profile,host),/Invalid saved/);
isFile=true;size=4194305;assert.throws(()=>context.restoreOrbisFoxPreferences(Cc,Ci,profile,host),/Invalid saved/);assert.equal(reads,2);
const register=source.indexOf('directories.registerProvider(provider);'),restore=source.indexOf('restoreOrbisFoxPreferences(Cc,Ci,profile,host);'),policy=source.indexOf('applyRuntimePreferences();'),browser=source.indexOf('runOrbisFoxBrowserShell(');
assert(register<restore&&restore<policy&&policy<browser);
'''
        subprocess.run(['node','-e',code],cwd=ROOT,check=True,timeout=10)
