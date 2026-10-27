"""Run isolated offline test processes; never enable a real transport."""
from pathlib import Path
import os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
commands=[
 (ROOT,['-m','unittest','discover','-s','minimal_slice_vnext/tests','-v']),
 (ROOT/'metadata-adapter-candidate',['-m','unittest','discover','-s','tests','-v']),
 (ROOT,['-m','unittest','discover','-s','next_phase','-t','.','-p','test*.py','-v']),
 (ROOT/'credential-store-candidate',['-m','unittest','discover','-s','tests','-v']),
]
commands += [(ROOT,[str(p.relative_to(ROOT)),'-v']) for p in sorted((ROOT/'tests/independent').glob('test_*.py'))]
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
for cwd,args in commands:
 print('\n=== '+str(cwd.relative_to(ROOT))+' : '+ ' '.join(args)+' ===',flush=True)
 result=subprocess.run([sys.executable,'-B',*args],cwd=cwd,env=env)
 if result.returncode:raise SystemExit(result.returncode)
print('\nAll isolated offline suites passed; this does not establish live acceptance.',flush=True)
