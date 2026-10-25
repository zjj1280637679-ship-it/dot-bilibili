"""Independent QR security tests. Only synthetic protocol data; no live I/O."""
import json
import unittest
import time
import signal
from unittest.mock import Mock
from bili_bridge import auth_contracts as contract
from bili_bridge.auth_broker import QRBroker, MemoryCredentials, AuthTransport, NoRedirect, request_deadline

KEY = 'synthetic-key-123456789'
URL = 'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=' + KEY
COOKIE = 'SESSDATA=synthetic-session; Domain=.bilibili.com; Path=/; Secure; HttpOnly'

def body(data):
    return json.dumps({'code': 0, 'data': data}).encode()

class FakeTransport:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
    def request(self, operation, **kwargs):
        self.calls.append(operation)
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def sleep(self, amount): self.now += amount

class QRAdversarialTests(unittest.TestCase):
    def test_exact_qr_destination(self):
        for url in (URL + '&evil=', URL + '&navhide=', URL + '#x', URL.replace('https:', 'http:'), URL.replace('passport.bilibili.com', 'passport.bilibili.com:443'), URL.replace('passport.bilibili.com', 'passport.bilibili.com@evil.test'), URL.replace('/scan?', '/scan/?'), URL.replace(KEY, 'different-key-1234567'), URL + '&qrcode_key=' + KEY, URL + '&x=%00'):
            with self.subTest(url=url):
                with self.assertRaises(contract.TrialStopped):
                    contract.generated(body({'url': url, 'qrcode_key': KEY}))
    def test_json_ambiguity_and_nonfinite_are_rejected(self):
        for raw in (b'{"code":5,"code":0,"data":{"code":0}}', b'{"code":0,"data":{"code":86038,"code":0}}', b'{"code":0,"data":{"code":0,"x":NaN}}', b'{"code":0,"data":{"code":0,"x":Infinity}}', b'{"code":true,"data":{"code":0}}', body({'code': False}), body({'code':'0'}), b'[]', b'{'*1000):
            with self.subTest(raw=raw):
                with self.assertRaises(contract.TrialStopped): contract.polled(raw)
    def test_cookies_cannot_expand_domain_or_path_or_revive_expired_session(self):
        for cookie in ('SESSDATA=x; Path=/', 'SESSDATA=x; Domain=passport.bilibili.com; Path=/', 'SESSDATA=x; Domain=evil.test; Path=/', 'SESSDATA=x; Domain=.bilibili.com; Path=/private; Secure', 'SESSDATA=x; Domain=.bilibili.com; Path=/; Secure; Max-Age=0', 'SESSDATA=x; Domain=.bilibili.com; Path=/; Secure; Expires=Thu, 01 Jan 1970 00:00:00 GMT'):
            with self.subTest(cookie=cookie):
                with self.assertRaises(contract.TrialStopped): MemoryCredentials().accept([cookie])
    def test_duplicate_session_cookie_rejected(self):
        with self.assertRaises(contract.TrialStopped):
            MemoryCredentials().accept([COOKIE, COOKIE.replace('synthetic-session', 'different-session')])
        for raw in ('SESSDATA=a; SESSDATA=b; Domain=.bilibili.com; Path=/; Secure', 'SESSDATA=a; Domain=..bilibili.com; Path=/; Secure'):
            with self.subTest(raw=raw):
                with self.assertRaises(contract.TrialStopped): MemoryCredentials().accept([raw])
    def test_secret_repr_and_exception_boundary(self):
        self.assertNotIn(KEY, repr(contract.Challenge(URL, KEY)))
        creds = MemoryCredentials(); creds.accept([COOKIE])
        self.assertNotIn('synthetic-session', repr(creds))
        transport = FakeTransport([RuntimeError('RAW_SECRET_DO_NOT_LEAK')])
        broker = QRBroker(transport)
        try:
            broker.generate(approved=True, consent_ref='parent-user-consent')
        except Exception as exc:
            self.assertIsInstance(exc, contract.TrialStopped)
            self.assertNotIn('RAW_SECRET', str(exc))
        else: self.fail('expected rejection')
        self.assertEqual(transport.calls, ['generate'])
        self.assertEqual(broker.state, 'closed')
    def test_consent_gate_and_no_regeneration(self):
        transport = FakeTransport([(body({'url': URL, 'qrcode_key': KEY}), [])])
        broker = QRBroker(transport)
        for approved in (False, 1, 'true', None):
            with self.assertRaises(contract.TrialStopped): broker.generate(approved=approved, consent_ref='consent')
        self.assertEqual(transport.calls, [])
        broker.generate(approved=True, consent_ref='consent')
        with self.assertRaises(contract.TrialStopped): broker.generate(approved=True, consent_ref='consent')
        self.assertEqual(transport.calls, ['generate'])
        broker.close()
    def test_expiry_is_terminal_and_no_nav(self):
        clock = Clock()
        transport = FakeTransport([(body({'url': URL, 'qrcode_key': KEY}), []), (body({'code': 86038}), [])])
        broker = QRBroker(transport, clock=clock, sleep=clock.sleep)
        broker.generate(approved=True, consent_ref='consent')
        self.assertEqual(broker.poll(), 'expired')
        with self.assertRaises(contract.TrialStopped): broker.poll()
        with self.assertRaises(contract.TrialStopped): broker.verify_once()
        self.assertEqual(transport.calls, ['generate', 'poll'])
    def test_success_without_cookie_is_not_success(self):
        clock = Clock(); statuses = []
        transport = FakeTransport([(body({'url': URL, 'qrcode_key': KEY}), []), (body({'code': 0}), [])])
        broker = QRBroker(transport, clock=clock, sleep=clock.sleep)
        broker.generate(approved=True, consent_ref='consent')
        with self.assertRaises(contract.TrialStopped): broker.poll(statuses.append)
        self.assertNotIn('authenticated', statuses)
        self.assertEqual(broker.state, 'closed')
    def test_confirmation_cannot_regress_to_waiting(self):
        clock = Clock()
        transport = FakeTransport([(body({'url': URL, 'qrcode_key': KEY}), []), (body({'code': 86090}), []), (body({'code': 86101}), []), (body({'code': 86038}), [])])
        broker = QRBroker(transport, clock=clock, sleep=clock.sleep)
        broker.generate(approved=True, consent_ref='consent')
        with self.assertRaises(contract.TrialStopped): broker.poll()
        self.assertEqual(transport.calls, ['generate', 'poll', 'poll'])
        self.assertEqual(broker.state, 'closed')
    def test_failed_validation_closes_session(self):
        clock = Clock()
        transport = FakeTransport([(body({'url': URL, 'qrcode_key': KEY}), []), (body({'code': 0}), [COOKIE]), (body({'isLogin': False}), [])])
        broker = QRBroker(transport, clock=clock, sleep=clock.sleep)
        broker.generate(approved=True, consent_ref='consent')
        broker.poll()
        try: result = broker.verify_once()
        except contract.TrialStopped: result = False
        self.assertFalse(result)
        self.assertEqual(broker.state, 'closed')
        self.assertEqual(broker._credentials._nav_header(), '')
        with self.assertRaises(contract.TrialStopped): broker.verify_once()
        self.assertEqual(transport.calls, ['generate', 'poll', 'nav'])
    def test_callback_exception_is_redacted(self):
        clock = Clock()
        transport = FakeTransport([(body({'url': URL, 'qrcode_key': KEY}), []), (body({'code': 86101}), [])])
        broker = QRBroker(transport, clock=clock, sleep=clock.sleep)
        broker.generate(approved=True, consent_ref='consent')
        def notify(state): raise RuntimeError('SECRET_CALLBACK')
        with self.assertRaises(contract.TrialStopped) as caught: broker.poll(notify)
        self.assertNotIn('SECRET_CALLBACK', str(caught.exception))
        self.assertEqual(broker.state, 'closed')
    def test_poll_budget_caps_even_if_injected_clock_stalls(self):
        clock = Clock()
        transport = FakeTransport([(body({'url': URL, 'qrcode_key': KEY}), [])] + [(body({'code': 86101}), [])] * 50)
        broker = QRBroker(transport, clock=clock, sleep=lambda _: None)
        broker.generate(approved=True, consent_ref='consent')
        self.assertEqual(broker.poll(), 'expired')
        self.assertEqual(transport.calls.count('poll'), 35)
        self.assertEqual(broker.state, 'closed')
    def test_invalid_transport_timeouts_and_safe_error_reason(self):
        transport = AuthTransport()
        for timeout in (True, float('nan'), float('inf'), 0, -1, 11, '5'):
            with self.subTest(timeout=timeout):
                with self.assertRaises(contract.TrialStopped): transport.request('generate', timeout=timeout)
        self.assertEqual(str(contract.TrialStopped('SECRET_REMOTE_ERROR')), 'internal_failure')
    def test_redirect_is_rejected_without_following(self):
        with self.assertRaises(contract.TrialStopped) as caught:
            NoRedirect().redirect_request(None, None, 302, 'SECRET_REMOTE', {}, 'https://evil.test/SECRET')
        self.assertEqual(str(caught.exception), 'redirect_denied')
    def test_wallclock_deadline_restores_signal_handler(self):
        original = signal.getsignal(signal.SIGALRM)
        with self.assertRaises(contract.TrialStopped) as caught:
            with request_deadline(0.01): time.sleep(0.05)
        self.assertEqual(str(caught.exception), 'request_timeout')
        self.assertEqual(signal.getsignal(signal.SIGALRM), original)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
    def test_transport_failure_redacted_without_retry(self):
        transport = AuthTransport()
        transport._opener = Mock()
        transport._opener.open.side_effect = RuntimeError('SECRET_TRANSPORT_URL_COOKIE')
        with self.assertRaises(contract.TrialStopped) as caught: transport.request('generate')
        self.assertEqual(str(caught.exception), 'network_failure')
        self.assertEqual(transport._opener.open.call_count, 1)
    def test_transport_rejects_unlisted_operations_before_network(self):
        transport = AuthTransport()
        for op in ('https://evil.test', 'POST', 'dm', 'comment', 'like', 'favorites', ''):
            with self.subTest(op=op):
                with self.assertRaises(contract.TrialStopped): transport.request(op)

if __name__ == '__main__': unittest.main()
