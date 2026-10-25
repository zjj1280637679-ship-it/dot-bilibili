"""Resource gate checks are tests, not implementation formal proof."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('verification_budget',
    Path(__file__).resolve().parents[1] / 'scripts' / 'check_verification_budget.py')
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


class VerificationBudgetTests(unittest.TestCase):
    def test_all_current_models_complete_and_match_original(self):
        report = budget.run()
        self.assertTrue(report['ok'], report)
        self.assertEqual(len(report['models']), 8)
        for result in report['models'].values():
            self.assertEqual(result['status'], 'complete')
            self.assertTrue(result['reference_agrees'])

    def test_state_limit_never_passes_truncated_search(self):
        result = budget.explore(0, lambda n: [('next', n + 1)], lambda _: None, max_states=4)
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'budget_exceeded')
        self.assertEqual(result['reason'], 'states')
        self.assertEqual(result['states'], 5)

    def test_memory_limit_fails_closed(self):
        result = budget.explore(0, lambda _: [], lambda _: None, max_memory_bytes=1)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'memory')

    def test_runtime_limit_fails_closed(self):
        with patch.object(budget.time, 'perf_counter', side_effect=[0, 2, 3]):
            result = budget.explore(0, lambda _: [], lambda _: None, max_seconds=1.0)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'runtime')

    def test_invariant_failure_not_resource_pass(self):
        result = budget.explore(0, lambda _: [], lambda _: 'bad')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'invariant_violation')

    def test_dependency_overrun_fails_overall_report(self):
        limits = dict(budget.DEFAULTS, max_dependencies=1)
        result = budget.run(limits)
        self.assertFalse(result['ok'])
        self.assertFalse(result['dependencies']['within_budget'])

    def test_invalid_limits_rejected(self):
        with self.assertRaises(ValueError):
            budget.explore(0, lambda _: [], lambda _: None, max_states=0)

    def test_whole_kernel_injection_is_removed_and_narrow_port_visible(self):
        report = budget.retained_ports()
        self.assertEqual(report['wide_kernel_injections'], 0)
        matches = [p for p in report['retained_ports'] if p['attribute'] == 'selection_consumer']
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['used_methods'], ['consume_browser_selection'])

    def test_new_whole_kernel_injection_fails_zero_allowance(self):
        detected = dict(retained_ports=[], wide_kernel_injections=1)
        with patch.object(budget, 'retained_ports', return_value=detected):
            result = budget.run()
        self.assertFalse(result['ok'])
        self.assertFalse(result['runtime_coupling']['within_budget'])

    def test_revalidation_frontier_keeps_callback_provider_edge(self):
        report = budget.run()
        affected = report['revalidation']['candidate_implementation_frontiers']['kernel']
        self.assertIn('selection_consumer', affected)
        self.assertIn('browser_video_open_plugin', affected)
        self.assertIn('cli', affected)
        isolated = budget.revalidation_frontiers({'a': [], 'b': ['a'], 'c': []}, [])
        self.assertEqual(isolated['candidate_implementation_frontiers']['a'], ['a', 'b'])

    def test_ast_detects_tuple_retained_whole_kernel_in_synthetic_plugin(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bili_bridge').mkdir()
            (root / 'bili_bridge' / 'bad_plugin.py').write_text(
                'class BadPlugin:\n'
                '    def __init__(self, host, kernel):\n'
                '        self.host, self.kernel = host, kernel\n'
                '    def execute(self, request):\n'
                '        return self.kernel.dispatch(request)\n')
            report = budget.retained_ports(root)
        self.assertEqual(report['wide_kernel_injections'], 1)
        self.assertEqual([p['used_methods'] for p in report['retained_ports']
                          if p['broad_kernel']], [['dispatch']])
