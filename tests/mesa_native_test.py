# SPDX-License-Identifier: MIT
import importlib.util
import shlex
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('orbis_mesa_builder',ROOT/'scripts/build-orbis-mesa.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


DISPATCH_CORE='''struct _glapi_table *
_glapi_new_nop_table(void)
{
   struct _glapi_table *table = malloc(_gloffset_COUNT * sizeof(_glapi_proc));

   if (table)
      memcpy(table, table_noop_array, _gloffset_COUNT * sizeof(_glapi_proc));
   return table;
}
'''
DISPATCH_CONTEXT='''struct _glapi_table *
_mesa_new_nop_table(bool glthread)
{
   struct _glapi_table *table = _glapi_new_nop_table();

   if (glthread) {
      _glapi_proc *entry = (_glapi_proc *) table;
      for (unsigned i = 0; i < _gloffset_COUNT; i++)
         entry[i] = (_glapi_proc)glthread_nop;
   }

   return table;
}
'''


class MesaNativeTests(unittest.TestCase):
    def test_render_thread_policy_precedes_egl_and_checks_visibility(self):
        source=r'''
#include "orbisfox/mesa_threading.h"
#include <cassert>
#include <cstdlib>
#include <cstring>
int main(){
 int sets=0,gets=0;
 auto setter=[&](const char* name,const char* value,int replace){
  assert(!strcmp(name,"mesa_glthread")&&!strcmp(value,"false")&&replace==1);++sets;return 0;
 };
 auto getter=[&](const char* name){assert(!strcmp(name,"mesa_glthread"));++gets;return "false";};
 assert(orbisfox::configure_mesa_render_thread_policy(setter,getter));assert(sets==1&&gets==1);
 auto fail=[&](const char*,const char*,int){++sets;return -1;};
 assert(!orbisfox::configure_mesa_render_thread_policy(fail,getter));assert(gets==1);
 assert(!orbisfox::configure_mesa_render_thread_policy(setter,[](const char*)->const char*{return nullptr;}));
 assert(!orbisfox::configure_mesa_render_thread_policy(setter,[](const char*){return "true";}));
 assert(setenv("mesa_glthread","true",1)==0);
 assert(setenv("ORBISFOX_UNRELATED_POLICY_TEST","keep",1)==0);
 assert(orbisfox::configure_mesa_render_thread_policy(setenv,getenv));
 assert(!strcmp(getenv("mesa_glthread"),"false"));
 assert(!strcmp(getenv("ORBISFOX_UNRELATED_POLICY_TEST"),"keep"));
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            cpp=Path(tmp)/'policy.cpp';cpp.write_text(source);binary=Path(tmp)/'policy'
            subprocess.run(['clang++','-std=c++20','-Wall','-Wextra','-Werror',
                            '-fsanitize=address,undefined','-I'+str(ROOT/'include'),str(cpp),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
        native=(ROOT/'src/ps4/native_mesa.cpp').read_text()
        self.assertLess(native.index('configure_mesa_render_thread_policy(setenv, getenv)'),
                        native.index('bindings_ready = bind_mesa_gnm'))
        main=(ROOT/'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('!prepare_native_mesa() || !probe_native_mesa_gpu()',main)

    def test_binding_fails_closed_and_retries_only_enoent(self):
        source=r'''
#include "orbisfox/mesa_binding.h"
#include <cassert>
#include <cstring>
#include <cstdint>
struct State {int found=-1,loads=0,lookups=0,fail=-1;int32_t error=int32_t(0x80020002u);bool entryFail=false,null=false;};
int32_t find(void* p){return static_cast<State*>(p)->found;}
int32_t load(void* p,const char* path,int32_t* entry){auto& s=*static_cast<State*>(p);++s.loads;
 assert(*entry==0); if(s.loads==1)assert(!strcmp(path,"libSceGnmDriver.sprx"));
 if(s.loads==2)assert(!strcmp(path,"/common/lib/libSceGnmDriver.sprx"));
 if(s.entryFail){*entry=-4;return 8;}
 if(s.loads==2 && s.error==int32_t(0x80020002u)){s.found=19;return 19;}return s.error;}
bool resolve(void* p,int32_t h,const char* name,void** out){auto& s=*static_cast<State*>(p);assert(h>=0&&name&&*name);
 int index=s.lookups++;if(index==s.fail)return false;*out=s.null?nullptr:reinterpret_cast<void*>(uintptr_t(index+1));return true;}
int main(){using namespace orbisfox;void* targets[mesa_gnm_symbol_count];
 auto reset=[&](){for(auto& p:targets)p=reinterpret_cast<void*>(uintptr_t(99));};
 State s;reset();assert(bind_mesa_gnm({&s,find,load,resolve},targets));assert(s.loads==2&&s.lookups==10);
 for(size_t i=0;i<10;i++)assert(targets[i]==reinterpret_cast<void*>(i+1));
 for(int fail=0;fail<10;fail++){s={};s.found=7;s.fail=fail;reset();assert(!bind_mesa_gnm({&s,find,load,resolve},targets));
 assert(s.loads==0);for(auto p:targets)assert(p==reinterpret_cast<void*>(uintptr_t(99)));}
 s={};s.error=int32_t(0x80020001u);reset();assert(!bind_mesa_gnm({&s,find,load,resolve},targets));assert(s.loads==1&&!s.lookups);
 s={};s.entryFail=true;assert(!bind_mesa_gnm({&s,find,load,resolve},targets));assert(s.loads==1&&!s.lookups);
 s={};s.found=7;s.null=true;assert(!bind_mesa_gnm({&s,find,load,resolve},targets));
 s={};s.found=-2;assert(!bind_mesa_gnm({&s,find,load,resolve},targets));assert(s.loads==0&&!s.lookups);
 assert(!bind_mesa_gnm({&s,nullptr,load,resolve},targets));assert(!bind_mesa_gnm({&s,find,load,resolve},nullptr));
}
'''
        self.compile_run(source)

    def compile_run(self,source,extra=()):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);cpp=p/'test.cpp';cpp.write_text(source)
            command=['clang++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                     '-fno-omit-frame-pointer','-I'+str(ROOT/'include'),str(cpp),*map(str,extra),'-o',str(p/'test')]
            subprocess.run(command,check=True)
            subprocess.run([p/'test'],check=True)

    def test_static_thunks_preserve_registers_stack_and_trap_missing_target(self):
        self.compile_run(r'''
#include <cassert>
#include <signal.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <unistd.h>
extern "C" {extern void* orbis_mesa_gnm_targets[10];
long orbis_sysconf(int);
long sceGnmAreSubmitsAllowed(long,long,long,long,long,long,long,long);
double sceGnmFlushGarlic(double,double,double,double,double,double,double,double,double);
}
long integers(long a,long b,long c,long d,long e,long f,long g,long h){return a+2*b+3*c+4*d+5*e+6*f+7*g+8*h;}
double floats(double a,double b,double c,double d,double e,double f,double g,double h,double i){return a+b+c+d+e+f+g+h+i;}
int main(){orbis_mesa_gnm_targets[0]=reinterpret_cast<void*>(integers);
 orbis_mesa_gnm_targets[3]=reinterpret_cast<void*>(floats);
 assert(orbis_sysconf(_SC_NPROCESSORS_ONLN)==sysconf(_SC_NPROCESSORS_ONLN));
 assert(sceGnmAreSubmitsAllowed(1,2,3,4,5,6,7,8)==204);
 assert(sceGnmFlushGarlic(1.,2.,3.,4.,5.,6.,7.,8.,9.)==45.);
 orbis_mesa_gnm_targets[0]=nullptr;pid_t child=fork();assert(child>=0);
 if(child==0){rlimit limit{0,0};assert(setrlimit(RLIMIT_CORE,&limit)==0);signal(SIGILL,SIG_DFL);sceGnmAreSubmitsAllowed(0,0,0,0,0,0,0,0);_exit(3);}
 int status=0;assert(waitpid(child,&status,0)==child);assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGILL);
}
''',[ROOT/'src/ps4/mesa_runtime_bridge.cpp',ROOT/'src/ps4/mesa_gnm_stubs.S'])

    def test_exact_object_dedup_preserves_nonidentical_duplicate_basenames(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);objects=[]
            for i in range(3):
                d=p/str(i);d.mkdir();source=d/'same.c';source.write_text('int f'+str(i)+'(void){return '+str(i)+';}\n')
                obj=d/'same.o';subprocess.run(['clang','-c',source,'-o',obj],check=True);objects.append(obj)
            forced=p/'forced.a';archive=p/'input.a'
            subprocess.run(['llvm-ar','qc',forced,objects[0]],check=True)
            subprocess.run(['llvm-ar','qc',archive,*objects],check=True)
            outputs,removed=builder.deduplicate([archive],forced,p/'result')
            members=list(builder.archive_members(outputs[0]));self.assertEqual(len(members),2)
            self.assertEqual([body for _,body in members],[objects[1].read_bytes(),objects[2].read_bytes()])
            self.assertEqual(len(removed),1)
            before=outputs[0].read_bytes();mtime=outputs[0].stat().st_mtime_ns
            builder.deduplicate([archive],forced,p/'result')
            self.assertEqual(outputs[0].read_bytes(),before);self.assertEqual(outputs[0].stat().st_mtime_ns,mtime)

    def test_thin_materialization_confines_reads_and_keeps_duplicate_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);objects=[]
            for name in ('first','second'):
                path=root/name;path.mkdir();source=path/'same.c';source.write_text('int '+name+'(void){return 1;}')
                obj=path/'same.o';subprocess.run(['clang','-c',source,'-o',obj],check=True);objects.append(obj)
            archive=root/'thin.a';subprocess.run(['llvm-ar','qcT',archive,*objects],check=True)
            members=list(builder.archive_members(archive,thin_root=root))
            self.assertEqual([body for _,body in members],[path.read_bytes() for path in objects])
            with self.assertRaisesRegex(ValueError,'out-of-tree'):
                list(builder.archive_members(archive,thin_root=root/'first'))
            before=[path.read_bytes() for path in objects]
            forced=root/'forced.a';subprocess.run(['llvm-ar','qc',forced,objects[0]],check=True)
            outputs,removed=builder.deduplicate([archive],forced,root/'out',thin_root=root)
            self.assertTrue(outputs[0].read_bytes().startswith(b'!<arch>\n'))
            self.assertEqual([body for _,body in builder.archive_members(outputs[0])],[objects[1].read_bytes()])
            self.assertEqual([path.read_bytes() for path in objects],before)
            self.assertEqual(len(removed),1)

    def test_response_uses_real_newlines_and_preserves_paths(self):
        forced=Path('/build with spaces/radv.a');others=[Path('/build with spaces/egl.a'),Path('/build/gles.a')]
        bridge=[Path('/build with spaces/runtime.o'),Path('/build/gnm.o')]
        response=builder.link_response(forced,others,bridge)
        self.assertNotIn('\\\\n',response)
        self.assertEqual(shlex.split(response),['--start-group',*map(str,bridge),'--whole-archive',str(forced),'--no-whole-archive',*map(str,others),'--end-group'])

    def test_bridge_resolves_real_shared_gate_without_service_imports(self):
        # The exact missed stage: strict shared-library linkage, not just the
        # final executable. The C caller is a host double, not a GPU test.
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);source=p/'caller.cpp'
            source.write_text('extern "C" long orbis_sysconf(int);\n'
                'extern "C" long sceGnmAreSubmitsAllowed();\n'
                'extern "C" long gate(int n) { return orbis_sysconf(n)+sceGnmAreSubmitsAllowed(); }\n')
            command=['clang++','-shared','-fPIC','-Wl,-z,defs','-I'+str(ROOT/'include'),
                     source,ROOT/'src/ps4/mesa_gnm_stubs.S']
            missing=subprocess.run([*map(str,command),'-o',str(p/'missing.so')],capture_output=True,text=True)
            self.assertNotEqual(missing.returncode,0)
            self.assertIn('orbis_sysconf',missing.stderr)
            self.assertIn('orbis_mesa_gnm_targets',missing.stderr)
            library=p/'gate.so'
            subprocess.run([*command,ROOT/'src/ps4/mesa_runtime_bridge.cpp','-o',library],check=True)
            defined=subprocess.check_output(['llvm-nm','--defined-only',library],text=True)
            self.assertIn(' orbis_sysconf',defined)
            self.assertIn(' sceGnmAreSubmitsAllowed',defined)
            dynamic=subprocess.check_output(['llvm-nm','-D','-u',library],text=True)
            self.assertNotIn('sceGnm',dynamic)
            self.assertIn('sysconf',dynamic)

    def test_thin_and_malformed_archives_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'bad.a'
            for data in (b'!<thin>\n',b'!<arch>\ntruncated',b'not an archive'):
                p.write_bytes(data)
                with self.assertRaises(ValueError):list(builder.archive_members(p))

    def test_offscreen_policy_is_stable_and_rejects_unknown_source_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            originals={builder.OFFSCREEN_FILES[0]:"if with_platform_orbis\n  files_vulkan_wsi += files('wsi_orbis.c')\nendif\n",
                builder.OFFSCREEN_FILES[1]:'/** VK_EXT_headless_surface */\n'+('#ifdef HAVE_ORBIS_PLATFORM\n#endif\n'*11)+('#ifndef HAVE_ORBIS_PLATFORM\n#endif\n'*2),
                builder.OFFSCREEN_FILES[2]:'EGL_WINDOW_BIT | EGL_PBUFFER_BIT\n',
                builder.DISPATCH_FILES[0]:DISPATCH_CORE,
                builder.DISPATCH_FILES[1]:DISPATCH_CONTEXT}
            for name,text in originals.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            subprocess.run(['git','init','-q',root],check=True)
            subprocess.run(['git','-C',root,'add','.'],check=True)
            subprocess.run(['git','-C',root,'-c','user.name=Mesa Test','-c','user.email=mesa-test@example.invalid','commit','-qm','fixture'],check=True)
            report=builder.patch_offscreen(root)
            before={name:((root/name).read_bytes(),(root/name).stat().st_mtime_ns) for name in originals}
            self.assertEqual(builder.patch_offscreen(root),report)
            self.assertEqual(before,{name:((root/name).read_bytes(),(root/name).stat().st_mtime_ns) for name in originals})
            self.assertNotIn("files('wsi_orbis.c')",(root/builder.OFFSCREEN_FILES[0]).read_text())
            self.assertNotIn('EGL_WINDOW_BIT',(root/builder.OFFSCREEN_FILES[2]).read_text())
            headless=root/builder.OFFSCREEN_FILES[1];headless.write_text(originals[builder.OFFSCREEN_FILES[1]])
            (root/builder.OFFSCREEN_FILES[2]).write_text('unrecognized modification')
            before=(headless.read_bytes(),headless.stat().st_mtime_ns)
            with self.assertRaisesRegex(RuntimeError,'Unrecognized Mesa source modification'):
                builder.patch_offscreen(root)
            self.assertEqual((headless.read_bytes(),headless.stat().st_mtime_ns),before)

    def test_unavailable_driver_fails_egl_closed_and_keeps_software_startup(self):
        patch=(ROOT/'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('if (!orbis_mesa_gpu_ready || !orbis_mesa_gpu_ready())',patch)
        self.assertIn('extern "C" bool orbis_mesa_gpu_ready() __attribute__((weak));',patch)
        main=(ROOT/'gecko/orbisfox/native/main.cpp').read_text()
        start=main.index('if (!sharedMemoryReady || !prepare_native_mesa() || !probe_native_mesa_gpu())')
        block=main[start:main.index('}',start)]
        self.assertIn('retaining software rendering',block)
        self.assertNotIn('request_system_exit',block)
        native=(ROOT/'src/ps4/native_mesa.cpp').read_text()
        self.assertIn('bool orbis_mesa_native_ready() { return bindings_ready; }',native)

    def test_native_probe_rejects_real_host_software_gl(self):
        # Real host EGL/GLES calls, not console proof. Only the native binding
        # readiness is doubled; production renderer policy must reject llvmpipe.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);harness=root/'probe.cpp';binary=root/'probe'
            harness.write_text(r'''
#include "orbisfox/mesa_probe.h"
#include <cassert>
#include <cstdarg>
#include <cstdio>
extern "C" bool orbis_mesa_native_ready() { return true; }
extern "C" bool orbis_mesa_gpu_ready();
namespace orbisfox { void log(const char* format,...) { va_list args;va_start(args,format);vfprintf(stderr,format,args);va_end(args);fputc('\n',stderr); } }
int main() {
 assert(orbisfox::IsOrbisMesaRenderer("zink Vulkan 1.3 RADV ORBIS/MESA_RADV"));
 assert(!orbisfox::IsOrbisMesaRenderer("llvmpipe"));
 assert(!orbisfox::IsOrbisMesaRenderer("zink RADV non-console"));
 assert(!orbisfox::IsOrbisMesaRenderer(nullptr));
 unsigned char pixel[]={64,128,191,255};assert(orbisfox::IsMesaProbePixel(pixel));
 pixel[3]=0;assert(!orbisfox::IsMesaProbePixel(pixel));
 assert(!orbisfox::probe_native_mesa_gpu());assert(!orbis_mesa_gpu_ready());
 assert(!orbisfox::probe_native_mesa_gpu());
}
''')
            subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(ROOT/'include'),
                ROOT/'src/ps4/native_mesa_probe.cpp',harness,'-lEGL','-lGLESv2','-o',binary],check=True)
            import os
            environment=dict(os.environ,EGL_PLATFORM='surfaceless',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',
                             __EGL_VENDOR_LIBRARY_FILENAMES='/usr/share/glvnd/egl_vendor.d/50_mesa.json')
            subprocess.run([binary],env=environment,check=True)

    def test_mesa_does_not_supply_global_runtime_or_videoout_replacements(self):
        producer=(ROOT/'scripts/build-orbis-mesa.py').read_text()
        self.assertNotIn("run([compat/'build.sh']",producer)
        self.assertIn("cross=cross.replace(\"'-lorbis-compat'\",repr(str(probe_archive)))",producer)
        self.assertIn("'-fno-exceptions','-fno-rtti'",producer)
        names=(ROOT/'include/orbisfox/mesa_gnm_symbols.inc').read_text()
        self.assertNotIn('ORBIS_MESA_GNM(0, sceVideoOut',names)
        runtime=(ROOT/'src/ps4/mesa_runtime_bridge.cpp').read_text()
        self.assertIn('return sysconf(name);',runtime)
        self.assertNotIn('sceKernelJit',runtime)
        application=(ROOT/'scripts/build-gecko-app.py').read_text()
        self.assertIn('*bridge_paths',application)
        self.assertIn('Mesa common runtime bridge source binding changed',application)


if __name__=='__main__':unittest.main()
