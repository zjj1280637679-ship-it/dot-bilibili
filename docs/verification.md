# Verification scope

The public source snapshot has 295 offline unittest cases (final 0.3.0 aggregate run). Reproduce them with
`python -m unittest discover -s tests -v`; run `python scripts/check_model.py` for
finite-state safe cases and deliberately unsafe mutations. The script exits
nonzero if a safe case fails or an expected counterexample is missing.
`node scripts/host_projection_smoke.cjs` exercises synthetic DOM objects only.

The Python models, TLA+ specification and configurations are first-party model
sources. No TLC binary, prior machine log or private provenance is distributed.
The Python checker is not a TLC run. Model checks establish bounded abstract
invariants under explicit assumptions, not implementation refinement, truthful
DOM/account attestation, arbitrary composition or full-program formal proof.

## Current 0.3.0 scoped acceptance

Two new five-stage workflows passed after source/recipe freeze, with different targets and independently initialized host sessions. The second used the real Python facade; a subsequent status read returned the identical result without another journal reservation. See [five-primitive acceptance](milestone-five-acceptance.md) and its sanitized evidence files. All 67 offline case slots, 18 live case slots and ten infrastructure gates passed for the frozen five-primitive scope; this is not completion of all 122 inventoried business leaves.

The aggregate 295-test run adds facade and delivery-layer model regressions to the preserved historical 261-test freeze log. Both are dated evidence, not competing counts. The supplementary model checks four-stage and five-stage paths with explicit assumptions; it does not prove OS/process races or implementation refinement.

Additional checks:
`python scripts/check_verification_budget.py`,
`python scripts/check_delivery_boundaries.py`,
`python scripts/check_milestone_five.py`,
`node scripts/host_capture_smoke.cjs`.

No new positive-comment-body live coverage is claimed: the current workflows observed accessible but empty viewports, not an absence of comments on the videos. Fixed source scopes and geometry are retained without raw page bodies. Ten earlier ad-hoc observations were excluded after host-projection evidence defects, not relabeled as passing.

## Historical 0.2 limited live acceptance, 2026-10-25

One separately recorded supported-host chain completed public-homepage search,
exact selected-result opening, independent video metadata reading and current
viewport comments reading. All four operations reached applied/observed using
the same journal and spool with normal default budgets. The exact-open primitive
was exercised live, not merely planned. Video fields were partial; description
was not visible. The comment region had zero viewport-intersecting threads,
which says nothing about total comments. A host pause action addressed incidental
autoplay; that action is not a typed plugin capability or media-understanding test.

This is a minimal historical outcome summary, not independently reproducible
public browser evidence or a performance benchmark. No operation IDs, tab IDs,
account data, private research, raw receipts, screenshots, page text or session
artifacts are distributed. Real deployment requires fresh user authorization,
current supported-host access and new end-to-end validation. No unattended or
standalone browser integration is claimed.
