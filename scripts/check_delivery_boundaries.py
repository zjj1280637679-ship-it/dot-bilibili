#!/usr/bin/env python3
"""Supplementary delivery-layer graph/model check; never an all-project proof."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('_budget', ROOT / 'scripts/check_verification_budget.py')
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)
from formal import read_workflow_model as model

# Explicit semantic edges include non-import dependencies. Markers check only
# source presence, NOT correctness, exclusivity, aliasing or dataflow refinement.
EDGES = (
    ('facade.adapter', 'scripts.read_workflow', 'dynamic import and ledger read', 'facade/adapter.py', 'workflow.load(path)'),
    ('facade.adapter', 'scripts.read_workflow', 'subprocess command', 'facade/adapter.py', "str(ROOT / 'scripts/read_workflow.py')"),
    ('facade.adapter', 'facade.projection', 'public result projection', 'facade/adapter.py', 'projection.search('),
    ('facade.adapter', 'facade.contracts', 'public input schema', 'facade/adapter.py', 'args = validate(args)'),
    ('scripts.read_workflow', 'bili_bridge.__main__', 'child process module entry', 'scripts/read_workflow.py', "'-m', 'bili_bridge'"),
    ('bili_bridge.__main__', 'bili_bridge.cli', 'CLI entry function', 'bili_bridge/__main__.py', 'from .cli import main'),
    ('scripts.read_workflow', 'workflow ledger', 'shared persisted intent/results', 'scripts/read_workflow.py', 'save(path, record)'),
    ('facade.adapter', 'workflow ledger', 'same authoritative result ledger', 'facade/adapter.py', 'record = workflow.load(path)'),
    ('bili_bridge.cli', 'bili_bridge.selection_consumer', 'composition root callback injection', 'bili_bridge/cli.py', 'JournalSelectionConsumer(kernel.consume_browser_selection)'),
    ('bili_bridge.selection_consumer', 'bili_bridge.kernel', 'atomic journal provider callback', 'bili_bridge/selection_consumer.py', 'self._consume(request)'),
    ('bili_bridge.cli', 'bili_bridge.kernel', 'dispatch shared authority', 'bili_bridge/cli.py', 'kernel.dispatch(request)'),
)


def run():
    edges = [dict(source=a, target=b, kind=k, evidence_file=p,
                  marker_present=marker in (ROOT / p).read_text())
             for a, b, k, p, marker in EDGES]
    variants = {}
    for steps in (4, 5):
        invariant = lambda state, steps=steps: model.invariant(state, steps)
        safe = budget.explore(model.State(),
                              lambda state, steps=steps: model.transitions(state, steps=steps), invariant)
        mutants = {name: budget.explore(model.State(),
                        lambda state, name=name, steps=steps: model.transitions(state, name, steps), invariant)
                   for name in model.MUTANTS}
        variants[str(steps)] = dict(comments=steps == 5, safe=safe, mutants=mutants)
    paths = {str(p.relative_to(ROOT)) for directory in ('facade', 'bili_bridge')
             for p in (ROOT / directory).glob('*.py')} | {edge['evidence_file'] for edge in edges} | {'formal/read_workflow_model.py',
             'scripts/check_delivery_boundaries.py', 'scripts/check_verification_budget.py'}
    return dict(ok=all(variant['safe']['ok'] and all(not v['ok'] and v['status'] == 'invariant_violation'
                        for v in variant['mutants'].values()) for variant in variants.values())
                and all(e['marker_present'] for e in edges),
                scope='Supplementary four/five-step abstractions and reviewed source markers, NOT implementation refinement or all-project proof',
                graph_kind='explicit reviewed subset; markers do not prove dependency completeness',
                bounded_model=dict(owners=1, workflow_ids=1, distinct_child_ids=[4, 5], max_children=[4, 5],
                                   pending_children=1, queue_capacity=0, comments=[False, True]),
                budgets=dict(max_states=10000, max_seconds=5.0, max_memory_bytes=33554432),
                variants=variants, edges=edges,
                source_sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(paths)})


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
