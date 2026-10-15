#!/usr/bin/env python3
"""Read-only controlled LAN byte server, not a remote browser/renderer."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
ROOT = Path(__file__).resolve().parent.parent

def configuration():
    source = (ROOT / 'gecko/orbisfox/fixtures/network-probe.js').read_text()
    origin = re.search(r'const origin = "(http://[0-9.]+:[0-9]+)";', source)
    token = re.search(r'const token = "([a-f0-9]{32})";', source)
    if not origin or not token: raise ValueError('Missing bounded LAN probe configuration')
    parsed = urlsplit(origin.group(1))
    return parsed.hostname, parsed.port, token.group(1)

class ProbeServer(HTTPServer):
    def __init__(self, address, fixture, token):
        self.fixture = fixture
        self.token = token
        self.probe = ('OrbisFox native Necko probe ' + token + '\n').encode('ascii')
        super().__init__(address, ProbeHandler)
        self.timeout = 1
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/orbisfox/probe/' + self.server.token:
            content, kind = self.server.probe, 'text/plain; charset=utf-8'
        elif self.path == '/orbisfox/offline.html':
            content, kind = self.server.fixture, 'text/html; charset=utf-8'
        else:
            self.send_error(404); return
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(content)
        self.close_connection = True
    def log_message(self, message, *args):
        print(f'{time.time():.3f} peer={self.client_address[0]} ' + message % args, flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=7200)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 7200: raise ValueError('Server lifetime must be 1..7200 seconds')
    fixture = (ROOT / 'gecko/orbisfox/fixtures/offline.html').read_bytes()
    if not 0 < len(fixture) <= 65536 or not fixture.lower().startswith(b'<!doctype html>'):
        raise ValueError('Invalid controlled fixture bounds/doctype')
    host, port, token = configuration()
    server = ProbeServer((host, port), fixture, token)
    report = ROOT / 'build/network-fixture-server-report.json'
    record = {'active': True, 'bound_host': host, 'port': port, 'seconds': args.seconds,
              'fixture_bytes': len(fixture), 'fixture_sha256': hashlib.sha256(fixture).hexdigest(),
              'probe_token': token, 'token_is_diagnostic_not_authentication': True,
              'tls_enabled': False, 'remote_rendering': False,
              'scope': 'Only exact probe and frozen HTML fixture bytes, GET only; no credentials or general file serving'}
    report.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)
    end = time.monotonic() + args.seconds
    try:
        while time.monotonic() < end: server.handle_request()
    finally:
        server.server_close()
        record['active'] = False
        report.write_text(json.dumps(record, indent=2) + '\n')
    return 0
if __name__ == '__main__': raise SystemExit(main())
