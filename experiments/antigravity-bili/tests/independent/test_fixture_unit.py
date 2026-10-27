"""Independent fixture-only tests. Never imports unsafe product drafts."""
import hashlib, importlib.util, json, pathlib, subprocess, sys, tempfile, threading, unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
_artifact_tmp=tempfile.TemporaryDirectory(prefix='bili-independent-');OUT=pathlib.Path(_artifact_tmp.name)
DATA=(ROOT/'minimal_slice_vnext/service.py').read_bytes();SHA=hashlib.sha256(DATA).hexdigest()
SNAP=OUT/f'service-{SHA[:16]}.py';SNAP.write_bytes(DATA)
spec=importlib.util.spec_from_file_location('independent_minimal_service',SNAP);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
A='BV1234567890';B='BV0987654321'

def no_network(event,args):
 if event.startswith('socket.') or event == 'os.system':raise AssertionError('independent_test_forbids_network_or_shell')
sys.addaudithook(no_network)

class TestMinimal(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='bili-minimal-test-');self.addCleanup(self.tmp.cleanup);self.db=pathlib.Path(self.tmp.name)/'fixture.sqlite';self.calls=[]
 def service(self,paused=False,backend=None):
  def fake(bvid):self.calls.append(bvid);return {'status':'completed','data':{'bvid':bvid,'title':'synthetic'}}
  return mod.Service(self.db,backend=backend or fake,initial_paused=paused)
 def args(self,s,bvid=A,id='one'):
  ref=s.call('video.reference.resolve',{'value':bvid})['data']['reference_id']
  return dict(reference_id=ref,expected_bvid=bvid,operation_id=id,backend='fixture')
 def test_discovery_honest(self):
  s=self.service();r=s.call('capabilities.list',{});self.assertFalse(r['live']);self.assertEqual(r['backend'],'fixture');self.assertEqual(r['data']['authentication'],'not_implemented');self.assertEqual(r['data']['network'],'not_implemented');self.assertNotIn('search.query.submit',r['data']['tools'])
 def test_reference_is_pure_and_syntax_only(self):
  s=self.service(paused=True)
  for x in [A,f'https://www.bilibili.com/video/{A}',f'https://www.bilibili.com/video/{A}/']:
   r=s.call('video.reference.resolve',{'value':x});self.assertEqual(r['status'],'completed');self.assertEqual(r['data']['bvid'],A);self.assertEqual(r['data']['existence'],'not_checked')
  self.assertEqual(self.calls,[])
 def test_reference_rejects_spoofing_and_unsupported_normalizations(self):
  s=self.service()
  for x in [f'http://www.bilibili.com/video/{A}',f'https://www.bilibili.com.evil/video/{A}',f'https://user@www.bilibili.com/video/{A}',f'https://www.bilibili.com:443/video/{A}',f'https://www.bilibili.com/video/{A}?x=1',f'https://www.bilibili.com/video/{A}#x',f'https://www.bilibili.com/video/{A}\n',f'https://www.bilibili.com/video/%42V1234567890','https://b23.tv/fake',float('nan'),None,{'value':A}]:
   with self.subTest(value=repr(x)):self.assertEqual(s.call('video.reference.resolve',{'value':x})['status'],'rejected')
  self.assertEqual(self.calls,[])
 def test_strict_args(self):
  s=self.service()
  for name,args in [('video.reference.resolve',{}),('video.reference.resolve',{'value':A,'extra':1}),('operation.status',{'operation_id':'one','secret':'x'}),('capabilities.list',[])]:self.assertEqual(s.call(name,args)['status'],'rejected')
 def test_default_pause_and_restart(self):
  s=mod.Service(self.db);self.assertTrue(s.paused());r=s.call('video.metadata.read',self.args(s));self.assertEqual(r['status'],'blocked')
  restarted=mod.Service(self.db,initial_paused=False);self.assertTrue(restarted.paused());self.assertEqual(restarted.status('one')['status'],'not_found')
 def test_standalone_metadata_no_implicit_search(self):
  s=self.service();r=s.call('video.metadata.read',self.args(s));self.assertEqual(r['status'],'completed');self.assertEqual(r['data']['bvid'],A);self.assertFalse(r['live']);self.assertEqual(self.calls,[A])
  self.assertEqual(s.call('search.query.submit',{'query':'x'})['status'],'unsupported');self.assertEqual(self.calls,[A])
 def test_wrong_target_and_backend_zero_dispatch(self):
  s=self.service();a=self.args(s);a['expected_bvid']=B;self.assertEqual(s.call('video.metadata.read',a)['status'],'blocked');a['expected_bvid']=A;a['backend']='network';self.assertEqual(s.call('video.metadata.read',a)['status'],'unsupported');self.assertEqual(self.calls,[])
 def test_idempotency_and_fresh_reference(self):
  s=self.service();a=self.args(s);r=s.call('video.metadata.read',a);self.assertEqual(s.call('video.metadata.read',self.args(s)),r);self.assertEqual(self.calls,[A])
 def test_changed_target_conflict(self):
  s=self.service();s.call('video.metadata.read',self.args(s));r=s.call('video.metadata.read',self.args(s,B));self.assertEqual(r['error'],'operation_id_conflict');self.assertEqual(self.calls,[A])
 def test_status_is_local_no_retry(self):
  s=self.service();s.call('video.metadata.read',self.args(s));before=len(self.calls)
  for i in range(5):self.assertEqual(s.call('operation.status',{'operation_id':'one'})['status'],'completed')
  self.assertEqual(s.status('missing')['status'],'not_found');self.assertEqual(s.status('../bad')['status'],'rejected');self.assertEqual(len(self.calls),before)
 def test_malformed_backend_never_completed(self):
  for n,value in enumerate([None,[],{}, {'code':False},{'status':'completed','code':0},{'status':'completed','data':{'bvid':B,'title':'x'}},{'status':'completed','data':{'bvid':A,'title':'x','secret':'x'}}]):
   with self.subTest(value=value):
    s=self.service(backend=lambda b,v=value:v);r=s.call('video.metadata.read',self.args(s,id=f'bad{n}'));self.assertEqual(r['status'],'unknown')
 def test_exception_sanitized_unknown_no_replay(self):
  def bad(b):self.calls.append(b);raise RuntimeError('Cookie: SYNTHETIC-SECRET-MARKER')
  s=self.service(backend=bad);a=self.args(s);r=s.call('video.metadata.read',a);self.assertEqual(r['status'],'unknown');self.assertNotIn('SYNTHETIC-SECRET',json.dumps(s.status('one')));self.assertEqual(s.call('video.metadata.read',a)['status'],'unknown');self.assertEqual(len(self.calls),1)
 def test_concurrent_same_id_one_backend_call(self):
  entered=threading.Event();release=threading.Event();results=[]
  def backend(b):self.calls.append(b);entered.set();release.wait(5);return {'status':'completed','data':{'bvid':b,'title':'x'}}
  s=self.service(backend=backend);a=self.args(s)
  t=threading.Thread(target=lambda:results.append(s.call('video.metadata.read',a)));t.start();self.assertTrue(entered.wait(5))
  try:second=s.call('video.metadata.read',a);self.assertEqual(second['status'],'pending');self.assertEqual(len(self.calls),1)
  finally:release.set();t.join(5)
  self.assertFalse(t.is_alive());self.assertEqual(results[0]['status'],'completed')
 def test_restart_completed_no_redispatch(self):
  s=self.service();oldargs=self.args(s);r=s.call('video.metadata.read',oldargs);other=self.service();self.assertEqual(other.call('video.metadata.read',oldargs)['status'],'blocked');self.assertEqual(other.call('video.metadata.read',self.args(other)),r);self.assertEqual(self.calls,[A])
 def test_incomplete_previous_owner_unknown_no_replay(self):
  s=self.service();a=self.args(s)
  fp=hashlib.sha256(json.dumps(['fixture','video.metadata.read',A]).encode()).hexdigest()
  with s.connect() as c:c.execute('INSERT INTO operations VALUES(?,?,?,NULL)',('one',fp,'different-old-process'))
  self.assertEqual(s.status('one')['status'],'unknown');self.assertEqual(s.call('video.metadata.read',a)['status'],'unknown');self.assertEqual(self.calls,[])
 def test_paused_retry_no_poisoned_reservation(self):
  s=self.service(paused=True);a=self.args(s);self.assertEqual(s.call('video.metadata.read',a)['status'],'blocked');s.set_pause(False);self.assertEqual(s.call('video.metadata.read',a)['status'],'completed');self.assertEqual(self.calls,[A])
 def test_real_process_crash_after_reservation_never_replays(self):
  marker=pathlib.Path(self.tmp.name)/'backend-entered.txt'
  code = "import importlib.util,sys,os,pathlib;spec=importlib.util.spec_from_file_location('crash_fixture',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\ndef backend(bvid):\n pathlib.Path(sys.argv[3]).write_text(bvid);os._exit(71)\ns=m.Service(sys.argv[2],backend=backend,initial_paused=False);r=s.resolve('BV1234567890');s.metadata(reference_id=r['data']['reference_id'],expected_bvid='BV1234567890',operation_id='crash-op',backend='fixture')"
  completed=subprocess.run([sys.executable,'-B','-c',code,str(SNAP),str(self.db),str(marker)],capture_output=True,timeout=5,env={'HOME':self.tmp.name,'PATH':str(pathlib.Path(sys.executable).parent)})
  self.assertEqual(completed.returncode,71);self.assertEqual(marker.read_text(),A)
  restarted=self.service();self.assertEqual(restarted.status('crash-op')['status'],'unknown');self.assertEqual(restarted.call('video.metadata.read',self.args(restarted,id='crash-op'))['status'],'unknown');self.assertEqual(self.calls,[])
 def test_pause_not_tool_accessible(self):
  s=self.service(paused=True);self.assertEqual(s.call('set_pause',{'paused':False})['status'],'unsupported');self.assertTrue(s.paused())
 def test_no_unsafe_product_imports(self):
  import ast
  tree=ast.parse(DATA)
  imports=[]
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):imports.extend(n.name for n in node.names)
   elif isinstance(node,ast.ImportFrom):imports.append(node.module or '')
  self.assertFalse(any(x.startswith('product') or 'operations' in x or 'session_gate' in x for x in imports))

if __name__=='__main__':unittest.main()
