"""Offline adapter tests; no browser evidence or host registration."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from facade import adapter as a

class FacadeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = a.HostProfile(self.temp.name+'/db', self.temp.name+'/spool', 'https://www.bilibili.com/', '7')
        self.args = dict(query='公开搜索', select='first_visible')
        self.calls = []
    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return SimpleNamespace(returncode=1, stdout=b'{"status":"failed","reason":"workflow_session_busy"}')
    def call(self, args=None):
        return a.search_read(self.args if args is None else args, profile=self.profile, invocation_id='trusted-call-1', runner=self.runner)
    def ledger(self, state='partial'):
        rid = a._id('trusted-call-1')
        directory = Path(self.profile.db+'.workflows')
        directory.mkdir(mode=0o700)
        record = dict(schema_version=1, status=state, steps=[], selected_bvid=None, reason=None,
            intent=dict(id=rid, db=self.profile.db, spool=self.profile.spool,
                source_root=str(a.ROOT), source_digest=a.workflow.source_digest(), query=self.args['query'], selection='first-visible-video', bvid=None, comments=False))
        a.workflow.save(directory/(rid+'.json'), record)
        return rid
    def test_fixed_real_entry_command(self):
        result = self.call()
        command, kwargs = self.calls[0]
        self.assertEqual(command[1], str(a.ROOT/'scripts/read_workflow.py'))
        self.assertNotIn('--comments', command)
        self.assertEqual(result['error']['code'], 'session_busy')
        self.assertFalse(kwargs.get('shell', False))
    def test_comments_opt_in(self):
        self.call(dict(self.args, comments=True))
        self.assertIn('--comments', self.calls[0][0])
    def test_strict_validation_before_spawn(self):
        for args in ({}, dict(self.args, path='/tmp/a'), dict(self.args, comments=1), dict(self.args, query=' '), dict(self.args, query='a\n'), dict(self.args, query='\ud800'), dict(self.args, select='best')):
            with self.subTest(args=repr(args)):
                self.assertEqual(self.call(args)['error']['code'], 'invalid_arguments')
        self.assertFalse(self.calls)
    def test_cache_and_status_do_not_spawn(self):
        rid = self.ledger()
        self.assertEqual(self.call()['status'], 'partial')
        self.assertEqual(a.status(dict(request_id=rid), profile=self.profile)['status'], 'partial')
        self.assertFalse(self.calls)
    def test_conflicting_retry(self):
        self.ledger()
        self.assertEqual(self.call(dict(self.args, comments=True))['error']['code'], 'request_conflict')
        self.assertFalse(self.calls)
    def test_interrupted_never_replayed(self):
        self.ledger('running')
        self.assertEqual(self.call()['status'], 'unknown')
        self.assertFalse(self.calls)
    def test_unknown_child_no_retry(self):
        def lost(*args, **kwargs):
            raise OSError('secret/path')
        result = a.search_read(self.args, profile=self.profile, invocation_id='trusted-call-1', runner=lost)
        self.assertEqual(result['status'], 'unknown')
        self.assertNotIn('secret', json.dumps(result))
    def test_status_no_directory_creation(self):
        result = a.status(dict(request_id=a._id('missing')), profile=self.profile)
        self.assertEqual(result['error']['code'], 'request_not_found')
        self.assertFalse(Path(self.profile.db+'.workflows').exists())
    def test_no_auto_identity(self):
        with self.assertRaises(ValueError):
            a.search_read(self.args, profile=self.profile, invocation_id='', runner=self.runner)
    def test_state_symlink_rejected(self):
        rid = self.ledger()
        path = Path(self.profile.db+'.workflows')/(rid+'.json')
        path.unlink()
        path.symlink_to('/dev/null')
        self.assertEqual(a.status(dict(request_id=rid), profile=self.profile)['status'], 'unknown')
    def test_observed_projection_preserves_visibility_and_bounds(self):
        metadata = {k: {'state': 'not_visible', 'value': None} for k in a.projection.FIELDS}
        def step(data):
            return dict(operation_id='internal', status='applied', error=None,
                        data=dict(source='browser_dom', status='observed', **data))
        record = dict(status='succeeded_visible_subset', selected_bvid='BV1xx411c7mD',
                      steps=[step({'items': []}), step({'items': [{'bvid': 'BV1xx411c7mD', 'title':'test', 'url':'https://www.bilibili.com/video/BV1xx411c7mD/', 'uploader':'', 'duration':'', 'displayed_counts':[]}]}),
                             step({}), step({'bvid': 'BV1xx411c7mD', 'observed_url': 'https://www.bilibili.com/video/BV1xx411c7mD/', 'metadata': metadata})])
        result = a._project('returned', record)
        self.assertEqual(result['data']['video']['metadata'], metadata)
        self.assertFalse(result['coverage']['complete'])
        self.assertNotIn('internal', json.dumps(result))
        record['steps'][3]['data']['metadata']['description'] = {'state':'visible', 'value':'a' * 262144}
        self.assertEqual(a._project('returned', record)['error']['code'], 'result_too_large')
    def test_status_rejects_traversal_as_arguments(self):
        result = a.status({'request_id': '../secret'}, profile=self.profile)
        self.assertEqual(result['error']['code'], 'invalid_arguments')
    def test_malformed_child_result_fails_closed(self):
        def malformed(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=b'{"status":"partial","steps":[null]}')
        result = a.search_read(self.args, profile=self.profile, invocation_id='malformed', runner=malformed)
        self.assertEqual(result['status'], 'unknown')
    def test_actual_subprocess_fail_closed_without_browser(self):
        # Real fixed workflow script, invalid trusted source: no browser host exists.
        # Use tiny timeout; actual kernel rejects unsupported source before emission.
        p = a.HostProfile(self.profile.db, self.profile.spool, 'https://invalid.example/', '7', 1)
        result = a.search_read(self.args, profile=p, invocation_id='offline-real-entry')
        self.assertNotEqual(result['status'], 'succeeded')
        self.assertTrue(Path(p.db+'.workflows').is_dir())

if __name__ == '__main__':
    unittest.main()
