"""Independent offline facade audit: never services a browser request."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from facade import adapter as a


class FacadeIndependentAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = a.HostProfile(self.temp.name + '/db', self.temp.name + '/spool',
                                     'https://www.bilibili.com/', '7', 1)
        self.args = dict(query='公开搜索', select='first_visible', comments=True)

    def persisted_workflow(self, invocation='audit-persisted'):
        rid = a._id(invocation)
        directory = Path(self.profile.db + '.workflows')
        directory.mkdir(mode=0o700, exist_ok=True)
        config = dict(id=rid, db=self.profile.db, spool=self.profile.spool,
                      source_root=str(a.ROOT), source_digest=a.workflow.source_digest(),
                      query=self.args['query'], selection='first-visible-video', bvid=None,
                      comments=True, source_url=self.profile.source_url, tab='7', timeout=1)
        bvid = 'BV1xx411c7mD'
        video_url = 'https://www.bilibili.com/video/' + bvid + '/'
        search_url = 'https://search.bilibili.com/all?keyword=%E5%85%AC%E5%BC%80%E6%90%9C%E7%B4%A2'
        seen = []
        def runner(argv):
            index = len(seen)
            seen.append(argv)
            oid = argv[argv.index('--operation-id') + 1]
            data = dict(source='browser_dom', status='observed', tab_id='7', captured_at=123.0,
                        complete=False, coverage='destination_only' if index == 2 else 'visible_subset',
                        observed_url=search_url if index < 2 else video_url)
            if index < 2:
                data.update(query=config['query'], items=[dict(bvid=bvid, title='Observed title',
                    url=video_url, uploader='', duration='', displayed_counts=[])])
            else:
                data['bvid'] = bvid
            if index == 3:
                data['metadata'] = {key: {'state': 'not_visible', 'value': None}
                    for key in ('title', 'uploader', 'description', 'duration', 'displayed_counts')}
            if index == 4:
                data.update(threads=[], extraction='open_shadow_dom')
            return dict(operation_id=oid, status='applied', error=None, data=data)
        record = a.workflow.execute(config, directory / (rid + '.json'), runner=runner, sleeper=lambda _: None)
        self.assertEqual(record['status'], 'succeeded_visible_subset')
        self.assertEqual(len(seen), 5)
        return rid, record

    def test_real_workflow_shape_cached_without_new_source(self):
        rid, record = self.persisted_workflow()
        changed = a.HostProfile(self.profile.db, self.profile.spool, 'https://www.bilibili.com/changed', '99', 1)
        def forbidden(*args, **kwargs):
            raise AssertionError('cached retry must not spawn')
        result = a.search_read(self.args, profile=changed, invocation_id='audit-persisted', runner=forbidden)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['data']['comments'], [])
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(result['data']['video']['metadata']['title'], {'state': 'not_visible', 'value': None})
        self.assertNotIn(self.profile.db, json.dumps(result))
        self.assertNotIn('wf-', json.dumps(result))
        self.assertEqual(a.status({'request_id': rid}, profile=changed), result)

    def test_running_record_is_unknown_without_replay(self):
        rid, record = self.persisted_workflow()
        record['status'] = 'running'
        a.workflow.save(Path(self.profile.db + '.workflows') / (rid + '.json'), record)
        def forbidden(*args, **kwargs):
            raise AssertionError('uncertain retry must not spawn')
        self.assertEqual(a.search_read(self.args, profile=self.profile,
            invocation_id='audit-persisted', runner=forbidden)['status'], 'unknown')
        self.assertEqual(a.status({'request_id': rid}, profile=self.profile)['status'], 'unknown')

    def test_malformed_persisted_intent_is_safe(self):
        rid, record = self.persisted_workflow()
        record['intent'] = []
        a.workflow.save(Path(self.profile.db + '.workflows') / (rid + '.json'), record)
        result = a.status({'request_id': rid}, profile=self.profile)
        self.assertEqual(result['status'], 'unknown')

    def test_source_version_drift_fails_closed_without_spawn(self):
        rid, record = self.persisted_workflow()
        record['intent']['source_digest'] = '0' * 64
        a.workflow.save(Path(self.profile.db + '.workflows') / (rid + '.json'), record)
        def forbidden(*args, **kwargs):
            raise AssertionError('version drift must not spawn')
        self.assertEqual(a.search_read(self.args, profile=self.profile,
            invocation_id='audit-persisted', runner=forbidden)['status'], 'unknown')

    def test_projection_suppresses_nested_receipt_keys(self):
        rid, record = self.persisted_workflow()
        secret = '/private/spool/secret-operation-id'
        record['steps'][1]['data']['items'][0]['private_path'] = secret
        record['steps'][3]['data']['metadata']['title']['correlation_id'] = secret
        record['steps'][3]['data']['metadata']['private_route'] = secret
        result = a._project(rid, record, True)
        self.assertNotIn(secret, json.dumps(result))

    def test_public_blocker_error_preserved(self):
        rid, record = self.persisted_workflow()
        record.update(status='partial', reason='step_not_observed')
        record['steps'][-1].update(status='blocked', error='captcha')
        record['steps'][-1]['data'].update(status='blocked', threads=[])
        result = a._project(rid, record, True)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['error']['code'], 'captcha')
        self.assertEqual(result['next_action'], 'contact_host')
        self.assertIsNone(result['data']['comments'])

    def test_real_streaming_executor_caps_output(self):
        # A harmless local child, not the browser workflow or an execution API.
        with patch.object(a.workflow, 'MAX_STATE', 512):
            with self.assertRaisesRegex(ValueError, 'oversize_workflow_output'):
                a._run_bounded([a.sys.executable, '-c', 'print("x" * 4096)'],
                    cwd=a.ROOT, stdout=a.subprocess.PIPE, stderr=a.subprocess.DEVNULL,
                    timeout=5, check=False)

    def test_all_67_frozen_sources_unchanged(self):
        frozen = json.loads((a.ROOT / 'docs/milestone-five-acceptance.json').read_text())['source_sha256']
        self.assertEqual(len(frozen), 67)
        for name, digest in frozen.items():
            with self.subTest(source=name):
                self.assertEqual(hashlib.sha256((a.ROOT / name).read_bytes()).hexdigest(), digest)

    def test_malformed_success_not_promoted(self):
        def malformed(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=b'{"status":"succeeded_visible_subset","steps":[]}')
        result = a.search_read(self.args, profile=self.profile, invocation_id='audit-malformed', runner=malformed)
        self.assertNotEqual(result['status'], 'succeeded')

    def test_invalid_model_fields_never_reach_executor(self):
        with patch.object(a.subprocess, 'Popen', side_effect=AssertionError('spawn forbidden')):
            for key in ('db', 'spool', 'source_url', 'tab', 'invocation_id', 'runner', 'command', 'code', 'timeout'):
                with self.subTest(field=key):
                    result = a.search_read(dict(self.args, **{key: 'untrusted'}),
                                           profile=self.profile, invocation_id='audit-fields')
                    self.assertEqual(result['error']['code'], 'invalid_arguments')

    def test_status_is_read_only_and_does_not_spawn(self):
        before = sorted(Path(self.temp.name).rglob('*'))
        with patch.object(a.subprocess, 'Popen', side_effect=AssertionError('spawn forbidden')):
            result = a.status({'request_id': a._id('nonexistent')}, profile=self.profile)
        self.assertEqual(result['error']['code'], 'request_not_found')
        self.assertEqual(before, sorted(Path(self.temp.name).rglob('*')))

    def test_exception_details_never_exposed(self):
        def failed(*args, **kwargs):
            raise OSError('/private/session/spool secret-correlation-id')
        result = a.search_read(self.args, profile=self.profile, invocation_id='audit-failure', runner=failed)
        self.assertEqual(result['status'], 'unknown')
        self.assertNotIn('/private', json.dumps(result))
        self.assertNotIn('secret-correlation', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
