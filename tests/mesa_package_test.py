# SPDX-License-Identifier: MIT
"""Experimental package identity/profile isolation and emitted SELF metadata."""
import runpy
import struct
import subprocess
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = runpy.run_path(str(ROOT/'scripts/gecko-package-identity.py'))
PACKAGE = runpy.run_path(str(ROOT/'scripts/package.py'))


class MesaPackageTests(unittest.TestCase):
    def test_identity_is_separate_fixed_and_path_confined(self):
        normal = IDENTITY['package_identity']()
        mesa = IDENTITY['package_identity'](True)
        for key in ('title_id','content_id','package_name','profile'):
            self.assertNotEqual(normal[key],mesa[key])
        self.assertEqual(IDENTITY['report_identity']({'experimental_mesa':True}),mesa)
        for bad in ({'experimental_mesa':'true'},
                    {'experimental_mesa':True,'package':'../other.pkg'},
                    {'experimental_mesa':True,'package_identity':normal}):
            with self.assertRaises(ValueError):IDENTITY['report_identity'](bad)

    def test_profile_comes_from_native_allowlist_not_gpu_success(self):
        source=(ROOT/'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        helper=source[source.index('function getTrustedProfilePath'):source.index('// Bounded synchronous')]
        script=r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const context={};vm.runInNewContext(HELPER,context);
for(const value of ['/data/orbisfox/gecko-profile','/data/orbisfox/mesa-profile']) {
 const Cc={'@mozilla.org/process/environment;1':{getService(){return {get(name){assert.equal(name,'HOME');return value;}};}}};
 assert.equal(context.getTrustedProfilePath(Cc,{}),value);
}
for(const value of ['',undefined,'/tmp/profile','/data/orbisfox/mesa-profile/../gecko-profile']) {
 const Cc={'@mozilla.org/process/environment;1':{getService(){return {get(){return value;}};}}};
 assert.throws(()=>context.getTrustedProfilePath(Cc,{}));
}
'''
        import json
        subprocess.run(['node','-e',script.replace('HELPER',json.dumps(helper))],cwd=ROOT,check=True)
        native=(ROOT/'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('profilePath = "/data/orbisfox/mesa-profile"',native)
        self.assertIn('cachePath = "/data/orbisfox/mesa-cache"',native)

    def test_exact_self_metadata_rejects_truncation_paid_and_bad_bounds(self):
        auth=PACKAGE['AUTHINFO'];raw=PACKAGE['auth_info_bytes'](auth);paid=0x3800000000000035
        data=bytearray(288);struct.pack_into('<I',data,0,0x1d3d154f)
        struct.pack_into('<HH',data,12,32,256);struct.pack_into('<Q',data,16,len(data))
        data[32:]=(struct.pack('<QQ',136,paid)+raw[8:]).ljust(256,b'\0')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'eboot.bin';path.write_bytes(data)
            self.assertTrue(PACKAGE['verify_self'](path,auth,paid)['signature_verified'])
            with self.assertRaises(ValueError):PACKAGE['auth_info_bytes'](auth[:-6])
            with self.assertRaises(ValueError):PACKAGE['verify_self'](path,auth,paid+1)
            bad=bytearray(data);struct.pack_into('<Q',bad,32,133);path.write_bytes(bad)
            with self.assertRaises(ValueError):PACKAGE['verify_self'](path,auth,paid)
            bad=bytearray(data);struct.pack_into('<H',bad,14,65535);path.write_bytes(bad)
            with self.assertRaises(ValueError):PACKAGE['verify_self'](path,auth,paid)


if __name__=='__main__':unittest.main()
