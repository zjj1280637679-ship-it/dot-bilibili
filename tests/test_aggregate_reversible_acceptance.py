"""Synthetic contract tests only: no real leaf coverage is earned here."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import aggregate_reversible_acceptance as union
import test_reversible_acceptance as fixtures


class AggregateTests(unittest.TestCase):
    put = fixtures.ReversibleAcceptanceTests.put
    fixture = fixtures.ReversibleAcceptanceTests.fixture
    def setUp(self):
        fixtures.ReversibleAcceptanceTests.setUp(self)
        leaf = self.fixture()
        leaf['id'] = 'search.query.submit'
        for phase in union.gate.PHASES:
            event = json.loads((self.root / (phase + '.json')).read_text())
            event['leaf_id'] = leaf['id']
            leaf['evidence'][phase] = self.put(phase + '.json', event)
        self.put('support.json', {'synthetic': True})
        review = {'status': 'approved', 'reviewer': 'synthetic-test-only',
                  'leaf_id': leaf['id'], 'run_id': 'synthetic-run',
                  'remaining_conditions_for_this_scoped_leaf': [],
                  'evidence': [self.put('support.json', {'synthetic': True})]}
        leaf['review']['reference'] = self.put('review.json', review)
        self.data['leaves'] = [leaf if x['id'] == leaf['id'] else x for x in self.data['leaves']]
        self.case = {'case_id': 'synthetic-case', 'leaf_id': leaf['id'], 'run_id': 'synthetic-run',
                     'expected_status': 'accepted', 'executor': 'synthetic-executor', 'evidence_root': str(self.root),
                     'matrix': self.put('matrix.json', self.data), 'review': leaf['review']['reference']}
        self.manifest = {'schema_version': 1, 'cases': [self.case]}
        # Parent tests require the clean authoritative inventory.
        self.data = json.loads(union.gate.DEFAULT.read_text())

    def result(self):
        return union.aggregate(self.manifest, [self.root], ['synthetic-test-only'])

    def test_union_deduplicates_leaf_not_trials(self):
        other = dict(self.case, case_id='synthetic-repeat')
        self.manifest['cases'].append(other)
        r = self.result()
        self.assertTrue(r['report_valid'], r['errors'])
        self.assertEqual(r['accepted_unique_leaves'], 1)
        self.assertEqual(len(r['cases']), 2)
        self.assertEqual(r['baseline']['accepted'], 0)
        self.assertEqual(r['reviewed_subset_denominator'], 5)
        self.assertIsNone(r['reversible_denominator'])
        self.assertFalse(r['acceptance_complete'])
        self.assertEqual(r['historical']['reused'], 0)

    def test_no_self_declared_trust(self):
        for roots, reviewers in [([], ['synthetic-test-only']), ([self.root.parent], ['synthetic-test-only']),
                                  ([self.root], [])]:
            r = union.aggregate(self.manifest, roots, reviewers)
            self.assertFalse(r['report_valid'])
            self.assertEqual(r['accepted_unique_leaves'], 0)

    def test_registration_mismatch(self):
        for key, value in [('run_id', 'wrong'), ('leaf_id', 'collection.read'),
                            ('executor', 'synthetic-test-only')]:
            old = self.case[key]
            self.case[key] = value
            self.assertFalse(self.result()['report_valid'])
            self.case[key] = old

    def test_review_content_not_only_hash_is_checked(self):
        for key, value in [('status', 'pending'), ('reviewer', 'other'), ('leaf_id', 'wrong'),
                            ('run_id', 'wrong'), ('remaining_conditions_for_this_scoped_leaf', ['blocked']),
                            ('evidence', [])]:
            with self.subTest(key=key):
                matrix = json.loads((self.root / 'matrix.json').read_text())
                leaf = next(x for x in matrix['leaves'] if x['id'] == self.case['leaf_id'])
                review = json.loads((self.root / 'review.json').read_text())
                original = copy.deepcopy(review)
                review[key] = value
                ref = self.put('review.json', review)
                leaf['review']['reference'] = self.case['review'] = ref
                self.case['matrix'] = self.put('matrix.json', matrix)
                self.assertFalse(self.result()['report_valid'])
                self.put('review.json', original)

    def test_entire_candidate_not_just_selected_leaf_validated(self):
        matrix = json.loads((self.root / 'matrix.json').read_text())
        matrix['leaves'][0]['historical_evidence_carried_forward'] = True
        self.case['matrix'] = self.put('matrix.json', matrix)
        self.assertEqual(self.result()['accepted_unique_leaves'], 0)

    def test_scope_cannot_be_redefined_by_candidate(self):
        matrix = json.loads((self.root / 'matrix.json').read_text())
        matrix['leaves'][0]['scope'] = 'excluded'
        matrix['leaves'][0]['exclusion_reason'] = 'synthetic'
        self.case['matrix'] = self.put('matrix.json', matrix)
        self.assertFalse(self.result()['report_valid'])

    def test_failed_attempt_retained_without_erasing_success(self):
        matrix = copy.deepcopy(self.data)
        leaf = next(x for x in matrix['leaves'] if x['id'] == self.case['leaf_id'])
        leaf.update(status='failed', blocker='synthetic failure')
        failed = dict(self.case, case_id='failed-trial', expected_status='failed', matrix=self.put('failed.json', matrix))
        self.manifest['cases'].insert(0, failed)
        r = self.result()
        self.assertTrue(r['report_valid'], r['errors'])
        self.assertEqual(r['accepted_unique_leaves'], 1)
        self.assertEqual(r['cases'][0]['status'], 'failed')
        self.assertEqual(r['cases'][0]['blocker'], 'synthetic failure')

    def test_invalid_trial_propagates_without_erasing_valid_evidence(self):
        invalid = dict(self.case, case_id='tampered', matrix={'path': 'matrix.json', 'sha256': 'bad'})
        self.manifest['cases'].append(invalid)
        r = self.result()
        self.assertFalse(r['report_valid'])
        self.assertEqual(r['accepted_unique_leaves'], 1)
        self.assertFalse(r['acceptance_complete'])

    def test_duplicate_case_id_rejected(self):
        self.manifest['cases'].append(dict(self.case))
        self.assertFalse(self.result()['report_valid'])

    def test_nested_review_evidence_tampering_and_escape(self):
        (self.root / 'support.json').write_text('tampered')
        self.assertFalse(self.result()['report_valid'])
        self.case['matrix']['path'] = '../matrix.json'
        self.assertFalse(self.result()['report_valid'])

    def test_symlink_escape(self):
        (self.root / 'escaped').symlink_to(self.root.parent)
        self.case['matrix']['path'] = 'escaped/whatever'
        self.assertFalse(self.result()['report_valid'])

    def test_explicit_verdict_review_format_and_negative_checks(self):
        review = {'verdict': 'approved', 'execution_order': {'basis': 'synthetic'},
                  'actual_outcome': 'synthetic', 'checks': self.put('checks.json', {'checks': {'a': True}})}
        union.review_evidence(review, self.root, 'verdict_checks_v1')
        for value in (False, 'true', 1, None):
            review['checks'] = self.put('checks.json', {'checks': {'a': value}})
            with self.assertRaises(ValueError):
                union.review_evidence(review, self.root, 'verdict_checks_v1')
        review['checks'] = self.put('checks.json', {'all_assertions_passed': True, 'checks': {'a': False}})
        with self.assertRaises(ValueError):
            union.review_evidence(review, self.root, 'verdict_checks_v1')
        review['checks'] = self.put('checks.json', {'all_assertions_passed': True})
        union.review_evidence(review, self.root, 'verdict_checks_v1')
        review['checks'] = self.put('checks.json', {'all_assertions_passed': True, 'checks': 'descriptive findings only'})
        union.review_evidence(review, self.root, 'verdict_checks_v1')
        for value in (False, 'true', 1):
            bad = dict(review, checks=self.put('bad-checks.json', {'all_assertions_passed': value, 'checks': 'description'}))
            with self.assertRaises(ValueError):
                union.review_evidence(bad, self.root, 'verdict_checks_v1')
        for update in ({'verdict': 'not_accepted'}, {'status': 'approved'},
                       {'remaining_conditions_for_this_scoped_leaf': ['pending']}):
            with self.assertRaises(ValueError):
                union.review_evidence(dict(review, **update), self.root, 'verdict_checks_v1')
        with self.assertRaises((KeyError, ValueError)):
            union.review_evidence(review, self.root, 'status_evidence_v1')
        with self.assertRaises(ValueError):
            union.review_evidence(review, self.root, 'unknown')
        (self.root / 'checks.json').write_text('{}')
        with self.assertRaises(ValueError):
            union.review_evidence(review, self.root, 'verdict_checks_v1')

    def pin_verdict_review(self, checks=None, **updates):
        checks = {'checks': {'a': True}} if checks is None else checks
        review = {'verdict': 'approved', 'reviewer': 'synthetic-test-only',
                  'leaf_id': self.case['leaf_id'], 'run_id': self.case['run_id'],
                  'execution_order': {'basis': 'synthetic only'}, 'actual_outcome': 'synthetic only',
                  'checks': self.put('checks.json', checks)}
        review.update(updates)
        matrix = json.loads((self.root / 'matrix.json').read_text())
        leaf = next(x for x in matrix['leaves'] if x['id'] == self.case['leaf_id'])
        leaf['review']['reference'] = self.case['review'] = self.put('review.json', review)
        self.case['matrix'] = self.put('matrix.json', matrix)
        self.case['review_format'] = 'verdict_checks_v1'

    def test_verdict_end_to_end_approval_and_ambiguity(self):
        for checks in ({'checks': {'a': True}}, {'all_assertions_passed': True},
                       {'all_assertions_passed': True, 'checks': 'synthetic description'}):
            self.pin_verdict_review(checks)
            r = self.result()
            self.assertTrue(r['report_valid'], r['errors'])
            self.assertEqual(r['accepted_unique_leaves'], 1)
            self.assertTrue(r['cases'][0]['run_identity_verified'])
        for update in ({'verdict': 'not_accepted'}, {'status': 'approved'},
                       {'reviewer': 'wrong'}, {'leaf_id': 'wrong'}, {'run_id': 'wrong'},
                       {'actual_outcome': ''}, {'remaining_conditions_for_this_scoped_leaf': ['pending']}):
            with self.subTest(update=update):
                self.pin_verdict_review(**update)
                r = self.result()
                self.assertFalse(r['report_valid'])
                self.assertEqual(r['accepted_unique_leaves'], 0)
        self.pin_verdict_review()
        for fmt in ('status_evidence_v1', 'unknown'):
            self.case['review_format'] = fmt
            self.assertFalse(self.result()['report_valid'])

    def test_verdict_end_to_end_false_checks_and_hash_changes(self):
        for checks in ({'checks': {'a': False}}, {'checks': {'a': 1}},
                       {'checks': {'a': 'true'}}, {'checks': {}},
                       {'all_assertions_passed': False}, {'all_assertions_passed': 1},
                       {'all_assertions_passed': 'true'},
                       {'all_assertions_passed': False, 'checks': 'synthetic description'},
                       {'all_assertions_passed': 'true', 'checks': 'synthetic description'},
                       {'all_assertions_passed': 1, 'checks': 'synthetic description'},
                       {'all_assertions_passed': True, 'checks': '   '},
                       {'checks': 'synthetic description'},
                       {'all_assertions_passed': True, 'checks': {'a': False}}):
            with self.subTest(checks=checks):
                self.pin_verdict_review(checks)
                r = self.result()
                self.assertFalse(r['report_valid'])
                self.assertEqual(r['accepted_unique_leaves'], 0)
        for name in ('checks.json', 'review.json', 'matrix.json'):
            self.pin_verdict_review()
            original = (self.root / name).read_bytes()
            (self.root / name).write_bytes(original + b' ')
            r = self.result()
            self.assertFalse(r['report_valid'])
            self.assertEqual(r['accepted_unique_leaves'], 0)
            (self.root / name).write_bytes(original)

    def test_rejection_review_end_to_end_preserves_reason_and_rejects_tampering(self):
        matrix = copy.deepcopy(self.data)
        leaf = next(x for x in matrix['leaves'] if x['id'] == self.case['leaf_id'])
        leaf.update(status='failed', blocker='synthetic failure')
        self.case.update(expected_status='failed', matrix=self.put('matrix.json', matrix))
        review = {'verdict': 'not_accepted', 'reviewer': 'synthetic-test-only',
                  'leaf_id': self.case['leaf_id'], 'run_id': self.case['run_id'],
                  'reason': 'synthetic rejection',
                  'passed_checks_reference': self.put('rejection-checks.json', {'synthetic': True})}
        self.case['rejection_review'] = self.put('rejection.json', review)
        r = self.result()
        self.assertTrue(r['report_valid'], r['errors'])
        self.assertEqual(r['accepted_unique_leaves'], 0)
        self.assertEqual(r['cases'][0]['rejection_reason'], 'synthetic rejection')
        self.assertFalse(r['cases'][0]['run_identity_verified'])
        for update in ({'verdict': 'approved'}, {'reviewer': 'wrong'},
                       {'leaf_id': 'wrong'}, {'run_id': 'wrong'}, {'status': 'approved'},
                       {'reason': None}, {'reason': ''}, {'reason': '   '}):
            self.case['rejection_review'] = self.put('rejection.json', dict(review, **update))
            self.assertFalse(self.result()['report_valid'])
        self.case['rejection_review'] = self.put('rejection.json', review)
        (self.root / 'rejection-checks.json').write_text('{}')
        self.assertFalse(self.result()['report_valid'])

    def test_nested_review_attestation_closure_is_digest_bound(self):
        attestation = self.put('attestation.json', {'statement': 'synthetic only'})
        review = {'execution_order': {'post_run_executor_attestation': attestation}}
        union.review_artifact_closure(review, self.root)
        self.pin_verdict_review(execution_order=review['execution_order'])
        self.assertTrue(self.result()['report_valid'])
        (self.root / 'attestation.json').write_text('{}')
        result = self.result()
        self.assertFalse(result['report_valid'])
        self.assertEqual(result['accepted_unique_leaves'], 0)
        with self.assertRaises(ValueError):
            union.review_artifact_closure(review, self.root)
        wrapped = self.put('wrapper.json', review)
        with self.assertRaises(ValueError):
            union.review_artifact_closure({'evidence': [wrapped]}, self.root)
        with self.assertRaises(ValueError):
            union.review_artifact_closure({'nested': {'path': '../escape', 'sha256': 'x'}}, self.root)

    def test_empty_manifest_is_baseline_only(self):
        r = union.aggregate({'schema_version': 1, 'cases': []}, [], [])
        self.assertTrue(r['report_valid'])
        self.assertEqual(r['accepted_unique_leaves'], 0)


if __name__ == '__main__':
    unittest.main()
