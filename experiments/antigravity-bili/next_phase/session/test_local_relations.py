"""dot-local relationship regressions; synthetic bytes/SQLite only."""
import json,unittest
from dataclasses import replace
from .session_authority import *

def raw(mid=1001):return json.dumps({'code':0,'data':{'isLogin':True,'mid':mid,'uname':'fixture','silence':0}}).encode()
class Relations(unittest.TestCase):
 def setUp(self):
  self.pause=PauseManager();self.pause.set_paused('fixture',False);self.a=SessionAuthority('fixture',1001,self.pause);self.a.stage_unverified()
 def verified(self):self.a.verify_and_apply(raw());return self.a.acquire_lease(CapabilityFlag.AUTH_READ)
 def test_plain_parser_result_is_not_owner_authority(self):
  with self.assertRaises(SessionStateError):self.a.apply_nav_verification(verify_nav_response(raw(),1001))
 def test_wrong_expected_identity_rejected(self):
  ticket=self.a.begin_verification()
  with self.assertRaises(SessionStateError):self.a.apply_nav_verification(verify_nav_response(raw(1002),1002),ticket=ticket)
  self.assertEqual(self.a.state,SessionState.IDENTITY_MISMATCH)
 def test_ticket_generation_bound(self):
  ticket=self.a.begin_verification();self.a.stage_unverified()
  with self.assertRaises(SessionStateError):self.a.apply_nav_verification(verify_nav_response(raw(),1001),ticket=ticket)
 def test_ticket_single_use(self):
  ticket=self.a.begin_verification();result=verify_nav_response(raw(),1001);self.a.apply_nav_verification(result,ticket=ticket)
  with self.assertRaises(SessionStateError):self.a.apply_nav_verification(result,ticket=ticket)
 def test_close_blocks_old_work_but_explicit_new_generation_allowed(self):
  ticket=self.a.begin_verification();self.a.close()
  for fn in (self.a.begin_verification,lambda:self.a.apply_nav_verification(verify_nav_response(raw(),1001),ticket=ticket),lambda:self.a.acquire_lease(CapabilityFlag.ANONYMOUS_READ)):
   with self.assertRaises(SessionStateError):fn()
  old_owner=self.a._session_id;self.a.stage_unverified();self.assertEqual(self.a.state,SessionState.UNVERIFIED);self.assertNotEqual(old_owner,self.a._session_id)
  with self.assertRaises(SessionStateError):self.a.apply_nav_verification(verify_nav_response(raw(),1001),ticket=ticket)
  self.a.verify_and_apply(raw());self.assertEqual(self.a.state,SessionState.VERIFIED)
 def test_pause_unpause_fences_inflight_result(self):
  ticket=self.a.begin_verification();self.pause.set_paused('fixture',True);self.pause.set_paused('fixture',False)
  with self.assertRaises(SessionStateError):self.a.apply_nav_verification(verify_nav_response(raw(),1001),ticket=ticket)
  self.assertEqual(self.a.state,SessionState.UNVERIFIED)
 def test_pause_blocks_existing_lease_and_no_resurrection(self):
  lease=self.verified();self.pause.set_paused('fixture',True)
  with self.assertRaises(SessionStateError):self.a.assert_valid_lease(lease)
  self.pause.set_paused('fixture',False)
  with self.assertRaises(SessionStateError):self.a.assert_valid_lease(lease)
 def test_owner_unique_and_cross_lease_rejected(self):
  lease=self.verified();b=SessionAuthority('fixture',1001,self.pause);b.verify_and_apply(raw());self.assertNotEqual(self.a._session_id,b._session_id)
  with self.assertRaises(SessionStateError):b.assert_valid_lease(lease)
 def test_forged_capability_rejected(self):
  lease=self.verified()
  with self.assertRaises(SessionStateError):self.a.assert_valid_lease(replace(lease,capability=CapabilityFlag.ADMIN))
 def test_cross_owner_ticket_rejected(self):
  ticket=self.a.begin_verification();b=SessionAuthority('fixture',1001,self.pause)
  with self.assertRaises(SessionStateError):b.apply_nav_verification(verify_nav_response(raw(),1001),ticket=ticket)
 def test_nonfinite_extra_and_error_redaction(self):
  data=raw()[:-1]+b',"extra":1e999}'
  self.assertEqual(verify_nav_response(data,1001).state,SessionState.VERIFICATION_UNKNOWN)
  marker='FAKE_PRIVATE_DUPKEY';data=(' {"'+marker+'":1,"'+marker+'":2}').encode();result=verify_nav_response(data,1001)
  self.assertNotIn(marker,result.reason)
 def test_pause_is_account_wide_not_anonymous_bypass(self):
  self.pause.set_paused('fixture',True)
  for cap in (CapabilityFlag.ANONYMOUS_READ,CapabilityFlag.AUTH_READ):
   with self.assertRaises(SessionStateError):self.a.acquire_lease(cap)
 def test_login_does_not_grant_writes(self):
  self.verified()
  for cap in (CapabilityFlag.WRITE_LOW_RISK,CapabilityFlag.WRITE_HIGH_RISK):
   with self.assertRaisesRegex(SessionStateError,'not_implemented'):self.a.acquire_lease(cap)
 def test_bound_pause_gate_same_account(self):
  gate=AccountPauseGate(self.pause,'fixture');self.assertFalse(gate.is_paused());self.pause.set_paused('fixture',True);self.assertTrue(gate.is_paused())
if __name__=='__main__':unittest.main()
