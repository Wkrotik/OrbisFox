# SPDX-License-Identifier: MIT
"""Native-compiled SysV libffi; reject unsupported MS ABI without miscalling."""
import ast
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
LIBFFI = SOURCE / 'js/src/ctypes/libffi'
CONFIG = ROOT / 'build/gecko-layout/js/src/ctypes/libffi'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
FILES = ('config/external/ffi/moz.build', 'js/src/ctypes/libffi/src/x86/ffi64.c')


class HomebrewFfiTest(unittest.TestCase):
    def fixture(self, root):
        for name in FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(['git', '-C', str(SOURCE), 'show',
                                                      PATCH['REVISION'] + ':' + name]))

    def test_pinned_selection_idempotency_and_atomic_drift_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            PATCH['patch_native_ffi'](root)
            before = {name: ((root / name).read_bytes(), (root / name).stat().st_mtime_ns) for name in FILES}
            PATCH['patch_native_ffi'](root)
            for name, value in before.items():
                self.assertEqual(((root / name).read_bytes(), (root / name).stat().st_mtime_ns), value)
            tree = ast.parse((root / FILES[0]).read_text())
            branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                          and ast.unparse(node.test) == "CONFIG['FFI_TARGET'] == 'X86_64'")
            for native in (False, True):
                env = {'CONFIG': {'MOZ_ORBIS_HOMEBREW_SDK': native}, 'DEFINES': {}}
                exec(compile(ast.Module(body=branch.body, type_ignores=[]), '<ffi-selection>', 'exec'), env)
                self.assertEqual(env['ffi_srcs'], ('ffi64.c', 'unix64.S') +
                                 (() if native else ('ffiw64.c', 'win64.S')))
            self.fixture(root)
            bad = root / FILES[1]
            bad.write_text(bad.read_text().replace('ffi_call (ffi_cif *cif,', 'unknown_foreign_edit (ffi_cif *cif,'))
            unchanged = {name: (root / name).read_bytes() for name in FILES}
            with self.assertRaisesRegex(RuntimeError, 'native libffi ABI drift'):
                PATCH['patch_native_ffi'](root)
            for name, value in unchanged.items():
                self.assertEqual((root / name).read_bytes(), value)

    def test_native_compiled_sysv_calls_structs_variadics_and_bad_abi(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            flags = ['-std=gnu11', '-O1', '-fPIC', '-DX86_64', '-DFFI_STATIC_BUILD',
                     '-DFFI_NO_RAW_API', '-DHAVE_AS_X86_PCREL', '-DHAVE_HIDDEN_VISIBILITY_ATTRIBUTE',
                     '-DHAVE_AS_X86_64_UNWIND_SECTION_TYPE', '-DEH_FRAME_FLAGS="a"',
                     '-I' + str(CONFIG), '-I' + str(CONFIG / 'include'),
                     '-I' + str(LIBFFI / 'include'), '-I' + str(LIBFFI / 'src/x86')]
            failed = subprocess.run(DRIVER['compiler_command'](flags + [
                '-c', str(LIBFFI / 'src/x86/ffiw64.c'), '-o', str(root / 'unsupported.o')]),
                capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("'ms_abi' calling convention is not supported", failed.stderr)
            PATCH['patch_native_ffi'](root)
            sources = (root / FILES[1], LIBFFI / 'src/x86/unix64.S',
                       LIBFFI / 'src/types.c', LIBFFI / 'src/prep_cif.c')
            objects = []
            for i, source in enumerate(sources):
                output = root / f'unit-{i}.o'
                command = DRIVER['compiler_command'](flags + ['-c', str(source), '-o', str(output)])
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                symbols = subprocess.check_output(['llvm-nm', str(output)], text=True)
                self.assertNotIn('_efi64', symbols)
                self.assertNotIn('_win64', symbols)
                objects.append(output)
            # Native code is executed with host libc doubles, NOT on firmware.
            # Preserve Sony's global SSP guard, seed it using genuine OS entropy.
            main = root / 'host.cpp'
            main.write_text('''#include <ffi.h>
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstring>
#include <initializer_list>
#include <sys/random.h>
#include <sys/resource.h>
extern "C" {uintptr_t __stack_chk_guard;}
__attribute__((constructor)) static void seed(){
 assert(getrandom(&__stack_chk_guard,sizeof(__stack_chk_guard),0)==sizeof(__stack_chk_guard));
 assert(__stack_chk_guard);
}
static int add(int a,int b){return a+b;}
struct Triple{int64_t a,b,c;};
static int64_t sum_struct(Triple x,int y){return x.a+x.b+x.c+y;}
static double variadic(unsigned n,...){
 va_list ap;va_start(ap,n);double result=0;
 for(unsigned i=0;i<n;++i)result+=va_arg(ap,double);
 va_end(ap);return result;
}
static void never(ffi_cif*,void*,void**,void*){__builtin_trap();}
int main(int argc,char** argv){
 static_assert(FFI_DEFAULT_ABI==FFI_UNIX64);
 if(argc>1){
  rlimit limit={0,0};assert(setrlimit(RLIMIT_CORE,&limit)==0);
  ffi_cif bad={};bad.abi=FFI_WIN64;
  if(argv[1][0]=='g')ffi_call_go(&bad,FFI_FN(add),nullptr,nullptr,nullptr);
  else ffi_call(&bad,FFI_FN(add),nullptr,nullptr);
  return 19;
 }
 for(int cycle=0;cycle<32;++cycle){
  ffi_cif cif;ffi_type* ints[]={&ffi_type_sint32,&ffi_type_sint32};
  int a=17,b=25;void* args[]={&a,&b};ffi_arg result=0;
  assert(ffi_prep_cif(&cif,FFI_DEFAULT_ABI,2,&ffi_type_sint32,ints)==FFI_OK);
  ffi_call(&cif,FFI_FN(add),&result,args);assert(result==42);
  ffi_type* elements[]={&ffi_type_sint64,&ffi_type_sint64,&ffi_type_sint64,nullptr};
  ffi_type triple={0,0,FFI_TYPE_STRUCT,elements};
  ffi_type* stypes[]={&triple,&ffi_type_sint32};
  Triple value={7,11,19},original=value;int extra=5;int64_t sum=0;
  void* sargs[]={&value,&extra};
  assert(ffi_prep_cif(&cif,FFI_DEFAULT_ABI,2,&ffi_type_sint64,stypes)==FFI_OK);
  ffi_call(&cif,FFI_FN(sum_struct),&sum,sargs);
  assert(sum==42 && sargs[0]==&value && memcmp(&original,&value,sizeof(value))==0);
  unsigned n=3;double x=1.25,y=2.5,z=38.25,dresult=0;
  ffi_type* vtypes[]={&ffi_type_uint32,&ffi_type_double,&ffi_type_double,&ffi_type_double};
  void* vargs[]={&n,&x,&y,&z};
  assert(ffi_prep_cif_var(&cif,FFI_DEFAULT_ABI,1,4,&ffi_type_double,vtypes)==FFI_OK);
  ffi_call(&cif,FFI_FN(variadic),&dresult,vargs);assert(dresult==42);
  for(ffi_abi abi:{FFI_WIN64,FFI_GNUW64}){
   assert(ffi_prep_cif(&cif,abi,2,&ffi_type_sint32,ints)==FFI_BAD_ABI);
   ffi_closure closure;memset(&closure,0xa5,sizeof(closure));
   unsigned char before[sizeof(closure)];memcpy(before,&closure,sizeof(closure));
   char code[32];
   assert(ffi_prep_closure_loc(&closure,&cif,never,nullptr,code)==FFI_BAD_ABI);
   assert(memcmp(before,&closure,sizeof(closure))==0);
   ffi_go_closure go;memset(&go,0xa5,sizeof(go));
   assert(ffi_prep_go_closure(&go,&cif,never)==FFI_BAD_ABI);
  }
 }
}
''')
            executable = root / 'host'
            result = subprocess.run(['clang++', '-std=c++20', '-DX86_64',
                                     '-fsanitize=address,undefined', '-I' + str(CONFIG / 'include'),
                                     '-I' + str(LIBFFI / 'src/x86'), str(main),
                                     *map(str, objects), '-Wl,--no-gc-sections', '-o', str(executable)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for kind in ('call', 'go'):
                result = subprocess.run([str(executable), kind], capture_output=True, text=True)
                self.assertEqual(result.returncode, -6, result.stderr)  # real abort, not fake success


if __name__ == '__main__':
    unittest.main()
