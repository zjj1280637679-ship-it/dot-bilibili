"""All evidence constructed here is synthetic; these tests do not accept real leaves."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reversible', ROOT / 'scripts/check_reversible_acceptance.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ReversibleAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(gate.DEFAULT.read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, data):
        raw = json.dumps(data).encode()
        (self.root / name).write_bytes(raw)
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def fixture(self):
        leaf = copy.deepcopy(next(x for x in self.data['leaves'] if x['id'] == 'player.volume.set'))
        leaf.update(scope='included', classification_status='reviewed', status='accepted')
        leaf['authorization'] = {'status': 'approved', 'target': 'synthetic-target',
            'reference': self.put('auth.json', {'synthetic': True}), 'residual_effects_approved': True}
        leaf['review'] = {'status': 'approved', 'reviewer': 'synthetic-test-only',
            'reference': self.put('review.json', {'synthetic': True})}
        leaf['state_contract'] = {'route': 'synthetic-route', 'state_keys': ['volume'],
            'action': 'set volume 20', 'inverse': 'set volume 10', 'residual_effects': [],
            'expected_after': {'volume': 20}}
        for n, phase in enumerate(gate.PHASES):
            event = {'phase': phase, 'leaf_id': leaf['id'], 'mode': 'live', 'outcome': 'success',
                'target': 'synthetic-target', 'route': 'synthetic-route', 'run_id': 'synthetic-run',
                'observed_at': f'2026-10-25T10:00:0{n}Z'}
            if phase in {'before', 'after', 'final'}:
                event['state'] = {'volume': 20 if phase == 'after' else 10}
            else:
                event['operation'] = 'set volume 20' if phase == 'action' else 'set volume 10'
            capture = dict(event, source='host_dom')
            event['observation'] = self.put(phase + '-capture.json', capture)
            leaf['evidence'][phase] = self.put(phase + '.json', event)
        return leaf

    def mutate_event(self, leaf, phase, **updates):
        path = self.root / leaf['evidence'][phase]['path']
        event = json.loads(path.read_text())
        event.update(updates)
        leaf['evidence'][phase] = self.put(path.name, event)

    def test_baseline_never_claims_round_trip_completion(self):
        r = gate.check(self.data, self.root)
        self.assertTrue(r['schema_valid'], r)
        self.assertEqual(r['accepted_evidence_records'], 0)
        self.assertEqual(r['unresolved_leaves'], 117)
        self.assertEqual(r['reviewed_subset_denominator'], 5)
        self.assertEqual(r['reviewed_subset_observation_only'], 3)
        self.assertIsNone(r['reversible_denominator'])
        self.assertFalse(r['acceptance_complete'])

    def test_synthetic_shape_only(self):
        gate.round_trip(self.fixture(), self.root)

    def test_verified_no_op_read_restore(self):
        leaf = self.fixture()
        leaf.update(classification='observation_only', operation_kind='read_or_derive')
        leaf['state_contract'].update(inverse='verified_no_op', expected_after={'volume': 10})
        for phase, change in [('after', {'state': {'volume': 10}}),
                              ('restore', {'operation': 'verified_no_op'})]:
            path = self.root / leaf['evidence'][phase]['path']
            event = json.loads(path.read_text())
            event.update(change)
            event['observation'] = self.put(phase + '-capture.json', dict(event, source='host_dom'))
            leaf['evidence'][phase] = self.put(path.name, event)
        gate.round_trip(leaf, self.root)
        leaf['state_contract']['expected_after'] = {'volume': 20}
        with self.assertRaises(ValueError):
            gate.round_trip(leaf, self.root)

    def test_malformed_matrix_is_invalid(self):
        for data in ([], {}, {'leaves': [None]}):
            self.assertFalse(gate.check(data, self.root)['schema_valid'])

    def test_missing_each_phase_rejected(self):
        for phase in gate.PHASES:
            with self.subTest(phase=phase):
                leaf = self.fixture()
                leaf['evidence'][phase] = None
                with self.assertRaises(ValueError):
                    gate.round_trip(leaf, self.root)

    def test_reject_modes_target_run_order_state_and_wrong_action(self):
        for phase, change in [('action', {'mode': 'offline'}), ('after', {'target': 'other'}),
                              ('restore', {'run_id': 'other'}), ('final', {'state': {'volume': 20}}),
                              ('action', {'operation': 'unrelated'}),
                              ('after', {'observed_at': '2026-10-25T10:00:00Z'})]:
            with self.subTest(change=change):
                leaf = self.fixture()
                self.mutate_event(leaf, phase, **change)
                with self.assertRaises(ValueError):
                    gate.round_trip(leaf, self.root)

    def test_tamper_and_path_escape_rejected(self):
        leaf = self.fixture()
        (self.root / 'before.json').write_text('{}')
        with self.assertRaises(ValueError):
            gate.round_trip(leaf, self.root)
        for path in ('../escape', '/tmp/escape'):
            with self.assertRaises(ValueError):
                gate.artifact({'path': path, 'sha256': 'x'}, self.root)

    def test_markdown_proof_is_not_an_observation(self):
        leaf = self.fixture()
        event = json.loads((self.root / 'after.json').read_text())
        event['observation'] = self.put('proof.json', 'I promise it worked')
        self.mutate_event(leaf, 'after', observation=event['observation'])
        with self.assertRaises((ValueError, TypeError)):
            gate.round_trip(leaf, self.root)

    def test_residual_side_effects_require_approval(self):
        leaf = self.fixture()
        leaf['state_contract']['residual_effects'] = ['watch-history']
        leaf['authorization']['residual_effects_approved'] = False
        with self.assertRaises(ValueError):
            gate.round_trip(leaf, self.root)

    def test_no_historical_promotion_or_duplicate_leaf(self):
        self.data['leaves'][0]['historical_evidence_carried_forward'] = True
        self.assertFalse(gate.check(self.data, self.root)['schema_valid'])
        self.data['leaves'][0]['historical_evidence_carried_forward'] = False
        self.data['leaves'][1]['id'] = self.data['leaves'][0]['id']
        self.assertFalse(gate.check(self.data, self.root)['schema_valid'])

    def test_false_reviewed_scope_rejected(self):
        self.data['scope_status'] = 'reviewed'
        self.assertFalse(gate.check(self.data, self.root)['schema_valid'])

    def test_read_cannot_be_counted_as_state_change(self):
        leaf = self.fixture()
        leaf['operation_kind'] = 'read_or_derive'
        with self.assertRaises(ValueError):
            gate.round_trip(leaf, self.root)


if __name__ == '__main__':
    unittest.main()
