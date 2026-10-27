"""Independent synthetic integration relations; no product edits or account requests."""
import json,multiprocessing,os,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from next_phase.composition import SyntheticComposition
from next_phase.session.session_authority import SessionState,StorageState
from next_phase.metadata import versioned_adapter as m
BVID='BV17x411w7KC';OTHER='BV1xx411c7X8';KEY='abcdefghijklmnop';SECRET='synthetic_not_real_COOKIE_871'
def nav(mid=1001):return json.dumps({'code':0,'data':{'isLogin':True,'mid':mid,'uname':'Fixture','silence':0}}).encode()
def body():return json.dumps({'code':0,'data':{'bvid':BVID,'title':'Synthetic partial','aid':True}}).encode()
class QR:
    def __init__(self):self.calls=0
    def request(self,operation,*,key=None):
        if operation=='generate':return self.generate()
        if operation=='poll':return self.poll(key)
        raise AssertionError('unexpected_fixture_operation')
    def generate(self):
        self.calls+=1
        return json.dumps({'code':0,'data':{'qrcode_key':KEY,'url':'https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key='+KEY}}).encode(),[]
    def poll(self,key):
        assert key==KEY;self.calls+=1
        return b'{"code":0,"data":{"code":0}}',['SESSDATA='+SECRET]
class ActualComposition(unittest.TestCase):
    def setUp(self):
        guard=patch('socket.socket',side_effect=AssertionError('network_forbidden'));self.socket=guard.start();self.addCleanup(guard.stop);self.addCleanup(self.socket.assert_not_called)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.q=QR();self.f=SyntheticComposition(self.tmp.name,'fixture-account',1001,self.q);self.calls=0
    def marker(self,f=None):
        f=f or self.f;f.pause.set_paused(f.account_id,False)
        self.assertEqual(f.qr.generate(approved=True,consent_ref='trusted_fixture_scope')['status'],'ready')
        r=f.poll_once();self.assertEqual(r['session_state'],'unverified');return r
    def verified(self,f=None):
        f=f or self.f;self.marker(f);f.authority.verify_and_apply(nav());self.assertEqual(f.authority.state,SessionState.VERIFIED)
    def transport(self,req):self.calls+=1;return m.TransportReply('response',200,body())
    def read(self,op='operation',f=None,transport=None,ref=None,bvid=BVID):
        f=f or self.f;ref=ref or f.resolve_fixture_reference(bvid)
        return f.read_fixture_metadata(ref,bvid,op,transport or self.transport)
    def test_real_modules_connect_marker_not_cookie_to_partial(self):
        r=self.marker();self.assertTrue(r['marker_persisted']);self.assertFalse(r['credential_persisted'])
        saved=self.f.store.load_handle(self.f.account_id);self.assertEqual(saved.storage_state,StorageState.PRESENT)
        self.assertEqual(saved.handle_id,r['session_handle'].handle_id)
        self.assertEqual(self.read('not_verified')['status'],'blocked');self.assertEqual(self.calls,0)
        self.f.authority.verify_and_apply(nav());a=self.read();self.assertEqual(a['observation_status'],'partial')
        self.assertEqual(a['field_states']['aid'],'invalid');self.assertEqual(a['field_states']['duration'],'missing')
        self.assertEqual(a['operation_completion'],'recorded');self.assertEqual(a['source'],'synthetic');self.assertFalse(a['evidence']['live_verified'])
        self.assertEqual(self.f.authority.__class__.__module__,'next_phase.session.session_authority')
        for p in Path(self.tmp.name).glob('*'):
            if p.is_file():self.assertNotIn(SECRET.encode(),p.read_bytes())
    def test_wrong_identity_and_nonfinite_nav_zero_business(self):
        self.marker();self.f.authority.verify_and_apply(nav(1002));self.assertEqual(self.read()['status'],'blocked')
        self.f.authority.stage_unverified();self.f.authority.verify_and_apply(b'{"code":0,"data":{"isLogin":true,"mid":1001,"silence":0},"extra":1e999}')
        self.assertNotEqual(self.f.authority.state,SessionState.VERIFIED);self.assertEqual(self.read('overflow')['status'],'blocked');self.assertEqual(self.calls,0)
    def test_same_operation_different_account_does_not_disclose_cached_data(self):
        self.verified();self.assertEqual(self.read()['status'],'partial')
        other=SyntheticComposition(self.tmp.name,'different-account',1001,QR());self.verified(other)
        r=self.read(f=other);self.assertEqual(r['status'],'rejected');self.assertEqual(r['diagnostic']['code'],'operation_id_conflict');self.assertEqual(r['data'],{});self.assertEqual(self.calls,1)
    def test_restart_unverified_and_old_reference_never_implicit_search(self):
        self.verified();ref=self.f.resolve_fixture_reference(BVID);self.assertEqual(self.read(ref=ref)['status'],'partial')
        restarted=SyntheticComposition(self.tmp.name,self.f.account_id,1001,QR());restarted.authority.restore_from_store()
        self.assertEqual(restarted.authority.state,SessionState.UNVERIFIED);self.assertEqual(self.read('restart',f=restarted,ref=ref)['status'],'blocked')
        restarted.authority.verify_and_apply(nav());self.assertEqual(self.read('stale',f=restarted,ref=ref)['diagnostic']['code'],'stale_or_wrong_target_reference');self.assertEqual(self.calls,1)
        r=self.read(f=restarted);self.assertEqual(r['delivery'],'cached');self.assertEqual(r['invocation']['transport_callback_entries'],0);self.assertEqual(self.calls,1)
    def test_inflight_pause_does_not_forge_cancellation_or_reauthorize(self):
        self.verified()
        def pause_then_return(req):self.f.pause.set_paused(self.f.account_id,True);return self.transport(req)
        r=self.read(transport=pause_then_return);self.assertEqual(r['status'],'partial');self.assertEqual(r['evidence']['transport_callback_entries'],1)
        self.assertEqual(self.read('afterpause')['status'],'blocked');self.assertEqual(self.calls,1)
    def test_inflight_close_observation_never_revives_authority(self):
        self.verified()
        def close_then_return(req):self.f.authority.close();return self.transport(req)
        self.assertEqual(self.read(transport=close_then_return)['status'],'partial');self.assertEqual(self.f.authority.state,SessionState.CLOSED)
        self.assertEqual(self.read('afterclose')['status'],'blocked');self.assertEqual(self.calls,1)
        self.f.authority.stage_unverified();self.assertEqual(self.read('newgeneration')['status'],'blocked')
    def test_wrong_reference_binding_zero_callback(self):
        self.verified();ref=self.f.resolve_fixture_reference(OTHER)
        r=self.read(ref=ref);self.assertEqual(r['status'],'blocked');self.assertEqual(self.calls,0)
    def test_same_operation_concurrent_one_transport(self):
        self.verified();entered=threading.Event();release=threading.Event();results=[]
        def slow(req):entered.set();self.assertTrue(release.wait(5));return self.transport(req)
        worker=threading.Thread(target=lambda:results.append(self.read(transport=slow)));worker.start();self.assertTrue(entered.wait(5))
        try:r=self.read();self.assertEqual(r['status'],'unknown');self.assertEqual(r['evidence']['transport_callback_entries'],0)
        finally:release.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(results[0]['status'],'partial');self.assertEqual(self.calls,1)
    def test_durable_reserved_then_process_exit_never_replays(self):
        self.verified()
        def child():
            def crash(req):os._exit(71)
            self.read('crashed',transport=crash)
        process=multiprocessing.get_context('fork').Process(target=child);process.start();process.join(5)
        self.assertFalse(process.is_alive());self.assertEqual(process.exitcode,71)
        r=self.read('crashed');self.assertEqual(r['status'],'unknown');self.assertEqual(r['diagnostic']['code'],'previous_run_incomplete');self.assertEqual(self.calls,0)
        self.assertEqual(self.read('unrelated')['status'],'partial');self.assertEqual(self.calls,1)
    def test_unknown_error_is_redacted_cached_without_retry_or_auth_poison(self):
        self.verified()
        def fail(req):self.calls+=1;raise RuntimeError(SECRET)
        first=self.read(transport=fail);again=self.read(transport=fail)
        self.assertEqual(first['status'],'unknown');self.assertEqual(again['delivery'],'cached');self.assertEqual(again['invocation']['transport_callback_entries'],0)
        self.assertNotIn(SECRET,json.dumps(first));self.assertEqual(self.calls,1);self.assertEqual(self.f.authority.state,SessionState.VERIFIED)
if __name__=='__main__':unittest.main()
