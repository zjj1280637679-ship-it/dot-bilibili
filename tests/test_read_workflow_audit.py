"""Independent adversarial workflow checks. All evidence is offline fake CLI only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('audit_read_workflow', Path(__file__).resolve().parents[1] / 'scripts/read_workflow.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WorkflowAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'audit.json'
        self.config = dict(id='audit', db='/fixed/db', spool='/fixed/spool', query='query',
            source_url='https://www.bilibili.com/', tab='7', bvid='BV1xx411c7mD',
            selection=None, comments=False, timeout=1, source_digest='fixed')
        self.calls = []

    def runner(self, args):
        self.calls.append(args)
        operation_id = args[args.index('--operation-id') + 1]
        durable = json.loads(self.path.read_text())
        self.assertEqual(durable['pending_operation_id'], operation_id)
        return {'operation_id': operation_id, 'status': 'applied', 'error': None,
                'data': {'source': 'browser_dom', 'status': 'observed',
                         'items': [{'bvid': self.config['bvid']}], 'bvid': self.config['bvid'],
                         'query': self.config['query'], 'tab_id': '7', 'observed_url':
                         ('https://search.bilibili.com/all?keyword=query' if args[2] in ('browser-public-search', 'browser-read')
                          else 'https://www.bilibili.com/video/BV1xx411c7mD/')}}

    def run_workflow(self, runner=None):
        return w.execute(self.config, self.path, runner or self.runner, lambda _: None)

    def test_post_child_ledger_crash_never_replays(self):
        original_save = w.save
        def fail_after_child(path, record):
            if record.get('steps'):
                raise OSError('simulated durable write failure')
            return original_save(path, record)
        with mock.patch.object(w, 'save', side_effect=fail_after_child):
            try:
                self.run_workflow()
            except OSError:
                pass
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.run_workflow()['status'], 'unknown')
        self.assertEqual(len(self.calls), 1)

    def test_malformed_child_data_is_unknown_no_replay(self):
        def malformed(args):
            result = self.runner(args)
            result['data'] = None
            return result
        self.assertEqual(self.run_workflow(malformed)['status'], 'unknown')
        self.assertEqual(self.run_workflow()['status'], 'unknown')
        self.assertEqual(len(self.calls), 1)

    def test_save_does_not_follow_predictable_temp_symlink(self):
        victim = Path(self.tmp.name) / 'victim'
        victim.write_text('untouched')
        self.path.with_suffix('.tmp').symlink_to(victim)
        try:
            w.save(self.path, {'safe': True})
        except OSError:
            pass
        self.assertEqual(victim.read_text(), 'untouched')

    def test_invoke_bounds_child_output_and_terminates(self):
        original_popen = subprocess.Popen
        processes = []
        def local_child(*args, **kwargs):
            self.assertIsInstance(args[0], list)
            self.assertNotIn('shell', kwargs)
            process = original_popen([sys.executable, '-c',
                "import sys,time; sys.stdout.write('x'*65536); sys.stdout.flush(); time.sleep(30)"], **kwargs)
            processes.append(process)
            return process
        with mock.patch.object(w.subprocess, 'Popen', side_effect=local_child), mock.patch.object(w, 'MAX_OUTPUT', 1024):
            with self.assertRaises(ValueError):
                w.invoke(['--timeout', '1'])
        self.assertIsNotNone(processes[0].poll())

    def test_invoke_timeout_terminates_child(self):
        original_popen = subprocess.Popen
        processes = []
        def local_child(*args, **kwargs):
            process = original_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            processes.append(process)
            return process
        with mock.patch.object(w.subprocess, 'Popen', side_effect=local_child), mock.patch.object(w.time, 'monotonic', side_effect=[0, 100]):
            with self.assertRaises(TimeoutError):
                w.invoke(['--timeout', '1'])
        self.assertIsNotNone(processes[0].poll())

    def test_last_read_wrong_target_never_reports_success(self):
        def wrong_target(args):
            result = self.runner(args)
            if len(self.calls) == 4:
                result['data']['bvid'] = 'BV1234567890'
            return result
        self.assertEqual(self.run_workflow(wrong_target)['status'], 'unknown')
        self.assertEqual(self.run_workflow()['status'], 'unknown')
        self.assertEqual(len(self.calls), 4)

    def test_malformed_search_items_never_opens(self):
        def malformed_items(args):
            result = self.runner(args)
            result['data']['items'] = [None]
            return result
        self.assertEqual(self.run_workflow(malformed_items)['status'], 'unknown')
        self.assertEqual(len(self.calls), 1)

    def test_changed_source_hash_conflicts_without_replay(self):
        self.run_workflow()
        self.config['source_digest'] = 'changed'
        self.assertEqual(self.run_workflow()['reason'], 'workflow_identity_conflict')
        self.assertEqual(len(self.calls), 4)

    def test_stale_first_search_selection_does_not_open(self):
        def stale_only(args):
            result = self.runner(args)
            if args[2] == 'browser-read':
                result['data']['items'] = [{'bvid': 'BV1234567890'}]
            return result
        result = self.run_workflow(stale_only)
        self.assertEqual(result['reason'], 'exact_selection_absent')
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn('selected_bvid', result)
        self.assertEqual(self.run_workflow(), result)
        self.assertEqual(len(self.calls), 2)

    def test_fresh_second_search_is_only_open_source(self):
        self.config['comments'] = True
        result = self.run_workflow()
        self.assertEqual(result['status'], 'succeeded_visible_subset')
        self.assertEqual(len(self.calls), 5)
        opening = self.calls[2]
        self.assertEqual(opening[opening.index('--source-operation-id') + 1],
                         result['steps'][1]['operation_id'])
        self.assertNotEqual(result['steps'][0]['operation_id'], result['steps'][1]['operation_id'])

    def test_no_comments_without_explicit_opt_in(self):
        self.run_workflow()
        self.assertEqual([a[2] for a in self.calls],
                         ['browser-public-search', 'browser-read', 'browser-video-open', 'browser-video-read'])
        self.assertTrue(all(a[0:2] == ['--db', '/fixed/db'] for a in self.calls))
        self.assertTrue(all(a[a.index('--spool') + 1] == '/fixed/spool' for a in self.calls))

if __name__ == '__main__':
    unittest.main()
