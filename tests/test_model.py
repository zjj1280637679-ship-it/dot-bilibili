import unittest
from formal.model import STAGES, State, Operation, check, transitions

class ModelTests(unittest.TestCase):
    def test_exhaustive_composition(self):
        for accounts in ((0, 0), (0, 1), (1, 0), (1, 1)):
            with self.subTest(accounts=accounts):
                result = check(accounts)
                self.assertTrue(result['ok'], result)
                self.assertEqual(set(result['coverage']), set(STAGES))

    def test_mutant_authorization(self):
        result = check(mutation='bypass_authorization')
        self.assertFalse(result['ok'])
        self.assertEqual(result['violation'], 'authorization_at_send')
        self.assertIn('o0:expire_or_revoke', result['trace'])

    def test_mutant_unknown_retry(self):
        result = check(mutation='retry_unknown')
        self.assertFalse(result['ok'])
        self.assertEqual(result['violation'], 'no_unknown_replay')

    def test_restart_preserves_budget_and_uncertainty(self):
        state = State((Operation(stage='prepared', durable=True), Operation()), 1)
        recovered = dict(transitions(state, (0, 0)))['restart']
        self.assertEqual(recovered.used, 1)
        self.assertEqual(recovered.operations[0].stage, 'unknown')
        self.assertFalse(any('prepare' in action for action, _ in transitions(recovered, (0, 0))))

    def test_scope_mismatch_cannot_prepare(self):
        state = State((Operation(grant='wrong_scope'), Operation()), 0)
        self.assertFalse(any(action == 'o0:prepare' for action, _ in transitions(state, (0, 1))))

class RelayModelTests(unittest.TestCase):
    def test_relay_composition(self):
        from formal.relay_model import check_relays
        result = check_relays()
        self.assertTrue(result['ok'])
        self.assertIn('exact:send', result['actions'])
        self.assertIn('exact:budget_denied', result['actions'])
        for field in ('operation', 'account', 'capability', 'target', 'payload_hash', 'version', 'effect', 'route'):
            self.assertIn('wrong_' + field + ':reject', result['actions'])

    def test_scope_widening_counterexample(self):
        from formal.relay_model import check_relays
        self.assertEqual(check_relays('widen_scope')['violation'], 'immutable_scope')

    def test_direct_bypass_counterexample(self):
        from formal.relay_model import check_relays
        self.assertEqual(check_relays('bypass_relay')['violation'], 'no_bypass_and_durable_journal')
