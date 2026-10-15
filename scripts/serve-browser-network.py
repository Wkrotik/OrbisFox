#!/usr/bin/env python3
"""Bounded, controlled HTTP/iframe/WebSocket browser fixture, not a browser shim.

Open the printed HTTP URL in OrbisFox. PASS requires actual browser messages;
server-side tests alone do not establish Gecko/PS4 or TLS WebSocket success.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore
import json
import time

PAGE = b'''<!doctype html><meta charset="utf-8"><title>OrbisFox networking check</title>
<style>body{background:#fff;color:#18202a;font:24px sans-serif}pre{white-space:pre-wrap}@media(prefers-color-scheme:dark){body{background:#18202a;color:white}}</style>
<h1>Real browser networking check</h1><p>Tests HTTP fetch, a separate same-origin frame, and a WebSocket upgrade/echo. No browser bridge or TLS exceptions.</p><pre id="status"></pre><p id="appearance"></p><button id="fullscreen">Request real website fullscreen</button><p id="fullscreen-result"></p><iframe hidden></iframe>
<script>
const scheme=matchMedia('(prefers-color-scheme:dark)');const appearance=()=>document.querySelector('#appearance').textContent='Website prefers-color-scheme: '+(scheme.matches?'dark':'light');scheme.addEventListener('change',appearance);appearance();
document.querySelector('#fullscreen').onclick=async()=>{try{await document.documentElement.requestFullscreen();document.querySelector('#fullscreen-result').textContent='Real fullscreenElement: '+!!document.fullscreenElement;}catch(e){document.querySelector('#fullscreen-result').textContent='Fullscreen rejected: '+e;}};
const state={http:'waiting',frame:'waiting',webSocket:'waiting',userAgent:navigator.userAgent};
const display=()=>document.querySelector('#status').textContent=JSON.stringify(state,null,2);
const nonce=Array.from(crypto.getRandomValues(new Uint32Array(4)),x=>x.toString(16)).join('-');
let socket;const timer=setTimeout(()=>{for(const k of ['http','frame','webSocket'])if(state[k]==='waiting')state[k]='FAIL: timeout';socket?.close();display();},8000);
fetch('/poll',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json();}).then(r=>{state.http=r.probe==='orbisfox-network'?'PASS':'FAIL: response';display();}).catch(e=>{state.http='FAIL: '+e;display();});
const frame=document.querySelector('iframe');
window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==frame.contentWindow||e.data?.nonce!==nonce)return;state.frame=e.data.ok===true?'PASS':'FAIL: frame fetch';display();});
frame.src='/frame#'+nonce;
try{socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/socket','orbisfox-probe');
socket.onopen=()=>socket.send(nonce);socket.onmessage=e=>{state.webSocket=e.data===nonce?'PASS':'FAIL: echo mismatch';display();};
socket.onerror=()=>{state.webSocket='FAIL: connection error';display();};socket.onclose=e=>{if(state.webSocket==='waiting')state.webSocket='FAIL: closed '+e.code;display();};
}catch(e){state.webSocket='FAIL: '+e;}
window.addEventListener('pagehide',()=>{clearTimeout(timer);socket?.close();},{once:true});display();
</script>'''
FRAME = b'''<!doctype html><meta charset="utf-8"><title>Independent frame probe</title><script>
fetch('/poll',{cache:'no-store'}).then(r=>r.json()).then(r=>parent.postMessage({nonce:location.hash.slice(1),ok:r.probe==='orbisfox-network'},location.origin)).catch(()=>parent.postMessage({nonce:location.hash.slice(1),ok:false},location.origin));
</script>'''


def read_exact(stream, count):
    data = bytearray()
    while len(data) < count:
        part = stream.read(count - len(data))
        if not part:
            raise EOFError('Truncated WebSocket fixture frame')
        data.extend(part)
    return bytes(data)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.connection.settimeout(4)
        self.close_connection = True
        if self.path == '/socket':
            self.websocket()
            return
        content = {'/': (PAGE, 'text/html; charset=utf-8'),
                   '/frame': (FRAME, 'text/html; charset=utf-8'),
                   '/poll': (b'{"probe":"orbisfox-network"}', 'application/json')}.get(self.path)
        if not content:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content[1])
        self.send_header('Content-Length', str(len(content[0])))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src 'self'; connect-src 'self' ws:")
        self.end_headers()
        self.wfile.write(content[0])

    def websocket(self):
        expected = 'http://' + self.server.probe_address
        try:
            key = self.headers.get('Sec-WebSocket-Key', '')
            valid = (self.headers.get('Host') == self.server.probe_address and
                     self.headers.get('Origin') == expected and
                     self.headers.get('Upgrade', '').lower() == 'websocket' and
                     'upgrade' in [part.strip().lower() for part in self.headers.get('Connection', '').split(',')] and
                     self.headers.get('Sec-WebSocket-Version') == '13' and
                     self.headers.get('Sec-WebSocket-Protocol') == 'orbisfox-probe' and
                     len(base64.b64decode(key, validate=True)) == 16)
        except ValueError:
            valid = False
        if not valid:
            self.send_error(403)
            return
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest()).decode('ascii')
        self.send_response(101)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.send_header('Sec-WebSocket-Protocol', 'orbisfox-probe')
        self.end_headers()
        try:
            first, second = read_exact(self.rfile, 2)
            # Deliberately tiny fixture: one final masked UTF-8 text message.
            # Never allocate from an unbounded or extended peer length.
            length = second & 127
            if first != 0x81 or not second & 128 or not 1 <= length <= 125:
                self.wfile.write(b'\x88\x02\x03\xea')  # protocol error 1002
                return
            mask = read_exact(self.rfile, 4)
            payload = read_exact(self.rfile, length)
            text = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            text.decode('utf-8', errors='strict')
            self.wfile.write(bytes((0x81, len(text))) + text + b'\x88\x02\x03\xe8')
            self.wfile.flush()
        except (EOFError, OSError, UnicodeError):
            return


class ProbeServer(ThreadingHTTPServer):
    # A browser can preconnect without sending bytes. Never let that block
    # the real HTTP/iframe/WS request behind one idle accepted socket.
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(4)
        return connection, address


def server(host, port):
    instance = ProbeServer((host, port), Handler)
    instance.probe_address = f'{host}:{instance.server_port}'
    instance.timeout = 1
    return instance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--seconds', type=int, default=7200)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 7200 or not 1 <= args.port <= 65535:
        parser.error('Use lifetime1..7200 and valid port')
    with server(args.host, args.port) as instance:
        print(json.dumps({'url': 'http://' + instance.probe_address + '/', 'seconds': args.seconds,
                          'browser_verified': False, 'wss_verified': False}), flush=True)
        end = time.monotonic() + args.seconds
        while time.monotonic() < end:
            instance.handle_request()


if __name__ == '__main__':
    main()
