"""Independent real-subprocess stdio checks with synthetic fixtures and network guard."""
import hashlib,json,os,pathlib,select,shutil,subprocess,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
_artifact_tmp=tempfile.TemporaryDirectory(prefix='bili-independent-');OUT=pathlib.Path(_artifact_tmp.name)
FILES={n:(ROOT/'minimal_slice_vnext'/n).read_bytes() for n in ('__init__.py','service.py','server.py')}
HASHES={n:hashlib.sha256(b).hexdigest() for n,b in FILES.items()};COMBINED=hashlib.sha256(json.dumps(HASHES,sort_keys=True).encode()).hexdigest()
SNAP=OUT/f'protocol-snapshot-{COMBINED[:16]}';PKG=SNAP/'minimal_slice_vnext';PKG.mkdir(parents=True,exist_ok=True)
for n,b in FILES.items():(PKG/n).write_bytes(b)
GUARD="""import sys,runpy

def guard(event,args):
 if event.startswith('socket.') or event in {'subprocess.Popen','os.system','os.posix_spawn'}:
  raise RuntimeError('OFFLINE_REVIEW_FORBIDS_NETWORK_OR_CHILD')
sys.addaudithook(guard)
runpy.run_module('minimal_slice_vnext.server',run_name='__main__')
"""
KNOWN='BV17x411w7KC';UNKNOWN='BV1234567890'
class Client:
 def __init__(self,tmp,ready=False):
  env={'PATH':str(pathlib.Path(sys.executable).parent),'HOME':tmp,'PYTHONPATH':str(SNAP),'PYTHONDONTWRITEBYTECODE':'1','LANG':'C.UTF-8'}
  argv=[sys.executable,'-B','-c',GUARD,'--db',str(pathlib.Path(tmp)/'state.sqlite')]+(['--fixture-ready'] if ready else [])
  self.p=subprocess.Popen(argv,cwd=SNAP,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
  self.buffer=b'';self.id=1
 def send_raw(self,raw):self.p.stdin.write(raw+b'\n');self.p.stdin.flush()
 def recv(self):
  while b'\n' not in self.buffer:
   if not select.select([self.p.stdout],[],[],3)[0]:raise AssertionError('bounded protocol response timed out')
   chunk=os.read(self.p.stdout.fileno(),65536)
   if not chunk:raise AssertionError('unexpected EOF; stderr='+self.p.stderr.read().decode(errors='replace'))
   self.buffer+=chunk
  line,self.buffer=self.buffer.split(b'\n',1);return json.loads(line)
 def req(self,method,params=None,id=None):
  if id is None:id=self.id;self.id+=1
  obj={'jsonrpc':'2.0','id':id,'method':method}
  if params is not None:obj['params']=params
  self.send_raw(json.dumps(obj).encode());r=self.recv();assert r['id']==id,(r,id);return r
 def initialize(self):
  r=self.req('initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'independent-offline-test','version':'1'}})
  self.send_raw(b'{"jsonrpc":"2.0","method":"notifications/initialized"}');return r
 def tool(self,name,args):return self.req('tools/call',{'name':name,'arguments':args})['result']['structuredContent']
 def resolve(self,bvid):return self.tool('video.reference.resolve',{'value':bvid})['data']['reference_id']
 def metadata(self,bvid=KNOWN,id='one'):
  return self.tool('video.metadata.read',{'reference_id':self.resolve(bvid),'expected_bvid':bvid,'operation_id':id,'backend':'fixture'})
 def close(self):
  if self.p.poll() is None:
   self.p.stdin.close()
   try:self.p.wait(timeout=3)
   except subprocess.TimeoutExpired:self.p.kill();self.p.wait();raise AssertionError('EOF did not stop server')
  out=self.p.stdout.read();err=self.p.stderr.read();self.p.stdout.close();self.p.stderr.close()
  return self.p.returncode,self.buffer+out,err

class ProtocolTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory(prefix='bili-proto-test-');self.addCleanup(self.tmp.cleanup);self.clients=[]
 def client(self,ready=False):
  c=Client(self.tmp.name,ready);self.clients.append(c);return c
 def tearDown(self):
  for c in self.clients:
   if c.p.stdout.closed:continue
   code,out,err=c.close();self.assertEqual(code,0);self.assertEqual(out,b'');self.assertEqual(err,b'')
 def test_initialization_discovery_honest(self):
  c=self.client();self.assertIn('error',c.req('tools/list'));r=c.initialize();self.assertEqual(r['result']['protocolVersion'],'2025-06-18');tools=c.req('tools/list')['result']['tools'];self.assertEqual({t['name'] for t in tools},{'capabilities.list','video.reference.resolve','video.metadata.read','operation.status'})
  for t in tools:self.assertFalse(t['inputSchema']['additionalProperties']);self.assertIn('fixture',t['description'])
  cap=c.tool('capabilities.list',{});self.assertTrue(cap['data']['paused']);self.assertFalse(cap['live'])
 def test_protocol_request_ids_and_notifications(self):
  c=self.client();c.initialize();self.assertEqual(c.req('ping',id='string-id')['id'],'string-id');self.assertEqual(c.req('ping',id=789)['id'],789)
  c.send_raw(b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"video.metadata.read","arguments":{}}}')
  self.assertEqual(c.req('ping',id='after-notification')['id'],'after-notification')
 def test_invalid_frames_recover(self):
  c=self.client();c.initialize()
  for line in [b'{',b'[]',b'{"jsonrpc":"2.0","id":true,"method":"ping"}',b'{"jsonrpc":"2.0","id":1,"method":"ping","id":2}',b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"bad":NaN}}',b'\xff']:
   c.send_raw(line);self.assertIn('error',c.recv());self.assertEqual(c.req('ping')['result'],{})
 def test_oversized_frame_drained_once(self):
  c=self.client();c.initialize();c.send_raw(b'x'*40000);r=c.recv();self.assertEqual(r['error']['message'],'Frame too large');self.assertEqual(c.req('ping')['result'],{})
 def test_errors_and_extra_tool_fields(self):
  c=self.client();c.initialize();self.assertEqual(c.req('unknown/method')['error']['code'],-32601);self.assertIn('error',c.req('tools/call',{'name':[],'arguments':{}}));self.assertEqual(c.tool('video.reference.resolve',{'value':KNOWN,'extra':1})['status'],'rejected');self.assertEqual(c.tool('authenticate',{})['status'],'unsupported')
 def test_default_pause_blocks_metadata_but_not_pure_reference(self):
  c=self.client();c.initialize();self.assertEqual(c.metadata()['status'],'blocked');self.assertEqual(c.tool('operation.status',{'operation_id':'one'})['status'],'not_found')
 def test_known_fixture_and_unknown_target_distinct(self):
  c=self.client(ready=True);c.initialize();r=c.metadata();self.assertEqual(r['status'],'completed');self.assertFalse(r['live']);self.assertEqual(r['backend'],'fixture');self.assertIn('fixture',r['data']['title'].lower());unknown=c.metadata(UNKNOWN,'unknown');self.assertEqual(unknown['status'],'not_found');self.assertIsNone(unknown['data'])
 def test_status_and_restart_persist(self):
  c=self.client(ready=True);c.initialize();r=c.metadata();self.assertEqual(c.tool('operation.status',{'operation_id':'one'}),r);code,out,err=c.close();self.assertEqual((code,out,err),(0,b'',b''))
  d=self.client();d.initialize();self.assertEqual(d.tool('operation.status',{'operation_id':'one'}),r);self.assertEqual(d.metadata(),r)
 def test_restart_cannot_clear_pause_with_fixture_ready(self):
  c=self.client();c.initialize();self.assertTrue(c.tool('capabilities.list',{})['data']['paused']);self.assertEqual(c.close(),(0,b'',b''));d=self.client(ready=True);d.initialize();self.assertTrue(d.tool('capabilities.list',{})['data']['paused']);self.assertEqual(d.metadata()['status'],'blocked')
 def test_optional_arguments_for_empty_schema(self):
  c=self.client();c.initialize();r=c.req('tools/call',{'name':'capabilities.list'})['result']['structuredContent'];self.assertEqual(r['status'],'completed');self.assertTrue(r['data']['paused'])
  r=c.req('tools/call',{'name':'video.metadata.read'})['result']['structuredContent'];self.assertEqual(r['status'],'rejected')
 def test_meta_object_ignored_and_never_echoed(self):
  c=self.client();c.initialize();meta={'SYNTHETIC-PRIVATE-MARKER':{'name':'authenticate','arguments':{'backend':'live'},'value':'SYNTHETIC-PRIVATE-MARKER'}}
  r=c.req('tools/call',{'name':'capabilities.list','_meta':meta});self.assertEqual(r['result']['structuredContent']['status'],'completed');self.assertNotIn('SYNTHETIC-PRIVATE-MARKER',json.dumps(r))
  r=c.req('tools/call',{'name':'video.reference.resolve','arguments':{'value':KNOWN},'_meta':meta});self.assertEqual(r['result']['structuredContent']['data']['bvid'],KNOWN);self.assertNotIn('SYNTHETIC-PRIVATE-MARKER',json.dumps(r))
 def test_meta_and_argument_types_do_not_widen_business_schema(self):
  c=self.client();c.initialize()
  for value in (None,[],False,'secret',12):
   self.assertEqual(c.req('tools/call',{'name':'capabilities.list','_meta':value})['error']['code'],-32602)
   self.assertEqual(c.req('tools/call',{'name':'capabilities.list','arguments':value})['error']['code'],-32602)
  self.assertEqual(c.req('tools/call',{'name':'capabilities.list','unknown':'secret'})['error']['code'],-32602)
  r=c.req('tools/call',{'name':'capabilities.list','arguments':{'_meta':{}},'_meta':{}})['result']['structuredContent'];self.assertEqual(r['status'],'rejected')
  self.assertEqual(c.req('ping')['result'],{})
 def test_meta_cannot_change_pause_or_backend(self):
  c=self.client();c.initialize();ref=c.resolve(KNOWN)
  r=c.req('tools/call',{'name':'video.metadata.read','arguments':{'reference_id':ref,'expected_bvid':KNOWN,'operation_id':'meta-attempt','backend':'fixture'},'_meta':{'paused':False,'backend':'live','user_approved':True}})['result']['structuredContent'];self.assertEqual(r['status'],'blocked');self.assertEqual(r['backend'],'fixture');self.assertFalse(r['live']);self.assertTrue(c.tool('capabilities.list',{})['data']['paused'])
 def test_reference_not_persisted_as_authority(self):
  c=self.client(ready=True);c.initialize();ref=c.resolve(KNOWN);self.assertEqual(c.close(),(0,b'',b''));d=self.client(ready=True);d.initialize();r=d.tool('video.metadata.read',{'reference_id':ref,'expected_bvid':KNOWN,'operation_id':'not-run','backend':'fixture'});self.assertEqual(r['error'],'stale_or_wrong_target_reference')

if __name__=='__main__':unittest.main()
