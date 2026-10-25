#!/usr/bin/env python3
"""Verify frozen milestone structure/source binding without live actions."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
m = json.loads((ROOT/'docs/milestone-five-acceptance.json').read_text())
expected = {
    'search.query.submit': (['N01','N02','N03'], False),
    'search.results.visible.read': ([], True),
    'video.search_result.open': (['N01','N02','N03','N04'], False),
    'video.metadata.visible.read': ([], True),
    'comments.viewport.read': ([], True),
}
assert len(m['leaves']) == 5
assert {p['id'] for p in m['leaves']} == set(expected)
known = set()
for f in (ROOT/'tests').glob('test_*.py'):
    for cls in ast.parse(f.read_text()).body:
        if isinstance(cls, ast.ClassDef):
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                    known.add(f'{f.stem}.{cls.name}.{node.name}')
for path, wanted in m['source_sha256'].items():
    assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == wanted, f'source drift: {path}'
for p in m['leaves']:
    nav, read = expected[p['id']]
    assert [c['id'] for c in p['offline_cases']] == [f'O{i:02}' for i in range(1,13)] + nav
    assert [c['id'] for c in p['live_cases']] == ['L01','L02','L03'] + (['L04'] if read else [])
    for c in p['offline_cases']:
        assert c['tests'] and set(c['tests']) <= known, (p['id'], c['id'])
    if p['accepted_for_release']:
        assert p['robust'] == 'pass'
        assert not m['unresolved_high_severity_defects']
        assert all(c['evidence'] for c in p['live_cases'])
        for case in p['live_cases']:
            for ref in case['evidence']:
                proof_path = (ROOT/ref['path']).resolve()
                assert proof_path.is_relative_to(ROOT.resolve())
                raw = proof_path.read_bytes()
                assert hashlib.sha256(raw).hexdigest() == ref['sha256'], 'evidence drift'
                proof = json.loads(raw)
                assert proof['evidence_kind'] == 'trusted_host_live_browser_attestation'
                assert proof['case_review_status'] == 'pass'
                assert proof['recipe_sha256'] == m['source_sha256']['scripts/host_capture_recipes.js']
                assert proof['workflow_sha256'] == m['source_sha256']['scripts/read_workflow.py']
                assert proof['runtime_source_digest'] == m['accepted_runtime_source_digest']
                observation = proof['operations'][ref['operation_index']]
                assert observation['operation'] == p['operation'] and observation['state'] == 'applied'
                assert observation['operation_binding_sha256'] == ref['operation_binding_sha256']
                if case['id'] == 'L03':
                    assert proof['independent_session']['inherited_handles'] is False
                if case['id'] == 'L02':
                    assert proof['query_target_alternate'] is True
                # Structural/hash validation checks recorded attestations, not live DOM truth.

        assert all(c['status']=='pass' for c in p['offline_cases']+p['live_cases'])
        assert all(g['status']=='pass' for g in m['infrastructure_gates'])
assert [g['id'] for g in m['infrastructure_gates']] == [f'G{i:02}' for i in range(1,11)]
for g in m['infrastructure_gates']:
    assert len(g['tests']) >= 2 and set(g['tests']) <= known
accepted = sum(p['accepted_for_release'] for p in m['leaves'])
assert m['strict_accepted'] == accepted
print(json.dumps({'manifest_valid': True, 'strict_accepted': accepted, 'milestone_denominator': 5,
                  'all_business_denominator': 122, 'offline_cases': sum(len(p['offline_cases']) for p in m['leaves']),
                  'live_cases': sum(len(p['live_cases']) for p in m['leaves']),
                  'source_files_verified': len(m['source_sha256'])}))
