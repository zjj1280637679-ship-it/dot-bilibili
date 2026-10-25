#!/usr/bin/env python3
"""Offline staged 0.3.1 build and isolated smoke; never uses a live binding."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd):
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel-dir', help='optional directory to retain built wheel')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='bili-offline-package-') as tmp:
        base = Path(tmp)
        stage = base / 'source'
        stage.mkdir()
        for name in ('bili_bridge', 'facade', 'bili_integration'):
            shutil.copytree(ROOT / name, stage / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (stage / 'scripts').mkdir()
        for name in ('read_workflow.py', 'browser_host_exchange.py'):
            shutil.copyfile(ROOT / 'scripts' / name, stage / 'scripts' / name)
        resources = stage / 'bili_integration/resources'
        resources.mkdir()
        for folder, names in [('docs', ['read-workflow.md', 'host-capture-recipes.md',
                                        'browser-host-contract.md', 'installable-integration.md']),
                              ('scripts', ['host_capture_recipes.js', 'host_projection_recipe.js'])]:
            for name in names:
                shutil.copyfile(ROOT / folder / name, resources / name)
        shutil.copyfile(ROOT / 'integration_dist/pyproject.toml', stage / 'pyproject.toml')
        shutil.copyfile(ROOT / 'LICENSE', stage / 'LICENSE')
        wheels = base / 'wheels'
        run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-build-isolation',
             '--no-deps', str(stage), '-w', str(wheels)], base)
        wheel = next(wheels.glob('*.whl'))
        env = base / 'venv'
        venv.create(env, with_pip=True)
        python = str(env / 'bin/python')
        run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], base)
        source_digest = run([sys.executable, '-c',
                             'from facade.adapter import workflow; print(workflow.source_digest())'], ROOT).strip()
        smoke = r'''
import hashlib,json,tempfile
from pathlib import Path
import facade,bili_integration,bili_bridge
from facade import HostProfile, search_read, status
from facade.adapter import ROOT, workflow
from bili_integration.cli import diagnostics,instructions
for package in [facade,bili_integration,bili_bridge]:
 assert '/site-packages/' in package.__file__, package.__file__
assert diagnostics()['runtime_assets_present']
assert all(Path(p).is_file() for p in instructions()['resources'].values())
with tempfile.TemporaryDirectory(prefix='bili-synthetic-state-') as d:
 p=HostProfile(d+'/state.sqlite3',d+'/spool','https://www.bilibili.com/','synthetic-offline',1)
 args={'query':'synthetic offline','select':'first_visible'}
 result=search_read(args,profile=p,invocation_id='synthetic-stable-id')
 assert result['status']=='unknown', result
 def snapshot():
  return {str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path(d).rglob('*') if f.is_file()}
 before=snapshot()
 assert search_read(args,profile=p,invocation_id='synthetic-stable-id')==result
 assert status({'request_id':result['request_id']},profile=p)==result
 assert snapshot()==before
 # The frozen absolute source-root conflict must remain fail-closed.
 state=next(Path(d+'/state.sqlite3.workflows').glob('fr-*.json'))
 record=json.loads(state.read_text()); record['intent']['source_root']='/synthetic/old-checkout'
 state.write_text(json.dumps(record)); before=snapshot()
 assert status({'request_id':result['request_id']},profile=p)['error']['code']=='state_unavailable'
 assert search_read(args,profile=p,invocation_id='synthetic-stable-id')['status']=='unknown'
 assert snapshot()==before
print(json.dumps({'installed_source_digest':workflow.source_digest(),'origin_checked':True,
 'fail_closed_no_host':True,'same_id_no_replay':True,'status_read_only':True,
 'relocation_conflict_preserved':True,'installed_resource_paths_present':True}))
'''
        result = json.loads(run([python, '-c', smoke], base))
        assert result['installed_source_digest'] == source_digest
        for name, arguments in [('bili-tools', ['diagnose']), ('bili-tools', ['schemas']),
                                 ('bili-tools', ['instructions']), ('bili-bridge', ['--help'])]:
            run([str(env / 'bin' / name), *arguments], base)
        if args.wheel_dir:
            dest = Path(args.wheel_dir).resolve()
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wheel, dest / wheel.name)
            result['wheel'] = str(dest / wheel.name)
        result['ok'] = True
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
