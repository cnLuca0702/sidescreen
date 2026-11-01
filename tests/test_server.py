import importlib.util
import json
from pathlib import Path
import threading
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import urlopen
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
server = load('sidescreen_server', ROOT / 'server.py')
renderer = load('launchagent_renderer', ROOT / 'scripts/render_launchagent.py')

class ConfigurationTests(unittest.TestCase):
    def test_default_is_loopback_with_no_outbound_gost_probes(self):
        args = server.parse_args([])
        self.assertEqual((args.host, args.port, args.enable_gost), ('127.0.0.1', 8790, False))
        self.assertFalse(server.GostSampler().snapshot()['enabled'])

    def test_explicit_probe_opt_in_and_ephemeral_test_port(self):
        args = server.parse_args(['--port', '0', '--enable-gost'])
        self.assertEqual(args.port, 0)
        self.assertTrue(args.enable_gost)

    def test_launchagent_is_parameterized_and_loopback_by_default(self):
        result = renderer.build_plist(ROOT, '/usr/bin/python3', ROOT / 'local')
        self.assertEqual(result['ProgramArguments'][-4:], ['--host', '127.0.0.1', '--port', '8790'])
        self.assertNotIn('--enable-gost', result['ProgramArguments'])
        self.assertEqual(result['Label'], 'com.example.sidescreen')

    def test_launchagent_preserves_virtualenv_interpreter_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / '.venv' / 'bin' / 'python'
            executable.parent.mkdir(parents=True)
            executable.symlink_to(sys.executable)
            result = renderer.build_plist(ROOT, executable, Path(directory) / 'logs')
            self.assertEqual(result['ProgramArguments'][0], str(executable))

class SamplingTests(unittest.TestCase):
    def test_timestamp_and_counter_histories_stay_aligned_and_isolated(self):
        with patch.object(server.psutil, 'cpu_percent', return_value=[20, 40]):
            sampler = server.SystemSampler()
            sampler._top_processes = lambda: []
            replacements = {
                'virtual_memory': lambda: SimpleNamespace(total=16 * 2**30, available=8 * 2**30, percent=50),
                'net_io_counters': lambda **kw: {'en0': SimpleNamespace(bytes_recv=400, bytes_sent=200)},
                'disk_usage': lambda _: SimpleNamespace(used=10 * 2**30, total=100 * 2**30, percent=10),
                'disk_io_counters': lambda: None, 'getloadavg': lambda: (1, 2, 3),
                'boot_time': lambda: 0, 'swap_memory': lambda: SimpleNamespace(percent=0),
                'sensors_battery': lambda: None,
            }
            with patch.multiple(server.psutil, **replacements), patch.object(server.socket, 'gethostname', return_value='ExampleHost'):
                with patch.object(server.time, 'time', return_value=100): sampler._sample()
                with patch.object(server.time, 'time', return_value=104): sampler._sample()
        snapshot, history = sampler.snapshot()
        self.assertEqual(snapshot['hostname'], 'ExampleHost')
        self.assertEqual(history['time'], [100, 104])
        self.assertTrue(all(len(values) == 2 for values in history.values()))
        history['time'].append(999)
        self.assertEqual(sampler.snapshot()[1]['time'], [100, 104])

class ProxyTests(unittest.TestCase):
    def probe_response(self, response):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.recv.return_value = response
        success, finished = Mock(), Mock()
        with patch.object(server.socket, 'create_connection', return_value=connection):
            server._probe_http(12345, finished, server._Race(), success)
        finished.assert_called_once_with()
        return success

    def test_proxy_authentication_and_upstream_errors_are_not_healthy(self):
        for code in [407, 500, 502]:
            self.assertFalse(self.probe_response(('HTTP/1.1 %s Error\r\n' % code).encode()).called)

    def test_successful_http_response_is_healthy(self):
        self.probe_response(b'HTTP/1.1 204 No Content\r\n').assert_called_once()

class HTTPTests(unittest.TestCase):
    def test_read_only_routes_and_snapshot_schema(self):
        fixture = ({'time': 100, 'hostname': 'ExampleHost'}, {'time': [100], 'cpu': [20], 'mem': [50], 'netDown': [0], 'netUp': [0]})
        system = SimpleNamespace(snapshot=lambda: fixture)
        gost = SimpleNamespace(snapshot=lambda: {'enabled': False, 'running': False, 'ports': [], 'processes': [], 'upCount': 0, 'totalPorts': 0, 'bestMs': None})
        with patch.object(server, 'system_sampler', system), patch.object(server, 'gost_sampler', gost):
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:%s' % http.server_port
            try:
                with urlopen(base + '/healthz') as response:
                    self.assertEqual(response.read(), b'ok')
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                for path in ['/', '/index']:
                    with urlopen(base + path) as response: self.assertIn(b'SideScreen', response.read())
                with urlopen(base + '/metrics') as response: data = json.load(response)
                self.assertEqual(data['sampleInterval'], 2)
                self.assertEqual(data['history']['time'], [100])
                self.assertFalse(data['gost']['enabled'])
                with self.assertRaises(HTTPError) as error: urlopen(base + '/not-a-route')
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
            finally:
                http.shutdown(); http.server_close(); thread.join(timeout=2)

if __name__ == '__main__': unittest.main()
