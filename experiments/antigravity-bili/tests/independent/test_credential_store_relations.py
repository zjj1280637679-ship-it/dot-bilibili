"""Independent POSIX credential-file contract tests; temporary FAKE_ONLY material."""
import contextlib,hashlib,importlib.util,io,json,os,pathlib,stat,subprocess,sys,tempfile,unittest
from unittest.mock import patch
OUT=pathlib.Path(__file__).resolve().parent;ROOT=OUT.parents[1]
SOURCE=ROOT/'credential-store-candidate/credential_store.py';SHA=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
_snapshot_tmp=tempfile.TemporaryDirectory(prefix='bili-store-review-');SNAP=pathlib.Path(_snapshot_tmp.name)/('credential_store-'+SHA[:16]+'.py');SNAP.write_bytes(SOURCE.read_bytes())
spec=importlib.util.spec_from_file_location('independent_credential_store',SNAP);s=importlib.util.module_from_spec(spec);sys.modules[spec.name]=s;spec.loader.exec_module(s)
FAKE=b'FAKE_ONLY_INDEPENDENT_ORIGINAL_1907';ROTATED=b'FAKE_ONLY_INDEPENDENT_ROTATED_1907';ACCOUNT='independent-account'
def guard(event,args):
 if event.startswith('socket.'):raise AssertionError('independent_network_forbidden')
sys.addaudithook(guard)
class IndependentStore(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='bili-credential-review-');self.addCleanup(self.tmp.cleanup)
  self.path=pathlib.Path(self.tmp.name);self.store=s.FileCredentialStore(s.TrustedConfig(self.path,ACCOUNT));self.record=self.path/self.store._record_name
 def save(self,expected=None,material=FAKE):return self.store.save(s.SecretMaterial(material),expected=expected)
 def original(self):
  r=self.save();self.assertEqual(r.state,s.StorageState.PRESENT);self.assertEqual(r.write_outcome,'committed');return r.handle
 def secret(self,h):
  collected=[];r=self.store.with_material(h,collected.append);self.assertEqual(r.callback_entries,1);return collected[0]
 def child(self,mode,expected=None,interactive=False):
  args=[sys.executable,'-B',str(OUT/'credential_store_child.py'),str(SNAP),str(self.path),mode]
  if expected is not None:args.append(json.dumps(expected.to_dict()))
  env={'PATH':str(pathlib.Path(sys.executable).parent),'HOME':self.tmp.name,'LANG':'C.UTF-8'}
  if interactive:
   p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
   def cleanup():
    if p.poll() is None:p.kill();p.wait()
   self.addCleanup(cleanup);return p
  return subprocess.run(args,capture_output=True,text=True,env=env,timeout=6)
 def test_receipts_repr_errors_callback_returns_do_not_expose_material(self):
  captured=io.StringIO()
  with contextlib.redirect_stdout(captured),contextlib.redirect_stderr(captured):
   h=self.original();receipt=self.store.with_material(h,lambda raw: {'secret':raw})
   def fail(raw):raise RuntimeError(raw.decode())
   failure=self.store.with_material(h,fail)
  public=repr(receipt)+repr(failure)+repr(s.SecretMaterial(FAKE))+json.dumps(receipt.to_dict())+json.dumps(failure.to_dict())+captured.getvalue()
  self.assertNotIn('FAKE_ONLY',public);self.assertNotIn('material_b64',public)
  self.assertEqual(failure.code,'consumer_outcome_unknown');self.assertEqual(failure.callback_entries,1);self.assertEqual(self.store.inspect().handle,h)
 def test_cross_process_restore_only_unverified_handle(self):
  h=self.original();p=self.child('inspect');self.assertEqual(p.returncode,0,p.stderr)
  r=json.loads(p.stdout);self.assertEqual(r['handle'],h.to_dict());self.assertEqual(r['restoration_state'],'unverified');self.assertNotIn('FAKE_ONLY',p.stdout+p.stderr)
 def test_initial_create_competition_one_commit_no_auto_retry(self):
  first=self.child('hold_create',interactive=True);self.assertEqual(first.stdout.readline().strip(),'write_entered')
  second=self.child('save');self.assertEqual(second.returncode,0,second.stderr);r=json.loads(second.stdout);self.assertEqual(r['code'],'store_busy');self.assertEqual(r['write_outcome'],'not_attempted')
  first.stdin.write('release\n');first.stdin.flush();out,err=first.communicate(timeout=6);self.assertEqual(first.returncode,0,err);winner=json.loads(out)
  self.assertEqual(winner['state'],'present');self.assertEqual(winner['handle']['generation'],1)
  late=self.child('save');self.assertEqual(json.loads(late.stdout)['state'],'conflict');self.assertEqual(self.store.inspect().handle.generation,1)
 def test_shared_material_use_prevents_cross_process_rotation(self):
  h=self.original();reader=self.child('hold_use',h,interactive=True);self.assertEqual(reader.stdout.readline().strip(),'callback_entered')
  writer=self.child('save',h);r=json.loads(writer.stdout);self.assertEqual(r['state'],'unknown');self.assertEqual(r['code'],'store_busy');self.assertEqual(self.store.inspect().handle,h)
  reader.stdin.write('release\n');reader.stdin.flush();out,err=reader.communicate(timeout=6);self.assertEqual(reader.returncode,0,err);self.assertEqual(json.loads(out)['callback_entries'],1)
  after=self.child('save',h);self.assertEqual(json.loads(after.stdout)['state'],'present');self.assertEqual(self.store.inspect().handle.generation,2)
 def test_exact_handle_cas_and_account_namespace(self):
  a=self.original();wrong=s.OpaqueHandle(ACCOUNT,'0'*32,a.generation);self.assertEqual(self.save(wrong).state,s.StorageState.CONFLICT)
  wronggen=s.OpaqueHandle(ACCOUNT,a.handle_id,a.generation+1);self.assertEqual(self.save(wronggen).state,s.StorageState.CONFLICT)
  other=s.FileCredentialStore(s.TrustedConfig(self.path,'other-account'));o=other.save(s.SecretMaterial(ROTATED),expected=None);self.assertEqual(o.state,s.StorageState.PRESENT)
  self.assertNotEqual(self.store._record_name,other._record_name);self.assertEqual(self.secret(a),FAKE)
  self.assertEqual(self.store.with_material(o.handle,lambda _:self.fail('must_not_enter')).state,s.StorageState.REJECTED)
 def test_io_unknown_and_corrupt_both_preserve_bytes_without_overwrite(self):
  h=self.original();before=self.record.read_bytes()
  with patch.object(s.os,'read',side_effect=OSError('FAKE_ONLY_IO_DETAIL')):
   r=self.store.inspect();w=self.save(h,ROTATED)
  self.assertEqual(r.state,s.StorageState.UNKNOWN);self.assertEqual(w.state,s.StorageState.UNKNOWN);self.assertEqual(self.record.read_bytes(),before)
  self.record.write_bytes(b'{"bad":"FAKE_ONLY_CORRUPT"}');bad=self.record.read_bytes()
  self.assertEqual(self.store.inspect().state,s.StorageState.CORRUPT);self.assertEqual(self.save(h,ROTATED).state,s.StorageState.CORRUPT);self.assertEqual(self.record.read_bytes(),bad)
 def test_known_precommit_zero_write_preserves_old_cleans_own_temp(self):
  h=self.original();before=self.record.read_bytes()
  with patch.object(s.os,'write',return_value=0) as write:r=self.save(h,ROTATED)
  self.assertEqual(write.call_count,1);self.assertEqual(r.write_outcome,'not_committed');self.assertEqual(r.state,s.StorageState.UNKNOWN);self.assertEqual(self.record.read_bytes(),before);self.assertFalse(list(self.path.glob('.*.tmp-*')))
 def test_replace_failure_is_conservatively_unknown_then_explicit_inspect(self):
  h=self.original();before=self.record.read_bytes()
  with patch.object(s.os,'replace',side_effect=OSError('FAKE_ONLY_REPLACE_DETAIL')) as replace:r=self.save(h,ROTATED)
  self.assertEqual(replace.call_count,1);self.assertEqual(r.write_outcome,'unknown');self.assertIsNone(r.handle);self.assertEqual(self.record.read_bytes(),before);self.assertEqual(self.store.inspect().handle,h)
 def test_replace_success_then_error_retains_new_but_receipt_unknown(self):
  h=self.original();real=s.os.replace
  def uncertain(*a,**kw):real(*a,**kw);raise OSError('FAKE_ONLY_POST_REPLACE')
  with patch.object(s.os,'replace',side_effect=uncertain) as replace:r=self.save(h,ROTATED)
  self.assertEqual(replace.call_count,1);self.assertEqual(r.write_outcome,'unknown');new=self.store.inspect();self.assertEqual(new.handle.generation,2);self.assertEqual(self.secret(new.handle),ROTATED);self.assertEqual(self.save(h).state,s.StorageState.CONFLICT)
 def test_partial_write_process_crash_keeps_complete_old_record(self):
  h=self.original();before=self.record.read_bytes();p=self.child('crash_partial',h);self.assertEqual(p.returncode,73);self.assertEqual(self.record.read_bytes(),before);self.assertEqual(self.store.inspect().handle,h)
  remnants=list(self.path.glob('.*.tmp-*'));self.assertTrue(remnants)
  for file in remnants:self.assertEqual(stat.S_IMODE(file.stat().st_mode),0o600)
 def test_crash_after_replace_restores_complete_new_unverified(self):
  h=self.original();p=self.child('crash_replaced',h);self.assertEqual(p.returncode,74);observed=self.store.inspect();self.assertEqual(observed.handle.generation,2);self.assertEqual(observed.to_dict()['restoration_state'],'unverified');self.assertEqual(self.secret(observed.handle),ROTATED)
  self.assertEqual(self.store.with_material(h,lambda _:self.fail('stale')).state,s.StorageState.CONFLICT)
 def test_first_save_partial_crash_leaves_missing_not_corrupt_authority(self):
  p=self.child('crash_partial');self.assertEqual(p.returncode,73);r=self.store.inspect();self.assertEqual(r.state,s.StorageState.MISSING);self.assertIsNone(r.handle)
  # Explicit fresh save is allowed; the store itself never retried or scanned.
  self.assertEqual(self.save().handle.generation,1)
 def test_lock_hardlink_refused_without_mutating_target(self):
  h=self.original();lock=self.path/self.store._lock_name;copy=self.path/'hardlink-fixture';os.link(lock,copy);before=self.record.read_bytes()
  r=self.save(h,ROTATED);self.assertEqual(r.state,s.StorageState.UNKNOWN);self.assertEqual(r.code,'unsafe_file_boundary');self.assertEqual(self.record.read_bytes(),before);self.assertEqual(lock.stat().st_nlink,2)
 def test_existing_unsafe_permissions_never_repaired(self):
  h=self.original();os.chmod(self.record,0o640)
  with patch.object(s.os,'fchmod',wraps=s.os.fchmod) as chmod:r=self.save(h,ROTATED)
  self.assertEqual(r.state,s.StorageState.UNKNOWN);chmod.assert_not_called();self.assertEqual(stat.S_IMODE(self.record.stat().st_mode),0o640)
  os.chmod(self.path,0o750);self.assertEqual(self.store.inspect().state,s.StorageState.UNKNOWN);self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o750)
 def test_symlink_ancestor_and_record_do_not_touch_outside_target(self):
  actual=self.path/'actual';actual.mkdir(mode=0o700);alias=self.path/'alias';alias.symlink_to(actual,target_is_directory=True)
  linked=s.FileCredentialStore(s.TrustedConfig(alias,ACCOUNT));self.assertEqual(linked.save(s.SecretMaterial(FAKE),expected=None).state,s.StorageState.UNKNOWN);self.assertEqual(list(actual.iterdir()),[])
  target=self.path/'target-fixture';target.write_bytes(ROTATED);os.chmod(target,0o600);self.record.symlink_to(target)
  self.assertEqual(self.save().state,s.StorageState.UNKNOWN);self.assertEqual(target.read_bytes(),ROTATED);self.assertTrue(self.record.is_symlink())
 def test_nonregular_record_refused_without_hang(self):
  self.record.mkdir(mode=0o700);self.assertEqual(self.store.inspect().state,s.StorageState.UNKNOWN);self.assertEqual(self.save().state,s.StorageState.UNKNOWN);self.assertTrue(self.record.is_dir())
 def test_unsafe_serialized_record_never_promotes_or_overwrites(self):
  self.original();original=json.loads(self.record.read_bytes())
  variants=[]
  for key,value in [('account_id','other-account'),('generation',True),('generation',float('inf')),('material_sha256','bad'),('verified',True)]:
   data=dict(original);data[key]=value;variants.append(json.dumps(data).encode())
  variants.append(b'['*1200+b']'*1200)
  for raw in variants:
   with self.subTest(raw_length=len(raw)):
    self.record.write_bytes(raw);r=self.store.inspect();self.assertEqual(r.state,s.StorageState.CORRUPT);self.assertIsNone(r.handle);self.assertEqual(self.save().state,s.StorageState.CORRUPT);self.assertEqual(self.record.read_bytes(),raw)
 def test_config_and_handle_reject_ambiguous_identity_or_generation(self):
  for account in ('../outside','fixture/account',True,''):
   with self.assertRaises(ValueError):s.TrustedConfig(self.path,account)
  for generation in (True,0,-1,1.0,'1'):
   with self.assertRaises(ValueError):s.OpaqueHandle(ACCOUNT,'0'*32,generation)
  self.assertEqual(self.store.save(FAKE,expected=None).state,s.StorageState.REJECTED);self.assertFalse(self.record.exists())
if __name__=='__main__':unittest.main()
