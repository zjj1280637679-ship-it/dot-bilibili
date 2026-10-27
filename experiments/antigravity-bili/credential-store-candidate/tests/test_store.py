"""Synthetic file-port tests; only new temporary fake fixtures have permissions changed."""
import json,os,fcntl,socket,stat,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from credential_store import (FileCredentialStore,TrustedConfig,SecretMaterial,OpaqueHandle,StorageState,
                              MAX_SECRET_BYTES,MAX_GENERATION)
FAKE=b'FAKE_ONLY_ORIGINAL';OTHER=b'FAKE_ONLY_ROTATED';ROOT=Path(__file__).resolve().parents[1]
class StoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)
  self.store=FileCredentialStore(TrustedConfig(self.directory,'fixture-account'))
  guard=patch('socket.socket',side_effect=AssertionError('offline_network_forbidden'))
  self.sockets=guard.start();self.addCleanup(guard.stop);self.addCleanup(self.sockets.assert_not_called)
 @property
 def path(self):return self.directory/self.store._record_name
 def save(self,material=FAKE,expected=None):return self.store.save(SecretMaterial(material),expected=expected)
 def original(self):
  result=self.save();self.assertEqual(result.state,StorageState.PRESENT);return result.handle
 def read_internal(self,handle):
  seen=[];r=self.store.with_material(handle,seen.append);self.assertEqual(r.code,'material_callback_entered');return seen[0]
 def replace_fixture(self,data):
  self.path.write_bytes(data);os.chmod(self.path,0o600)
 def probe(self,mode,*args):
  return subprocess.run([sys.executable,'-B',str(ROOT/'tests/process_probe.py'),mode,str(self.directory),*args],capture_output=True,text=True,timeout=10)
 def test_missing_is_not_unavailable(self):
  self.assertEqual(self.store.inspect().state,StorageState.MISSING)
  missing=FileCredentialStore(TrustedConfig(self.directory/'absent','fixture-account'))
  self.assertEqual(missing.inspect().state,StorageState.UNKNOWN);self.assertFalse((self.directory/'absent').exists())
 def test_private_material_and_public_unverified_handle(self):
  handle=self.original();r=self.store.inspect();self.assertEqual(r.handle,handle)
  self.assertEqual(r.to_dict()['restoration_state'],'unverified');self.assertEqual(self.read_internal(handle),FAKE)
  public=json.dumps(r.to_dict())+repr(r)+repr(SecretMaterial(FAKE));self.assertNotIn('FAKE_ONLY',public)
  self.assertNotIn('material_b64',public);self.assertEqual(set(r.to_dict()['handle']),{'account_id','handle_id','generation'})
 def test_restart_new_process_recovers_material_unverified(self):
  handle=self.original();p=self.probe('restore');self.assertEqual(p.returncode,0,p.stderr)
  r=json.loads(p.stdout);self.assertEqual(r['handle'],handle.to_dict());self.assertEqual(r['restoration_state'],'unverified')
  self.assertNotIn('FAKE_ONLY',p.stdout)
 def test_minimal_file_lock_and_directory_permissions(self):
  self.original();self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode),0o700)
  for file in self.directory.iterdir():
   self.assertTrue(file.is_file());self.assertEqual(stat.S_IMODE(file.stat().st_mode),0o600);self.assertEqual(file.stat().st_nlink,1)
 def test_trusted_config_validation(self):
  for path in ('relative','/tmp/../other'):
   with self.assertRaises(ValueError):TrustedConfig(path,'fixture-account')
  for account in ('../escape','',True,'x'*129):
   with self.assertRaises(ValueError):TrustedConfig(self.directory,account)
  with self.assertRaises(ValueError):FileCredentialStore({'directory':self.directory})
 def test_material_exact_bytes_and_bounds(self):
  for data in (b'',b'x'*(MAX_SECRET_BYTES+1),'FAKE_ONLY',bytearray(b'fake')):
   with self.assertRaises(ValueError):SecretMaterial(data)
  r=self.save(b'x'*MAX_SECRET_BYTES);self.assertEqual(r.state,StorageState.PRESENT)
  self.assertEqual(len(self.read_internal(r.handle)),MAX_SECRET_BYTES);self.assertEqual(repr(SecretMaterial(FAKE)),'SecretMaterial(<redacted>)')
 def test_cas_rotation_rejects_stale_or_missing_expectation(self):
  a=self.original();b=self.save(OTHER,expected=a);self.assertEqual(b.state,StorageState.PRESENT)
  self.assertEqual(b.handle.generation,2);self.assertNotEqual(a.handle_id,b.handle.handle_id)
  self.assertEqual(self.save(expected=a).state,StorageState.CONFLICT);self.assertEqual(self.save().state,StorageState.CONFLICT)
  seen=[];self.assertEqual(self.store.with_material(a,seen.append).state,StorageState.CONFLICT);self.assertEqual(seen,[])
  self.assertEqual(self.read_internal(b.handle),OTHER)
 def test_cross_account_cannot_read_or_write(self):
  a=self.original();alien=OpaqueHandle('different-account',a.handle_id,a.generation);seen=[]
  self.assertEqual(self.store.with_material(alien,seen.append).state,StorageState.REJECTED)
  self.assertEqual(self.save(OTHER,expected=alien).state,StorageState.REJECTED)
  self.assertEqual(FileCredentialStore(TrustedConfig(self.directory,'different-account')).inspect().state,StorageState.MISSING)
  self.assertEqual(seen,[])
 def test_callback_result_not_returned_exception_not_reauth(self):
  a=self.original();r=self.store.with_material(a,lambda secret:secret)
  self.assertEqual(r.callback_entries,1);self.assertNotIn('FAKE_ONLY',json.dumps(r.to_dict()))
  def bad(secret):raise RuntimeError(secret.decode())
  r=self.store.with_material(a,bad);self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(r.callback_entries,1)
  self.assertNotIn('FAKE_ONLY',repr(r));self.assertEqual(self.store.inspect().handle,a)
 def test_corrupt_never_deleted_or_overwritten(self):
  self.original();self.replace_fixture(b'{bad_json_FAKE_ONLY');before=self.path.read_bytes()
  self.assertEqual(self.store.inspect().state,StorageState.CORRUPT);self.assertEqual(self.save().state,StorageState.CORRUPT)
  self.assertEqual(self.path.read_bytes(),before)
 def test_strict_schema_identity_checksum_duplicate_and_nonfinite(self):
  self.original();base=json.loads(self.path.read_bytes());variants=[]
  for key,value in (('generation',True),('generation',0),('generation',1.5),('generation',MAX_GENERATION+1),('account_id','other'),('material_b64','!invalid'),('material_sha256','0'*64),('verified',True)):
   obj=dict(base);obj[key]=value;variants.append(json.dumps(obj).encode())
  variants += [b'{"format":"x","format":"y"}',b'NaN',b'{"generation":1e999}',b'[]',b'\xff',b'']
  for data in variants:
   with self.subTest(data=data[:25]):self.replace_fixture(data);self.assertEqual(self.store.inspect().state,StorageState.CORRUPT)
 def test_unsafe_existing_file_permission_not_repaired(self):
  self.original();os.chmod(self.path,0o644)
  self.assertEqual(self.store.inspect().state,StorageState.UNKNOWN);self.assertEqual(self.save().state,StorageState.UNKNOWN)
  self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o644)
 def test_unsafe_directory_permission_not_repaired(self):
  self.original();os.chmod(self.directory,0o755)
  self.assertEqual(self.store.inspect().state,StorageState.UNKNOWN);self.assertEqual(self.save().state,StorageState.UNKNOWN)
  self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode),0o755)
 def test_record_symlink_hardlink_refused(self):
  self.original();other=self.directory/'other-fake';self.path.rename(other);self.path.symlink_to(other)
  self.assertEqual(self.store.inspect().state,StorageState.UNKNOWN);self.assertEqual(self.save().state,StorageState.UNKNOWN)
  self.assertTrue(self.path.is_symlink());self.path.unlink();os.link(other,self.path)
  self.assertEqual(self.store.inspect().state,StorageState.UNKNOWN);self.assertEqual(self.save().state,StorageState.UNKNOWN)
 def test_any_directory_symlink_component_refused(self):
  real=self.directory/'real';real.mkdir(mode=0o700);alias=self.directory/'alias';alias.symlink_to(real,target_is_directory=True)
  self.assertEqual(FileCredentialStore(TrustedConfig(alias,'fixture-account')).inspect().state,StorageState.UNKNOWN)
  nested=real/'nested';nested.mkdir(mode=0o700)
  self.assertEqual(FileCredentialStore(TrustedConfig(alias/'nested','fixture-account')).inspect().state,StorageState.UNKNOWN)
 def test_lock_symlink_never_touches_target(self):
  target=self.directory/'other-fake';target.write_bytes(OTHER);os.chmod(target,0o600)
  (self.directory/self.store._lock_name).symlink_to(target)
  self.assertEqual(self.save().state,StorageState.UNKNOWN);self.assertEqual(target.read_bytes(),OTHER);self.assertFalse(self.path.exists())
 def test_fifo_refused_without_blocking(self):
  os.mkfifo(self.path,0o600);self.assertEqual(self.store.inspect().state,StorageState.UNKNOWN)
 def test_io_unknown_preserves_record_no_raw_error(self):
  a=self.original();before=self.path.read_bytes()
  with patch('credential_store.os.read',side_effect=OSError('FAKE_ONLY_SECRET_ERROR')):
   r=self.store.inspect();s=self.save(OTHER,expected=a)
  self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(s.state,StorageState.UNKNOWN)
  self.assertNotIn('FAKE_ONLY',repr(r));self.assertEqual(self.path.read_bytes(),before)
 def test_file_fsync_failure_keeps_old_and_cleans_own_temp(self):
  a=self.original();before=self.path.read_bytes()
  with patch('credential_store.os.fsync',side_effect=OSError('FAKE_ONLY_FSYNC')):r=self.save(OTHER,expected=a)
  self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(r.write_outcome,'not_committed')
  self.assertEqual(self.path.read_bytes(),before);self.assertEqual(list(self.directory.glob('.*.tmp-*')),[])
 def test_replace_uncertainty_no_false_success_no_retry(self):
  a=self.original();original=os.replace;calls=[]
  def uncertain(*args,**kw):calls.append(1);original(*args,**kw);raise OSError('FAKE_ONLY_POST_RENAME')
  with patch('credential_store.os.replace',side_effect=uncertain):r=self.save(OTHER,expected=a)
  self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(r.write_outcome,'unknown');self.assertEqual(len(calls),1)
  observed=self.store.inspect();self.assertEqual(observed.handle.generation,2);self.assertEqual(self.read_internal(observed.handle),OTHER)
 def test_directory_fsync_unknown_preserves_observed_new_record(self):
  a=self.original();original=os.fsync
  def faildir(fd):
   if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('FAKE_ONLY_DIR_FSYNC')
   return original(fd)
  with patch('credential_store.os.fsync',side_effect=faildir):r=self.save(OTHER,expected=a)
  self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(r.write_outcome,'unknown');self.assertEqual(self.store.inspect().handle.generation,2)
 def test_short_writes_completed_before_replace(self):
  original=os.write;calls=[]
  def short(fd,data):calls.append(1);return original(fd,data[:7])
  with patch('credential_store.os.write',side_effect=short):a=self.original()
  self.assertGreater(len(calls),1);self.assertEqual(self.read_internal(a),FAKE)
 def test_busy_lock_unknown_without_retry(self):
  a=self.original();fd=os.open(self.directory/self.store._lock_name,os.O_RDWR)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);r=self.save(OTHER,expected=a)
   self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(r.code,'store_busy')
  finally:os.close(fd)
  self.assertEqual(self.read_internal(a),FAKE)
 def test_internal_use_binds_generation_and_blocks_rotation(self):
  a=self.original();inside=[]
  r=self.store.with_material(a,lambda data:inside.append(self.save(OTHER,expected=a)))
  self.assertEqual(r.callback_entries,1);self.assertEqual(inside[0].code,'store_busy')
  self.assertEqual(self.save(OTHER,expected=a).state,StorageState.PRESENT)
 def test_fresh_process_concurrent_cas_only_one_winner(self):
  a=self.original();args=[sys.executable,'-B',str(ROOT/'tests/process_probe.py'),'rotate',str(self.directory),json.dumps(a.to_dict())]
  children=[subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
  try:
   for child in children:self.assertEqual(child.stdout.readline().strip(),'ready')
   for child in children:child.stdin.write('go\n');child.stdin.flush()
   results=[]
   for child in children:
    out,err=child.communicate(timeout=10);self.assertEqual(child.returncode,0,err);results.append(json.loads(out))
   self.assertEqual(sum(r['state']=='present' for r in results),1)
   self.assertTrue(all(r['state'] in ('present','conflict','unknown') for r in results));self.assertEqual(self.store.inspect().handle.generation,2)
  finally:
   for child in children:
    if child.poll() is None:child.kill();child.wait()
 def test_child_crash_before_replace_keeps_old(self):
  a=self.original();p=self.probe('crash-before-replace',json.dumps(a.to_dict()))
  self.assertEqual(p.returncode,71);self.assertEqual(self.store.inspect().handle,a);self.assertEqual(self.read_internal(a),FAKE)
  for orphan in self.directory.glob('.*.tmp-*'):self.assertEqual(stat.S_IMODE(orphan.stat().st_mode),0o600)
 def test_child_crash_after_replace_complete_new_unverified(self):
  a=self.original();p=self.probe('crash-after-replace',json.dumps(a.to_dict()));self.assertEqual(p.returncode,72)
  r=self.store.inspect();self.assertEqual(r.state,StorageState.PRESENT);self.assertEqual(r.handle.generation,2)
  self.assertEqual(r.to_dict()['restoration_state'],'unverified');self.assertEqual(self.read_internal(r.handle),OTHER)
 def test_no_persisted_auth_or_lease_fields(self):
  self.original();data=json.loads(self.path.read_bytes())
  self.assertEqual(set(data),{'format','account_id','handle_id','generation','material_b64','material_sha256'})
 def test_generation_exhausted_keeps_record(self):
  self.original();data=json.loads(self.path.read_bytes());data['generation']=MAX_GENERATION;self.replace_fixture(json.dumps(data).encode())
  a=self.store.inspect().handle;before=self.path.read_bytes();self.assertEqual(self.save(OTHER,expected=a).code,'generation_exhausted')
  self.assertEqual(self.path.read_bytes(),before)
 def test_zero_write_keeps_old_and_cleans_owned_temp(self):
  a=self.original();before=self.path.read_bytes()
  with patch('credential_store.os.write',return_value=0):r=self.save(OTHER,expected=a)
  self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(r.write_outcome,'not_committed')
  self.assertEqual(self.path.read_bytes(),before);self.assertEqual(list(self.directory.glob('.*.tmp-*')),[])
 def test_oversized_and_deep_json_are_corrupt_not_exceptions(self):
  self.original()
  for raw in (b'x'*100001,b'['*1500+b'0'+b']'*1500):
   self.replace_fixture(raw);self.assertEqual(self.store.inspect().state,StorageState.CORRUPT)
 def test_external_removal_does_not_make_old_handle_valid_again(self):
  old=self.original();self.path.unlink();new=self.original()
  self.assertEqual(new.generation,1);self.assertNotEqual(new.handle_id,old.handle_id)
  self.assertEqual(self.store.with_material(old,lambda secret:None).state,StorageState.CONFLICT)
 def test_temp_collision_does_not_delete_preexisting_file(self):
  temp=self.directory/('.'+self.store._record_name+'.tmp-'+'b'*32)
  temp.write_bytes(b'FAKE_ONLY_PREEXISTING');os.chmod(temp,0o600)
  with patch('credential_store.secrets.token_hex',side_effect=['a'*32,'b'*32]):r=self.save()
  self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(temp.read_bytes(),b'FAKE_ONLY_PREEXISTING')
  self.assertFalse(self.path.exists())
 def test_callback_cleanup_failure_preserves_entry_count(self):
  a=self.original();original=fcntl.flock
  def fail_unlock(fd,operation):
   if operation==fcntl.LOCK_UN:raise OSError('FAKE_ONLY_UNLOCK')
   return original(fd,operation)
  with patch('credential_store.fcntl.flock',side_effect=fail_unlock):r=self.store.with_material(a,lambda secret:None)
  self.assertEqual(r.state,StorageState.UNKNOWN);self.assertEqual(r.callback_entries,1)
  self.assertNotIn('FAKE_ONLY',repr(r));self.assertEqual(self.store.inspect().handle,a)
 def test_constructor_no_io_and_rejected_input_no_write(self):
  self.assertEqual(list(self.directory.iterdir()),[])
  self.assertEqual(self.store.save(b'FAKE_ONLY_NOT_WRAPPED',expected=None).state,StorageState.REJECTED)
  self.assertEqual(self.store.save(SecretMaterial(FAKE),expected=True).state,StorageState.REJECTED)
  self.assertEqual(list(self.directory.iterdir()),[])
if __name__=='__main__':unittest.main()
