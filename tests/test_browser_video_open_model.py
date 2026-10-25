"""Exhaustive bounded protocol checks, not implementation/browser verification."""
import unittest
from dataclasses import replace
from formal.browser_video_open_model import (
    CAPTURE_ERRORS, MUTANTS, PREFLIGHT_ERRORS, SOURCE_ERRORS, State, check, transitions,
)


class VideoOpenModelTests(unittest.TestCase):
    def test_safe_state_space_and_adversarial_coverage(self):
        result = check()
        self.assertTrue(result['ok'], result)
        self.assertLess(result['states'], 2000)
        for action in ('consume:exact', 'claim', 'preflight:exact',
                       'begin_navigation:durable', 'navigate_once', 'capture:exact',
                       'second_open_id:reject_consumed_source', 'same_open_id:reject_duplicate',
                       'duplicate_claim:reject', 'duplicate_begin:reject',
                       'early_capture:reject', 'restart:unknown', 'restart:preserve',
                       'host_action_uncertain:unknown', 'invalidated:unknown',
                       'intervening_operation', 'target_captcha:block'):
            self.assertIn(action, result['actions'])
        for kind in SOURCE_ERRORS:
            self.assertIn('consume:' + kind + ':reject', result['actions'])
        for kind in PREFLIGHT_ERRORS:
            self.assertIn('preflight:' + kind + ':block', result['actions'])
        for kind in CAPTURE_ERRORS:
            self.assertIn('capture:' + kind + ':unknown', result['actions'])

    def test_every_negative_mutant_has_counterexample(self):
        expected = {'bypass_' + kind: 'fresh_applied_exact_source_and_member'
                    for kind in SOURCE_ERRORS}
        expected.update({
            'reuse_consumed_source': 'single_use_search_receipt',
            'bypass_preflight': 'fresh_preflight_and_durable_start_before_navigation',
            'skip_checkpoint': 'fresh_preflight_and_durable_start_before_navigation',
            'duplicate_navigation': 'at_most_once',
            'early_capture': 'capture_after_durable_navigation',
            'invalid_capture': 'fresh_exact_target_receipt',
            'implicit_replay': 'unknown_and_terminal_never_replay',
            'ignore_invalidation': 'fresh_applied_exact_source_and_member',
        })
        self.assertEqual(set(expected), set(MUTANTS))
        for mutant, violation in expected.items():
            with self.subTest(mutant=mutant):
                result = check(mutant)
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['violation'], violation, result)
                self.assertTrue(result['trace'])

    def test_durable_start_crash_cannot_reauthorize_navigation(self):
        state = State(stage='navigation_started', consumes=1, claims=1,
                      preflight_valid=True, durable=True)
        retired = dict(transitions(state))['restart:unknown']
        self.assertTrue(retired.durable)
        self.assertEqual(retired.stage, 'unknown')
        self.assertEqual(set(dict(transitions(retired))),
                         {'duplicate_delivery:reject', 'restart:preserve'})
        for invalid in (replace(state, fresh=False), replace(state, alive=False)):
            self.assertNotIn('navigate_once', dict(transitions(invalid)))

    def test_intervening_operation_invalidates_before_durable_start(self):
        for stage in ('select', 'issued', 'claimed', 'preflight'):
            actions = dict(transitions(State(stage=stage, latest=False)))
            self.assertIn('invalidated:unknown', actions)
            self.assertFalse(any(action.startswith(('consume:', 'claim', 'preflight:',
                                                   'begin_navigation:')) for action in actions))

    def test_unknown_mutation_is_not_silently_safe(self):
        with self.assertRaises(ValueError):
            check('misspelled_mutation')
