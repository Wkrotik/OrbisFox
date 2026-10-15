import base64
import http.client
import hashlib
from pathlib import Path
import runpy
import socket
import subprocess
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrowserNetworkTests(unittest.TestCase):
    def test_controlled_real_websocket_handshake_mask_echo_close_and_origin(self):
        fixture = runpy.run_path(str(ROOT / 'scripts/serve-browser-network.py'))
        with fixture['server']('127.0.0.1', 0) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
            worker.start()
            # Genuine browser preconnections may sit idle. The HTTP and WS
            # checks must still complete while this socket stays open.
            idle = socket.create_connection(('127.0.0.1', server.server_port), timeout=3)
            try:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                connection.request('GET', '/poll')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), b'{"probe":"orbisfox-network"}')
                connection.close()
                for origin, expected in [('https://foreign.example', 403), ('http://' + server.probe_address, 101)]:
                    with socket.create_connection(('127.0.0.1', server.server_port), timeout=3) as stream:
                        key = base64.b64encode(b'0123456789abcdef').decode('ascii')
                        stream.sendall((f'GET /socket HTTP/1.1\r\nHost: {server.probe_address}\r\n'
                                        f'Origin: {origin}\r\nUpgrade: websocket\r\nConnection: keep-alive,Upgrade\r\n'
                                        f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                                        'Sec-WebSocket-Protocol: orbisfox-probe\r\n\r\n').encode('ascii'))
                        reader = stream.makefile('rb')
                        headers = bytearray()
                        while not headers.endswith(b'\r\n\r\n'):
                            headers += fixture['read_exact'](reader, 1)
                            self.assertLess(len(headers), 8192)
                        self.assertIn(f' {expected} '.encode(), headers.split(b'\r\n')[0])
                        if expected == 101:
                            expected_accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')).digest())
                            self.assertIn(b'Sec-WebSocket-Accept: ' + expected_accept + b'\r\n', headers)
                            value = b'actual-echo-not-a-static-pass'
                            mask = b'\x01\x02\x03\x04'
                            stream.sendall(bytes((0x81, 128 | len(value))) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(value)))
                            self.assertEqual(fixture['read_exact'](reader, len(value) + 6), bytes((0x81, len(value))) + value + b'\x88\x02\x03\xe8')
                        reader.close()
            finally:
                idle.close()
                server.shutdown()
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())

    def test_fullscreen_uses_real_focus_activation_and_owned_events(self):
        subprocess.run(['node', str(ROOT / 'tests/browser_fullscreen_test.js')], check=True)
        embedding = (ROOT / 'gecko/orbisfox/create-visible-browser.inc').read_text()
        self.assertIn('browser->FocusActivate(nsFocusManager::GenerateFocusActionId())', embedding)
        startup = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('"full-screen-api.ignore-widgets": true', startup)
        self.assertNotIn('full-screen-api.allow-trusted-requests-only": false', startup)

    def test_bounded_opt_in_content_network_observer(self):
        subprocess.run(['node', str(ROOT / 'tests/browser_network_observer_test.js')], check=True)

    def test_native_identity_and_actual_protocol_implementation(self):
        startup = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        configure = (ROOT / 'gecko/orbisfox/moz.configure').read_text()
        self.assertIn('imply_option("MOZ_APP_UA_NAME", "OrbisFox")', configure)
        self.assertIn('"general.useragent.compatMode.firefox": true', startup)
        self.assertNotIn('general.useragent.override', startup)
        build = (ROOT / '.deps/gecko-layout/netwerk/protocol/websocket/moz.build').read_text()
        self.assertIn('WebSocketChannel.cpp', build)
        self.assertNotIn('network.websocket.enabled": false', startup)
