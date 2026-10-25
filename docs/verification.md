# Verification scope

The public source snapshot has 216 offline unittest cases. Reproduce them with
`python -m unittest discover -s tests -v`; run `python scripts/check_model.py` for
finite-state safe cases and deliberately unsafe mutations. The script exits
nonzero if a safe case fails or an expected counterexample is missing.
`node scripts/host_projection_smoke.cjs` exercises synthetic DOM objects only.

The Python models, TLA+ specification and configurations are first-party model
sources. No TLC binary, prior machine log or private provenance is distributed.
The Python checker is not a TLC run. Model checks establish bounded abstract
invariants under explicit assumptions, not implementation refinement, truthful
DOM/account attestation, arbitrary composition or full-program formal proof.

## Limited live acceptance, 2026-10-25

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
