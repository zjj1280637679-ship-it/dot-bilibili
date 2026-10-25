"""Offline fake CLI tests; never browser evidence."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('read_workflow', Path(__file__).resolve().parents[1] / 'scripts/read_workflow.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
BVID = 'BV1xx411c7mD'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'run.json'
        self.config = dict(id='run', db='/fixed/db', spool='/fixed/spool', query='exact',
                           source_url='https://www.bilibili.com/', tab='7', bvid=BVID,
                           selection=None, comments=True, timeout=120, source_digest='fixed')
        self.calls = []
        self.events = []

    def runner(self, args):
        self.calls.append(args)
        self.events.append('call')
        operation_id = args[args.index('--operation-id') + 1]
        self.assertEqual(__import__('json').loads(self.path.read_text())['pending_operation_id'], operation_id)
        return dict(operation_id=operation_id, status='applied', error=None,
                    data=dict(source='browser_dom', status='observed', complete=False,
                              items=[dict(bvid=BVID)], bvid=BVID, tab_id='7', query=self.config['query'],
                              observed_url=('https://search.bilibili.com/en/all?keyword=exact' if args[2] in ('browser-public-search', 'browser-read') else 'https://www.bilibili.com/video/'+BVID+'/')))

    def sleep(self, duration):
        self.assertGreaterEqual(duration, 5)
        self.events.append('wait')

    def run_workflow(self, runner=None):
        return w.execute(self.config, self.path, runner or self.runner, self.sleep)

    def test_success_and_cooldown(self):
        result = self.run_workflow()
        self.assertEqual(result['status'], 'succeeded_visible_subset')
        self.assertFalse(result['complete'])
        self.assertEqual(self.events, ['call', 'wait', 'call', 'wait', 'call', 'wait', 'call', 'wait', 'call'])
        self.assertEqual(len(self.calls), 5)
        for args in self.calls:
            self.assertEqual(args[1], self.config['db'])
            self.assertEqual(args[args.index('--spool')+1], self.config['spool'])
        self.assertEqual(self.calls[2][self.calls[2].index('--source-operation-id')+1], result['steps'][1]['operation_id'])

    def test_repeat_no_replay(self):
        first = self.run_workflow()
        self.assertEqual(self.run_workflow(), first)
        self.assertEqual(len(self.calls), 5)

    def test_changed_intent_conflict(self):
        self.run_workflow()
        self.config['query'] = 'different'
        self.assertEqual(self.run_workflow()['reason'], 'workflow_identity_conflict')
        self.assertEqual(len(self.calls), 5)

    def test_crash_record_never_replays(self):
        w.save(self.path, dict(intent=self.config, status='running', pending_operation_id='old'))
        self.assertEqual(self.run_workflow()['status'], 'unknown')
        self.assertFalse(self.calls)

    def test_exception_unknown_and_no_retry(self):
        def crash(args):
            raise OSError('lost process')
        self.assertEqual(self.run_workflow(crash)['status'], 'unknown')
        self.assertEqual(self.run_workflow()['status'], 'unknown')
        self.assertFalse(self.calls)

    def test_absent_exact_selection_stops_before_open(self):
        self.config['bvid'] = 'BV1234567890'
        self.assertEqual(self.run_workflow()['reason'], 'exact_selection_absent')
        self.assertEqual(len(self.calls), 2)

    def test_opt_in_selection(self):
        self.config.update(bvid=None, selection='first-visible-video', comments=False)
        result = self.run_workflow()
        self.assertEqual(result['selected_bvid'], BVID)
        self.assertEqual(len(self.calls), 4)

    def test_blocked_partial_and_unknown_stop(self):
        for status, outcome in [('blocked', 'partial'), ('deferred', 'partial'), ('unknown', 'unknown')]:
            with self.subTest(status=status):
                self.path.unlink(missing_ok=True)
                self.calls.clear()
                def blocked(args):
                    result = self.runner(args)
                    if len(self.calls) == 2:
                        result['status'] = status
                    return result
                self.assertEqual(self.run_workflow(blocked)['status'], outcome)
                self.assertEqual(len(self.calls), 2)

    def test_open_handoff_mismatch_stops(self):
        def wrong(args):
            result = self.runner(args)
            if len(self.calls) == 3:
                result['data']['tab_id'] = 'other'
            return result
        self.assertEqual(self.run_workflow(wrong)['reason'], 'open_handoff_mismatch')
        self.assertEqual(len(self.calls), 3)

    def test_non_browser_evidence_never_advances(self):
        def fake(args):
            result = self.runner(args)
            result['data']['source'] = 'synthetic'
            return result
        self.assertEqual(self.run_workflow(fake)['status'], 'failed')
        self.assertEqual(len(self.calls), 1)
