"""Finite public-search host protocol specification, not browser-control proof.

One immutable request, one trusted host, and one semantic navigation are modeled.
``exact`` abstracts source URL/tab/context and destination URL/tab/context checks;
it is an assumption about honest host attestations, not DOM truth, account
cryptographic authentication, a per-HTTP budget, or a verified implementation.
The durable begin-navigation checkpoint precedes the host action; any uncertain
restart retires the request instead of authorizing another navigation.
"""
from collections import deque
from dataclasses import dataclass, replace

ACTIVE = frozenset({'issued', 'claimed', 'preflight', 'navigation_started', 'navigated'})


@dataclass(frozen=True)
class State:
    stage: str = 'issued'
    alive: bool = True
    fresh: bool = True
    claims: int = 0
    checkpoints: int = 0
    navigations: int = 0
    captures: int = 0
    source_verified: bool = False
    checkpoint_durable: bool = False
    navigation_authorized: bool = True
    capture_matched: bool = True
    terminal_seen: bool = False
    cooldown: bool = False


def terminal(s, stage, **updates):
    return replace(s, stage=stage, terminal_seen=True, cooldown=True, **updates)


def transitions(s, mutation=None):
    if s.alive:
        yield 'owner_dead', replace(s, alive=False)
    if s.fresh:
        yield 'expiry', replace(s, fresh=False)
    if s.stage not in ACTIVE:
        yield 'duplicate_delivery:reject', s
        yield 'restart:preserve', s
        if s.cooldown:
            yield 'cooldown_elapsed', replace(s, cooldown=False)
        if mutation == 'implicit_replay':
            yield 'restart:reissue', replace(s, stage='issued', alive=True, fresh=True)
        return
    yield 'restart:unknown', terminal(s, 'unknown')
    if not s.alive or not s.fresh:
        yield 'lease_lost:unknown', terminal(s, 'unknown')
        return
    if s.stage == 'issued':
        yield 'claim', replace(s, stage='claimed', claims=s.claims + 1)
        return
    yield 'duplicate_claim:reject', s
    if s.stage == 'claimed':
        for kind in ('exact', 'wrong_source_url', 'wrong_source_tab', 'context_changed', 'context_unavailable'):
            if kind == 'exact' or mutation == 'bypass_source_check':
                yield 'preflight:' + kind, replace(s, stage='preflight', source_verified=kind == 'exact')
            else:
                yield 'preflight:' + kind + ':block', terminal(s, 'blocked')
    if s.stage in ('claimed', 'preflight'):
        yield 'early_capture:reject', s
        if mutation == 'capture_before_navigation':
            yield 'early_capture:accept', terminal(s, 'observed', captures=s.captures + 1)
    if s.stage == 'preflight':
        yield 'begin_navigation:durable', replace(s, stage='navigation_started',
            checkpoint_durable=True, checkpoints=s.checkpoints + 1)
    if s.stage in ('navigation_started', 'navigated'):
        yield 'duplicate_begin:reject', s
    if s.stage == 'navigation_started':
        yield 'navigate_once', replace(s, stage='navigated', navigations=s.navigations + 1,
            navigation_authorized=s.source_verified and s.checkpoint_durable)
        yield 'host_action_uncertain:unknown', terminal(s, 'unknown')
    if s.stage == 'navigated':
        for kind in ('exact', 'wrong_target', 'wrong_tab', 'context_changed', 'context_unavailable', 'stale'):
            if kind == 'exact':
                yield 'capture:exact', terminal(s, 'observed', captures=s.captures + 1)
            elif mutation == 'accept_invalid_capture':
                yield 'capture:' + kind + ':accept', terminal(s, 'observed', captures=s.captures + 1,
                    capture_matched=False)
            else:
                yield 'capture:' + kind + ':reject', terminal(s, 'unknown')
        yield 'target_captcha:block', terminal(s, 'blocked')


def invariant(s):
    if s.claims > 1 or s.checkpoints > 1 or s.navigations > 1 or s.captures > 1:
        return 'at_most_once'
    if s.navigations and not s.navigation_authorized:
        return 'verified_source_before_navigation'
    if s.captures and (s.navigations != 1 or not s.checkpoint_durable):
        return 'capture_after_durable_navigation'
    if s.captures and not s.capture_matched:
        return 'fresh_exact_context_capture'
    if s.terminal_seen and s.stage in ACTIVE:
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
