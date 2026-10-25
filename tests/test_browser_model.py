import unittest
from formal.browser_relay_model import check


class BrowserRelayModelTests(unittest.TestCase):
    def test_bounded_protocol(self):
        result = check()
        self.assertTrue(result['ok'], result)
        for event in ('claim', 'exact:observe', 'stale:reject', 'mismatch:reject',
                      'owner_dead', 'expiry', 'timeout_or_owner_dead',
                      'duplicate_claim:reject', 'duplicate_receipt:reject', 'restart:preserve'):
            self.assertIn(event, result['actions'])

    def test_invalid_receipt_mutation(self):
        self.assertEqual(check('accept_invalid')['violation'], 'fresh_exact_live_receipt')

    def test_restart_replay_mutation(self):
        self.assertEqual(check('implicit_replay')['violation'], 'no_implicit_replay')
