# Scoped live round-trip acceptance v1

This is a **new metric**, not a reinterpretation of the historical five accepted
browser primitives. No historical result has been promoted. No live operation was
performed to create this inventory.

## Frozen phase one and unresolved coverage

`acceptance/reversible-v1.json` preserves all 122 semantic leaf IDs from the dated
feature inventory. Only IDs, labels, tier and effect semantics are carried across;
no private plugin implementation, account data or private audit is included.
The source digest identifies the inventory, not executable code provenance.

The initial reviewed **semantic scope** is five existing browser primitives:

| Leaf | Restoration projection / oracle |
|---|---|
| `search.query.submit` | Restore original URL, query, filters, result page and scroll; capture distinct submitted query/results before restoring. |
| `search.results.visible.read` | Same URL/query/filters/page/scroll before and after; returned BV/URL/title matches currently rendered cards. |
| `video.search_result.open` | Open exact selected BV and confirm visible identity, then restore prior results URL/query/filter/page/scroll. |
| `video.metadata.visible.read` | Same URL/BV/scroll/paused state; returned fields match captured visible metadata. |
| `comments.viewport.read` | Same URL/BV/scroll/comment sort; report only rendered comments, explicitly distinguish empty visible state. |

Published baseline evidence accepted: **0/5 reviewed subset** (three observation-only,
two navigation). **117 leaves still need scope assessment**; the final project
reversible denominator is **unresolved**, not 122 and not 5. Phase-one semantic
review is not execution approval, verified reversibility, or final scope approval.
The remaining provisional classes are surfaced, never silently removed from the
inventory. An excluded leaf requires a reason; exclusions do not count as passes.

Initial triage totals: 31 reversible UI, 20 external state-restorable with residual
effects, 23 observation-only, 8 provisionally irreversible, 40 unknown. These
categories describe candidate contracts, not successful tests. “Unknown” includes
unverified inverse/recall behavior, privacy/read-receipt-sensitive reads, and media
processing whose output lifecycle needs assessment. Coin spending, reports and
identity-destroying deletion have no established inverse and are not test targets.

## What restoration means

Restoration is equality of the **declared state projection**, not restoration of
the entire world. Each leaf declares `restoration_scope`, `inverse` and
`irreversible_residuals`. Execution adds the exact route, target, state keys,
action/inverse and expected postcondition in `state_contract`.

For example, restoring a like bit does not retract a notification; navigating
back does not erase watch history. Residuals are listed separately and approved
before applicable external operations. A server access log alone does not make
an observational read irreversible. Account writes, creator operations and live
broadcast actions are not authorized by this document or by the user's acceptance
criterion. Exact external targets, effects and restoration must be authorized.

Observation-only operations still require actual execution and before/after/final
observations showing unchanged declared state. Their restore operation is
`verified_no_op`, not an omitted phase. Navigation is **not** observation-only.
A state-changing action must actually change the projection; clicking a toggle
already in its requested state cannot qualify as a round-trip test.

## Evidence contract and trust boundary

Every accepted leaf needs five separate, chronological event files:
`before → action → after → restore → final`. Event objects bind `leaf_id`, `phase`,
`mode: live`, `outcome: success`, nonempty `run_id`, exact `target`, `route` and
an offset-aware `observed_at`. Before/after/final carry the exact declared `state`
projection; action/restore carry `operation`. One run and one target must span all
five events. After must match `expected_after`; final must equal before.

Each event references a structured observation artifact using `{path, sha256}`.
Observation JSON includes `source: host_dom | api_response`, matching `target`,
`observed_at`, `run_id`, and matching `state` or successful `operation/outcome`.
Markdown statements and screenshots alone are not machine-readable observations.
Evidence must be captured by the trusted observer, not reconstructed from this
matrix. Keep raw account-sensitive evidence local; publication needs separate
redaction/review. Authorization and independent review have their own artifact
references; review identifies its reviewer. The checker confines file reads to the
explicit evidence root, rejects traversal/symlink escape, and verifies digests.

**Hashes prove artifact integrity, not live authenticity or consent.** The offline
gate checks structure, bindings and declared state equality. Independent inspection
of the live observation, authorization and oracle interpretation remains essential;
a fabricated JSON receipt cannot become genuine live evidence because a checker
accepts its shape. Unit tests intentionally use synthetic data and do not populate
the live matrix. No private browser/account execution occurs in the checker.

## Running the gate

```sh
python scripts/check_reversible_acceptance.py
python scripts/check_reversible_acceptance.py --require-complete
python -m unittest discover -s tests -p 'test_reversible_acceptance.py' -v
```

The default command validates an honest incomplete inventory; it may exit zero
while `acceptance_complete` is false. The release gate **must** use
`--require-complete`, which currently exits 1. `reviewed_subset_denominator` stays
computable while `reversible_denominator` remains null until all scope decisions
are resolved. No empty denominator can pass. Evidence should be supplied through
`--evidence-root`; nothing is fetched or executed remotely.

## Separately reviewed phase-one progress

A separate private evidence union has reached **5/5 independently reviewed
phase-one leaves** under the declared projections above. That scoped progress is
not the content of the published baseline matrix and does not establish full
project completion. **117 leaves remain unresolved; the final reversible
denominator is null.** The full `--require-complete` gate still fails.

The private union retains earlier blocked and rejected attempts without promotion
or overwrite. Recovery success does not establish a timeout root cause or future
reliability guarantee. Physical execution and some causal ordering/navigation
arguments depend on trusted observers and disclosed retrospective executor
attestations, not hashes or a complete original automated audit trail. No private
targets, raw captures, reviewer identities, manifests or evidence files are
published here. Synthetic tests validate contracts, not live feature coverage.

## Next live run (not performed by these offline tools)

Bind exact public targets and route; record the preflight projection; choose a
nontrivial query/navigation destination; fill expected postconditions from the
actual target; confirm current authorization and residual handling. Execute each
of the five phases, halt on a failed action, and attempt only the authorized
restoration. Record a failed restore as failure with a recovery blocker, never as
a partial success. Independently review the captured evidence before setting
`status: accepted`. Then assess the next leaf's bounded inverse and scope; do not
invent an operation to force unknown/irreversible candidates into the denominator.
