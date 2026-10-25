"""Additive host integration checks; frozen browser/workflow proofs are unchanged."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bili_integration import cli, dispatcher
from facade import HostProfile


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = HostProfile(str(self.root / 'state.sqlite3'), str(self.root / 'spool'),
                                   'https://www.bilibili.com/', 'synthetic', 1)

    def test_dispatch_exact_search(self):
        args = {'query': 'synthetic', 'select': 'first_visible'}
        with patch.object(dispatcher, 'search_read', return_value={'status': 'unknown'}) as run:
            result = dispatcher.dispatch({'tool': 'bili_search_read', 'arguments': args},
                                         profile=self.profile, invocation_id='durable-id')
        self.assertEqual(result, {'status': 'unknown'})
        run.assert_called_once_with(args, profile=self.profile, invocation_id='durable-id')

    def test_status_no_search(self):
        args = {'request_id': 'fr-' + '0' * 64}
        with patch.object(dispatcher, 'search_read') as run:
            result = dispatcher.dispatch({'tool': 'bili_status', 'arguments': args}, profile=self.profile)
        run.assert_not_called()
        self.assertEqual(result['error']['code'], 'request_not_found')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_status_does_not_execute_or_construct_browser_host(self):
        with patch('subprocess.Popen', side_effect=AssertionError('subprocess')), patch(
                'bili_bridge.browser_host.FileBrowserHost', side_effect=AssertionError('host')):
            result = dispatcher.dispatch({'tool': 'bili_status', 'arguments': {
                'request_id': 'fr-' + 'a' * 64}}, profile=self.profile)
        self.assertEqual(result['error']['code'], 'request_not_found')

    def test_malformed_transport_never_searches(self):
        values = [None, [], {}, {'tool': 'bili_search_read'},
                  {'tool': 'bili_search_read', 'arguments': [],},
                  {'tool': 'bili_search_read', 'arguments': {}, 'invocation_id': 'model-id'},
                  {'tool': 'bili_search_read', 'arguments': {}, 'profile': '/tmp/other'}]
        with patch.object(dispatcher, 'search_read') as run:
            for value in values:
                with self.subTest(value=value):
                    self.assertEqual(dispatcher.dispatch(value, profile=self.profile)['error']['code'],
                                     'invalid_arguments')
        run.assert_not_called()

    def test_unknown_tool(self):
        for name in ['navigate', 'browser.eval', [], None, 'bili_search_read;sh']:
            result = dispatcher.dispatch({'tool': name, 'arguments': {}}, profile=self.profile)
            self.assertEqual(result['error']['code'], 'unknown_tool')

    def test_search_requires_host_id(self):
        with patch.object(dispatcher, 'search_read') as run:
            for value in [None, '', 3, 'x' * 1001, '\udcff']:
                result = dispatcher.dispatch({'tool': 'bili_search_read', 'arguments': {}},
                                             profile=self.profile, invocation_id=value)
                self.assertEqual(result['error']['code'], 'host_invocation_required')
        run.assert_not_called()

    def test_business_arguments_cannot_change_authority(self):
        for field in ['db', 'spool', 'source_url', 'tab', 'invocation_id', 'command', 'script']:
            result = dispatcher.dispatch({'tool': 'bili_search_read', 'arguments': {
                'query': 'synthetic', 'select': 'first_visible', field: 'injected'}},
                profile=self.profile, invocation_id='durable-id')
            self.assertEqual(result['error']['code'], 'invalid_arguments')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_decode_strict_json(self):
        for raw in [b'{"a":1,"a":2}', b'{"x":{"a":1,"a":2}}', b'NaN', b'Infinity',
                    b'{"x":-Infinity}', b'{}{}', b'\xff', b' ' * 8193]:
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                cli.decode(raw)
        self.assertEqual(cli.decode(b'{"tool":"bili_status","arguments":{}}'),
                         {'tool': 'bili_status', 'arguments': {}})

    def write_profile(self, **extra):
        data = dict(db=self.profile.db, spool=self.profile.spool,
                    source_url=self.profile.source_url, tab=self.profile.tab, timeout=1)
        data.update(extra)
        path = self.root / 'profile.json'
        path.write_text(json.dumps(data))
        path.chmod(0o600)
        return path

    def test_private_profile(self):
        path = self.write_profile()
        self.assertEqual(cli.load_profile(path), self.profile)

    def test_profile_rejects_world_readable_and_symlink(self):
        path = self.write_profile()
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            cli.load_profile(path)
        path.chmod(0o600)
        link = self.root / 'link'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            cli.load_profile(link)

    def test_profile_rejects_unknown_or_relative_fields(self):
        for args in [{'url': 'https://example.com'}, {'db': 'relative.sqlite3'},
                     {'timeout': True}, {'tab': 1}, {'spool': ''}]:
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                cli.load_profile(self.write_profile(**args))

    def test_diagnostics_does_not_touch_state(self):
        result = cli.diagnostics()
        self.assertEqual(result['status'], 'ready_for_host_binding')
        self.assertIs(result['native_tool_registration'], False)
        self.assertEqual(result['browser_access'], 'not_checked')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_invalid_payload_and_no_profile_detail_leak(self):
        with patch('sys.stdout', new_callable=io.StringIO) as out:
            cli.main(['call', '--profile', str(self.root / 'private-missing.json')])
        result = json.loads(out.getvalue())
        self.assertEqual(result['error']['code'], 'host_profile_unavailable')
        self.assertNotIn(str(self.root), out.getvalue())

    def test_instructions_only_locates_reviewed_resources(self):
        result = cli.instructions()
        self.assertIs(result['native_tool_registration'], False)
        self.assertTrue(all(Path(p).is_file() for p in result['resources'].values()))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_profile_environment_is_host_only(self):
        profile = self.write_profile()
        with patch.dict('os.environ', {'BILI_HOST_PROFILE': str(profile)}), patch(
                'sys.stdin', io.TextIOWrapper(io.BytesIO(b'{"tool":"unknown","arguments":{}}'))), patch(
                'sys.stdout', new_callable=io.StringIO) as out:
            cli.main(['call'])
        self.assertEqual(json.loads(out.getvalue())['error']['code'], 'unknown_tool')

    def test_cli_one_call_not_a_server(self):
        profile = self.write_profile()
        request = json.dumps({'tool': 'bili_status', 'arguments': {'request_id': 'fr-' + '0' * 64}})
        stdin = io.TextIOWrapper(io.BytesIO(request.encode()))
        with patch('sys.stdin', stdin), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(cli.main(['call', '--profile', str(profile)]), 0)
        self.assertEqual(json.loads(out.getvalue())['error']['code'], 'request_not_found')
        self.assertEqual(list(self.root.iterdir()), [profile])


if __name__ == '__main__':
    unittest.main()
