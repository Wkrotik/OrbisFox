import hashlib
import http.client
import importlib.util
from pathlib import Path
import threading
import unittest
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('lan_server', ROOT / 'scripts/serve-network-fixture.py')
SERVER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SERVER)

class NetworkFixtureServerTest(unittest.TestCase):
    def test_host_server_only_serves_exact_probe_and_frozen_fixture(self):
        # Host HTTP transport only, never console/Necko/DNS/TLS certification.
        fixture = (ROOT / 'gecko/orbisfox/fixtures/offline.html').read_bytes()
        host, port, token = SERVER.configuration()
        self.assertEqual((host, port), ('10.42.0.1', 8765))
        server = SERVER.ProbeServer(('127.0.0.1', 0), fixture, token)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        worker.start()
        try:
            def request(path, method='GET'):
                client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                client.request(method, path)
                response = client.getresponse()
                result = response.status, response.read(), dict(response.getheaders())
                client.close()
                return result
            status, body, headers = request('/orbisfox/probe/' + token)
            self.assertEqual(status, 200)
            self.assertEqual(body, ('OrbisFox native Necko probe ' + token + '\n').encode('ascii'))
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['Connection'], 'close')
            status, body, headers = request('/orbisfox/offline.html')
            self.assertEqual(status, 200)
            self.assertEqual(hashlib.sha256(body).digest(), hashlib.sha256(fixture).digest())
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
            for path in ['/orbisfox/probe/wrong-token', '/../../etc/passwd', '/', '/orbisfox/offline.html?other=1']:
                self.assertEqual(request(path)[0], 404)
            self.assertEqual(request('/orbisfox/offline.html', 'POST')[0], 501)
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=3)
        self.assertFalse(worker.is_alive())

if __name__ == '__main__': unittest.main()
