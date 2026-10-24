"""Exercise the real hosting entrypoint and durable state across a restart."""
import http.cookies
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import unittest
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

class HostingTests(unittest.TestCase):
    def test_start_health_secure_cookie_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'nested' / 'state'
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, HOW2_STATE_DIR=str(state), HOW2_DATABASE=str(state / 'how2.sqlite'), HOW2_HTTPS='1', HOW2_PROXY_HOPS='1', PORT=str(port), WEB_CONCURRENCY='2')
            env.pop('HOW2_SECRET_KEY', None)
            env['PATH'] = str(Path(os.sys.executable).parent) + os.pathsep + env['PATH']
            base = f'http://127.0.0.1:{port}'
            key = None
            for cycle in range(2):
                process = subprocess.Popen(['bash', 'scripts/start.sh'], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    for _ in range(100):
                        if process.poll() is not None:
                            self.fail('Hosting process exited before readiness')
                        try:
                            with urlopen(base + '/healthz', timeout=1) as response:
                                self.assertEqual(json.load(response)['status'], 'ok')
                            break
                        except OSError:
                            time.sleep(.05)
                    else:
                        self.fail('Hosting process did not become healthy')
                    with urlopen(base + '/api/catalog') as response:
                        self.assertEqual(len(json.load(response)['lessons']), 7)
                    if cycle == 0:
                        with urlopen(base + '/api/session') as response:
                            session = json.load(response)
                            raw_cookie = response.headers['Set-Cookie']
                            self.assertIn('Secure;', raw_cookie)
                            cookies = http.cookies.SimpleCookie(raw_cookie)
                            cookie = 'session=' + cookies['session'].value
                        payload = json.dumps(dict(type='General feedback', message='Persistence test across a hosting restart.')).encode()
                        req = Request(base + '/api/feedback', data=payload, headers={'Content-Type': 'application/json', 'Cookie': cookie, 'X-CSRF-Token': session['csrf'], 'X-Forwarded-Proto': 'https'})
                        with urlopen(req) as response:
                            self.assertTrue(json.load(response)['ok'])
                        key = (state / 'session.key').read_bytes()
                    else:
                        self.assertEqual((state / 'session.key').read_bytes(), key)
                        with sqlite3.connect(state / 'how2.sqlite') as connection:
                            self.assertEqual(connection.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 1)
                            self.assertEqual(connection.execute('SELECT COUNT(*) FROM lessons').fetchone()[0], 7)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

if __name__ == '__main__':
    unittest.main()
