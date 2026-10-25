#!/usr/bin/env python3
"""Additive bounded relationship gate; offline, no state or browser writes."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formal import video_reference_model as model
from scripts.check_verification_budget import explore


def run(**limits):
    base = explore(model.State(), model.transitions, model.invariant, **limits)
    mutants = {name: explore(model.State(), lambda s, m=name: model.transitions(s, m),
                            model.invariant, **limits) for name in model.MUTANTS}
    return dict(ok=base['ok'] and all(r['status'] == 'invariant_violation' for r in mutants.values()),
                scope='Finite relation abstraction and mutation sensitivity; NOT implementation or browser proof',
                model=base, mutants=mutants)


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['ok'] else 1)
