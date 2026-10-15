import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('heap_trace', ROOT / 'scripts/decode-heap-trace.py')
TRACE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TRACE)


def fixture(latest, events, fault=b'', version=1, occupancy=0, saturated=0, untracked=0):
    data = bytearray(64+4096*64+768)
    data[:64] = TRACE.HEADER.pack(TRACE.MAGIC, version, 64, 4096, latest, occupancy, saturated, untracked)
    for values in events:
        at = 64+((values[0]-1) % 4096)*64
        data[at:at+64] = TRACE.EVENT.pack(*values)
    data[64+4096*64:64+4096*64+len(fault)] = fault
    return data


class HeapTraceTests(unittest.TestCase):
    def test_format_and_empty_trace(self):
        self.assertEqual(TRACE.decode(fixture(0, []))['events'], [])
        for data in (b'', bytes(64), TRACE.HEADER.pack(TRACE.MAGIC, 3, 64, 4096, 0, 0, 0, 0)):
            with self.assertRaises(ValueError):
                TRACE.decode(data)

    def test_v2_saturation_is_explicit_partial_coverage_not_synthetic_ENOMEM(self):
        result = TRACE.decode(fixture(2, [(1, 10, 0, 0, 320, 0x410000, 0, 0),
                                         (2, 11, 0x90000, 0, 320, 0x410000, 0, 0)],
                                      version=2, occupancy=(196608 << 32) | 196608, saturated=1, untracked=1))
        self.assertEqual(result['coverage'], dict(tracked_live_and_quarantined_at_latest_callback=196608,
                                                tracking_admission_limit=196608, saturation_requests=1,
                                                successful_untracked_fallback_allocations=1, coverage_degraded=True))
        self.assertIn('raw SDK without guards', result['events'][0]['operation'])
        self.assertNotIn('ENOMEM', result['events'][0]['operation'])
        self.assertIn('no guards', result['events'][1]['operation'])
        self.assertFalse(TRACE.decode(fixture(0, [], version=2))['coverage']['coverage_degraded'])

    def test_v2_failed_raw_fallback_is_distinct_from_success_and_v1_stays_historical(self):
        result = TRACE.decode(fixture(1, [(1, 11, 0, 0, 320, 0, 0, 0)], version=2, saturated=1))
        self.assertEqual(result['coverage']['successful_untracked_fallback_allocations'], 0)
        self.assertEqual(result['events'][0]['pointer'], '0x0')
        self.assertEqual(result['events'][0]['operation'], 'raw SDK allocation returned null (not synthetic tracking failure)')
        self.assertIsNone(TRACE.decode(fixture(0, []))['coverage'])

    def test_real_addresses_fault_and_historical_v1_tracking_exhaustion(self):
        result = TRACE.decode(fixture(2, [(1, 9, 0x1000, 0x0ff0, 32, 0x410000, 0x420000, 0x800030000),
                                          (2, 10, 0, 0, 64, 0, 0, 0)], b'ORBISFOX HEAP DIAGNOSTIC: allocation suffix overwritten\n'))
        self.assertEqual(result['missing_sequences'], [])
        self.assertIn('allocation suffix overwritten', result['fault'])
        self.assertEqual(result['events'][0]['caller_ELF'], '0x10000')
        self.assertIsNone(result['events'][0]['freed_at_ELF'])
        self.assertIsNone(result['events'][1]['caller_ELF'])
        self.assertEqual(result['events'][1]['operation'], 'tracking capacity exhausted (ENOMEM)')

    def test_circular_slot_order_not_physical_order(self):
        values = [(sequence, 2, 1, 2, 3, 4, 5, 6) for sequence in range(1, 5001)]
        result = TRACE.decode(fixture(5000, values))
        self.assertEqual(len(result['events']), 4096)
        self.assertEqual(result['events'][0]['sequence'], 905)
        self.assertEqual(result['events'][-1]['sequence'], 5000)
        self.assertEqual(result['missing_sequences'], [])

    def test_missing_torn_and_truncated_events_are_not_false_success(self):
        result = TRACE.decode(fixture(3, [(1, 1, 0, 0, 2, 3, 0, 0)]))
        self.assertEqual(result['missing_sequences'], [2, 3])
        result = TRACE.decode(fixture(3, [])[:64])
        self.assertEqual(result['missing_sequences'], [1, 2, 3])
        self.assertIn('not proof', result['limitations'])

    def test_custom_application_base_and_rollback_operation(self):
        result = TRACE.decode(fixture(1, [(1, 6, 0, 0, 16, 0x11000, 0, 0)]), base=0x10000)
        self.assertEqual(result['events'][0]['caller_ELF'], '0x1000')
        self.assertEqual(result['events'][0]['operation'], 'replacement allocation rolled back')


if __name__ == '__main__':
    unittest.main()
