"""Finite four/five-step orchestration safety abstraction; NOT implementation refinement.

One flock owner, one workflow ID, four/five distinct child IDs, no queue. Exact CLI
receipt truth, durable save and kernel freshness enforcement are assumptions.
Facade status/repeated invocation are abstract no-op reads, not a concurrency proof.
"""
from dataclasses import dataclass, replace

MUTANTS = ('replay_terminal', 'skip_durable', 'use_first_source',
           'accept_stale_source', 'accept_wrong_binding', 'continue_after_failure',
           'duplicate_child')


@dataclass(frozen=True)
class State:
    step: int = 0
    phase: str = 'ready'
    launches: tuple = (0, 0, 0, 0, 0)
    source: int = 0
    fresh: bool = True
    durable: bool = False
    terminal_seen: bool = False
    open_valid: bool = True
    binding_valid: bool = True


def terminal(s, phase):
    return replace(s, phase=phase, terminal_seen=True)


def transitions(s, mutation=None, steps=5):
    if steps not in (4, 5):
        raise ValueError('steps must be 4 or 5')
    if mutation is not None and mutation not in MUTANTS:
        raise ValueError('unknown mutation')
    yield 'status_or_duplicate_invocation:no_child', s
    if s.terminal_seen:
        if mutation == 'replay_terminal':
            yield 'unsafe_resume', replace(s, phase='ready', step=0)
        return
    yield 'crash_or_uncertain:terminal', terminal(s, 'unknown')
    if s.source == 2 and s.fresh and s.step <= 2:
        yield 'source_expiry', replace(s, fresh=False)
    if s.phase == 'ready':
        yield 'durable_intent', replace(s, phase='prepared', durable=True)
        if mutation == 'skip_durable':
            yield 'volatile_intent', replace(s, phase='prepared', durable=False)
    elif s.phase == 'prepared':
        counts = list(s.launches)
        counts[s.step] += 1
        yield 'child_launch', replace(s, phase='pending', launches=tuple(counts))
    elif s.phase == 'pending':
        if mutation == 'duplicate_child':
            counts = list(s.launches)
            counts[s.step] += 1
            yield 'duplicate_child', replace(s, launches=tuple(counts))
        yield 'failed_or_partial:stop', terminal(s, 'failed')
        yield 'unknown:stop', terminal(s, 'unknown')
        if mutation == 'continue_after_failure':
            yield 'failed:continue', replace(s, phase='ready', terminal_seen=True)
        for exact in (False, True):
            if not exact and mutation != 'accept_wrong_binding':
                yield 'wrong_id_target_tab_url:stop', terminal(s, 'unknown')
                continue
            valid_open = s.step != 2 or (s.source == 2 and s.fresh)
            if not valid_open and mutation not in ('accept_stale_source', 'use_first_source'):
                yield 'kernel_source_rejected:stop', terminal(s, 'failed')
                continue
            source = s.source
            if s.step == 0:
                source = 1
            elif s.step == 1:
                source = 1 if mutation == 'use_first_source' else 2
            nxt = replace(s, step=s.step + 1, phase='ready', source=source,
                          durable=False, binding_valid=s.binding_valid and exact,
                          open_valid=s.open_valid and valid_open)
            if nxt.step == steps:
                nxt = terminal(nxt, 'succeeded_visible_subset')
            yield 'exact_observed' if exact else 'wrong_binding:accepted', nxt


def invariant(s, steps=5):
    if steps not in (4, 5):
        raise ValueError('steps must be 4 or 5')
    if any(s.launches[steps:]):
        return 'no_unrequested_comments_child'
    if sum(s.launches) > steps or any(count > 1 for count in s.launches):
        return 'bounded_children_at_most_once_each'
    if s.phase == 'pending' and not s.durable:
        return 'durable_intent_before_child'
    if s.terminal_seen and s.phase in ('ready', 'prepared', 'pending'):
        return 'terminal_never_resumes_or_advances'
    if not s.open_valid:
        return 'fresh_second_read_source_for_open'
    if not s.binding_valid:
        return 'exact_source_target_tab_url_binding'
    if s.phase == 'succeeded_visible_subset' and (s.step != steps or sum(s.launches) != steps):
        return 'all_requested_steps_required'
    return None
