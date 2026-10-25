#!/usr/bin/env python3
"""Read-only finite-model resource gate; never treat a partial search as a pass."""
import argparse
import ast
from collections import deque
from dataclasses import fields, is_dataclass
import hashlib
from datetime import datetime, timezone
import importlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULTS = dict(max_states=10000, max_seconds=5.0, max_memory_bytes=32 * 1024 * 1024,
                max_dependencies=16, max_wide_kernel_injections=0)


def flatten(value, prefix=''):
    if is_dataclass(value):
        return {k: v for f in fields(value) for k, v in
                flatten(getattr(value, f.name), prefix + '.' + f.name).items()}
    if isinstance(value, tuple):
        return {k: v for i, item in enumerate(value) for k, v in
                flatten(item, prefix + '.' + str(i)).items()}
    return {prefix.lstrip('.'): value}


def explore(initial, successors, invariant, *, max_states=10000, max_seconds=5.0,
            max_memory_bytes=32 * 1024 * 1024):
    """Exhaust reachable states or explicitly fail closed. Memory = Python traced allocations."""
    if max_states < 1 or max_seconds <= 0 or max_memory_bytes < 1:
        raise ValueError('budgets must be positive')
    start = time.perf_counter()
    tracemalloc.start()
    queue, seen, domains = deque([initial]), {initial}, {}
    edges = 0
    status, reason = 'complete', None
    try:
        def guard():
            if len(seen) > max_states:
                return 'states'
            if time.perf_counter() - start > max_seconds:
                return 'runtime'
            if tracemalloc.get_traced_memory()[1] > max_memory_bytes:
                return 'memory'
            return None
        while queue:
            reason = guard()
            if reason:
                status = 'budget_exceeded'
                break
            state = queue.popleft()
            for key, value in flatten(state).items():
                domains.setdefault(key, set()).add(value)
            error = invariant(state)
            if error:
                status, reason = 'invariant_violation', error
                break
            for _, successor in successors(state):
                edges += 1
                if successor not in seen:
                    seen.add(successor)
                    queue.append(successor)
                reason = guard()
                if reason:
                    status = 'budget_exceeded'
                    break
            if reason:
                break
        peak = tracemalloc.get_traced_memory()[1]
        elapsed = time.perf_counter() - start
        # Also check after final work; completion never overrides exceeded limits.
        if status == 'complete':
            reason = guard()
            if reason:
                status = 'budget_exceeded'
        cardinalities = {k: len(v) for k, v in sorted(domains.items())}
        return dict(ok=status == 'complete', status=status, reason=reason,
                    states=len(seen), explored_states=len(seen)-len(queue),
                    edges=edges, elapsed_seconds=elapsed, peak_traced_bytes=peak,
                    observed_field_cardinalities=cardinalities,
                    observed_marginal_product=math.prod(cardinalities.values()),
                    observed_marginal_bits=sum(math.log2(n) for n in cardinalities.values()),
                    measurement='tracemalloc enabled; not process RSS; partial domains if incomplete')
    finally:
        tracemalloc.stop()


def models():
    lifecycle = importlib.import_module('formal.model')
    for accounts in ((0, 0), (0, 1), (1, 0), (1, 1)):
        yield ('lifecycle_' + ''.join(map(str, accounts)), lifecycle.State(),
               lambda s, a=accounts: lifecycle.transitions(s, a),
               lambda s, a=accounts: lifecycle.violation(s, a),
               lambda a=accounts: lifecycle.check(a))
    relay = importlib.import_module('formal.relay_model')
    yield 'relay', relay.RelayState(), relay.successors, relay.invariant, relay.check_relays
    for name in ('browser_relay', 'browser_public_search', 'browser_video_open'):
        model = importlib.import_module('formal.' + name + '_model')
        yield name, model.State(), model.transitions, model.invariant, model.check


def dependencies(root=ROOT):
    """Unique package-local imported modules, including function-local imports."""
    graph = {}
    for path in sorted((root / 'bili_bridge').glob('*.py')):
        deps = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                deps.add(node.module.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('bili_bridge.'):
                deps.add(node.module.split('.')[1])
            elif isinstance(node, ast.Import):
                deps.update(n.name.split('.')[1] for n in node.names
                            if n.name.startswith('bili_bridge.') and len(n.name.split('.')) > 1)
        graph[path.stem] = sorted(deps)
    incoming = {name: sorted(src for src, deps in graph.items() if name in deps) for name in graph}
    return dict(graph=graph, max_dependencies=max(map(len, graph.values()), default=0),
                top_fanout=sorted(((k, len(v)) for k, v in graph.items()), key=lambda x: (-x[1], x[0]))[:8],
                top_fanin=sorted(((k, len(v)) for k, v in incoming.items()), key=lambda x: (-x[1], x[0]))[:8],
                caveat='Static local imports only; runtime injection, reflection and calls are not captured.')


def retained_ports(root=ROOT):
    """Syntactic retained constructor parameters + used method surfaces (not points-to analysis)."""
    ports = []
    def pairs(target, value):
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
            for left, right in zip(target.elts, value.elts):
                yield from pairs(left, right)
        else:
            yield target, value
    for path in sorted((root / 'bili_bridge').glob('*plugin.py')):
        tree = ast.parse(path.read_text())
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            init = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__'), None)
            if init is None:
                continue
            parameters = {arg.arg for arg in init.args.args if arg.arg != 'self'}
            for assignment in (n for n in ast.walk(init) if isinstance(n, ast.Assign)):
                for target in assignment.targets:
                    for left, right in pairs(target, assignment.value):
                        if (isinstance(left, ast.Attribute) and isinstance(left.value, ast.Name)
                            and left.value.id == 'self' and isinstance(right, ast.Name)
                            and right.id in parameters):
                            methods = sorted({n.func.attr for n in ast.walk(cls)
                                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                and isinstance(n.func.value, ast.Attribute)
                                and isinstance(n.func.value.value, ast.Name)
                                and n.func.value.value.id == 'self' and n.func.value.attr == left.attr})
                            ports.append(dict(module=path.stem, class_name=cls.name,
                                parameter=right.id, attribute=left.attr, used_methods=methods,
                                broad_kernel=right.id == 'kernel' or left.attr == 'kernel'))
    return dict(retained_ports=ports, wide_kernel_injections=sum(p['broad_kernel'] for p in ports),
                caveat='Syntactic constructor retention/method calls only; aliases, dynamic access and hidden state are not proven absent.')


def revalidation_frontiers(graph, ports, callback_bindings=()):
    """Conservative candidate reachability, not certified proof dependencies."""
    augmented = {key: set(value) for key, value in graph.items()}
    for binding in callback_bindings:
        augmented.setdefault(binding['consumer_module'], set()).add(binding['provider_module'])
    for port in ports:
        if port['broad_kernel']:
            augmented.setdefault(port['module'], set()).add('kernel')
    frontiers = {}
    for changed in augmented:
        affected = {changed}
        while True:
            more = {module for module, deps in augmented.items() if deps & affected}
            if more <= affected:
                break
            affected |= more
        frontiers[changed] = sorted(affected)
    return dict(candidate_implementation_frontiers=frontiers,
                max_candidate_frontier=max(map(len, frontiers.values()), default=0),
                caveat='Imports plus detected kernel injection only; not certified proof dependency sets. Missing semantic edges require review. Contract-preserving equivalence is not assumed.')


def run(budgets=None):
    budgets = dict(DEFAULTS if budgets is None else budgets)
    results = {}
    for name, initial, successors, invariant, original in models():
        result = explore(initial, successors, invariant,
                         **{k: v for k, v in budgets.items() if k not in ('max_dependencies', 'max_wide_kernel_injections')})
        # Cross-check existing enumerator only after bounded enumeration completes.
        if result['ok']:
            before = time.perf_counter()
            reference = original()
            result['original_enumerator_seconds'] = time.perf_counter() - before
            result['original_enumerator_states'] = reference.get('states')
            result['reference_agrees'] = reference['ok'] and reference.get('states') == result['states']
            result['ok'] = result['ok'] and result['reference_agrees']
        results[name] = result
    graph = dependencies()
    ports = retained_ports()
    # Explicit reviewed composition-root binding; keep the provider dependency
    # visible after removing whole-kernel authority from business plugins.
    ports['callback_bindings'] = [dict(consumer_module='selection_consumer',
        provider_module='kernel', method='consume_browser_selection',
        wiring_module='cli', kind='reviewed_semantic_dependency_not_sandbox')]
    wiring = (ROOT / 'bili_bridge' / 'cli.py').read_text()
    ports['expected_wiring_present'] = 'JournalSelectionConsumer(kernel.consume_browser_selection)' in wiring
    ports['within_budget'] = ports['wide_kernel_injections'] <= budgets['max_wide_kernel_injections'] and ports['expected_wiring_present']
    graph['within_budget'] = graph['max_dependencies'] <= budgets['max_dependencies']
    return dict(schema_version=1, measured_at_utc=datetime.now(timezone.utc).isoformat(), ok=all(r['ok'] for r in results.values()) and graph['within_budget'] and ports['within_budget'],
                scope='Finite abstract safety models only; not code proof or end-to-end composition proof',
                budget_status='INITIAL engineering limits, not universal complexity thresholds', budgets=budgets,
                environment=dict(python=sys.version, platform=platform.platform(), machine=platform.machine()),
                models=results, dependencies=graph, runtime_coupling=ports,
                revalidation=revalidation_frontiers(graph['graph'], ports['retained_ports'], ports['callback_bindings']),
                source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted((ROOT / 'formal').glob('*.py'))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key, value in DEFAULTS.items():
        parser.add_argument('--' + key.replace('_', '-'), type=type(value), default=value)
    args = vars(parser.parse_args())
    if any(value <= 0 for key, value in args.items() if key != 'max_wide_kernel_injections') or args['max_wide_kernel_injections'] < 0:
        parser.error('resource/dependency budgets must be positive; kernel injections may be zero')
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
