#!/usr/bin/env python3
"""Bounded ten-card quotient gate; run from repository root."""
import json
import sys
import time
import tracemalloc
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formal.search_card_scope_model import check, MUTANTS


def run():
    tracemalloc.start()
    start = time.monotonic()
    result = check()
    killed = []
    for mutant in MUTANTS:
        try:
            check(mutant)
        except AssertionError:
            killed.append(mutant)
        else:
            raise AssertionError('survived:' + mutant)
    elapsed = time.monotonic() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result['states'] <= 10000 and elapsed <= 5 and peak <= 32 * 1024 * 1024, 'budget_exceeded'
    return dict(result, ok=True, elapsed_seconds=elapsed, peak_traced_bytes=peak,
                mutants_killed=killed, budgets={'states':10000,'seconds':5,'python_traced_bytes':33554432},
                scope='finite quotient transition model; not implementation refinement or browser proof')


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
