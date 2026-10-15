import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RunLogsTests(unittest.TestCase):
    def test_native_run_directories_do_not_overwrite_on_clock_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'orbis').mkdir()
            (work / 'orbis/libkernel.h').write_text(textwrap.dedent('''
                #pragma once
                #include <stddef.h>
                #include <stdint.h>
                #include <sys/time.h>
                typedef struct timeval OrbisKernelTimeval;
                extern "C" {
                int32_t sceKernelOpen(const char*,int,int);
                int64_t sceKernelWrite(int,const void*,size_t);
                int64_t sceKernelRead(int,void*,size_t);
                int32_t sceKernelClose(int);
                int32_t sceKernelFsync(int);
                int32_t sceKernelMkdir(const char*,int);
                int32_t sceKernelRename(const char*,const char*);
                int32_t sceKernelGettimeofday(OrbisKernelTimeval*);
                uint64_t sceKernelGetProcessTime();
                }
            '''))
            harness = work / 'harness.cpp'
            harness.write_text(textwrap.dedent('''
                #include "orbisfox/run_logs.h"
                #include <orbis/libkernel.h>
                #include <cassert>
                #include <cerrno>
                #include <cstdio>
                #include <cstring>
                #include <fcntl.h>
                #include <string>
                #include <sys/stat.h>
                #include <unistd.h>
                static std::string root;
                static bool failMkdir=false;
                static std::string path(const char* p){
                    const char* prefix="/data/orbisfox";
                    assert(!std::strncmp(p,prefix,std::strlen(prefix)));
                    return root+(p+std::strlen(prefix));
                }
                static int result(int rc){return rc<0?-int(0x7ffe0000-errno):rc;}
                extern "C" int32_t sceKernelOpen(const char* p,int flags,int mode){return result(open(path(p).c_str(),flags,mode));}
                extern "C" int64_t sceKernelWrite(int fd,const void* p,size_t n){return write(fd,p,n);}
                extern "C" int64_t sceKernelRead(int fd,void* p,size_t n){return read(fd,p,n);}
                extern "C" int32_t sceKernelClose(int fd){return result(close(fd));}
                extern "C" int32_t sceKernelFsync(int fd){return result(fsync(fd));}
                extern "C" int32_t sceKernelMkdir(const char* p,int mode){if(failMkdir){errno=EIO;return result(-1);}return result(mkdir(path(p).c_str(),mode));}
                extern "C" int32_t sceKernelRename(const char* a,const char* b){return result(rename(path(a).c_str(),path(b).c_str()));}
                extern "C" int32_t sceKernelGettimeofday(OrbisKernelTimeval* t){t->tv_sec=1791929999;t->tv_usec=17;return 0;}
                extern "C" uint64_t sceKernelGetProcessTime(){return 7;}
                int main(int argc,char** argv){
                    assert(argc==2);root=argv[1];
                    char buffer[256];
                    assert(!orbisfox::make_run_log_path(buffer,sizeof(buffer),"/runs/x","../bad"));
                    assert(!orbisfox::make_run_log_path(buffer,2,"/runs/x","a.log"));
                    assert(!orbisfox::make_run_log_path(buffer,sizeof(buffer),"/runs/x",".."));
                    assert(orbisfox::initialize_native_run_logs());
                    assert(!orbisfox::native_diagnostics_enabled());assert(access(root.c_str(),F_OK)!=0);
                    assert(!strcmp(orbisfox::NativeRunLogPath("startup-layout.log").c_str(),"/dev/null"));
                    assert(!orbisfox::native_write_heap_audit("not recorded",12));
                    assert(orbisfox::set_native_diagnostics_enabled(true));assert(orbisfox::native_diagnostics_enabled());
                    const auto generation=orbisfox::native_diagnostics_generation();
                    const std::string first=orbisfox::native_run_log_directory();
                    orbisfox::NativeRunLogPath log("startup-layout.log");
                    int fd=sceKernelOpen(log.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);
                    assert(sceKernelWrite(fd,"first-run-evidence",18)==18);assert(sceKernelClose(fd)==0);
                    assert(orbisfox::initialize_native_run_logs());
                    assert(first!=orbisfox::native_run_log_directory());
                    fd=sceKernelOpen((first+"/startup-layout.log").c_str(),O_RDONLY,0);assert(fd>=0);
                    char data[32]{};assert(read(fd,data,sizeof(data))==18);assert(!strcmp(data,"first-run-evidence"));close(fd);
                    assert(orbisfox::native_diagnostics_generation()>generation);
                    assert(orbisfox::set_native_diagnostics_enabled(false));assert(!orbisfox::native_diagnostics_enabled());
                    assert(!orbisfox::native_write_heap_audit("not recorded",12));
                    assert(orbisfox::initialize_native_run_logs());assert(!orbisfox::native_diagnostics_enabled());
                    failMkdir=true;assert(!orbisfox::set_native_diagnostics_enabled(true));assert(!orbisfox::native_diagnostics_enabled());
                    assert(access(path((first+"/startup-layout.log").c_str()).c_str(),F_OK)==0);
                }
            '''))
            executable = work / 'test'
            subprocess.run(['clang++', '-std=c++20', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-I' + str(work),
                            '-I' + str(ROOT / 'include'), str(harness),
                            str(ROOT / 'src/ps4/run_logs.cpp'), '-o', str(executable)], check=True)
            data = work / 'console-data'
            subprocess.run([str(executable), str(data)], check=True, capture_output=True, text=True)
            runs = sorted((data / 'runs').iterdir())
            self.assertEqual(len(runs), 2)
            for run in runs:
                metadata = json.loads((run / 'run-meta.json').read_text())
                self.assertEqual(metadata['version'], '0.68')
                self.assertEqual(metadata['category'], 'gd')
                self.assertEqual(metadata['run_id'], run.name)
            self.assertEqual((data / 'run-id.txt').read_text().strip(), runs[-1].name)
            self.assertEqual((runs[0] / 'startup-layout.log').read_text(), 'first-run-evidence')
