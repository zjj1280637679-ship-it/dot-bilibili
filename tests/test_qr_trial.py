"""All transports are fake. This file never makes live requests."""
import json
import unittest
from bili_bridge.auth_contracts import Challenge, TrialStopped, generated, polled
from bili_bridge.auth_broker import QRBroker, MemoryCredentials, AuthTransport

KEY = 'a' * 32
URL = 'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=' + KEY

def body(data):
    return json.dumps({'code': 0, 'data': data}).encode()

class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds

class Fake:
    def __init__(self, responses): self.responses, self.calls = iter(responses), []
    def request(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        out = next(self.responses)
        if isinstance(out, Exception): raise out
        return out

class QRTests(unittest.TestCase):
    def broker(self, responses):
        clock = Clock(); fake = Fake(responses)
        return QRBroker(fake, clock=clock, sleep=clock.sleep), fake, clock
    def generation(self): return body({'url': URL, 'qrcode_key': KEY}), []
    def test_full_fake_flow_and_single_nav(self):
        b,f,c = self.broker([self.generation(), (body({'code': 86101}), []),
                            (body({'code': 86090}), []),
                            (body({'code': 0}), ['SESSDATA=secret; Domain=.bilibili.com; Path=/; Secure; HttpOnly']),
                            (body({'isLogin': True, 'uname': 'DO NOT RETURN'}), [])])
        b.generate(approved=True, consent_ref='offline-test')
        seen=[]
        self.assertEqual(b.poll(seen.append), 'session_received')
        self.assertEqual(c.now, 15)
        self.assertEqual(seen, ['waiting_scan', 'waiting_confirmation', 'session_received'])
        self.assertIs(b.verify_once(), True)
        with self.assertRaises(TrialStopped): b.verify_once()
        self.assertEqual([x[0] for x in f.calls], ['generate','poll','poll','poll','nav'])
        b.close(); self.assertEqual(b._credentials._cookies, {})
    def test_consent_gate_no_request(self):
        b,f,_=self.broker([])
        for approved,ref in [(False,'x'),(True,''),(1,'x')]:
            with self.assertRaises(TrialStopped): b.generate(approved=approved,consent_ref=ref)
        self.assertEqual(f.calls,[])
    def test_denial_latched_no_retry(self):
        b,f,_=self.broker([TrialStopped('http_denied')])
        with self.assertRaises(TrialStopped): b.generate(approved=True,consent_ref='test')
        with self.assertRaises(TrialStopped): b.generate(approved=True,consent_ref='test')
        self.assertEqual(len(f.calls),1)
    def test_expired_before_user_starts(self):
        b,f,c=self.broker([self.generation()])
        b.generate(approved=True,consent_ref='test'); c.now=181
        self.assertEqual(b.poll(),'expired'); self.assertEqual(len(f.calls),1)
    def test_poll_budget(self):
        b,f,c=self.broker([self.generation()]+[(body({'code':86101}),[])]*40)
        b.generate(approved=True,consent_ref='test')
        self.assertEqual(b.poll(),'expired'); self.assertLessEqual(len(f.calls),36)
    def test_success_without_cookie_fails_closed(self):
        b,f,c=self.broker([self.generation(),(body({'code':0}),[])])
        b.generate(approved=True,consent_ref='test')
        with self.assertRaises(TrialStopped): b.poll()
        self.assertEqual(b.state,'closed')
    def test_protocol_and_repr(self):
        for value in [True,1,-1,'0',None]:
            with self.assertRaises(TrialStopped): polled(body({'code':value}))
        self.assertNotIn(KEY, repr(Challenge(URL,KEY)))
        self.assertNotIn('secret',repr(MemoryCredentials()))
        for url in [URL.replace('passport.bilibili.com','evil.example'), URL+'&extra=1', URL+'#x']:
            with self.assertRaises(TrialStopped): generated(body({'url':url,'qrcode_key':KEY}))
    def test_no_arbitrary_transport(self):
        t=AuthTransport()
        for operation in ['https://example.com', 'send_dm', 'POST']:
            with self.assertRaises(TrialStopped): t.request(operation)

if __name__=='__main__': unittest.main()
