#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build isolated pinned Mesa/RADV against the browser's private native runtime.

Does not link a browser, select a GPU, deploy, or alter the SDK. orbis-compat is
used for headers only: its global libc/allocator/thread/clock replacement archive
is deliberately NOT used even for configure checks. A single genuine sysconf
forwarder is supplied to cross-link probes instead.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PINS = {'mesa-ps4': '1a59cc147b54e3970814b37313e2f27357672e9d',
        'orbis-compat': '6922a7b6f4291a28edd239f1a4db50ed7aa00359',
        'orbis-porting-kit': '213b0c38ff25ea7ca402c8844a6494086d0f1cae'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_changed(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def run(command, env=None, cwd=ROOT):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


OFFSCREEN_FILES=('src/vulkan/wsi/meson.build','src/vulkan/wsi/wsi_common_headless.c',
                 'src/egl/drivers/dri2/platform_orbis.c')
DISPATCH_FILES=('src/mesa/glapi/shared-glapi/core.c', 'src/mesa/main/context.c')
MODIFIED_FILES=OFFSCREEN_FILES+DISPATCH_FILES


def patch_dispatch(text, name):
    """Observe the exact allocation/copy/fill boundaries; never replace storage."""
    declaration='extern void orbis_mesa_dispatch_checkpoint(void *, size_t, unsigned);\n\n'
    if name.endswith('core.c'):
        old='struct _glapi_table *\n_glapi_new_nop_table(void)\n{'
        new=declaration+old
        if text.count(old)!=1:raise RuntimeError('Pinned Mesa GLapi allocation entry drift')
        text=text.replace(old,new)
        old='   if (table)\n      memcpy(table, table_noop_array, _gloffset_COUNT * sizeof(_glapi_proc));'
        new=('   orbis_mesa_dispatch_checkpoint(table, _gloffset_COUNT * sizeof(_glapi_proc), 1);\n'
             '   if (table)\n      memcpy(table, table_noop_array, _gloffset_COUNT * sizeof(_glapi_proc));\n'
             '   orbis_mesa_dispatch_checkpoint(table, _gloffset_COUNT * sizeof(_glapi_proc), 2);')
    else:
        old='struct _glapi_table *\n_mesa_new_nop_table(bool glthread)\n{'
        new=declaration+old
        if text.count(old)!=1:raise RuntimeError('Pinned Mesa dispatch fill entry drift')
        text=text.replace(old,new)
        old=('   if (glthread) {\n'
             '      _glapi_proc *entry = (_glapi_proc *) table;\n'
             '      for (unsigned i = 0; i < _gloffset_COUNT; i++)\n'
             '         entry[i] = (_glapi_proc)glthread_nop;\n   }')
        new=('   if (glthread) {\n'
             '      orbis_mesa_dispatch_checkpoint(table, _gloffset_COUNT * sizeof(_glapi_proc), 3);\n'
             '      _glapi_proc *entry = (_glapi_proc *) table;\n'
             '      for (unsigned i = 0; i < _gloffset_COUNT; i++)\n'
             '         entry[i] = (_glapi_proc)glthread_nop;\n'
             '      orbis_mesa_dispatch_checkpoint(table, _gloffset_COUNT * sizeof(_glapi_proc), 4);\n   }')
    if text.count(old)!=1:raise RuntimeError('Pinned Mesa dispatch write boundary drift: '+name)
    return text.replace(old,new)


def patch_offscreen(mesa):
    """Preserve genuine headless WSI and add allocation-neutral dispatch evidence."""
    changes=[];report=[]
    for name in MODIFIED_FILES:
        original=subprocess.check_output(['git','-C',mesa,'show','HEAD:'+name])
        text=original.decode()
        if name in DISPATCH_FILES:
            text=patch_dispatch(text,name)
        elif name.endswith('meson.build'):
            old="if with_platform_orbis\n  files_vulkan_wsi += files('wsi_orbis.c')\nendif"
            if text.count(old)!=1:raise RuntimeError('Pinned Mesa scanout source list drift')
            text=text.replace(old,'# OrbisFox owns VideoOut outside Mesa; use genuine headless WSI only.')
        elif name.endswith('wsi_common_headless.c'):
            if text.count('#ifdef HAVE_ORBIS_PLATFORM')!=11 or text.count('#ifndef HAVE_ORBIS_PLATFORM')!=2:
                raise RuntimeError('Pinned Mesa headless platform conditions drift')
            text=text.replace('/** VK_EXT_headless_surface */',
                '/** VK_EXT_headless_surface */\n\n/* OrbisFox: no second scanout owner. Keep real generic headless WSI. */\n#define ORBISFOX_MESA_OFFSCREEN_ONLY 1')
            text=text.replace('#ifdef HAVE_ORBIS_PLATFORM',
                '#if defined(HAVE_ORBIS_PLATFORM) && !defined(ORBISFOX_MESA_OFFSCREEN_ONLY)')
            text=text.replace('#ifndef HAVE_ORBIS_PLATFORM',
                '#if !defined(HAVE_ORBIS_PLATFORM) || defined(ORBISFOX_MESA_OFFSCREEN_ONLY)')
        else:
            old='EGL_WINDOW_BIT | EGL_PBUFFER_BIT'
            if text.count(old)!=1:raise RuntimeError('Pinned Mesa EGL surface capabilities drift')
            text=text.replace(old,'EGL_PBUFFER_BIT /* OrbisFox: pbuffer only, native worker owns scanout */')
        patched=text.encode();path=mesa/name
        if path.read_bytes() not in (original,patched):
            raise RuntimeError('Unrecognized Mesa source modification: '+name)
        changes.append((path,patched))
        report.append({'path':name,'upstream_sha256':hashlib.sha256(original).hexdigest(),
                       'patched_sha256':hashlib.sha256(patched).hexdigest()})
    # Validate every file before changing any; repeat application is byte/mtime stable.
    for path,data in changes:write_changed(path,data)
    return report


def prepare_sources(cache=None):
    for name, revision in PINS.items():
        directory = ROOT/'.deps'/name
        if not (directory/'.git').is_dir():
            directory.parent.mkdir(parents=True, exist_ok=True)
            reference = cache/name if cache else None
            origin = str(reference) if reference and (reference/'.git').is_dir() else 'https://github.com/orbis-ports/'+name+'.git'
            # Independent objects/worktree, never mutate the reference or share
            # its generated files. No hard links into another active project.
            run(['git', 'clone', '--no-hardlinks', '--no-checkout', origin, directory])
            run(['git', '-C', directory, 'checkout', '--detach', revision])
        actual = subprocess.check_output(['git', '-C', directory, 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revision:
            raise RuntimeError(name+': wrong pinned revision: '+actual)
        exclusions=[':!'+path for path in MODIFIED_FILES] if name=='mesa-ps4' else []
        run(['git', '-C', directory, 'diff', '--exit-code', 'HEAD', '--', '.', *exclusions])


def archive_members(path, thin_root=None):
    """Preserve duplicate names; thin references need explicit read confinement."""
    path=Path(path)
    data=path.read_bytes()
    if data.startswith(b'!<thin>\n') and thin_root is not None:
        names=subprocess.check_output(['llvm-ar','t',path],text=True).splitlines()
        if not names:
            raise ValueError('Empty thin archive inventory')
        for name in names:
            member=(path.parent/name).resolve()
            if not member.is_relative_to(Path(thin_root).resolve()) or not member.is_file():
                raise ValueError('Missing/out-of-tree thin member: '+name)
            body=member.read_bytes()
            if not body.startswith(b'\x7fELF'):
                raise ValueError('Non-ELF thin member: '+name)
            yield name,body
        return
    if not data.startswith(b'!<arch>\n'):
        raise ValueError('Expected ordinary archive: '+str(path))
    offset=8;strings=b''
    while offset<len(data):
        header=data[offset:offset+60]
        if len(header)!=60 or header[58:]!=b'`\n':
            raise ValueError('Invalid archive header')
        size=int(header[48:58]);raw=header[:16].decode('ascii').strip()
        body=data[offset+60:offset+60+size]
        if len(body)!=size:
            raise ValueError('Truncated archive member')
        offset+=60+size+(size&1)
        if raw=='//':strings=body;continue
        if raw in ('/','/SYM64/'):continue
        if raw.startswith('#1/'):
            length=int(raw[3:])
            if length>len(body):raise ValueError('Truncated BSD name')
            name=body[:length].rstrip(b'\0').decode();body=body[length:]
        elif raw.startswith('/'):
            index=int(raw[1:])
            if index>=len(strings):raise ValueError('Invalid GNU name index')
            name=strings[index:].split(b'/\n',1)[0].decode()
        else:name=raw.rstrip('/')
        if name.startswith('__.SYMDEF'):continue
        if not body.startswith(b'\x7fELF'):
            raise ValueError('Non-ELF archive member: '+name)
        yield name,body


def deduplicate(archives, forced, output, thin_root=None):
    """Omit ONLY byte-identical utility objects already in the forced ICD."""
    hashes={hashlib.sha256(body).digest() for _,body in archive_members(forced,thin_root)}
    output.mkdir(parents=True,exist_ok=True)
    removed=[];results=[]
    for index,archive in enumerate(archives):
        data=bytearray(b'!<arch>\n');count=0
        for name,body in archive_members(archive,thin_root):
            digest=hashlib.sha256(body).digest()
            if digest in hashes:
                removed.append({'archive':str(archive),'member':name,'sha256':digest.hex()})
                continue
            # Stable unique member names do not collapse duplicate basenames.
            header=(('m'+str(count)+'.o/').ljust(16)+'0'.ljust(12)+'0'.ljust(6)+
                    '0'.ljust(6)+'100644'.ljust(8)+str(len(body)).ljust(10)+'`\n')
            data+=header.encode('ascii')+body
            if len(body)&1:data+=b'\n'
            count+=1
        target=output/('mesa-'+str(index)+'.a')
        # llvm-ar's symbol index is part of the final bytes, so compare a fully
        # indexed candidate before replacing an already stable output.
        pending=target.with_suffix('.pending.a');pending.write_bytes(data)
        run(['llvm-ranlib',pending])
        write_changed(target,pending.read_bytes());pending.unlink()
        results.append(target)
    return results,removed


BRIDGE_SOURCES = ('src/ps4/mesa_runtime_bridge.cpp', 'src/ps4/mesa_gnm_stubs.S',
                  'include/orbisfox/mesa_binding.h', 'include/orbisfox/mesa_gnm_symbols.inc')


def build_runtime_bridge(sdk, overlay, runtime, output, env):
    """Compile the same real C definitions/static thunks for BOTH link stages."""
    output.mkdir(parents=True, exist_ok=True)
    sources = {name: sha(ROOT/name) for name in BRIDGE_SOURCES}
    objects = []
    for name, compiler in ((BRIDGE_SOURCES[0], 'clang++'), (BRIDGE_SOURCES[1], 'clang')):
        target = output/(Path(name).stem+'.o')
        pending = target.with_suffix('.pending.o')
        flags = ['--target=x86_64-pc-freebsd12-elf', '-mno-red-zone', '-fPIC', '-O2',
                 '-I'+str(ROOT/'include')]
        if compiler == 'clang++':
            flags += ['-std=c++17', '-fno-exceptions', '-fno-rtti', '-nostdinc++',
                      '-isystem', str(runtime/'include/c++/v1'),
                      '-isystem', str(overlay), '-isystem', str(sdk/'include')]
        run([compiler, *flags, '-c', ROOT/name, '-o', pending], env)
        write_changed(target, pending.read_bytes());pending.unlink()
        objects.append({'path':str(target.relative_to(ROOT)), 'sha256':sha(target)})
    if sources != {name:sha(ROOT/name) for name in BRIDGE_SOURCES}:
        raise RuntimeError('Mesa runtime bridge changed during compilation')
    return {'sources':sources, 'objects':objects}


def link_response(forced, archives, bridge=()):
    tokens=['--start-group',*map(str,bridge),'--whole-archive',str(forced),'--no-whole-archive',
            *map(str,archives),'--end-group']
    return '\n'.join(shlex.quote(token) for token in tokens)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--source-cache',type=Path,help='Optional existing public Git checkouts, read only')
    parser.add_argument('--tool-bin',type=Path,help='Meson/Python virtualenv bin directory')
    parser.add_argument('--runtime',type=Path,default=ROOT/'.deps/libcxx-orbis')
    parser.add_argument('--sdk-overlay',type=Path,default=ROOT/'.deps/sdk-overlay')
    parser.add_argument('--sdk',type=Path,default=Path(os.environ.get('OO_PS4_TOOLCHAIN',ROOT/'.deps/OpenOrbis/PS4Toolchain')))
    parser.add_argument('--configure-only',action='store_true')
    args=parser.parse_args()
    producer_sha=sha(Path(__file__))
    if not 1<=args.jobs<=16:parser.error('jobs must be 1..16')
    runtime=args.runtime.resolve();sdk=args.sdk.resolve();overlay=args.sdk_overlay.resolve()
    for path in (runtime/'include/c++/v1/__config',runtime/'lib/libc++.a',
                 runtime/'lib/libc++abi.a',runtime/'lib/libunwind.a',
                 sdk/'lib/crt1.o',overlay/'bits/alltypes.h'):
        if not path.is_file():raise RuntimeError('Missing native runtime input: '+str(path))
    prepare_sources(args.source_cache.resolve() if args.source_cache else None)
    compat=ROOT/'.deps/orbis-compat';kit=ROOT/'.deps/orbis-porting-kit';mesa=ROOT/'.deps/mesa-ps4'
    offscreen_patches=patch_offscreen(mesa)
    out=ROOT/'build/orbis-mesa';out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,OO_PS4_TOOLCHAIN=str(sdk),PKG_CONFIG_PATH='',PKG_CONFIG_LIBDIR=str(out/'empty-pkgconfig'))
    if args.tool_bin:env['PATH']=str(args.tool_bin.resolve())+os.pathsep+env['PATH']
    (out/'empty-pkgconfig').mkdir(exist_ok=True)
    # Headers map sysconf to orbis_sysconf. Use a real SDK forwarding call for
    # configure checks, not the compatibility archive's allocator/C++ interposer.
    # The application's forwarder will go through its existing --wrap=sysconf.
    bootstrap=out/'configure-sysconf.c'
    write_changed(bootstrap,b'#include <unistd.h>\nlong orbis_sysconf(int name) { return sysconf(name); }\n')
    run(['clang','--target=x86_64-pc-freebsd12-elf','-mno-red-zone','-fPIC',
         '-isystem',overlay,'-isystem',sdk/'include','-c',bootstrap,'-o',out/'configure-sysconf.o'],env)
    probe_archive=out/'configure-sysconf.a'
    run(['llvm-ar','rcs',probe_archive,out/'configure-sysconf.o'],env)
    cross=(kit/'cmake/orbis.ini.in').read_text()
    substitutions={'OO_PS4_TOOLCHAIN':sdk,'ORBIS_COMPAT':compat,'ORBIS_KIT':kit,
                   'ORBIS_CROSS':out/'empty-cross','ORBIS_CC':shutil.which('clang'),
                   'ORBIS_CXX':shutil.which('clang++'),'ORBIS_AR':shutil.which('llvm-ar'),
                   'ORBIS_STRIP':shutil.which('llvm-strip')}
    for key,value in substitutions.items():
        if value is None:raise RuntimeError('Missing compiler tool: '+key)
        cross=cross.replace('@'+key+'@',str(value))
    cross=cross.replace("'-fPIC'","'-fPIC','-mno-red-zone'")
    cross=cross.replace("'-isystem','"+str(sdk/'include/c++/v1')+"'",
                        "'-isystem','"+str(runtime/'include/c++/v1')+"'")
    cross=cross.replace("'-isystem','"+str(sdk/'include')+"'",
                        "'-isystem','"+str(overlay)+"','-isystem','"+str(sdk/'include')+"'")
    cross=cross.replace("'-L"+str(sdk/'lib')+"'","'-L"+str(runtime/'lib')+"','-L"+str(sdk/'lib')+"'")
    cross=cross.replace("'-lc++'","'-lc++','-lc++abi','-lunwind'")
    cross=cross.replace("'-lorbis-compat'",repr(str(probe_archive)))
    cross=cross.replace('cpp_args = [',"cpp_args = ['-fno-exceptions','-fno-rtti',")
    if '-lorbis-compat' in cross:raise RuntimeError('Compatibility interposer leaked into configure')
    if '@' in cross:raise RuntimeError('Unexpanded cross-file variable')
    cross_path=out/'orbis.ini';write_changed(cross_path,cross.encode())
    # zlib's upstream wrap contains its source SHA; Meson checks the download.
    run(['meson','subprojects','download','zlib'],env,mesa)
    options=['-Dplatforms=orbis','-Dvulkan-drivers=amd','-Dgallium-drivers=zink',
             '-Dopengl=true','-Dgles1=enabled','-Dgles2=enabled','-Degl=enabled',
             '-Dglx=disabled','-Dgbm=disabled','-Dglvnd=disabled','-Dvideo-codecs=',
             '-Dllvm=disabled','-Dxmlconfig=disabled','-Dbuildtype=release',
             '-Dzlib=enabled','-Dshader-cache=disabled','-Dforce_fallback_for=zlib',
             '-Dradv-build-id='+PINS['mesa-ps4'],'-Ddefault_library=static',
             '-Dwrap_mode=nodownload','-Dzstd=disabled','-Dvalgrind=disabled',
             '-Dlmsensors=disabled','-Dlibunwind=disabled']
    build=out/'native'
    # Meson treats cross-file built-in args as initial values. Explicitly update
    # them on reconfigure and discard feature-test caches, otherwise an earlier
    # failed link probe can silently remain a false missing-API result.
    builtin_args=[]
    for line in cross.splitlines():
        key,separator,value=line.partition('=')
        if separator and key.strip() in ('c_args','cpp_args','c_link_args','cpp_link_args'):
            builtin_args.append('-D'+key.strip()+'='+repr(ast.literal_eval(value.strip())))
    run(['meson','setup',*(['--reconfigure','--clearcache'] if (build/'build.ninja').exists() else []),
         build,mesa,'--cross-file',cross_path,*builtin_args,*options],env)
    report={'sources':PINS,'native_build_completed':False,'browser_linked':False,
            'console_tested':False,'runtime':str(runtime),'sdk':str(sdk),
            'private_runtime_archives':{name:sha(runtime/'lib'/name) for name in ('libc++.a','libc++abi.a','libunwind.a')},
            'cross_file_sha256':sha(cross_path),'options':options,
            'orbis_compat_runtime_archive_linked':False,'archives':[],
            'offscreen_only':True,'source_modifications':offscreen_patches}
    if not args.configure_only:
        run(['ninja','-C',build,'-j',args.jobs],env)
        gallium=list(build.glob('src/gallium/targets/dri/libgallium-*.a'))
        if len(gallium)!=1:raise RuntimeError('Expected exactly one Gallium archive')
        radv=build/'src/amd/vulkan/libvulkan_radeon.a'
        originals=sorted(path for path in build.rglob('*.a') if path!=radv)
        if len(originals)!=13 or not all(path.is_file() for path in (radv,build/'src/egl/libEGL.a',build/'subprojects/zlib-1.3.1/libz.a')):
            raise RuntimeError('Pinned native Mesa archive inventory changed')
        archives,removed=deduplicate(originals,radv,out/'closure',thin_root=build)
        report['archives']=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'whole_archive':False} for p in archives]
        report['archives'].append({'path':str(radv.relative_to(ROOT)),'sha256':sha(radv),'whole_archive':True})
        report['input_archives']=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in [*originals,radv]]
        report['identical_members_removed']=removed
        # A linker response avoids moz.build's conversion of bare absolute
        # archive OS_LIBS into incorrect -l/path names. The ICD is intentionally
        # whole; all remaining archives are lazy and only exact copies removed.
        report['runtime_bridge']=build_runtime_bridge(sdk,overlay,runtime,out/'runtime',env)
        bridge=[ROOT/item['path'] for item in report['runtime_bridge']['objects']]
        write_changed(out/'link-inputs.rsp',link_response(radv,archives,bridge).encode())
        report['link_response_sha256']=sha(out/'link-inputs.rsp')
        if sha(Path(__file__))!=producer_sha:
            raise RuntimeError('Canonical Mesa producer changed during build; refusing stale report')
        report['producer_sha256']=producer_sha
        report['native_build_completed']=True
    write_changed(out/'build-report.json',(json.dumps(report,indent=2)+'\n').encode())


if __name__=='__main__':
    main()
