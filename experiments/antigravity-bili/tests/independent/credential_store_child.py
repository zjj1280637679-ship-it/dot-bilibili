"""Synthetic isolated-process probe. Material is fixed in code, never in argv/output."""
import importlib.util,json,os,sys
from pathlib import Path
source,directory,mode,*extra=sys.argv[1:]
spec=importlib.util.spec_from_file_location('review_store_child',source);s=importlib.util.module_from_spec(spec);sys.modules[spec.name]=s;spec.loader.exec_module(s)
def guard(event,args):
 if event.startswith('socket.'):raise AssertionError('network_forbidden')
sys.addaudithook(guard)
f=s.FileCredentialStore(s.TrustedConfig(Path(directory),'independent-account'))
expected=None if not extra else s.OpaqueHandle(**json.loads(extra[0]))
if mode=='inspect':
 r=f.inspect()
 if r.handle:
  def consume(raw):
   if raw not in (b'FAKE_ONLY_INDEPENDENT_ORIGINAL_1907',b'FAKE_ONLY_INDEPENDENT_ROTATED_1907'):raise AssertionError('unexpected_synthetic_material')
  used=f.with_material(r.handle,consume)
  if used.callback_entries!=1:raise SystemExit(8)
 print(json.dumps(r.to_dict()))
elif mode=='hold_use':
 def consume(raw):
  print('callback_entered',flush=True);sys.stdin.readline()
  return raw
 print(json.dumps(f.with_material(expected,consume).to_dict()))
else:
 if mode=='hold_create':
  write=os.write;held=False
  def hold(fd,data):
   global held
   if not held:held=True;print('write_entered',flush=True);sys.stdin.readline()
   return write(fd,data)
  os.write=hold
 elif mode=='crash_partial':
  write=os.write
  def partial(fd,data):write(fd,data[:11]);os._exit(73)
  os.write=partial
 elif mode=='crash_replaced':
  replace=os.replace
  def replaced(*args,**kwargs):replace(*args,**kwargs);os._exit(74)
  os.replace=replaced
 elif mode!='save':raise SystemExit(9)
 value=b'FAKE_ONLY_INDEPENDENT_ORIGINAL_1907' if expected is None else b'FAKE_ONLY_INDEPENDENT_ROTATED_1907'
 print(json.dumps(f.save(s.SecretMaterial(value),expected=expected).to_dict()))
