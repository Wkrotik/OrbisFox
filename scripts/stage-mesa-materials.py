#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage exact public Mesa dependency sources/notices; never archive the SDK.
This local test material is not a complete binary redistribution/relink sign-off.
"""
from pathlib import Path
import hashlib,json,os,shutil,subprocess
ROOT=Path(__file__).resolve().parent.parent
NAMES={'mesa-ps4','orbis-compat','orbis-porting-kit'}
MODIFIED={'src/vulkan/wsi/meson.build','src/vulkan/wsi/wsi_common_headless.c',
          'src/egl/drivers/dri2/platform_orbis.c',
          'src/mesa/glapi/shared-glapi/core.c','src/mesa/main/context.c'}
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def stage_mesa_materials(target,report):
    if set(report.get('sources',{}))!=NAMES or report.get('offscreen_only') is not True:
        raise ValueError('Unexpected Mesa source inventory/policy')
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    cache=ROOT/'build/orbis-mesa/public-source-archives';cache.mkdir(parents=True,exist_ok=True)
    files=[]
    env=dict(os.environ,GIT_NO_LAZY_FETCH='1')
    for name,pin in sorted(report['sources'].items()):
        source=ROOT/'.deps'/name
        if subprocess.check_output(['git','-C',source,'rev-parse','HEAD'],env=env,text=True).strip()!=pin:
            raise ValueError('Mesa source pin mismatch: '+name)
        archive=cache/(name+'-'+pin+'.tar.xz');checksum=archive.with_suffix('.sha256')
        if not (archive.exists() and checksum.exists() and checksum.read_text()==digest(archive)):
            pending=archive.with_suffix('.pending')
            with pending.open('wb') as output:
                git=subprocess.Popen(['git','-C',source,'archive','--format=tar','--prefix='+name+'/',pin],env=env,stdout=subprocess.PIPE)
                try:
                    compressed=subprocess.run(['xz','-T2','-3','-c'],stdin=git.stdout,stdout=output)
                finally:
                    git.stdout.close()
                status=git.wait()
            if status or compressed.returncode:
                pending.unlink(missing_ok=True);raise RuntimeError('Public source archive failed: '+name)
            pending.replace(archive);checksum.write_text(digest(archive))
        destination=target/archive.name;shutil.copyfile(archive,destination);files.append(destination)
    if {item['path'] for item in report['source_modifications']}!=MODIFIED:
        raise ValueError('Unexpected Mesa patched-file inventory')
    for item in report['source_modifications']:
        source=ROOT/'.deps/mesa-ps4'/item['path']
        if source.is_symlink() or digest(source)!=item['patched_sha256']:
            raise ValueError('Mesa modified source differs from built closure')
        destination=target/'patched-mesa'/item['path'];destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination);files.append(destination)
    public_files={
      'mesa-license.rst':ROOT/'.deps/mesa-ps4/docs/license.rst',
      'orbis-compat-LICENSE':ROOT/'.deps/orbis-compat/LICENSE',
      'orbis-porting-kit-LICENSE':ROOT/'.deps/orbis-porting-kit/LICENSE',
      'zlib-1.3.1.tar.gz':ROOT/'.deps/mesa-ps4/subprojects/packagecache/zlib-1.3.1.tar.gz',
      'zlib_1.3.1-1_patch.zip':ROOT/'.deps/mesa-ps4/subprojects/packagecache/zlib_1.3.1-1_patch.zip',
      'native-mesa-build-report.json':ROOT/'build/orbis-mesa/build-report.json',
      'orbis.ini':ROOT/'build/orbis-mesa/orbis.ini',
      'build-orbis-mesa.py':ROOT/'scripts/build-orbis-mesa.py',
    }
    for name in ('src/ps4/mesa_runtime_bridge.cpp','src/ps4/mesa_gnm_stubs.S',
                 'include/orbisfox/mesa_binding.h','include/orbisfox/mesa_gnm_symbols.inc'):
        public_files['native-bridge/'+Path(name).name]=ROOT/name
    for name,source in public_files.items():
        if source.is_symlink() or not source.is_file():raise ValueError('Missing public Mesa material: '+str(source))
        destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination);files.append(destination)
    manifest={'source_pins':report['sources'],'original_public_sources_plus_exact_patched_files':True,
      'sdk_code_or_assets_included':False,'binary_redistribution_signoff':False,
      'files':[{'path':str(p.relative_to(target)),'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(files)]}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest
