"""Review A: error-code correspondence and bounded-model sensitivity, offline only."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from facade import adapter
from bili_bridge.relays import BudgetRelay
from formal import video_reference_model as model
from scripts.check_video_reference_model import run


class ReviewARegressions(unittest.TestCase):
    def test_hourly_budget_survives_persisted_workflow_and_cached_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = adapter.HostProfile(tmp+'/db', tmp+'/spool', 'https://www.bilibili.com/', '7', 1)
            rid = adapter._id('budget-review')
            directory = Path(profile.db+'.workflows')
            directory.mkdir(mode=0o700)
            config = dict(id=rid, db=profile.db, spool=profile.spool,
                source_root=str(adapter.ROOT), source_digest=adapter.workflow.source_digest(),
                query='BV1xx411c7mD', selection=None, bvid='BV1xx411c7mD',
                comments=False, source_url=profile.source_url, tab=profile.tab, timeout=1)
            code = BudgetRelay.rejection(now=100., high_water=90., count=20,
                                         last_start=50., budget=20, interval=3.)
            self.assertEqual(code, 'hourly_budget')
            calls = []
            def deferred(args):
                calls.append(args)
                return dict(operation_id=args[args.index('--operation-id')+1],
                            status='deferred', data={}, error=code)
            path = directory/(rid+'.json')
            adapter.workflow.execute(config, path, runner=deferred, sleeper=lambda _:None)
            self.assertEqual(len(calls), 1)
            original = path.read_bytes()
            actual = adapter.status(dict(request_id=rid), profile=profile)
            self.assertEqual(actual['status'], 'failed')
            self.assertEqual(actual['error']['code'], 'hourly_budget')
            def never_spawn(*args, **kwargs):
                self.fail('cached retry must not spawn')
            retry = adapter.search_read(dict(query=config['query'], select=config['bvid']),
                profile=profile, invocation_id='budget-review', runner=never_spawn)
            self.assertEqual(retry, actual)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_relation_model_detects_added_fault_classes(self):
        report = run()
        self.assertTrue(report['ok'])
        self.assertEqual(report['model']['states'], 193)
        self.assertEqual(report['model']['edges'], 192)
        for name in ('drop_valid', 'drop_comments', 'reinterpret_outcome'):
            self.assertEqual(report['mutants'][name]['status'], 'invariant_violation')
        valid = model.State(phase='done', valid=True)
        self.assertEqual(model.invariant(valid), 'valid_input_must_delegate')


if __name__ == '__main__':
    unittest.main()
