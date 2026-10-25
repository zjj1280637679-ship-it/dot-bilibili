"""Ten-card quotient model; no implementation imports, DOM, browser or ledger.

Ad/course reasons are observationally merged ONLY for target/order/privacy/bound
properties. Concrete classifier tests retain their distinct reason strings.
"""
from dataclasses import dataclass

KINDS = ('video', 'advertisement', 'course', 'unknown')
MUTANTS = ('unknown_skip', 'reorder', 'leak', 'backfill', 'resume_rejected')


@dataclass(frozen=True)
class State:
    inspected: int = 0
    targets: tuple = ()
    exclusions: tuple = ()
    leaked: tuple = ()
    rejected: bool = False


REJECTED = State(rejected=True)


def step(s, kind, mutation=None):
    assert kind in KINDS
    if s.rejected:
        return State() if mutation == 'resume_rejected' else s
    if s.inspected == 10 and not (mutation == 'backfill' and len(s.targets) < 10):
        return s
    i = s.inspected
    if kind == 'unknown':
        if mutation != 'unknown_skip':
            return REJECTED
        kind = 'advertisement'
    if kind == 'video':
        targets = ((i,) + s.targets if mutation == 'reorder' else s.targets + (i,))
        return State(i + 1, targets, s.exclusions)
    return State(i + 1, s.targets, s.exclusions + (i,),
                 ('opaque-excluded-url',) if mutation == 'leak' else ())


def normal_state(n, mask):
    return State(n, tuple(i for i in range(n) if mask & (1 << i)),
                 tuple(i for i in range(n) if not mask & (1 << i)))


def check_edge(s, kind, got):
    # Independent relational postconditions, not a second implementation call.
    if s.rejected or s.inspected == 10:
        assert got == s, 'absorbing_window_or_rejection'
        return
    if kind == 'unknown':
        assert got == REJECTED, 'unknown_rejects_entire_capture'
        return
    assert not got.rejected and got.inspected == s.inspected + 1, 'one_input_consumed'
    assert not got.leaked, 'exclusions_never_return_payload'
    assert list(got.targets) == sorted(set(got.targets)), 'source_order_and_unique_positions'
    expected = list(s.targets)
    if kind == 'video':
        expected.append(s.inspected)
    assert list(got.targets) == expected, 'only_current_video_appended'
    assert set(got.exclusions) == set(range(got.inspected)) - set(got.targets), 'exact_partition'
    assert all(i < 10 for i in got.targets + got.exclusions), 'ten_card_window'


def check(mutation=None):
    states = [normal_state(n, mask) for n in range(11) for mask in range(1 << n)]
    states.append(REJECTED)
    edges = 0
    for s in states:
        for kind in KINDS:
            check_edge(s, kind, step(s, kind, mutation))
            edges += 1
    return {'states': len(states), 'edges': edges}
