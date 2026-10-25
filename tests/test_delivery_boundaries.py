"""Supplementary abstraction checks only; no browser, subprocess or ledger writes."""
import importlib.util
from pathlib import Path
import unittest
from formal import read_workflow_model as model

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('delivery_boundaries', ROOT / 'scripts/check_delivery_boundaries.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class DeliveryBoundaryTests(unittest.TestCase):
    def test_safe_model_completes_and_every_negative_mutant_is_detected(self):
        report = checker.run()
        self.assertTrue(report['ok'], report)
        for steps, states, edges in (('4', 36, 84), ('5', 43, 100)):
            variant = report['variants'][steps]
            self.assertEqual(variant['safe']['states'], states)
            self.assertEqual(variant['safe']['edges'], edges)
            self.assertEqual(len(variant['mutants']), 7)
            for result in variant['mutants'].values():
                self.assertEqual(result['status'], 'invariant_violation')

    def test_success_paths_require_requested_steps_and_second_receipt(self):
        for steps in (4, 5):
            with self.subTest(steps=steps):
                state = model.State()
                for index in range(steps):
                    for action in ('durable_intent', 'child_launch', 'exact_observed'):
                        state = dict(model.transitions(state, steps=steps))[action]
                        self.assertIsNone(model.invariant(state, steps))
                    if index == 1:
                        self.assertEqual(state.source, 2)
                self.assertEqual(state.phase, 'succeeded_visible_subset')
                self.assertEqual(state.launches, tuple([1]*steps + [0]*(5-steps)))
                self.assertEqual(list(model.transitions(state, steps=steps)),
                                 [('status_or_duplicate_invocation:no_child', state)])

    def test_unknown_and_failed_never_emit_later_child(self):
        for phase in ('unknown', 'failed'):
            state = model.terminal(model.State(step=2), phase)
            self.assertEqual(list(model.transitions(state)), [('status_or_duplicate_invocation:no_child', state)])

    def test_small_resource_budget_is_not_proof_pass(self):
        result = checker.budget.explore(model.State(), model.transitions, model.invariant, max_states=1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'budget_exceeded')

    def test_cross_layer_dynamic_and_process_edges_are_explicit(self):
        edges = checker.run()['edges']
        self.assertTrue(any(e['source'] == 'facade.adapter' and 'dynamic' in e['kind'] for e in edges))
        self.assertTrue(any(e['source'] == 'scripts.read_workflow' and e['target'] == 'bili_bridge.__main__' for e in edges))
        self.assertTrue(any(e['target'] == 'workflow ledger' for e in edges))

    def test_unknown_mutant_rejected(self):
        with self.assertRaises(ValueError):
            list(model.transitions(model.State(), 'misspelled'))

    def test_four_step_default_forbids_comments_child(self):
        state = model.State(launches=(1, 1, 1, 1, 1))
        self.assertEqual(model.invariant(state, 4), 'no_unrequested_comments_child')

    def test_unsupported_step_count_rejected(self):
        with self.assertRaises(ValueError):
            list(model.transitions(model.State(), steps=6))
        with self.assertRaises(ValueError):
            model.invariant(model.State(), steps=3)
