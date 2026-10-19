import json
from pathlib import Path
import runpy
import struct
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
DECODER = runpy.run_path(str(ROOT / 'scripts/decode-allocator-flight.py'))


class AllocatorFlightTests(unittest.TestCase):
    def test_actual_buffer_batches_failures_generation_and_serialized_threads(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            source = work / 'test.cpp'
            source.write_text(textwrap.dedent('''
                #include "orbisfox/allocator_flight.h"
                #include <cassert>
                #include <fstream>
                #include <mutex>
                #include <thread>
                #include <vector>
                int main(int argc,char** argv){
                  assert(argc==2);using namespace orbisfox;
                  AllocatorFlightBuffer<4> buffer;size_t writes=0,records=0;uint64_t last=0;
                  auto sink=[&](const AllocatorFlightEvent* events,size_t count,uint64_t run,bool){
                    assert(run==7);++writes;records+=count;
                    for(size_t i=0;i<count;++i){assert(events[i].sequence==++last);
                      assert(events[i].checksum==allocator_flight_checksum(events[i]));}
                    return true;
                  };
                  AllocatorFlightEvent event{};event.operation=allocator_flight_operation("realloc");
                  assert(event.operation==3&&allocator_flight_operation("not-an-api")==255);
                  for(unsigned i=0;i<3;++i)buffer.push(event,7,sink);
                  assert(writes==0);buffer.flush(sink,true);assert(writes==1&&records==3);
                  for(unsigned i=0;i<4;++i)buffer.push(event,7,sink);
                  assert(writes==2&&records==7);
                  buffer.flush([](auto,size_t,uint64_t,bool){return false;},true);assert(buffer.ioFailed());
                  auto newRun=[](const AllocatorFlightEvent* events,size_t n,uint64_t run,bool){
                    assert(run==8&&n==1&&events[0].sequence==1);return true;
                  };
                  buffer.push(event,8,newRun);assert(!buffer.ioFailed());buffer.flush(newRun,true);
                  buffer.discard();assert(!buffer.ioFailed());last=records=writes=0;
                  std::mutex allocatorMutex;std::vector<std::thread> threads;
                  for(unsigned i=0;i<4;++i)threads.emplace_back([&]{for(unsigned j=0;j<1000;++j){
                    std::lock_guard<std::mutex> lock(allocatorMutex);buffer.push(event,7,sink);
                  }});
                  for(auto& thread:threads)thread.join();buffer.flush(sink,true);
                  assert(records==4000&&last==4000);
                  AllocatorFlightEvent written{};written.sequence=1;written.operation=1;written.phase=2;
                  written.output=0x1234;written.bytes=13;written.checksum=allocator_flight_checksum(written);
                  const uint64_t header[8]={allocatorFlightMagic,1,64,allocatorFlightCapacity,1,7,0,1};
                  std::ofstream file(argv[1],std::ios::binary);file.write(reinterpret_cast<const char*>(header),64);
                  file.write(reinterpret_cast<const char*>(&written),64);assert(file.good());
                }
            '''))
            binary = work / 'test'
            subprocess.run(['clang++', '-std=c++20', '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-fsanitize=address,undefined', '-I' + str(ROOT / 'include'),
                            str(source), '-o', str(binary)], check=True)
            trace = work / 'actual-cpp-trace.bin'
            subprocess.run([str(binary), str(trace)], check=True)
            decoded = DECODER['decode'](trace)
            self.assertEqual(decoded['valid_records'], 1)
            self.assertEqual(decoded['events'][0]['output'], '0x1234')
            self.assertEqual(decoded['events'][0]['bytes'], 13)

    def record(self, sequence, source=0, output=0, requested=0, op=1):
        raw = struct.pack('<7QBBHI', sequence, 0x400080, source, output, requested, 0, 1, op, 2, 1, 0)
        return raw[:60] + struct.pack('<I', DECODER['checksum'](raw))

    def test_decoder_real_layout_address_filter_and_invalid_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'allocator-flight.bin'
            header = struct.pack('<8Q', DECODER['MAGIC'], 1, 64, DECODER['CAPACITY'], 3, 7, 1, 4)
            bad = bytearray(self.record(2));bad[-1] ^= 1
            trace.write_bytes(header + self.record(1, output=0x1000, requested=32) + bad +
                              self.record(3, source=0x1000, op=4))
            decoded = DECODER['decode'](trace, 0x1000, 80)
            self.assertEqual(decoded['valid_records'], 2)
            self.assertEqual(decoded['invalid_records'], 1)
            self.assertEqual(decoded['io_failures'], 1)
            self.assertEqual(decoded['attempted_sequence'], 4)
            self.assertEqual([e['operation'] for e in decoded['events']], ['malloc', 'free'])
            self.assertEqual(len(DECODER['decode'](trace, limit=1)['events']), 1)
            self.assertEqual(DECODER['decode'](trace, 0x4000)['matching_records'], 0)
            output = subprocess.check_output(['/usr/bin/python3', str(ROOT / 'scripts/decode-allocator-flight.py'),
                                               str(trace), '--address', '0x1000', '--limit', '1'], text=True)
            self.assertEqual(json.loads(output)['valid_records'], 2)

    def test_decoder_rejects_unknown_or_oversized_format_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / 'trace'
            trace.write_bytes(bytes(64))
            with self.assertRaisesRegex(ValueError, 'Unknown allocator flight format'):
                DECODER['decode'](trace)
            trace.write_bytes(struct.pack('<8Q', DECODER['MAGIC'], 1, 64, DECODER['CAPACITY'], 2, 7, 0, 2))
            self.assertEqual(DECODER['decode'](trace)['missing_or_overwritten_records'], 2)
            with trace.open('r+b') as stream:
                stream.truncate(65 + DECODER['CAPACITY'] * 64)
            with self.assertRaisesRegex(ValueError, 'fixed size bound'):
                DECODER['decode'](trace)
            with self.assertRaisesRegex(ValueError, '1..4096'):
                DECODER['decode'](trace, limit=0)


if __name__ == '__main__':
    unittest.main()
