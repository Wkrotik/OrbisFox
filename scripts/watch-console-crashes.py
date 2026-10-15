#!/usr/bin/env python3
"""Preserve completed OrbisFox dumps on the laptop before a subsequent launch deletes them.
Read-only FTP polling; does not install, launch, change markers or open a kernel reader.
"""
import argparse
from ftplib import FTP
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import time

FETCH=runpy.run_path(str(Path(__file__).with_name('fetch-console-crash.py')))

def snapshot_sizes(ftp,directory):
    result={}
    for name in FETCH['names'](ftp,directory):
        if not re.fullmatch(r'[A-Za-z0-9._-]+',name):raise ValueError('Unexpected dump filename')
        result[name]=ftp.size(directory+'/'+name)
    return result

def collect_ready(ftp,out,previous):
    current={}
    for dump in FETCH['names'](ftp,'/data/sce_coredumps'):
        if not re.fullmatch(r'ORBF00001_[0-9]+',dump):continue
        remote='/data/sce_coredumps/'+dump; sizes=snapshot_sizes(ftp,remote);current[dump]=sizes
        destination=out/dump
        if (destination/'capture-report.json').exists():continue
        # Native completion isn't inferred from stable bytes alone; this is a
        # conservative readiness heuristic. Preserve provenance as unconfirmed
        # until the kernel's matching coredump-end event is checked by analysis.
        required={dump+'.sorbisdmp',dump+'.orbisdmpmanifest','report.log',
                  'orbiscore-report.orbisstate','orbiscore-systemcrash.orbisstate','playgo-status.xml'}
        if not required.issubset(sizes) or previous.get(dump)!=sizes or not sizes[dump+'.sorbisdmp']:continue
        attempt=out/'.pending'/(dump+'-'+str(time.time_ns()))
        records=[FETCH['retrieve'](ftp,remote+'/'+name,attempt/name) for name in sizes]
        after=snapshot_sizes(ftp,remote)
        if after!=sizes or any(record['bytes']!=sizes[Path(record['remote']).name] for record in records):
            raise IOError('Dump changed during retrieval; partial evidence retained: '+dump)
        report={'directory':remote,'epoch':time.time(),'files':records,'console_files_changed':False,
                'ready_heuristic':'all six files present, sizes stable across polls and retrieval',
                'kernel_completion_and_native_version_association_verified':False}
        for record in records:record['local']=str(destination/Path(record['local']).name)
        (attempt/'capture-report.json').write_text(json.dumps(report,indent=2)+'\n')
        attempt.rename(destination)
        print('PRESERVED '+dump+' (check matching kernel completion/version)',flush=True)
    return current

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True,help='Explicit console address');parser.add_argument('--port',type=int,default=2121)
    parser.add_argument('--out',type=Path,default=Path(__file__).resolve().parents[1]/'build/console-crash-archive')
    parser.add_argument('--interval',type=float,default=3);parser.add_argument('--duration',type=float,default=7200)
    args=parser.parse_args()
    if args.interval<1 or args.duration<=0:parser.error('Positive duration and interval>=1 required')
    args.out.mkdir(parents=True,exist_ok=True);previous={};end=time.monotonic()+args.duration
    while time.monotonic()<end:
        try:
            with FTP() as ftp:
                ftp.connect(args.host,args.port,timeout=15)
                ftp.login('anonymous',os.environ.get('PS4_FTP_PASSWORD','anonymous@'))
                ftp.voidcmd('TYPE I');previous=collect_ready(ftp,args.out,previous)
        except Exception as failure:
            print('RETRY '+str(failure),flush=True);previous={}
        time.sleep(args.interval)

if __name__=='__main__':main()
