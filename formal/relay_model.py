"""Bounded assume/guarantee relay checker, independent of implementation.

Two immutable operation envelopes cross plugin and module relays before kernel.
Each handoff nondeterministically receives exact or singly corrupted envelope,
or missing/incorrect route evidence. Host journal and budget are globally owned.
"""
from collections import deque
from dataclasses import dataclass, replace

FIELDS = ('operation', 'account', 'capability', 'target', 'payload_hash', 'version', 'effect')
ROUTE = ('plugin_relay', 'module_relay', 'kernel')

@dataclass(frozen=True)
class Packet:
    hop: int = 0
    path: tuple = ()
    status: str = 'pending'
    accepted_scope: bool = True
    journal: bool = False

@dataclass(frozen=True)
class RelayState:
    packets: tuple = (Packet(), Packet())
    used: int = 0

def envelope(i):
    # plugin0/op0/account0 and plugin1/op1/account1; each is read-only.
    return (f'o{i}', f'a{i}', 'read', 'resource0', 'hash0', 1, 'read')

def candidates(expected, path):
    yield 'exact', expected, path
    for n, field in enumerate(FIELDS):
        changed = list(expected)
        changed[n] = 2 if field == 'version' else 'different_' + field
        yield 'wrong_' + field, tuple(changed), path
    yield 'missing_route', expected, () if path else ('module_relay',)
    yield 'wrong_route', expected, ('kernel',)

def successors(state, mutation=None):
    for i, packet in enumerate(state.packets):
        if packet.status != 'pending':
            continue
        def emit(label, changed, used=state.used):
            packets = list(state.packets)
            packets[i] = changed
            return f'o{i}:{label}', RelayState(tuple(packets), used)
        expected = envelope(i)
        if mutation == 'bypass_relay' and packet.hop == 0 and state.used < 1:
            yield emit('direct_send', replace(packet, status='sent', journal=True), state.used + 1)
        for label, incoming, path in candidates(expected, packet.path):
            valid_scope = incoming == expected
            valid_path = path == ROUTE[:packet.hop]
            accepted = valid_path and (valid_scope or mutation == 'widen_scope')
            if not accepted:
                yield emit(label + ':reject', replace(packet, status='rejected'))
                continue
            next_path = path + (ROUTE[packet.hop],)
            if packet.hop < 2:
                yield emit(label + ':handoff', replace(packet, hop=packet.hop + 1, path=next_path,
                           accepted_scope=packet.accepted_scope and valid_scope))
            elif state.used < 1:
                yield emit(label + ':send', replace(packet, hop=3, path=next_path, status='sent',
                           journal=True, accepted_scope=packet.accepted_scope and valid_scope), state.used + 1)
            else:
                yield emit(label + ':budget_denied', replace(packet, status='deferred'))

def invariant(state):
    if state.used > 1 or sum(p.status == 'sent' for p in state.packets) > state.used:
        return 'global_budget'
    for packet in state.packets:
        if not packet.accepted_scope:
            return 'immutable_scope'
        if packet.status == 'sent' and (packet.path != ROUTE or not packet.journal):
            return 'no_bypass_and_durable_journal'
    return None

def check_relays(mutation=None):
    start = RelayState()
    queue, parents, coverage = deque([start]), {start: None}, set()
    edges = 0
    while queue:
        state = queue.popleft()
        error = invariant(state)
        if error:
            trace, cursor = [], state
            while parents[cursor]:
                cursor, action = parents[cursor]
                trace.append(action)
            return {'ok': False, 'violation': error, 'trace': list(reversed(trace)), 'states': len(parents)}
        for action, successor in successors(state, mutation):
            edges += 1
            coverage.add(action.split(':', 1)[1])
            if successor not in parents:
                parents[successor] = state, action
                queue.append(successor)
    return {'ok': True, 'states': len(parents), 'edges': edges, 'actions': sorted(coverage)}
