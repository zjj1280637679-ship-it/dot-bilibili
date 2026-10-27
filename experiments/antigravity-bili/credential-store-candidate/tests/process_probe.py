"""Only fixed synthetic material; no credential bytes in arguments or output."""
import json,os,socket,stat,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from credential_store import FileCredentialStore,TrustedConfig,SecretMaterial,OpaqueHandle

def no_socket(*a,**k):raise AssertionError('offline_network_forbidden')
socket.socket=no_socket
store=FileCredentialStore(TrustedConfig(Path(sys.argv[2]),'fixture-account'))
mode=sys.argv[1]
if mode=='restore':
    result=store.inspect()
    if result.handle:
        def verify(payload):
            if payload!=b'FAKE_ONLY_ORIGINAL':raise AssertionError('wrong_fixture')
        used=store.with_material(result.handle,verify)
        if used.callback_entries!=1 or used.code!='material_callback_entered':raise SystemExit(4)
    print(json.dumps(result.to_dict()))
elif mode in ('rotate','crash-before-replace','crash-after-replace'):
    handle=OpaqueHandle(**json.loads(sys.argv[3]))
    if mode=='rotate':
        print('ready',flush=True);sys.stdin.readline()
    if mode=='crash-before-replace':os.replace=lambda *a,**k:os._exit(71)
    if mode=='crash-after-replace':
        original=os.fsync
        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):os._exit(72)
            return original(fd)
        os.fsync=fsync
    print(json.dumps(store.save(SecretMaterial(b'FAKE_ONLY_ROTATED'),expected=handle).to_dict()))
else:raise SystemExit(3)
