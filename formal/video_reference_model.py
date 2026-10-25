"""Finite resolver -> exact-search-port relation, not implementation proof.

Two abstract BVIDs, three aliases, two host IDs/comments choices and four port
outcomes. Grammar membership and trusted host validity are abstract inputs.
No browser, ledger, retries, registration, or implementation imports.
"""
from dataclasses import dataclass, replace
from itertools import product

MUTANTS = ('accept_invalid', 'change_host_id', 'first_visible', 'double_call', 'fallback')
OUTCOMES = ('succeeded', 'selection_not_found', 'unknown', 'request_conflict')


@dataclass(frozen=True)
class State:
    phase: str = 'initial'
    bvid: int = 0
    alias: int = 0
    valid: bool = True
    comments: bool = False
    host_id: int = 0
    passed_id: int = -1
    query: int = -1
    select: int = -1
    calls: int = 0
    navigation: int = 0
    outcome: str = ''
    returned: str = ''


def transitions(s, mutation=None):
    if mutation is not None and mutation not in MUTANTS:
        raise ValueError('unknown mutation')
    if s.phase == 'initial':
        for bvid, alias, valid, comments, host_id in product(range(2), range(3), (False, True), (False, True), range(2)):
            yield 'input', State('input', bvid, alias, valid, comments, host_id)
    elif s.phase == 'input':
        if not s.valid and mutation != 'accept_invalid':
            yield 'reject', replace(s, phase='done', returned='rejected')
        else:
            yield 'exact_search_port', replace(s, phase='pending', calls=2 if mutation == 'double_call' else 1,
                query=s.bvid, select=-1 if mutation == 'first_visible' else s.bvid,
                passed_id=1-s.host_id if mutation == 'change_host_id' else s.host_id)
    elif s.phase == 'pending':
        for outcome in OUTCOMES:
            yield 'return_unchanged', replace(s, phase='done', outcome=outcome, returned=outcome,
                navigation=int(mutation == 'fallback' and outcome == 'selection_not_found'))


def invariant(s):
    if s.navigation:
        return 'no_direct_navigation_or_fallback'
    if not s.valid and s.calls:
        return 'reject_before_port'
    if s.calls > 1:
        return 'at_most_one_port_call'
    if s.calls and (s.query != s.bvid or s.select != s.bvid):
        return 'exact_search_selection'
    if s.calls and s.passed_id != s.host_id:
        return 'host_identity_unchanged'
    if s.phase == 'done' and s.calls and s.returned != s.outcome:
        return 'port_outcome_unchanged'
    return None


def intent(s):
    """Alias is deliberately absent from normalized intent; host ID is unchanged."""
    return (s.query, s.select, s.comments, s.passed_id)
