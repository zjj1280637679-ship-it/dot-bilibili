"""Offline reference grammar and delegation checks; no live-browser evidence."""
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bili_video_reference import adapter, contracts
from facade import adapter as legacy

BV = 'BV1xx411c7mD'
URL = contracts.URL_PREFIX + BV


class ReferenceTests(unittest.TestCase):
    def test_aliases_normalize_to_exact_search_and_selection(self):
        for value in (BV, URL, URL + '/'):
            self.assertEqual(contracts.resolve(value), BV)
            self.assertEqual(contracts.validate({'video': value}),
                             dict(query=BV, select=BV, comments=False))

    def test_hostile_reference_forms_fail_closed(self):
        bad = [None, 1, True, [], {}, '', ' ' + BV, BV + '\n', BV.lower(),
               'BV1xx411c7m', BV + 'x', 'av1234', 'https://b23.tv/abc',
               URL.replace('https:', 'http:'), URL.replace('https:', 'HTTPS:'),
               URL.replace('www.', ''), URL.replace('www.', 'WWW.'),
               URL.replace('.com', '.com.evil.test'),
               URL.replace('.com', '.com:443'),
               URL.replace('www.', 'user@www.'),
               URL.replace('www.', 'user:pass@www.'),
               URL.replace('www.', 'evil.test@www.'),
               URL.replace('.com', '.com@evil.test'),
               URL.replace('/video/', '//video/'), URL.replace('/video/', '/x/../video/'),
               URL.replace('/video/', '/%76ideo/'), URL.replace('BV', '%42V'),
               URL.replace('/video/', '\\video\\'), URL + '//', URL + '/extra',
               URL + '?', URL + '#', URL + '/?p=2', URL + '/#reply',
               URL + '\n', URL + '\r', URL + '\x00', '\t' + URL,
               'Look at ' + URL, URL + ' share text', '／' + URL,
               'https://ｗｗｗ.bilibili.com/video/' + BV + '/', '\ud800', 'x' * 100000]
        for value in bad:
            with self.subTest(value=repr(value)), self.assertRaisesRegex(
                    ValueError, '^unsupported_video_reference$'):
                contracts.resolve(value)

    def test_schema_has_same_literal_boundary(self):
        schema = contracts.READ_VIDEO_SCHEMA
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['required'], ['video'])
        pattern = schema['properties']['video']['pattern']
        for value in (BV, URL, URL + '/'):
            self.assertIsNotNone(re.search(pattern, value))
        for value in (BV + '\n', URL + '/\n', URL + '?p=2'):
            self.assertIsNone(re.search(pattern, value))

    def test_invalid_argument_shapes_never_delegate(self):
        values = [None, [], {}, {'video': BV, 'comments': 1}, {'video': BV, 'comments': None}]
        values += [dict(video=BV, **{field: 'injected'}) for field in
                   ('query', 'select', 'url', 'db', 'spool', 'tab', 'source_url',
                    'invocation_id', 'runner', 'command', 'budget', 'retry')]
        with patch.object(adapter, 'search_read') as call:
            for value in values:
                result = adapter.read_video(value, profile=None, invocation_id='host-id')
                self.assertEqual(result['error']['code'], 'invalid_arguments')
        call.assert_not_called()

    def test_unsupported_reference_has_precise_error_without_execution(self):
        with patch.object(adapter, 'search_read') as call:
            result = adapter.read_video({'video': 'https://b23.tv/abc'},
                                        profile=None, invocation_id='host-id')
        call.assert_not_called()
        self.assertEqual(result['error']['code'], 'unsupported_video_reference')
        self.assertIsNone(result['data'])
        self.assertEqual(result['coverage']['scope'], 'none')

    def test_one_delegate_same_host_identity_and_unchanged_result(self):
        response = {'status': 'failed', 'error': {'code': 'selection_not_found'}}
        profile = object()
        for value in (BV, URL, URL + '/'):
            for comments in (False, True):
                with patch.object(adapter, 'search_read', return_value=response) as call:
                    result = adapter.read_video(dict(video=value, comments=comments),
                                                profile=profile, invocation_id='host-id')
                    self.assertIs(result, response)
                    call.assert_called_once_with(dict(query=BV, select=BV, comments=comments),
                                                 profile=profile, invocation_id='host-id')


class ExistingLedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = legacy.HostProfile(str(self.root/'db'), str(self.root/'spool'),
                                         'https://www.bilibili.com/', 'synthetic', 1)
        self.rid = legacy._id('host-id')

    def write_ledger(self, status='partial'):
        directory = Path(self.profile.db + '.workflows')
        directory.mkdir(mode=0o700)
        record = dict(schema_version=1, status=status, steps=[], selected_bvid=None,
                      reason=None, intent=dict(id=self.rid, db=self.profile.db,
                      spool=self.profile.spool, source_root=str(legacy.ROOT),
                      source_digest=legacy.workflow.source_digest(), query=BV,
                      selection=None, bvid=BV, comments=False))
        legacy.workflow.save(directory/(self.rid+'.json'), record)

    def read(self, video=BV, comments=False):
        return adapter.read_video(dict(video=video, comments=comments),
                                  profile=self.profile, invocation_id='host-id')

    def test_equivalent_aliases_reuse_existing_only_ledger_without_spawn(self):
        self.write_ledger()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('subprocess.Popen', side_effect=AssertionError('must not spawn')):
            results = [self.read(value) for value in (BV, URL, URL + '/')]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])
        self.assertEqual(results[0]['request_id'], self.rid)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(len(before), 1)

    def test_changed_video_or_comments_preserves_conflict_semantics(self):
        self.write_ledger()
        with patch('subprocess.Popen', side_effect=AssertionError('must not spawn')):
            for result in (self.read('BV2xx411c7mD'), self.read(comments=True)):
                self.assertEqual(result['error']['code'], 'request_conflict')

    def test_running_ledger_is_unknown_never_replayed(self):
        self.write_ledger('running')
        with patch('subprocess.Popen', side_effect=AssertionError('must not spawn')):
            self.assertEqual(self.read()['status'], 'unknown')

    def test_existing_fixed_workflow_command_and_comments_flag(self):
        for comments in (False, True):
            calls = []
            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return SimpleNamespace(returncode=1,
                    stdout=b'{"status":"failed","reason":"exact_selection_absent"}')
            def delegate(args, **kwargs):
                return legacy.search_read(args, runner=runner, **kwargs)
            with patch.object(adapter, 'search_read', side_effect=delegate):
                result = self.read(URL, comments)
            self.assertEqual(len(calls), 1)
            command, options = calls[0]
            self.assertEqual(command[1], str(legacy.ROOT/'scripts/read_workflow.py'))
            self.assertEqual(command[command.index('--query')+1], BV)
            self.assertEqual(command[command.index('--bvid')+1], BV)
            self.assertNotIn('--selection', command)
            self.assertEqual('--comments' in command, comments)
            self.assertEqual(options['timeout'], 5 * (self.profile.timeout + 30) + 30)
            self.assertEqual(result['error']['code'], 'selection_not_found')
            self.assertEqual(result['coverage']['comments_requested'], comments)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_lost_outcome_no_retry_or_new_ledger(self):
        def delegate(args, **kwargs):
            return legacy.search_read(args, runner=runner, **kwargs)
        # Runner injection is trusted test-only; no business argument enables it.
        from unittest.mock import Mock
        runner = Mock(side_effect=OSError('private path'))
        with patch.object(adapter, 'search_read', side_effect=delegate):
            result = self.read()
        runner.assert_called_once()
        self.assertEqual(result['status'], 'unknown')
        self.assertNotIn('private path', json.dumps(result))
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
