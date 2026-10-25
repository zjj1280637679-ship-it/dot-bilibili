"""Finite abstract protocol; not execution or verification of the Python kernel."""
from collections import deque
from dataclasses import dataclass, replace
from itertools import product

STAGES = ('draft', 'prepared', 'inflight', 'applied', 'rejected', 'unknown', 'cancelled')
GRANTS = ('none', 'exact', 'wrong_scope', 'stale')
UNRESOLVED = {'prepared', 'inflight', 'unknown'}

@dataclass(frozen=True)
class Operation:
    stage: str = 'draft'
    grant: str = 'none'
    attempts: int = 0
    effects: int = 0
    durable: bool = False
    authorized_sends: bool = True

@dataclass(frozen=True)
class State:
    operations: tuple = (Operation(), Operation())
    used: int = 0

def update(state, i, operation, used=None):
    ops = list(state.operations)
    ops[i] = operation
    return State(tuple(ops), state.used if used is None else used)

def transitions(state, accounts, limit=2, mutation=None):
    """Two operation IDs, one distinct plugin/capability each, one resource.

    Scope binding abstracts account + operation + capability + target + payload.
    No credential content or transport code is modeled. Time is exact/stale.
    """
    for i, op in enumerate(state.operations):
        def emit(label, **changes):
            return f'o{i}:{label}', update(state, i, replace(op, **changes))
        if op.stage == 'draft' and op.grant == 'none':
            yield emit('grant_exact', grant='exact')
            yield emit('grant_wrong_scope', grant='wrong_scope')
        if op.grant == 'exact':
            yield emit('expire_or_revoke', grant='stale')
        if op.stage in ('draft', 'prepared'):
            yield emit('cancel', stage='cancelled')
        conflict = any(j != i and accounts[i] == accounts[j] and other.stage in UNRESOLVED
                       for j, other in enumerate(state.operations))
        if op.stage == 'draft' and op.grant == 'exact' and not conflict and state.used < limit:
            yield f'o{i}:prepare', update(state, i, replace(op, stage='prepared', durable=True), state.used + 1)
        if op.stage == 'prepared' and (op.grant == 'exact' or mutation == 'bypass_authorization'):
            yield emit('send', stage='inflight', attempts=op.attempts + 1,
                       authorized_sends=op.authorized_sends and op.grant == 'exact')
        if op.stage == 'inflight':
            # Send may have taken effect without an observable response.
            if op.effects < op.attempts:
                yield emit('remote_effect', effects=op.effects + 1)
                yield emit('reject', stage='rejected')
            else:
                yield emit('response_evidence', stage='applied')
            yield emit('response_lost', stage='unknown')
        if op.stage == 'unknown' and mutation == 'retry_unknown' and state.used < limit:
            yield f'o{i}:unsafe_retry', update(state, i, replace(op, stage='prepared'), state.used + 1)
    recovered = tuple(replace(op, stage='unknown') if op.stage in ('prepared', 'inflight') else op
                      for op in state.operations)
    if recovered != state.operations:
        yield 'restart', State(recovered, state.used)

def violation(state, accounts, limit=2):
    if not 0 <= state.used <= limit:
        return 'shared_budget'
    if sum(op.attempts for op in state.operations) > state.used:
        return 'reservation_before_send'
    for op in state.operations:
        if op.attempts and not op.durable:
            return 'durable_intent'
        if not op.authorized_sends:
            return 'authorization_at_send'
        if op.attempts > 1:
            return 'no_unknown_replay'
        if op.stage == 'applied' and op.effects < 1:
            return 'success_requires_effect_evidence'
    for i, op in enumerate(state.operations):
        for j, other in enumerate(state.operations):
            if i < j and accounts[i] == accounts[j] and op.stage in UNRESOLVED and other.stage in UNRESOLVED:
                return 'resource_exclusion'
    return None

def check(accounts=(0, 0), limit=2, mutation=None):
    initial = State()
    queue = deque([initial])
    parents = {initial: None}
    coverage = set()
    edges = 0
    while queue:
        state = queue.popleft()
        coverage.update(op.stage for op in state.operations)
        error = violation(state, accounts, limit)
        if error:
            trace = []
            cursor = state
            while parents[cursor] is not None:
                previous, action = parents[cursor]
                trace.append(action)
                cursor = previous
            return {'ok': False, 'violation': error, 'trace': list(reversed(trace)),
                    'states': len(parents), 'edges': edges, 'coverage': sorted(coverage)}
        for action, successor in transitions(state, accounts, limit, mutation):
            edges += 1
            if successor not in parents:
                parents[successor] = state, action
                queue.append(successor)
    return {'ok': True, 'states': len(parents), 'edges': edges, 'coverage': sorted(coverage)}

def suite():
    return {'bounds': {'operations': 2, 'plugins': 2, 'accounts': 2, 'resources': 1,
                       'budget': 2, 'account_assignments': 4, 'time': 'valid/stale abstraction'},
            'safe': {str(a): check(a) for a in product(range(2), repeat=2)},
            'mutations': {m: check(mutation=m) for m in ('bypass_authorization', 'retry_unknown')}}
