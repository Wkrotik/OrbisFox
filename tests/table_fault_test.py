"""Allocation-free table fault record, not a repair or real media crash reproduction."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TableFaultTest(unittest.TestCase):
    def test_fault_reaches_stderr_and_preopened_writer(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ unavailable')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / 'test.cpp'
            source.write_text(r'''
#include "OrbisTableFault.h"
#include <cassert>
#include <cstring>
char persisted[256]{};size_t bytes=0;
bool save(const char* text,size_t size){assert(size<sizeof(persisted));memcpy(persisted,text,size);bytes=size;return true;}
int main(){
 orbisfox::record_table_fault("entry",0,nullptr,nullptr);assert(bytes==0);
 orbisfox::set_table_fault_writer(save);
 orbisfox::record_table_fault("entry",0,reinterpret_cast<void*>(0x1234),reinterpret_cast<void*>(0x8765));
 assert(bytes&&persisted[bytes-1]=='\n');
 assert(strstr(persisted,"table=0x0000000000000000"));
 assert(strstr(persisted,"key=0x0000000000001234"));
 assert(strstr(persisted,"caller=0x0000000000008765"));
}
''')
            binary = path / 'test'
            compiled = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                       '-fsanitize=address,undefined', '-I' + str(ROOT / 'gecko/orbisfox'),
                                       str(source), str(ROOT / 'gecko/orbisfox/OrbisTableFault.cpp'), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('ORBIS_TABLE_FAULT op=entry', run.stderr)


if __name__ == '__main__':
    unittest.main()
