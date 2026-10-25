# Minimal AI entry: explicit delivery-layer verification boundaries

The original `check_verification_budget.py` imports graph is scoped to `bili_bridge/*.py`.
**A green result is NOT an all-project coupling check.** It does not include the `facade/`
API, the dynamic workflow import, subprocess protocol, workflow ledger, projection code or
host registration. The simpler top-level API must not hide these dependencies.

This supplement adds only new files; no frozen runtime, old cost checker, prior models or
acceptance artifacts are modified. Existing live acceptance remains tied to its frozen source
identity. New abstract-model evidence is supplementary, not retroactively part of the freeze.

## Explicit cross-layer graph

```text
facade.contracts ── input validation ──► facade.adapter
facade.adapter ── output filtering ──► facade.projection
facade.adapter ── dynamic import/load/source_digest ──► scripts.read_workflow
facade.adapter ── subprocess fixed command ──────────► scripts.read_workflow
facade.adapter ── read same authoritative ledger ────► workflow ledger
scripts.read_workflow ── durable intent/results ────► workflow ledger
scripts.read_workflow ── subprocess -m bili_bridge ─► bili_bridge.__main__ ─► cli
cli ── scoped dispatch ─► kernel
cli ── bound callback injection ─► selection_consumer ─► kernel atomic selection
cli ── capability plugin/host exchange ─► trusted host ─► actual browser
```

The first validation arrow denotes information flow; the checker uses dependency direction
`facade.adapter → facade.contracts`. The adapter imports the workflow via
`importlib.util.spec_from_file_location`, calls its loader for status, and uses the same ledger;
it is not an isolated independent state machine. The workflow invokes `-m bili_bridge`, not
an imaginary independent RPC service. Its source digest includes runtime modules and the
workflow script, **not facade source**. The supplementary checker therefore hashes facade
sources separately as well as runtime sources. Hash equality records identity, not correctness.

The reviewed edges/marker checks in `check_delivery_boundaries.py` are an explicit subset,
not complete dynamic call-graph inference. The host/browser boundary is stated as an assumption,
not validated by marker presence. Existing core static graphs and the callback-provider edge
remain relevant; neither graph alone authorizes evidence reuse.

## Bounded four/five-step safety models

`formal/read_workflow_model.py` models the common prefix and explicit optional fifth step:

1. Public search navigation/capture.
2. Fresh search-results read (the sole source receipt for selection).
3. Selected-video open.
4. Video metadata read.
5. Opt-in visible comments read.

Scope: one workflow identity, one exclusive flock owner, four or five distinct child identities,
one pending child, no queue, no parallel child execution. Each child has durable intent before
launch. Exact CLI receipt matching abstracts operation ID, query/target, tab and URL checks.
The second source can expire; an invalid/stale source cannot lead to an accepted open under
assumed kernel enforcement. Child failure/partial or unknown stops further steps. Crashes retire
uncertain work; duplicate invocation/status causes no child. Success means all four requested steps with comments disabled, or all five with comments enabled, and **visible subset only**, not website completeness.

Both the default four-step comments-disabled branch and the five-step opt-in branch are exhaustively
checked in this finite abstraction. The four-step branch must terminate after metadata and cannot
launch a comments child. Both share the same search/search-read/open handoff contracts.
The facade projection/schema, invocation-ID hashing, OS flock behavior, malicious ledger files,
child process termination races, actual fsync durability, timing arithmetic and concurrent callers
outside the wrapper are NOT verified. A single flock owner is a stated assumption, not proved by
having only one modeled actor. Facade no-replay behavior is abstracted as a no-op repeated call;
that is not implementation refinement or a race proof. Valid source freshness is checked by the
kernel/host contract, not promised merely because the wrapper waited for cooldown.

Seven deliberate mutants violate respective invariants: replay after terminal state, skip durable
intent, select the first rather than second receipt, accept expired source, accept mismatched
binding, continue after failure, and duplicate child launch. Detecting these mutations is model
sensitivity evidence, not a code correctness certificate.

## Reproduction, cost and fail-closed policy

```sh
python scripts/check_delivery_boundaries.py
python -m unittest discover -s tests -p test_delivery_boundaries.py -v
```

The supplementary checker does not invoke subprocesses, touch the workflow ledger, operate a
browser, or import/execute the facade. It reads source markers, hashes inputs, and enumerates the
new model for both bounds. It reuses the existing instrumented finite-state enumerator without changing it.
It emits machine-readable measured evidence on stdout; no checked-in old report is rewritten.

Measured on 2026-10-25, current Python 3.12.14 Linux x86_64 environment:

| Variant | Reachable states | Edges | Instrumented seconds | Peak traced bytes | Observed marginal product |
|---|---:|---:|---:|---:|---:|
| 4 steps, comments false (default) | 36 | 84 | 0.00334 | 20,276 | 11,520 |
| 5 steps, comments true (opt-in) | 43 | 100 | 0.00301 | 20,340 | 27,648 |

Timing/allocation vary; rerun stdout is authoritative for that run. Observed marginal products
are not independent-variable counts or bounds on future implementations. Same engineering
budget per run: 10,000 states / 5 seconds / 32 MiB traced allocations. These are engineering
tripwires, not a universal complexity theorem. Resource overruns never count as proof passes.
All seven mutants in **each** variant must terminate with an invariant violation, not a resource
cutoff (14 mutant runs). Eight tests pass, including exact state/edge counts for both variants,
a deliberately too-small state budget, explicit dependency edges, and a forbidden comments-child
check for the default branch.

## Composition obligations still open

- Facade validation/projection must preserve workflow identity, target and partial/unknown status;
  public output must not claim completeness or silently select an unrequested target.
- The workflow ledger is the single owner of orchestration progress. Adapter status must remain
  read-only, preserve version/binding checks and never resume uncertain work.
- Workflow child requests/results must satisfy the existing CLI envelope contract. Every exact
  modeled receipt needs a refinement argument to actual validation code; this is not supplied.
- Kernel/host guarantees must discharge workflow assumptions about at-most-once navigation,
  source consumption, freshness, durable intent and receipt truth. Current individual finite
  models do not automatically establish these cross-layer implications.
- Browser-host scheduling/registration, concurrent invocations, queue limits and actual process
  crash behavior need separate implementation/integration evidence. Two live chains are examples,
  not universal correctness proofs.

For a future claim manifest, edits to workflow schema/load/source-digest logic invalidate adapter
ledger-reader claims; edits to CLI JSON invalidate workflow handoff claims; changes to kernel
selection guarantees invalidate the port and downstream open/workflow claims. A private internal
edit can have a smaller frontier only after behavioral preservation is established. A small API
surface does not imply low proof complexity unless its hidden shared state and assumptions are
also bounded and recorded.
