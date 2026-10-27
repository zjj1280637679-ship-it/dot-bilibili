"""Independent synthetic QR/session relationship regressions for revised APIs."""
import dataclasses,hashlib,importlib.util,json,pathlib,sys,tempfile,threading,unittest
ROOT=pathlib.Path(__file__).resolve().parents[2];_artifact_tmp=tempfile.TemporaryDirectory(prefix='bili-relations-');OUT=pathlib.Path(_artifact_tmp.name)

def load(name,relative):
 b=(ROOT/relative).read_bytes();h=hashlib.sha256(b).hexdigest();p=OUT/f'{name}-{h[:16]}.py';p.write_bytes(b)
 spec=importlib.util.spec_from_file_location('review_v2_'+name,p);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m,h
q,QH=load('qr','next_phase/qr/qr_login.py');s,SH=load('session','next_phase/session/session_authority.py')
def guard(event,args):
 if event.startswith('socket.') or event in {'subprocess.Popen','os.system','os.posix_spawn'}:raise AssertionError('synthetic_review_no_network')
sys.addaudithook(guard)
KEY='SYNTHETICFIXTUREKEY0001'
def generate_body():return json.dumps({'code':0,'data':{'url':'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key='+KEY,'qrcode_key':KEY}}).encode()
def poll_body(code=86101):return json.dumps({'code':0,'data':{'code':code}}).encode()
def nav(mid=1001):return json.dumps({'code':0,'data':{'isLogin':True,'mid':mid,'uname':'synthetic-fixture'}}).encode()
class FakeTransport:
 def __init__(self):self.calls=[];self.hook=None;self.poll_code=86101
 def request(self,operation,**kwargs):
  self.calls.append((operation,kwargs))
  if self.hook:self.hook(operation)
  return (generate_body(),[]) if operation=='generate' else (poll_body(self.poll_code),['SESSDATA=SYNTHETIC_FIXTURE_ONLY; Path=/; Secure'])
class Relations(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='qr-session-v2-');self.addCleanup(self.tmp.cleanup);self.pm=s.PauseManager(str(pathlib.Path(self.tmp.name)/'pause.sqlite'));self.pm.set_paused('fixture',False);self.g=s.AccountPauseGate(self.pm,'fixture')
 def authority(self,verified=False):
  a=s.SessionAuthority('fixture',1001,self.pm);a.stage_unverified()
  if verified:a.verify_and_apply(nav())
  return a
 def qr(self):
  t=FakeTransport();c=q.QRLoginCoordinator(transport=t,pause_gate=self.g);return c,t
 def test_unknown_pause_gate_zero_calls(self):
  class BadGate:
   def snapshot(self):return (None,0)
  for gate in (None,object(),BadGate()):
   t=FakeTransport();c=q.QRLoginCoordinator(transport=t,pause_gate=gate);r=c.generate(approved=True,consent_ref='synthetic-consent');self.assertEqual(r['status'],'blocked');self.assertEqual(t.calls,[])
 def test_qr_actual_shared_pause_gate_blocks_new_poll(self):
  c,t=self.qr();c.generate(approved=True,consent_ref='synthetic-consent');self.pm.set_paused('fixture',True);r=c.poll_once();self.assertEqual(r['status'],'blocked');self.assertEqual(len(t.calls),1)
 def test_qr_late_generate_cannot_undo_close(self):
  c,t=self.qr();t.hook=lambda op:c.close();r=c.generate(approved=True,consent_ref='synthetic-consent');self.assertEqual(r['status'],'blocked');self.assertEqual(c.state,'closed')
 def test_qr_late_poll_cannot_undo_close(self):
  c,t=self.qr();c.generate(approved=True,consent_ref='synthetic-consent');t.hook=lambda op:c.close();r=c.poll_once();self.assertEqual(r['status'],'blocked');self.assertEqual(c.state,'closed')
 def test_qr_pause_aba_during_callback_fenced(self):
  c,t=self.qr()
  def pause_cycle(op):self.pm.set_paused('fixture',True);self.pm.set_paused('fixture',False)
  t.hook=pause_cycle;r=c.generate(approved=True,consent_ref='synthetic-consent');self.assertEqual(r['status'],'blocked');self.assertEqual(c.state,'closed')
 def test_qr_challenge_immutable(self):
  c,t=self.qr();r=c.generate(approved=True,consent_ref='synthetic-consent')
  with self.assertRaises(dataclasses.FrozenInstanceError):r['challenge'].qrcode_key='DIFFERENTKEY00000000'
  c.poll_once();self.assertEqual(t.calls[-1][1]['key'],KEY)
 def test_qr_concurrent_poll_one_transport(self):
  c,t=self.qr();c.generate(approved=True,consent_ref='synthetic-consent');entered=threading.Event();release=threading.Event();results=[]
  def hold(op):entered.set();release.wait(3)
  t.hook=hold;worker=threading.Thread(target=lambda:results.append(c.poll_once()));worker.start();self.assertTrue(entered.wait(3))
  try:
   with self.assertRaises(q.QRProtocolError):c.poll_once()
   self.assertEqual(len(t.calls),2)
  finally:release.set();worker.join(3)
  self.assertFalse(worker.is_alive());self.assertEqual(results[0]['status'],'waiting_scan')
 def test_qr_synthetic_handle_not_persistence_or_auth_proof(self):
  c,t=self.qr();c.generate(approved=True,consent_ref='synthetic-consent');t.poll_code=0;r=c.poll_once();self.assertEqual(r['status'],'session_received');self.assertFalse(r['credential_persisted']);self.assertEqual(r['auth_assessment'],'not_assessed');self.assertEqual(r['session_handle'].to_safe_dict()['type'],'synthetic_session_handle');self.assertNotIn('SYNTHETIC_FIXTURE_ONLY',repr(r))
 def test_both_parsers_reject_overflow_and_redact_diagnostics(self):
  with self.assertRaises(q.QRProtocolError):q.parse_fail_closed_json(b'{"code":0,"data":{"extra":1e999}}')
  raw=nav()[:-1]+b',"extra":1e999}';self.assertEqual(s.verify_nav_response(raw,1001).state,s.SessionState.VERIFICATION_UNKNOWN)
  r=s.verify_nav_response(b'{"code":0,"SYNTHETIC_PRIVATE_MARKER":1,"SYNTHETIC_PRIVATE_MARKER":2}',1001);self.assertNotIn('SYNTHETIC_PRIVATE_MARKER',r.reason)
 def test_default_memory_store_and_pause_work(self):
  store=s.SyntheticCredentialStore();store.save_handle('fixture','opaque-fixture',1);self.assertEqual(store.load_handle('fixture').storage_state,s.StorageState.PRESENT);self.assertTrue(s.PauseManager().is_paused('fixture'))
 def test_wrong_expected_result_never_promotes(self):
  a=self.authority();ticket=a.begin_verification();wrong=s.verify_nav_response(nav(1002),1002)
  with self.assertRaises(s.SessionStateError):a.apply_nav_verification(wrong,ticket=ticket)
  self.assertEqual(a.state,s.SessionState.IDENTITY_MISMATCH)
  with self.assertRaises(s.SessionStateError):a.acquire_lease(s.CapabilityFlag.AUTH_READ)
 def test_result_without_issued_ticket_not_authority(self):
  a=self.authority()
  with self.assertRaises(s.SessionStateError):a.apply_nav_verification(s.verify_nav_response(nav(),1001))
  self.assertEqual(a.state,s.SessionState.UNVERIFIED)
 def test_ticket_single_use_and_not_equal_value_forgery(self):
  a=self.authority();t=a.begin_verification();r=s.verify_nav_response(nav(),1001)
  with self.assertRaises(s.SessionStateError):a.apply_nav_verification(r,ticket=dataclasses.replace(t))
  with self.assertRaises(s.SessionStateError):a.apply_nav_verification(r,ticket=t)
  fresh=a.begin_verification();a.apply_nav_verification(r,ticket=fresh)
  with self.assertRaises(s.SessionStateError):a.apply_nav_verification(r,ticket=fresh)
 def test_close_new_generation_rejects_old_ticket_and_lease(self):
  a=self.authority(verified=True);lease=a.acquire_lease(s.CapabilityFlag.AUTH_READ);old=a.begin_verification();r=s.verify_nav_response(nav(),1001);a.close();a.stage_unverified();self.assertEqual(a.state,s.SessionState.UNVERIFIED)
  with self.assertRaises(s.SessionStateError):a.apply_nav_verification(r,ticket=old)
  with self.assertRaises(s.SessionStateError):a.assert_valid_lease(lease)
  a.verify_and_apply(nav());self.assertEqual(a.state,s.SessionState.VERIFIED);a.assert_valid_lease(a.acquire_lease(s.CapabilityFlag.AUTH_READ))
 def test_pause_aba_invalidates_old_ticket_and_lease(self):
  a=self.authority(verified=True);lease=a.acquire_lease(s.CapabilityFlag.AUTH_READ);ticket=a.begin_verification();self.pm.set_paused('fixture',True);self.pm.set_paused('fixture',False)
  with self.assertRaises(s.SessionStateError):a.assert_valid_lease(lease)
  with self.assertRaises(s.SessionStateError):a.apply_nav_verification(s.verify_nav_response(nav(),1001),ticket=ticket)
 def test_cross_owner_ticket_lease_rejected(self):
  a=self.authority(verified=True);b=self.authority(verified=True);self.assertNotEqual(a._session_id,b._session_id)
  with self.assertRaises(s.SessionStateError):b.assert_valid_lease(a.acquire_lease(s.CapabilityFlag.AUTH_READ))
  with self.assertRaises(s.SessionStateError):b.apply_nav_verification(s.verify_nav_response(nav(),1001),ticket=a.begin_verification())
 def test_pause_blocks_anonymous_and_write_not_implemented(self):
  a=self.authority(verified=True)
  with self.assertRaises(s.SessionStateError):a.acquire_lease(s.CapabilityFlag.WRITE_LOW_RISK)
  with self.assertRaises(s.SessionStateError):a.acquire_lease(s.CapabilityFlag.WRITE_HIGH_RISK)
  self.pm.set_paused('fixture',True)
  with self.assertRaises(s.SessionStateError):a.acquire_lease(s.CapabilityFlag.ANONYMOUS_READ)
 def test_business_outcomes_do_not_poison_verified_session(self):
  a=self.authority(verified=True);epoch=a.epoch
  for status in ('pending','deferred','blocked','unsupported','wrong_target','unknown'):a.record_business_outcome(status)
  self.assertEqual(a.state,s.SessionState.VERIFIED);self.assertEqual(a.epoch,epoch)
 def test_restore_opaque_handle_always_unverified(self):
  store=s.SyntheticCredentialStore(str(pathlib.Path(self.tmp.name)/'store.sqlite'));store.save_handle('fixture','synthetic-opaque-id',1);a=s.SessionAuthority('fixture',1001,self.pm,store);h=a.restore_from_store();self.assertEqual(h.handle_id,'synthetic-opaque-id');self.assertEqual(a.state,s.SessionState.UNVERIFIED)
  with self.assertRaises(s.SessionStateError):a.acquire_lease(s.CapabilityFlag.AUTH_READ)
  a.verify_and_apply(nav());self.assertEqual(a.state,s.SessionState.VERIFIED)

if __name__=='__main__':unittest.main()
