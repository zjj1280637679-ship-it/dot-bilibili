# Historical v3 independent browser acceptance handoff

> Public sanitized copy of the pre-release handoff. Statements about pending live
> acceptance and default v2 instructions below describe that historical stage,
> not current release status. Current 0.3.3 bootstrap and accepted-scope summary
> are in [the current guide](installable-integration-v033.md) and
> [acceptance scope](release-v033-acceptance-scope.md). This copy is not new live
> execution evidence and is not returned by current installed instructions.

This runbook grants no new authorization. Use the already approved serial browser
worker, source/tab preflight, durable journal/spool and shared operation budget.
Do not create another ledger, use another worker concurrently or bypass cooldown.
Implementation and offline gates are complete; live acceptance is still pending.

## Exact candidate and pins

Repository: `<repo-root>`.

Do not use `bili_video_reference.cli instructions` to select this candidate: that
historical/default path intentionally still points to v2. Instead, locally:

```python
import hashlib
from pathlib import Path
from scripts.compose_host_capture_v3 import compose, PINNED_SHA256
function = compose()  # verifies all four fixed source hashes before producing code
assert hashlib.sha256(function.encode()).hexdigest() == (
    'cec9e3b20fe9f2331de33ef286bc114b9afe4f14e68f620b0b5558dde8f95a60')
# Save function and a private manifest containing version, components and hash.
# function itself has no trailing newline; CLI print adds one, so hash compose().
```

`PINNED_SHA256` is the authoritative ordered component list: frozen v1 capture,
frozen v2 heading relation, new scope v3 relation, new v3 collector. Record each
component path/hash, the composed-function hash and `recipe_version=host-capture-v3`
in the **private recipe/capture evidence**, not in the closed receipt. If pins fail,
stop; do not dynamically replace expected hashes. Source tests/model additions
do not change this candidate closure hash.

Evaluate that **one function** using the supported read-only DOM evaluator with
only `{kind:'search',limit:3}` (or existing video/comments kinds and limit 1..3).
**Parameter semantics:** `limit` bounds comments only. Search uses a fixed
first-ten-intersecting-card inspection window and can return up to ten videos;
`{kind:'search',limit:3}` does not promise <=3 items. Thus seven videos plus two
course exclusions and one ad exclusion is consistent with a ten-card window.
Video mode returns one page's metadata fields. The inherited common argument
validator still requires any supplied `limit` to be an integer 1..3 for every
kind, even where it does not affect output size. Keep actual arguments and result
counts in evidence; never truncate or rewrite capture evidence to fit `limit`.

Never install page globals, concatenate caller code/selectors, or supply arbitrary
sources. Reuse existing trusted worker capture → receipt construction logic,
substituting this fixed composer/function only. It must not broaden navigation.

## Capture-to-receipt boundary

- Keep full `observed_url`, `captured_at`, selected `items` and selected `raw_hrefs`
  from the capture; preserve raw evidence privately before projection.
- Construct the unchanged public-search receipt using request identity/scope/query,
  requested tab ID, full observed URL, in-function capture time, `source=browser_dom`,
  `status=observed`, `phase=capture`, `context=confirmed`, selected `items`, `error=null`.
  Use existing worker checks for each item/raw href pair and Python validation.
- Do not add `recipe_version`, `diagnostics`, `raw_hrefs` or coverage keys to the
  closed receipt schema. Store those separately as host evidence. Do not strip
  semantic URL components to make validation pass.
- On collector exception follow the existing blocked/error settlement flow; do
  not fabricate empty items or an observed success. Preserve the original failed
  run and this new run separately.
- Any later video selection/navigation must use the unchanged exact BV, source
  freshness, claim/preflight/checkpoint and shared-budget chain. Excluded items
  have no selectable URL/BV and must never become click targets.

## Required observations and verdict

Prefer a genuinely visible mixed window containing recognized ad/course and at
least one public video. Record source DOM/viewport geometry without changing
scope merely to make a favorable fixture. Existing authorized five-stage flow
and restoration/cleanup must be observed independently; no implicit scroll,
retry, new operation ID or navigation is authorized by this runbook.

1. Verify the capture reports v3, the pinned closure, unchanged source URL and
   exact source/tab context; all selected titles intersect the viewport.
2. Inspect coverage: first ten intersecting recognized cards only; selected
   indices and exclusions partition the inspected window; order is retained;
   no replacement scan after exclusions; `window_truncated` reflects >10 visible
   recognized cards. Unknown card inside the window must block, not be skipped.
3. Only exact public-video hrefs appear in selected items/raw_hrefs; ad/course
   evidence contains index/reason, never their URL/tracking value. Keep any raw
   diagnostic tracking links private; public reporting uses synthetic identities.
4. Confirm unchanged Python receipt acceptance and public result projection with
   `visible_subset`. All-excluded or no-intersecting-card output may be valid but
   does **not** establish useful mixed-video success or search completeness.
5. Confirm durable terminal settlement, no pending request, restoration/cleanup
   evidence, and final state as required by existing acceptance protocol.

Report actual outcome (accepted, blocked, unavailable or inconclusive), evidence
paths/hashes and unresolved gaps. Offline model/source passes are never substitutes
for this observed result. If current DOM lacks qualifying mixed cards, report that
coverage gap rather than manufacturing or silently widening the test.
