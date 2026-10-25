"""Finite protocol specification, not an implementation or browser-control proof.

One request, nondeterministic host claims, receipt validity, owner death, expiry,
restart and duplicate delivery. Cooldown abstracts wall-clock passage. Terminal
requests cannot be reissued. Identity checks abstract the complete immutable
scope and live observed target, NOT authentication of an untrusted local host.
"""
from collections import deque
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class State:
    stage: str = 'issued'
    alive: bool = True
    fresh: bool = True
    claims: int = 0
    observations: int = 0
    matched: bool = True
    cooldown: bool = False
    terminal_seen: bool = False


def transitions(s, mutation=None):
    if s.alive:
        yield 'owner_dead', replace(s, alive=False)
    if s.fresh:
        yield 'expiry', replace(s, fresh=False)
    if s.stage in ('issued', 'claimed'):
        if not s.alive or not s.fresh:
            yield 'timeout_or_owner_dead', replace(s, stage='timeout', cooldown=True, terminal_seen=True)
        if s.stage == 'issued' and s.alive and s.fresh:
            yield 'claim', replace(s, stage='claimed', claims=s.claims + 1)
        if s.stage == 'claimed':
            for kind in ('exact', 'stale', 'mismatch'):
                valid = kind == 'exact' and s.alive and s.fresh
                if valid or mutation == 'accept_invalid':
                    yield kind + ':observe', replace(s, stage='observed', observations=s.observations+1,
                        matched=valid, cooldown=True, terminal_seen=True)
                else:
                    yield kind + ':reject', replace(s, stage='rejected', cooldown=True, terminal_seen=True)
            yield 'duplicate_claim:reject', s
        yield 'restart', replace(s, stage='timeout', cooldown=True, terminal_seen=True)
    else:
        yield 'duplicate_receipt:reject', s
        yield 'restart:preserve', s
        if mutation == 'implicit_replay':
            yield 'restart:reissue', replace(s, stage='issued', fresh=True, alive=True)
        if s.cooldown:
            yield 'cooldown_elapsed', replace(s, cooldown=False)


def invariant(s):
    if s.claims > 1 or s.observations > 1:
        return 'at_most_once'
    if s.observations and not s.matched:
        return 'fresh_exact_live_receipt'
    if s.terminal_seen and s.stage in ('issued', 'claimed'):
        return 'no_implicit_replay'
    return None


def check(mutation=None):
    start = State()
    queue, parents, coverage = deque([start]), {start: None}, set()
    while queue:
        state = queue.popleft()
        violation = invariant(state)
        if violation:
            trace, cursor = [], state
            while parents[cursor]:
                cursor, action = parents[cursor]
                trace.append(action)
            return {'ok': False, 'violation': violation, 'trace': list(reversed(trace))}
        for action, successor in transitions(state, mutation):
            coverage.add(action)
            if successor not in parents:
                parents[successor] = state, action
                queue.append(successor)
    return {'ok': True, 'states': len(parents), 'actions': sorted(coverage)}
