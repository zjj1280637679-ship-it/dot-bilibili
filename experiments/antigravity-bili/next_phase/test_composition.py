"""Actual QR -> opaque-marker store -> session -> metadata synthetic relations."""
import json,tempfile,unittest
from unittest.mock import patch
from .composition import SyntheticComposition
from .qr.test_qr import FakeTransport
from .session.session_authority import SessionState,StorageState
from .metadata.versioned_adapter import TransportReply
BVID='BV17x411w7KC';KEY='abcdefghijklmnop'
def generate_body():return json.dumps({'code':0,'data':{'qrcode_key':KEY,'url':'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key='+KEY}}).encode()
def nav(mid=1001):return json.dumps({'code':0,'data':{'isLogin':True,'mid':mid,'uname':'fixture','silence':0}}).encode()
class Composition(unittest.TestCase):
 def setUp(self):
  guard=patch('socket.socket',side_effect=AssertionError('network_forbidden_in_synthetic_test'));self.network_guard=guard.start();self.addCleanup(guard.stop);self.addCleanup(self.network_guard.assert_not_called)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.q=FakeTransport();self.q.generate_queue=[(generate_body(),[])];self.q.poll_queue=[(b'{"code":0,"data":{"code":0}}',['SESSDATA=fake-only'])]
  self.flow=SyntheticComposition(self.tmp.name,'account-fixture',1001,self.q);self.calls=0
 def transport(self,request):
  self.calls+=1
  return TransportReply('response',200,json.dumps({'code':0,'data':{'bvid':BVID,'title':'synthetic'}}).encode())
 def acquire_marker(self):
  self.flow.pause.set_paused('account-fixture',False)
  self.assertEqual(self.flow.qr.generate(approved=True,consent_ref='fixture-exact-scope')['status'],'ready')
  out=self.flow.poll_once();self.assertTrue(out['marker_persisted']);self.assertFalse(out['credential_persisted']);self.assertEqual(out['session_state'],'unverified')
 def read(self,op):
  ref=self.flow.resolve_fixture_reference(BVID)
  return self.flow.read_fixture_metadata(ref,BVID,op,self.transport)
 def test_new_flow_defaultpause_zero_qr_calls(self):
  out=self.flow.qr.generate(approved=True,consent_ref='fixture')
  self.assertEqual(out['status'],'blocked');self.assertEqual(self.q.call_count,0)
 def test_actual_marker_store_then_unverified_zero_business_calls(self):
  self.acquire_marker();self.assertEqual(self.flow.store.load_handle('account-fixture').storage_state,StorageState.PRESENT)
  self.assertEqual(self.flow.store.load_handle('different-account').storage_state,StorageState.MISSING)
  self.assertEqual(self.read('before-verification')['status'],'blocked');self.assertEqual(self.calls,0)
 def test_verified_partial_preserved_and_no_replay(self):
  self.acquire_marker();self.flow.authority.verify_and_apply(nav())
  a=self.read('same-operation');b=self.read('same-operation')
  self.assertEqual(a['observation_status'],'partial');self.assertFalse(a['coverage']['projection_complete']);self.assertFalse(a['evidence']['live_verified']);self.assertEqual({k:v for k,v in a.items() if k not in ('delivery','invocation')},{k:v for k,v in b.items() if k not in ('delivery','invocation')});self.assertEqual(b['delivery'],'cached');self.assertEqual(b['invocation']['transport_callback_entries'],0);self.assertEqual(self.calls,1)
  self.assertEqual(self.flow.authority.state,SessionState.VERIFIED)
 def test_shared_pause_blocks_qr_and_metadata_and_survives_new_flow(self):
  self.acquire_marker();self.flow.authority.verify_and_apply(nav());self.flow.pause.set_paused('account-fixture',True)
  self.assertEqual(self.read('paused')['status'],'blocked');self.assertEqual(self.calls,0)
  newer=SyntheticComposition(self.tmp.name,'account-fixture',1001,FakeTransport())
  self.assertTrue(newer.gate.is_paused());newer.authority.restore_from_store();self.assertEqual(newer.authority.state,SessionState.UNVERIFIED)
  self.assertEqual(newer.qr.generate(approved=True,consent_ref='fixture')['status'],'blocked')
 def test_close_then_explicit_new_generation_requires_fresh_verification(self):
  self.acquire_marker();self.flow.authority.verify_and_apply(nav());self.flow.authority.close()
  self.assertEqual(self.read('closed')['status'],'blocked');self.assertEqual(self.calls,0)
  self.flow.authority.stage_unverified();self.assertEqual(self.read('reopened-unverified')['status'],'blocked');self.assertEqual(self.calls,0)
  self.flow.authority.verify_and_apply(nav());self.assertEqual(self.read('reopened-verified')['observation_status'],'partial');self.assertEqual(self.calls,1)
 def test_unknown_no_replay_and_unrelated_read_preserves_auth(self):
  self.acquire_marker();self.flow.authority.verify_and_apply(nav())
  def uncertain(request):
   self.calls+=1
   return TransportReply('unknown')
  ref=self.flow.resolve_fixture_reference(BVID)
  a=self.flow.read_fixture_metadata(ref,BVID,'unknown-operation',uncertain)
  b=self.flow.read_fixture_metadata(ref,BVID,'unknown-operation',uncertain)
  self.assertEqual(a['observation_status'],'unknown');self.assertEqual({k:v for k,v in a.items() if k not in ('delivery','invocation')},{k:v for k,v in b.items() if k not in ('delivery','invocation')});self.assertEqual(b['delivery'],'cached');self.assertEqual(b['invocation']['transport_callback_entries'],0);self.assertEqual(self.calls,1)
  self.assertEqual(self.flow.authority.state,SessionState.VERIFIED)
  self.assertEqual(self.read('unrelated-read')['observation_status'],'partial');self.assertEqual(self.calls,2)
 def test_identity_mismatch_zero_business_calls(self):
  self.acquire_marker();self.flow.authority.verify_and_apply(nav(1002))
  self.assertEqual(self.flow.authority.state,SessionState.IDENTITY_MISMATCH);self.assertEqual(self.read('wrong-account')['status'],'blocked');self.assertEqual(self.calls,0)
if __name__=='__main__':unittest.main()
