"""Bounded executable safety model for receipt-selected video navigation.

Not TLC, implementation refinement, DOM truth, or a live-browser test. Domains:
one applied search receipt, one immutable selected target, two competing open IDs
(the second is represented by a consume attempt), one trusted host, and one
semantic navigation. Source freshness abstracts <=600 seconds without modeling
clock arithmetic; exact bindings abstract source operation, scope, query, tab,
BVID membership and the latest completed exchange. Atomic durable receipt
consumption and truthful host observations are assumptions. At most one receipt
can be emitted; crash/uncertain outcomes are terminal, not progress guarantees.
"""
from collections import deque
from dataclasses import dataclass, replace

ACTIVE = frozenset({'select', 'issued', 'claimed', 'preflight', 'navigation_started', 'navigated'})
SOURCE_ERRORS = ('not_applied', 'expired', 'wrong_source_operation', 'wrong_scope',
                 'target_not_member', 'not_latest_exchange')
PREFLIGHT_ERRORS = ('wrong_query', 'wrong_tab', 'wrong_bvid_anchor', 'missing_anchor',
                    'context_changed', 'context_unavailable', 'captcha')
CAPTURE_ERRORS = ('wrong_target', 'wrong_tab', 'stale', 'context_changed',
                  'context_unavailable')
MUTANTS = ('bypass_' + error for error in SOURCE_ERRORS)
MUTANTS = tuple(MUTANTS) + ('reuse_consumed_source', 'bypass_preflight',
    'skip_checkpoint', 'duplicate_navigation', 'early_capture', 'invalid_capture',
    'implicit_replay', 'ignore_invalidation')


@dataclass(frozen=True)
class State:
    stage: str = 'select'
    fresh: bool = True
    latest: bool = True
    alive: bool = True
    consumes: int = 0
    claims: int = 0
    navigations: int = 0
    captures: int = 0
    provenance_valid: bool = True
    preflight_valid: bool = False
    durable: bool = False
    navigation_valid: bool = True
    capture_valid: bool = True
    terminal_seen: bool = False


def terminal(s, stage, **updates):
    return replace(s, stage=stage, terminal_seen=True, **updates)


def transitions(s, mutation=None):
    if s.stage not in ACTIVE:
        yield 'duplicate_delivery:reject', s
        yield 'restart:preserve', s
        if mutation == 'implicit_replay':
            yield 'restart:reissue', replace(s, stage='issued', fresh=True, alive=True)
        return
    if s.fresh:
        yield 'expiry', replace(s, fresh=False)
    if s.latest:
        yield 'intervening_operation', replace(s, latest=False)
    if s.alive:
        yield 'owner_dead', replace(s, alive=False)
    yield 'restart:unknown', terminal(s, 'unknown')
    # Latest-exchange provenance is checked until the durable start. The host's
    # own navigation then legitimately replaces its previous search context.
    invalid = not s.fresh or not s.alive or (not s.latest and s.stage in
        ('select', 'issued', 'claimed', 'preflight'))
    if invalid and mutation != 'ignore_invalidation':
        yield 'invalidated:unknown', terminal(s, 'unknown')
        return
    if s.stage == 'select':
        for kind in ('exact',) + SOURCE_ERRORS:
            if kind == 'exact' or mutation == 'bypass_' + kind:
                yield 'consume:' + kind, replace(s, stage='issued', consumes=1,
                    provenance_valid=kind == 'exact' and s.fresh and s.latest and s.alive)
            else:
                yield 'consume:' + kind + ':reject', terminal(s, 'blocked')
        return
    yield 'second_open_id:reject_consumed_source', s
    yield 'same_open_id:reject_duplicate', s
    if mutation == 'reuse_consumed_source':
        yield 'second_open_id:consume', replace(s, consumes=s.consumes + 1)
    if s.stage == 'issued':
        yield 'claim', replace(s, stage='claimed', claims=s.claims + 1)
    if s.stage in ('claimed', 'preflight'):
        yield 'early_capture:reject', s
        if mutation == 'early_capture':
            yield 'early_capture:accept', terminal(s, 'observed', captures=1)
    if s.stage == 'claimed':
        yield 'duplicate_claim:reject', s
        for kind in ('exact',) + PREFLIGHT_ERRORS:
            if kind == 'exact' or mutation == 'bypass_preflight':
                yield 'preflight:' + kind, replace(s, stage='preflight', preflight_valid=kind == 'exact')
            else:
                yield 'preflight:' + kind + ':block', terminal(s, 'blocked')
    if s.stage == 'preflight':
        yield 'begin_navigation:durable', replace(s, stage='navigation_started', durable=True)
        if mutation == 'skip_checkpoint':
            yield 'begin_navigation:volatile', replace(s, stage='navigation_started')
    if s.stage in ('navigation_started', 'navigated'):
        yield 'duplicate_begin:reject', s
    if s.stage == 'navigation_started':
        yield 'navigate_once', replace(s, stage='navigated', navigations=s.navigations + 1,
            navigation_valid=s.provenance_valid and s.preflight_valid and s.durable and s.fresh and s.alive)
        yield 'host_action_uncertain:unknown', terminal(s, 'unknown')
    if s.stage == 'navigated':
        if mutation == 'duplicate_navigation':
            yield 'navigate_again', replace(s, navigations=s.navigations + 1)
        for kind in ('exact',) + CAPTURE_ERRORS:
            if kind == 'exact' or mutation == 'invalid_capture':
                yield 'capture:' + kind, terminal(s, 'observed', captures=1,
                    capture_valid=kind == 'exact' and s.fresh and s.alive)
            else:
                yield 'capture:' + kind + ':unknown', terminal(s, 'unknown')
        yield 'target_captcha:block', terminal(s, 'blocked')


def invariant(s):
    if s.consumes > 1:
        return 'single_use_search_receipt'
    if s.consumes and not s.provenance_valid:
        return 'fresh_applied_exact_source_and_member'
    if s.claims > 1 or s.navigations > 1 or s.captures > 1:
        return 'at_most_once'
    if s.navigations and not s.navigation_valid:
        return 'fresh_preflight_and_durable_start_before_navigation'
    if s.captures and (s.navigations != 1 or not s.durable):
        return 'capture_after_durable_navigation'
    if s.captures and not s.capture_valid:
        return 'fresh_exact_target_receipt'
    if s.terminal_seen and s.stage in ACTIVE:
        return 'unknown_and_terminal_never_replay'
    return None


def check(mutation=None):
    if mutation is not None and mutation not in MUTANTS:
        raise ValueError('unknown mutation: ' + mutation)
    start = State()
    queue, parents, coverage = deque([start]), {start: None}, set()
    while queue:
        state = queue.popleft()
        violation = invariant(state)
        if violation:
            trace, cursor = [], state
            while parents[cursor] is not None:
                cursor, action = parents[cursor]
                trace.append(action)
            return {'ok': False, 'violation': violation, 'trace': list(reversed(trace))}
        for action, successor in transitions(state, mutation):
            coverage.add(action)
            if successor not in parents:
                parents[successor] = state, action
                queue.append(successor)
    return {'ok': True, 'states': len(parents), 'actions': sorted(coverage)}
