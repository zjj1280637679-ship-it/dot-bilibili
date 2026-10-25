"""Finite protocol model checks; these tests do not exercise a live browser."""
import unittest
from dataclasses import replace
from formal.browser_public_search_model import State, check, transitions


class PublicSearchModelTests(unittest.TestCase):
    def test_safe_state_space_and_phase_coverage(self):
        result = check()
        self.assertTrue(result['ok'], result)
        self.assertLess(result['states'], 1000)
        for action in ('claim', 'preflight:exact', 'begin_navigation:durable',
                       'navigate_once', 'capture:exact', 'duplicate_begin:reject',
                       'early_capture:reject', 'restart:unknown', 'restart:preserve',
                       'host_action_uncertain:unknown', 'lease_lost:unknown'):
            self.assertIn(action, result['actions'])
        for action in ('wrong_source_url', 'wrong_source_tab', 'context_changed', 'context_unavailable'):
            self.assertIn('preflight:' + action + ':block', result['actions'])
        for action in ('wrong_target', 'wrong_tab', 'context_changed', 'context_unavailable', 'stale'):
            self.assertIn('capture:' + action + ':reject', result['actions'])

    def test_mutant_source_check_bypass(self):
        result = check('bypass_source_check')
        self.assertFalse(result['ok'])
        self.assertEqual(result['violation'], 'verified_source_before_navigation')
        self.assertIn('preflight:wrong_source_url', result['trace'])
        self.assertEqual(result['trace'][-1], 'navigate_once')

    def test_mutant_capture_before_navigation(self):
        result = check('capture_before_navigation')
        self.assertFalse(result['ok'])
        self.assertEqual(result['violation'], 'capture_after_durable_navigation')

    def test_mutant_implicit_replay(self):
        result = check('implicit_replay')
        self.assertFalse(result['ok'])
        self.assertEqual(result['violation'], 'no_implicit_replay')

    def test_mutant_invalid_capture(self):
        result = check('accept_invalid_capture')
        self.assertFalse(result['ok'])
        self.assertEqual(result['violation'], 'fresh_exact_context_capture')

    def test_checkpoint_survives_restart_without_reauthorization(self):
        state = State(stage='navigation_started', claims=1, checkpoints=1,
                      source_verified=True, checkpoint_durable=True)
        retired = dict(transitions(state))['restart:unknown']
        self.assertEqual(retired.stage, 'unknown')
        self.assertTrue(retired.checkpoint_durable)
        self.assertTrue(retired.cooldown)
        self.assertFalse(any('navigate' in action or 'reissue' in action
                             for action, _ in transitions(retired)))
        for lost in (replace(state, alive=False), replace(state, fresh=False)):
            self.assertNotIn('navigate_once', dict(transitions(lost)))
