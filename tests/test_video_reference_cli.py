"""Offline versioned CLI checks; no browser service or tool registration."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bili_video_reference import cli
from bili_integration import cli as old_cli

BV = 'BV1xx411c7mD'


class VideoReferenceCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = self.root/'profile.json'
        self.profile.write_text(json.dumps(dict(db=str(self.root/'db'),
            spool=str(self.root/'spool'), source_url='https://www.bilibili.com/',
            tab='synthetic', timeout=1)))
        self.profile.chmod(0o600)

    def run_cli(self, raw, *args):
        with patch('sys.stdin', io.TextIOWrapper(io.BytesIO(raw))), patch(
                'sys.stdout', new_callable=io.StringIO) as out:
            code = cli.main(list(args))
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_reuses_reviewed_decoder_and_profile_loader(self):
        self.assertIs(cli.decode, old_cli.decode)
        self.assertIs(cli.load_profile, old_cli.load_profile)
        self.assertEqual(cli.MAX_REQUEST_BYTES, old_cli.MAX_REQUEST_BYTES)

    def test_schemas_no_host_or_state_needed(self):
        with patch.object(cli, 'load_profile', side_effect=AssertionError('no load')):
            result = self.run_cli(b'', 'schemas')
        self.assertEqual([x['name'] for x in result], ['bili_read_video'])
        self.assertEqual(list(self.root.iterdir()), [self.profile])

    def test_dispatch_uses_only_trusted_metadata(self):
        args = {'video': BV}
        profile = object()
        with patch.object(cli, 'read_video', return_value={'status': 'unknown'}) as read:
            result = cli.dispatch({'tool': 'bili_read_video', 'arguments': args},
                                  profile=profile, invocation_id='durable-id')
        read.assert_called_once_with(args, profile=profile, invocation_id='durable-id')
        self.assertEqual(result, {'status': 'unknown'})

    def test_malformed_transport_never_delegates(self):
        bad = [None, [], {}, {'tool': 'bili_read_video'},
               {'tool': 'bili_read_video', 'arguments': []},
               {'tool': 'bili_read_video', 'arguments': {}, 'invocation_id': 'model-id'}]
        with patch.object(cli, 'read_video') as read:
            for value in bad:
                result = cli.dispatch(value, profile=None, invocation_id='trusted')
                self.assertEqual(result['error']['code'], 'invalid_arguments')
        read.assert_not_called()

    def test_other_tools_do_not_fall_through(self):
        with patch.object(cli, 'read_video') as read:
            for name in ('bili_status', 'bili_search_read', 'navigate', [], None):
                result = cli.dispatch({'tool': name, 'arguments': {}}, profile=None)
                self.assertEqual(result['error']['code'], 'unknown_tool')
        read.assert_not_called()

    def test_requires_valid_host_invocation(self):
        with patch.object(cli, 'read_video') as read:
            for value in (None, '', 3, 'x'*1001, '\ud800'):
                result = cli.dispatch({'tool': 'bili_read_video', 'arguments': {'video': BV}},
                                      profile=None, invocation_id=value)
                self.assertEqual(result['error']['code'], 'host_invocation_required')
        read.assert_not_called()

    def test_call_private_profile_and_env_path_one_dispatch(self):
        request = {'tool': 'bili_read_video', 'arguments': {'video': BV}}
        with patch.dict('os.environ', {'BILI_HOST_PROFILE': str(self.profile)}), patch.object(
                cli, 'dispatch', return_value={'status': 'unknown'}) as dispatch:
            result = self.run_cli(json.dumps(request).encode(), 'call', '--invocation-id', 'saved')
        dispatch.assert_called_once_with(request, profile=old_cli.load_profile(self.profile),
                                         invocation_id='saved')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(list(self.root.iterdir()), [self.profile])

    def test_bad_json_rejected_before_dispatch(self):
        with patch.object(cli, 'dispatch') as dispatch:
            for raw in (b'{"tool":1,"tool":2}', b'{"arguments":{"video":1,"video":2}}',
                        b'NaN', b'{}{}', b'\xff', b' '*8193):
                result = self.run_cli(raw, 'call', '--profile', str(self.profile),
                                      '--invocation-id', 'saved')
                self.assertEqual(result['error']['code'], 'invalid_arguments')
        dispatch.assert_not_called()

    def test_unavailable_profile_sanitized(self):
        result = self.run_cli(b'{}', 'call', '--profile', str(self.root/'secret'))
        self.assertEqual(result['error']['code'], 'host_profile_unavailable')
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_nonprivate_profile_never_dispatches(self):
        self.profile.chmod(0o644)
        with patch.object(cli, 'dispatch') as dispatch:
            result = self.run_cli(b'{}', 'call', '--profile', str(self.profile))
        dispatch.assert_not_called()
        self.assertEqual(result['error']['code'], 'host_profile_unavailable')


if __name__ == '__main__':
    unittest.main()
