# SPDX-License-Identifier: MIT
"""Exercise producer-adapted clone bodies, including silent command-17 success."""
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path

from homebrew_capabilities_test import fixture as gecko_fixture
from homebrew_rust_io_test import fixture as rust_fixture
from homebrew_rust_io_test import function

ROOT = Path(__file__).resolve().parent.parent
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
BOOT = runpy.run_path(str(ROOT / 'scripts/bootstrap-homebrew-rust.py'))


class HomebrewDescriptorCloneTest(unittest.TestCase):
    def test_actual_std_and_socket_bodies_own_checked_dup_and_never_command17(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rust_fixture(root)
            gecko_fixture(root)
            owned = root / 'std/src/os/fd/owned.rs'
            socket = root / 'third_party/rust/socket2/src/sys/unix.rs'
            originals = {'std': owned.read_text(), 'socket': socket.read_text()}
            BOOT['patch_native_std_io'](root)
            PATCH['patch_native_platform_capabilities'](root)
            fd = (root / 'std/src/sys/fd/unix.rs').read_text()
            fd = fd[fd.index('    #[cfg(any(\n        target_vendor = "scei",'):]
            setter = function(fd, 'pub fn set_cloexec(')
            for kind, file, signature in (
                    ('std', owned, 'pub fn try_clone_to_owned('),
                    ('socket', socket, 'pub(crate) fn try_clone(')):
                helpers = ''
                if kind == 'socket':
                    helpers = '\n'.join(function(socket.read_text(), 'fn ' + name + '(')
                                        for name in ('fcntl_get', 'fcntl_add'))
                for patched in (False, True):
                    body = function(file.read_text() if patched else originals[kind], signature)
                    if kind == 'std':
                        body = body.replace('pub fn try_clone_to_owned(&self)',
                                            'fn native_clone(fd: BorrowedFd<\'_>)')
                        body = body.replace('self.as_raw_fd()', 'fd.as_raw_fd()')
                        call = 'native_clone(source.as_fd())'
                    else:
                        call = 'try_clone(source.as_raw_fd()).map(|fd| unsafe { OwnedFd::from_raw_fd(fd) })'
                    body = body.replace('libc::fcntl(', 'native_fcntl!(')
                    unit = root / 'clone.rs'
                    unit.write_text(RUST_HEADER + helpers + '\n' + body + RUST_FD.replace(
                        'SETTER_BODY', setter.replace('libc::fcntl(', 'native_fcntl!(')) +
                        RUST_MAIN.replace('CLONE_CALL', call))
                    exe = root / 'clone'
                    result = subprocess.run(['rustc', '--edition=2021', '--cfg',
                        'target_vendor="scei"', '-Aexplicit_builtin_cfgs_in_flags',
                        '-Awarnings', str(unit), '-o', str(exe)], capture_output=True, text=True, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
                    if patched:
                        self.assertEqual(result.returncode, 0, result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0, 'Pristine atomic clone escaped trap')

    def test_actual_libcpp_reset_releases_genuine_fd_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'mfbt/UniquePtrExtensions.h'
            path.parent.mkdir(parents=True)
            path.write_bytes(subprocess.check_output(['git', '-C', str(ROOT / '.deps/gecko-layout'),
                'show', PATCH['REVISION'] + ':mfbt/UniquePtrExtensions.h']))
            libcxx = (ROOT / '.deps/libcxx-homebrew/include/c++/v1/__memory/unique_ptr.h').read_text()
            reset = function(libcxx, 'void reset(pointer').replace(' _NOEXCEPT', '')
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_file_handle_truthiness'](root)
                    before = (path.read_bytes(), path.stat().st_mtime_ns)
                    PATCH['patch_native_file_handle_truthiness'](root)
                    self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
                text = path.read_text()
                helper = text[text.index('struct FileHandleHelper {'):text.index('struct FileHandleDeleter {')]
                source = root / 'reset.cpp'
                source.write_text(r'''
#include <cassert>
#include <cstddef>
#include <fcntl.h>
#include <unistd.h>
#define MOZ_ORBIS_HOMEBREW_SDK 1
#define MOZ_IMPLICIT
using FileHandleType=int;
''' + helper + r'''
struct Owner {
 using pointer=FileHandleHelper;
 pointer __ptr_;
 static void __deleter_(pointer fd) {if(fd!=nullptr)assert(close(fd)==0);}
''' + reset + r'''
};
int main() {
 const int saved=dup(0);assert(saved>=0);
 const int source=open("/dev/null",O_RDONLY);assert(source>=0);
 assert(dup2(source,0)==0);assert(close(source)==0);
 Owner owner{0};owner.reset();
 assert(fcntl(0,F_GETFD)==-1);assert(!owner.__ptr_);
 assert(dup2(saved,0)==0);assert(close(saved)==0);
}
''')
                exe = root / 'reset'
                subprocess.run(['clang++', '-std=c++20', '-fsanitize=address,undefined',
                    str(source), '-o', str(exe)], check=True, capture_output=True, text=True)
                result = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
                if patched:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)

    def test_shuffle_preserves_minimum_flags_and_only_closes_owned_temporaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'ipc/glue/FileDescriptorShuffle.cpp'
            path.parent.mkdir(parents=True)
            path.write_bytes(subprocess.check_output(['git', '-C', str(ROOT / '.deps/gecko-layout'),
                'show', PATCH['REVISION'] + ':ipc/glue/FileDescriptorShuffle.cpp']))
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_descriptor_shuffle'](root)
                    before = (path.read_bytes(), path.stat().st_mtime_ns)
                    PATCH['patch_native_descriptor_shuffle'](root)
                    self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
                text = path.read_text()
                text = text[text.index('// F_DUPFD_CLOEXEC'):]
                text = text[:text.index('bool FileDescriptorShuffle::MapsTo')] + text[text.index(
                    'FileDescriptorShuffle::~FileDescriptorShuffle'):]
                text = text[:text.index('}  // namespace ipc')]
                for native in (False, True):
                    source = root / 'shuffle.cpp'
                    source.write_text(('#define MOZ_ORBIS_HOMEBREW_SDK 1\n' if native else '') +
                                      CPP_HEADER + text + CPP_MAIN)
                    exe = root / 'shuffle'
                    subprocess.run(['clang++', '-std=c++20', '-fsanitize=address,undefined',
                        str(source), '-Wl,--wrap=fcntl', '-o', str(exe)], check=True,
                        capture_output=True, text=True)
                    result = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
                    if patched or not native:
                        self.assertEqual(result.returncode, 0, result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0)


RUST_HEADER = r'''
use std::io;
use std::os::fd::{AsFd,AsRawFd,FromRawFd,IntoRawFd,OwnedFd,BorrowedFd};
type RawSocket=i32;
#[allow(non_camel_case_types)] type c_int=i32;
unsafe extern "C" {
 #[link_name="dup"] fn real_dup(fd:i32)->i32;
 #[link_name="fcntl"] fn real_fcntl(fd:i32,cmd:i32,...)->i32;
 fn close(fd:i32)->i32;
 fn dup2(fd:i32,to:i32)->i32;
 fn __errno_location()->*mut i32;
}
static mut MODE:i32=0;
static mut ATOMIC:i32=0;
static mut SETS:i32=0;
static mut LAST:i32=-1;
fn cvt(value:i32)->io::Result<i32> {
 if value<0 {Err(io::Error::last_os_error())}else{Ok(value)}
}
mod libc {
 pub const F_DUPFD_CLOEXEC:i32=17;
 pub const F_DUPFD:i32=0;
 pub const F_GETFD:i32=1;
 pub const F_SETFD:i32=2;
 pub const FD_CLOEXEC:i32=1;
 pub unsafe fn dup(fd:i32)->i32 {unsafe {
  if super::MODE==2 || super::MODE==3 || super::MODE==6 {
   *super::__errno_location()=if super::MODE==2{24}else if super::MODE==3{4}else{23};return -1;
  }
  super::LAST=super::real_dup(fd);
  if super::MODE==1 {assert_eq!(super::real_fcntl(super::LAST,F_SETFD,1),0);}
  super::LAST
 }}
 pub unsafe fn fcntl(fd:i32,cmd:i32,value:i32)->i32 {unsafe {
  if cmd==17 {super::ATOMIC+=1;*super::__errno_location()=0;return 0;}
  if cmd==F_GETFD {
   if super::MODE==4 {*super::__errno_location()=5;return -1;}
   return super::real_fcntl(fd,cmd)|0x80;
  }
  if cmd==F_SETFD {
   super::SETS+=1;assert_eq!(value,0x81);
   if super::MODE==5 {*super::__errno_location()=1;return -1;}
  }
  super::real_fcntl(fd,cmd,value)
 }}
}
macro_rules! native_fcntl {
 ($fd:expr,$cmd:expr)=>{libc::fcntl($fd,$cmd,0)};
 ($fd:expr,$cmd:expr,$value:expr)=>{libc::fcntl($fd,$cmd,$value)};
}
macro_rules! syscall {
 (dup($fd:expr))=>{cvt(unsafe{libc::dup($fd)})};
 (fcntl($fd:expr,$cmd:expr))=>{cvt(unsafe{libc::fcntl($fd,$cmd,0)})};
 (fcntl($fd:expr,$cmd:expr,$v:expr))=>{cvt(unsafe{libc::fcntl($fd,$cmd,$v)})};
}
'''
RUST_FD = r'''
mod sys {pub mod fd {
 use super::super::*;
 pub struct FileDesc(OwnedFd);
 impl FromRawFd for FileDesc {unsafe fn from_raw_fd(fd:i32)->Self {
  Self(unsafe{OwnedFd::from_raw_fd(fd)})
 }}
 impl AsRawFd for FileDesc {fn as_raw_fd(&self)->i32 {self.0.as_raw_fd()}}
 impl FileDesc {
  SETTER_BODY
  pub fn into_inner(self)->OwnedFd {self.0}
 }
}}
'''
RUST_MAIN = r'''
fn main() {unsafe {
 use std::os::unix::fs::FileExt;
 let path=std::env::temp_dir().join(format!("orbisfox-clone-{}",std::process::id()));
 std::fs::write(&path,b"immutable").unwrap();
 let source=std::fs::File::open(&path).unwrap();std::fs::remove_file(path).unwrap();
 for _ in 0..32 {for zero in [false,true] {for mode in 0..=6 {
  let saved=if zero {let fd=real_dup(0);assert!(fd>=0);assert_eq!(close(0),0);fd}else{-1};
  MODE=mode;ATOMIC=0;SETS=0;LAST=-1;
  let result=CLONE_CALL;
  assert_eq!(ATOMIC,0);
  if mode<=1 {
   let copy=result.unwrap();let raw=copy.as_raw_fd();assert!(raw>=0);
   if zero {assert_eq!(raw,0);}
   assert_ne!(raw,source.as_raw_fd());assert_eq!(real_fcntl(raw,1)&1,1);
   assert_eq!(SETS,if mode==1{0}else{1});
   let copy=std::fs::File::from(copy);let mut bytes=[0;9];
   assert_eq!(copy.read_at(&mut bytes,0).unwrap(),9);assert_eq!(&bytes,b"immutable");
   assert!(copy.write_at(b"x",0).is_err());drop(copy);
   assert_eq!(real_fcntl(raw,1),-1);
  } else {
   let error=result.unwrap_err();
   assert_eq!(error.raw_os_error(),Some(match mode {2=>24,3=>4,4=>5,5=>1,_=>23}));
   if LAST>=0 {assert_eq!(real_fcntl(LAST,1),-1);}
  }
  assert!(real_fcntl(source.as_raw_fd(),1)>=0);
  if zero {assert_eq!(real_fcntl(0,1),-1);assert_eq!(dup2(saved,0),0);assert_eq!(close(saved),0);}
 }}}
}}
'''
CPP_HEADER = r'''
#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstdarg>
#include <fcntl.h>
#include <unistd.h>
#include <vector>
#define MOZ_ASSERT assert
#define IGNORE_EINTR(x) (x)
namespace mozilla {template<class T>using DebugOnly=T;}
template<class T>struct List:std::vector<T> {
 bool IsEmpty()const{return this->empty();}
 void AppendElement(const T& value){this->push_back(value);}
};
using Mapping=List<std::pair<int,int>>;
struct FileDescriptorShuffle {
 using MappingRef=const Mapping&;
 Mapping mMapping;List<int>mTempFds;int mMaxDst=-1;
 bool Init(MappingRef);~FileDescriptorShuffle();
};
static int mode,last=-1,atomic;
extern "C" int __real_fcntl(int,int,...);
extern "C" int __wrap_fcntl(int fd,int cmd,...) {
 va_list args;va_start(args,cmd);int value=cmd==F_GETFD?0:va_arg(args,int);va_end(args);
#ifdef MOZ_ORBIS_HOMEBREW_SDK
 if(cmd==F_DUPFD_CLOEXEC){++atomic;errno=0;return 0;}
 if(cmd==F_DUPFD && mode==3){return 0;}
 if(fd==last && ((cmd==F_GETFD && mode==1)||(cmd==F_SETFD && mode==2))){errno=EIO;return -1;}
#endif
 int result=__real_fcntl(fd,cmd,value);
 if(cmd==F_DUPFD || cmd==F_DUPFD_CLOEXEC)last=result;
 return result;
}
'''
CPP_MAIN = r'''
int main() {
 int source=open("/dev/null",O_RDONLY|O_CLOEXEC);assert(source>=0);
 for(int i=0;i<32;++i)for(mode=0;mode<=3;++mode) {
  atomic=0;last=-1;
  {
   FileDescriptorShuffle shuffle;Mapping mapping;mapping.AppendElement({source,source+5});
   bool ready=shuffle.Init(mapping);
#ifdef MOZ_ORBIS_HOMEBREW_SDK
   assert(!atomic);assert(ready==(mode==0));
#else
   assert(ready);
#endif
   if(ready){assert(last>source+5);assert(__real_fcntl(last,F_GETFD)&FD_CLOEXEC);}
  }
  if(last>=0)assert(__real_fcntl(last,F_GETFD)==-1 && errno==EBADF);
  assert(__real_fcntl(source,F_GETFD)>=0);assert(__real_fcntl(0,F_GETFD)>=0);
 }
 close(source);
}
'''

if __name__ == '__main__':
    unittest.main()
