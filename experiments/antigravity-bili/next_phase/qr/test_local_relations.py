"""dot-local synthetic regressions against AG QR draft; no network."""
import json,unittest,threading
from dataclasses import FrozenInstanceError
from .qr_login import QRLoginCoordinator,QRProtocolError,parse_fail_closed_json,OpaqueSessionPort
from .test_qr import FakeTransport,FakePauseGate
KEY='abcdefghijklmnop'
def generated():return json.dumps({'code':0,'data':{'qrcode_key':KEY,'url':'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key='+KEY}}).encode()
def polled():return b'{"code":0,"data":{"code":86101}}'
class Relations(unittest.TestCase):
 def make(self):
  t=FakeTransport();t.generate_queue=[(generated(),[])];t.poll_queue=[(polled(),[])];g=FakePauseGate(False);c=QRLoginCoordinator(t,g);return c,t,g
 def test_unknown_gate_zero_calls(self):
  for gate in (None,object()):
   t=FakeTransport();c=QRLoginCoordinator(t,gate);self.assertEqual(c.generate(approved=True,consent_ref='fixture')['reason'],'pause_state_unknown');self.assertEqual(t.call_count,0)
 def test_invalid_gate_value_zero_calls(self):
  class Gate:
   def is_paused(self):return 0
  t=FakeTransport();c=QRLoginCoordinator(t,Gate());self.assertEqual(c.generate(approved=True,consent_ref='fixture')['status'],'blocked');self.assertEqual(t.call_count,0)
 def test_poll_pause_after_generate_zero_additional_calls(self):
  c,t,g=self.make();c.generate(approved=True,consent_ref='fixture');g.set_paused(True);self.assertEqual(c.poll_once()['reason'],'account_operations_paused');self.assertEqual(t.call_count,1)
 def test_generate_close_during_callback_not_resurrected(self):
  c,t,g=self.make();original=t.request
  def req(*a,**kw):c.close();return original(*a,**kw)
  t.request=req;self.assertEqual(c.generate(approved=True,consent_ref='fixture')['reason'],'stale_attempt');self.assertEqual(c.state,'closed')
 def test_poll_close_during_callback_not_resurrected(self):
  c,t,g=self.make();c.generate(approved=True,consent_ref='fixture');original=t.request
  def req(*a,**kw):c.close();return original(*a,**kw)
  t.request=req;self.assertEqual(c.poll_once()['reason'],'stale_attempt');self.assertEqual(c.state,'closed')
 def test_pause_during_response_drops_challenge(self):
  c,t,g=self.make();original=t.request
  def req(*a,**kw):g.set_paused(True);return original(*a,**kw)
  t.request=req;self.assertEqual(c.generate(approved=True,consent_ref='fixture')['reason'],'account_operations_paused');self.assertEqual(c.state,'closed')
 def test_pause_unpause_during_response_fences(self):
  c,t,g=self.make();original=t.request
  def req(*a,**kw):g.set_paused(True);g.set_paused(False);return original(*a,**kw)
  t.request=req;self.assertEqual(c.generate(approved=True,consent_ref='fixture')['reason'],'pause_generation_changed');self.assertEqual(c.state,'closed')
 def test_returned_challenge_immutable(self):
  c,t,g=self.make();x=c.generate(approved=True,consent_ref='fixture')['challenge']
  with self.assertRaises(FrozenInstanceError):x.qrcode_key='changed'
  c.poll_once();self.assertEqual(t.last_poll_key,KEY)
 def test_overflow_rejected(self):
  with self.assertRaises(QRProtocolError):parse_fail_closed_json(b'{"code":0,"data":{"x":1e999}}')
 def test_synthetic_handle_not_credential_persistence(self):
  h=OpaqueSessionPort.extract_opaque_handle(['SESSDATA=fake']);self.assertFalse(h.to_safe_dict()['credential_persisted'])
 def test_concurrent_generate_only_one_call_and_close_wins(self):
  c,t,g=self.make();started=threading.Event();finish=threading.Event();original=t.request;out=[]
  def req(*a,**kw):started.set();finish.wait(2);return original(*a,**kw)
  t.request=req;thread=threading.Thread(target=lambda:out.append(c.generate(approved=True,consent_ref='fixture')));thread.start();self.assertTrue(started.wait(1))
  with self.assertRaises(QRProtocolError):c.generate(approved=True,consent_ref='fixture')
  c.close();finish.set();thread.join(2);self.assertFalse(thread.is_alive());self.assertEqual(t.call_count,1);self.assertEqual(out[0]['reason'],'stale_attempt')
if __name__=='__main__':unittest.main()
