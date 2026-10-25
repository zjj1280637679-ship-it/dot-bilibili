#!/usr/bin/env python3
"""Offline allowlisted 0.3.3 candidate build and resource-relation/installed runtime checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('SOURCE_DATE_EPOCH', '1792886400')
sys.path.insert(0, str(ROOT))
from bili_distribution.resources_v033 import RESOURCE_FILES, check_closure


def run(command, cwd):
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout


def stage_runtime(stage):
    """Finite allowlist only. Source tree traversal is never a copy instruction."""
    check_closure(ROOT)
    manifest = ROOT / 'integration_dist/v033/runtime-files.json'
    paths = json.loads(manifest.read_text())
    if not isinstance(paths, list) or len(paths) != len(set(paths)):
        raise ValueError('invalid_runtime_manifest')
    for relative in paths:
        source = ROOT / relative
        if (not isinstance(relative, str) or Path(relative).is_absolute()
                or '..' in Path(relative).parts or source.is_symlink() or not source.is_file()):
            raise ValueError('invalid_runtime_file')
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    resources = stage / 'bili_distribution/resources'
    for relative in RESOURCE_FILES:
        target = resources / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    check_closure(resources)
    shutil.copyfile(ROOT / 'integration_dist/v033/pyproject.toml', stage / 'pyproject.toml')
    return paths


SMOKE = r'''
import hashlib,json,tempfile,subprocess,sys
from pathlib import Path
import facade,bili_integration,bili_bridge,bili_video_reference,bili_distribution
from facade import HostProfile, search_read, status
from facade.adapter import workflow
from bili_distribution.resources_v033 import check_closure
from bili_distribution.current_cli import instructions
from bili_distribution.capture import instructions as video_instructions
from scripts.compose_host_capture_v3 import compose
for package in [facade,bili_integration,bili_bridge,bili_video_reference,bili_distribution]:
 assert '/site-packages/' in package.__file__, package.__file__
closure=check_closure()
for view in [instructions(),video_instructions()]:
 assert all(Path(p).is_file() for p in view['resources'].values()),view
legacy=instructions(); video=video_instructions()
assert legacy['recipe_version']=='host-capture-v3'
assert Path(legacy['resources']['capture_protocol']).name=='host-capture-recipes-v033.md'
assert Path(legacy['resources']['capture_recipe']).name=='host_capture_recipes_v3.js'
assert Path(legacy['resources']['projection_recipe']).name=='host_projection_recipe.js'
assert video['recipe_version']=='host-capture-v3'
assert Path(video['resources']['capture_protocol']).name=='host-capture-recipes-v033.md'
assert compose().startswith('(args) =>')
assert legacy['components']==video['components']
assert len(legacy['components'])==4
assert hashlib.sha256(compose().encode()).hexdigest()==legacy['composed_function_sha256']=='cec9e3b20fe9f2331de33ef286bc114b9afe4f14e68f620b0b5558dde8f95a60'
for component in legacy['components']:
 assert hashlib.sha256(Path(component['path']).read_bytes()).hexdigest()==component['sha256']
from bili_distribution.current_cli import tool_main
from bili_distribution.video_cli import main as video_main
from unittest.mock import patch
with patch('bili_integration.cli.main',return_value=17) as port:
 assert tool_main(['schemas'])==17
 port.assert_called_once_with(['schemas'])
with patch('bili_video_reference.cli.main',return_value=18) as port:
 assert video_main(['schemas'])==18
 port.assert_called_once_with(['schemas'])
from bili_video_reference.cli import instructions as historical_video
from bili_distribution.cli import instructions as historical_search
assert historical_video()['recipe_version']=='host-capture-v2'
assert historical_search()['recipe_version']=='host-capture-v1'

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
 profile=Path(d)/'profile.json'
 profile.write_text(json.dumps(dict(db=p.db,spool=p.spool,source_url=p.source_url,tab=p.tab,timeout=p.timeout)))
 profile.chmod(0o600)
 before=snapshot()
 payload=json.dumps({'tool':'bili_status','arguments':{'request_id':result['request_id']}})
 output=subprocess.check_output([sys.executable,'-m','bili_integration.cli','call','--profile',str(profile)],input=payload,text=True)
 assert json.loads(output)==result
 assert snapshot()==before
 state=next(Path(d+'/state.sqlite3.workflows').glob('fr-*.json'))
 record=json.loads(state.read_text()); record['intent']['source_root']='/synthetic/old-checkout'
 state.write_text(json.dumps(record)); before=snapshot()
 assert status({'request_id':result['request_id']},profile=p)['error']['code']=='state_unavailable'
 assert search_read(args,profile=p,invocation_id='synthetic-stable-id')['status']=='unknown'
 assert snapshot()==before
with tempfile.TemporaryDirectory(prefix='bili-video-nohost-') as d:
 profile=Path(d)/'profile.json'
 profile.write_text(json.dumps(dict(db=d+'/state.sqlite3',spool=d+'/spool',source_url='https://www.bilibili.com/',tab='synthetic-tab',timeout=1)))
 profile.chmod(0o600)
 payload=json.dumps({'tool':'bili_read_video','arguments':{'video':'BV1234567890'}})
 args=[sys.executable,'-m','bili_distribution.video_cli','call','--profile',str(profile),'--invocation-id','synthetic-video-nohost']
 result=json.loads(subprocess.check_output(args,input=payload,text=True))
 assert result['status']=='unknown',result
 assert json.loads(subprocess.check_output(args,input=payload,text=True))==result
 views=[json.loads(subprocess.check_output([sys.executable,'-m',m,'instructions'],text=True))
        for m in ('bili_distribution.current_cli','bili_distribution.video_cli')]
 assert views[0]==views[1]
print(json.dumps({'installed_source_digest':workflow.source_digest(),'origin_checked':True,
 'both_read_routes_nohost_fail_closed':True,'normal_module_instructions_identical':True,
 'fail_closed_no_host':True,'same_id_no_replay':True,'status_read_only':True,
 'relocation_conflict_preserved':True,'installed_resource_closure':closure,
 'shared_v3_mapping_checked':True,'historical_v1_v2_routes_retained':True}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel-dir', help='optional output directory for wheel')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='bili-v033-candidate-offline-') as tmp:
        base = Path(tmp)
        stage = base / 'source'
        stage.mkdir()
        manifest = stage_runtime(stage)
        wheels = base / 'wheels'
        run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-build-isolation',
             '--no-deps', str(stage), '-w', str(wheels)], base)
        wheel = next(wheels.glob('*.whl'))
        with zipfile.ZipFile(wheel) as archive:
            expected_files = set(manifest) - {'LICENSE'}
            expected_files.update('bili_distribution/resources/' + p for p in RESOURCE_FILES)
            actual_files = {p for p in archive.namelist() if '.dist-info/' not in p}
            assert actual_files == expected_files, (actual_files - expected_files, expected_files - actual_files)
            for relative in expected_files:
                assert archive.read(relative) == (stage / relative).read_bytes(), relative
        env = base / 'venv'
        venv.create(env, with_pip=True)
        python = str(env / 'bin/python')
        run([python, '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], base)
        expected = run([sys.executable, '-c',
                        'from facade.adapter import workflow; print(workflow.source_digest())'], ROOT).strip()
        result = json.loads(run([python, '-c', SMOKE], base))
        assert result['installed_source_digest'] == expected
        for name, arguments in [('bili-tools', ['diagnose']), ('bili-tools', ['schemas']),
                                ('bili-tools', ['instructions']), ('bili-runtime', ['instructions']),
                                ('bili-video-reference', ['schemas']), ('bili-video-reference', ['instructions']),
                                ('bili-bridge', ['--help'])]:
            run([str(env / 'bin' / name), *arguments], base)
        for module, action in [('bili_distribution.current_cli', 'instructions'),
                               ('bili_distribution.current_cli', 'diagnose'),
                               ('bili_integration.cli', 'schemas'),
                               ('bili_video_reference.cli', 'schemas'),
                               ('bili_distribution.video_cli', 'instructions')]:
            run([python, '-m', module, action], base)
        search_schemas = json.loads(run([python, '-m', 'bili_integration.cli', 'schemas'], base))
        video_schemas = json.loads(run([python, '-m', 'bili_video_reference.cli', 'schemas'], base))
        assert {item['name'] for item in search_schemas} == {'bili_search_read', 'bili_status'}
        assert {item['name'] for item in video_schemas} == {'bili_read_video'}
        result['separate_schema_routes_checked'] = True
        result['exact_documented_module_bootstrap_checked'] = True
        result['wheel_file_allowlist_checked'] = True
        if args.wheel_dir:
            dest = Path(args.wheel_dir).resolve()
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wheel, dest / wheel.name)
            result['wheel'] = str(dest / wheel.name)
        result.update(ok=True, runtime_allowlist_count=len(manifest),
                      wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest())
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
