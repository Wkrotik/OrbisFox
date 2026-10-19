import json
from pathlib import Path
import tempfile
import unittest
from console_workflow_test import FETCH, load

WATCH=load('watch-console-crashes')

class FilesFTP:
    def __init__(self,files):self.files=files;self.directory=''
    def cwd(self,path):self.directory=path
    def nlst(self):
        prefix=self.directory+'/'
        return sorted({path[len(prefix):].split('/')[0] for path in self.files if path.startswith(prefix)})
    def size(self,path):return len(self.files[path])
    def retrbinary(self,command,callback,blocksize=8192):callback(self.files[command[5:]])

class RetainedRunTests(unittest.TestCase):
    def test_batch_keeps_two_runs_and_filters_other_build(self):
        files={}
        for number,version in [(1,'0.52'),(2,'0.52'),(3,'0.51')]:
            run='run-'+str(number)
            base='/data/orbisfox/runs/'+run
            files[base+'/run-meta.json']=json.dumps({'run_id':run,'version':version}).encode()
            files[base+'/startup-layout.log']=('evidence'+str(number)).encode()
            files[base+'/heap-audit.log']=b'audit'
        with tempfile.TemporaryDirectory() as directory:
            records=FETCH.fetch_runs(FilesFTP(files),'0.52',Path(directory))
            self.assertEqual(len(records),6)
            self.assertEqual((Path(directory)/'runs/run-1/startup-layout.log').read_bytes(),b'evidence1')
            self.assertEqual((Path(directory)/'runs/run-2/startup-layout.log').read_bytes(),b'evidence2')
            self.assertFalse((Path(directory)/'runs/run-3').exists())

    def test_flight_trace_is_collected_only_from_matching_owned_run(self):
        base='/data/orbisfox/runs/run-1'
        files={base+'/run-meta.json':b'{"run_id":"run-1","version":"0.68"}',
               base+'/allocator-flight.bin':b'binary metadata',
               '/data/orbisfox/allocator-flight.bin':b'not proven to belong to this launch'}
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);records=FETCH.fetch_runs(FilesFTP(files),'0.68',out)
            self.assertEqual(len(records),2)
            self.assertEqual((out/'runs/run-1/allocator-flight.bin').read_bytes(),b'binary metadata')
            self.assertFalse((out/'allocator-flight.bin').exists())
            self.assertEqual(next(r for r in records if r['remote'].endswith('allocator-flight.bin'))['bytes'],15)

    def test_mismatched_run_metadata_rejected(self):
        files={'/data/orbisfox/runs/run-1/run-meta.json':b'{"run_id":"run-2","version":"0.52"}'}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'mismatch'):FETCH.fetch_runs(FilesFTP(files),'0.52',Path(directory))

    def test_watcher_waits_for_stable_complete_set_and_preserves_independent_dump(self):
        dump='ORBF00001_99';base='/data/sce_coredumps/'+dump
        names=[dump+'.sorbisdmp',dump+'.orbisdmpmanifest','report.log','orbiscore-report.orbisstate','orbiscore-systemcrash.orbisstate','playgo-status.xml']
        ftp=FilesFTP({base+'/'+name:('data'+name).encode() for name in names})
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);first=WATCH.collect_ready(ftp,out,{})
            self.assertFalse((out/dump).exists())
            WATCH.collect_ready(ftp,out,first)
            saved=out/dump/(dump+'.sorbisdmp');before=saved.read_bytes()
            self.assertTrue((out/dump/'capture-report.json').exists())
            ftp.files[base+'/'+dump+'.sorbisdmp']=b'changed remote';WATCH.collect_ready(ftp,out,first)
            self.assertEqual(saved.read_bytes(),before)
