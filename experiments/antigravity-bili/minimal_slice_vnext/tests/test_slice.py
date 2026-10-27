import concurrent.futures
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from minimal_slice_vnext.service import Service, fixture_metadata, resolve_bvid
from minimal_slice_vnext.server import Protocol

BV='BV17x411w7KC'
BV2='BV1xx411c7mD'

class SliceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=Path(self.tmp.name)/'fixture.db'; self.calls=[]
  def backend(bvid): self.calls.append(bvid); return fixture_metadata(bvid)
  self.s=Service(self.db,backend=backend,initial_paused=False)
 def tearDown(self): self.tmp.cleanup()
 def args(self, s=None, bvid=BV, operation_id='one'):
  s=s or self.s
  return dict(reference_id=s.resolve(bvid)['data']['reference_id'],expected_bvid=bvid,operation_id=operation_id,backend='fixture')
 def test_strict_resolver(self):
  self.assertEqual(resolve_bvid(BV),BV)
  self.assertEqual(resolve_bvid('https://www.bilibili.com/video/'+BV+'/'),BV)
  for bad in ['http://www.bilibili.com/video/'+BV,'https://www.bilibili.com.evil/video/'+BV,'https://user@www.bilibili.com/video/'+BV,'https://www.bilibili.com/video/'+BV+'?x=y','https://b23.tv/x',True,' '+BV,'https://www.bilibili.com/video/'+BV+'\n']:
   with self.subTest(bad=bad),self.assertRaises(ValueError):resolve_bvid(bad)
 def test_independent_fixture_metadata(self):
  r=self.s.metadata(**self.args());self.assertEqual(r['status'],'completed');self.assertFalse(r['live']);self.assertEqual(r['backend'],'fixture');self.assertEqual(self.calls,[BV])
 def test_unknown_fixture_not_invented(self):
  self.assertEqual(self.s.metadata(**self.args(bvid=BV2))['status'],'not_found')
 def test_same_id_no_replay(self):
  a=self.args();one=self.s.metadata(**a);two=self.s.metadata(**a);self.assertEqual(one,two);self.assertEqual(len(self.calls),1)
 def test_conflicting_semantics(self):
  self.s.metadata(**self.args());r=self.s.metadata(**self.args(bvid=BV2));self.assertEqual(r['error'],'operation_id_conflict');self.assertEqual(len(self.calls),1)
 def test_status_zero_dispatch(self):
  for _ in range(3):self.s.status('missing')
  self.assertEqual(self.calls,[])
 def test_stale_wrong_target(self):
  a=self.args();a['expected_bvid']=BV2;self.assertEqual(self.s.metadata(**a)['status'],'blocked')
  a=self.args();other=Service(self.db,backend=lambda _: self.fail('no backend'))
  self.assertEqual(other.metadata(**a)['status'],'blocked');self.assertEqual(self.calls,[])
 def test_pause_persists_no_clear_on_startup(self):
  self.s.set_pause(True);s=Service(self.db,initial_paused=False,backend=lambda _:self.fail('paused call'))
  self.assertTrue(s.paused());self.assertEqual(s.metadata(**self.args(s))['error'],'account_operations_paused');self.assertEqual(s.status('one')['status'],'not_found')
 def test_default_paused(self):
  s=Service(Path(self.tmp.name)/'fresh.db');self.assertTrue(s.paused())
 def test_error_no_secret_or_replay(self):
  calls=[]
  def broken(_):calls.append(1);raise RuntimeError('SYNTHETIC-SECRET-MUST-NOT-ECHO')
  s=Service(self.db,backend=broken);a=self.args(s);r=s.metadata(**a)
  self.assertEqual(r['status'],'unknown');self.assertNotIn('SECRET',json.dumps(s.status('one')))
  self.assertEqual(s.metadata(**a),r);self.assertEqual(calls,[1])
 def test_unknown_does_not_poison_other_operations(self):
  s=Service(self.db,backend=lambda _:{'status':'pending'})
  self.assertEqual(s.metadata(**self.args(s))['status'],'pending')
  self.assertFalse(s.paused());s.backend=fixture_metadata
  self.assertEqual(s.metadata(**self.args(s,operation_id='two'))['status'],'completed')
 def test_transport_success_is_not_business_success(self):
  for raw in [None,[],{},True,{'code':False},{'status':'completed','data':{'bvid':BV,'title':'x'},'code':-400}]:
   self.assertEqual(Service._classify(raw,BV)['status'],'unknown')
 def test_typed_outcomes(self):
  for state in ['blocked','pending','unsupported','unknown','rejected']:
   self.assertEqual(Service._classify({'status':state,'private':'secret'},BV)['status'],state)
   self.assertNotIn('secret',json.dumps(Service._classify({'status':state,'private':'secret'},BV)))
 def test_atomic_concurrent_claim(self):
  entered=threading.Event();release=threading.Event();calls=[]
  def backend(bvid):calls.append(1);entered.set();self.assertTrue(release.wait(5));return fixture_metadata(bvid)
  s=Service(self.db,backend=backend);a=self.args(s)
  with concurrent.futures.ThreadPoolExecutor(2) as pool:
   f=pool.submit(s.metadata,**a);self.assertTrue(entered.wait(5))
   r=s.metadata(**a);self.assertEqual(r['status'],'pending');release.set();self.assertEqual(f.result()['status'],'completed')
  self.assertEqual(calls,[1])
 def test_crash_reservation_never_replays(self):
  a=self.args()
  import hashlib
  fp=hashlib.sha256(json.dumps(['fixture','video.metadata.read',BV]).encode()).hexdigest()
  with self.s.connect() as c:c.execute('INSERT INTO operations VALUES(?,?,?,NULL)',('one',fp,'old-run'))
  self.assertEqual(self.s.metadata(**a)['status'],'unknown');self.assertEqual(self.calls,[])
 def test_backend_unwired_not_denied(self):
  a=self.args();a['backend']='real';self.assertEqual(self.s.metadata(**a)['status'],'unsupported');self.assertEqual(self.calls,[])
 def test_input_surface_is_closed(self):
  self.assertEqual(self.s.call('account.login',{})['status'],'unsupported')
  self.assertEqual(self.s.call('capabilities.list',{'path':'secret'})['status'],'rejected')
  self.assertEqual(self.s.call('operation.status',{'operation_id':True})['status'],'rejected')
 def test_protocol_lifecycle(self):
  p=Protocol(self.s)
  self.assertIn('error',p.receive(json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/list'})))
  init=p.receive(json.dumps({'jsonrpc':'2.0','id':2,'method':'initialize','params':{'protocolVersion':'2025-06-18'}}))
  self.assertEqual(init['result']['protocolVersion'],'2025-06-18')
  self.assertIsNone(p.receive('{"jsonrpc":"2.0","method":"notifications/initialized"}'))
  tools=p.receive('{"jsonrpc":"2.0","id":3,"method":"tools/list"}')['result']['tools']
  self.assertEqual(len(tools),4)
 def test_strict_json(self):
  p=Protocol(self.s)
  for text in ['{"a":NaN}','{"a":1,"a":2}','[]','{bad']:
   self.assertIn('error',p.receive(text))
 def test_real_subprocess_stdio_and_restart_pause(self):
  cmd=[sys.executable,'-m','minimal_slice_vnext.server','--db',str(self.db),'--fixture-ready']
  def run():
   p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
   def call(obj,response=True):
    p.stdin.write(json.dumps(obj)+'\n');p.stdin.flush()
    return json.loads(p.stdout.readline()) if response else None
   call({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18'}})
   call({'jsonrpc':'2.0','method':'notifications/initialized'},False)
   def tool(id,name,args):return call({'jsonrpc':'2.0','id':id,'method':'tools/call','params':{'name':name,'arguments':args}})['result']['structuredContent']
   cap=tool(2,'capabilities.list',{})
   ref=tool(3,'video.reference.resolve',{'value':BV})['data']
   r=tool(4,'video.metadata.read',dict(reference_id=ref['reference_id'],expected_bvid=BV,operation_id='stdio',backend='fixture'))
   status=tool(5,'operation.status',{'operation_id':'stdio'})
   p.stdin.close();self.assertEqual(p.wait(5),0);self.assertEqual(p.stderr.read(),'');p.stdout.close();p.stderr.close()
   return cap,r,status
  cap,r,status=run();self.assertEqual(r['status'],'completed');self.assertEqual(r,status)
  self.s.set_pause(True);cap,r,status=run();self.assertTrue(cap['data']['paused'])
  # Already completed operation is only observed, not dispatched again while paused.
  self.assertEqual(r['status'],'completed')

if __name__=='__main__':unittest.main()
