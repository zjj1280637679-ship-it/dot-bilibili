# Fixed host capture v2: explicit search-card relationship

This additive recipe is only selected by the new `bili_read_video` route.
The old integration CLI and frozen `host-capture-v1` remain unchanged.
This is read-only DOM evidence, not media comprehension or browser authority.

## Architecture and closed relation

- `search_card_variant_v2.js`: pure relation on two heading counts saturated
  at 2 (many) and a featured-shape boolean. Exactly 18 possible inputs; only
  `(1,0,false)`, `(1,0,true)` select legacy and `(0,1,true)` selects featured.
  All other inputs fail `dom_unavailable`. No selector fallback or skipping.
- `host_capture_recipes_v2.js`: fixed DOM adapter maps heading occurrences to
  this relation, then uses the selected heading/author pair. Its only ports are
  the pure relation and frozen v1 capture. No whole browser/session injection.
- Legacy: exactly one `.bili-video-card__info--tit`, zero `__av--tit` headings;
  author `.bili-video-card__info--author`.
- Featured: exactly one `.bili-video-card__av--tit`, zero `__info--tit` headings;
  card matches `.bili-video-card.bili-video-card-grid` and heading matches
  `h3.bili-video-card__av--tit.text_ellipsis`; author `__av--author`.
  The observed `__av--desc` is intentionally not extracted: search has no
  description field in the unchanged receipt contract.
- Missing, multiple, ambiguous, wrong-shape, hidden, empty, or overbound titles
  fail closed. The selected heading's `closest('a')` raw href must pass the
  existing exact public video URL allowlist. No fabricated URL from a BVID.

The initial failed v1 case remains failed. A later fixed-recipe execution is a
new separately authorized invocation, not changed cached evidence. Read-only
post-terminal diagnosis confirmed a visible featured H3 whose closest anchor
raw href had the shape `//www.bilibili.com/en/video/BV1234567890/`
(video identity replaced with a synthetic fixture). This supports the narrow
layout selector only; it is not successful v2 live acceptance.

## Trusted host runbook

1. Run `python -m bili_video_reference.cli instructions` locally. It returns
   version, v2 entry path/hash, ordered component paths/hashes, and composed hash.
2. Run `python scripts/compose_host_capture_v2.py` locally. The composer accepts
   no business parameters/source paths and verifies every component's pinned
   SHA-256 before emitting one self-contained function. The printed newline is
   not part of `composed_function_sha256` (hash `compose()`'s UTF-8 string).
3. After existing source/tab/context preflight, submit that single function to
   the supported read-only DOM evaluator with only `{kind, limit}`. Do not
   install files as page globals, use script tags, or execute caller code.
   Constants and CommonJS names are local to the evaluated closure; even a
   page-provided `module` cannot receive writes.
4. Preserve full `observed_url`, `raw_hrefs`, capture time and recipe/hash audit
   evidence. Additive diagnostics record each selected card's variant. Build
   only the existing closed receipt fields; run unchanged Python validators.
   Never strip semantic URLs or add recipe diagnostics to closed receipts.
5. Retain the old workflow's operation budget, durable checkpoints, stable
   invocation IDs, authoritative ledger and unknown/reconcile rules. No new
   browser navigation, auth/account writes, fallback, scrolling or retries are
   granted by a recipe. Stop on challenge/consent/context changes.

Search still filters recognized cards by viewport and caps at ten in DOM order;
no recognized cards is an error, whereas no intersecting cards yields empty
items. A bad first intersecting card fails the capture rather than moving on.
Raw hrefs, complete observed URL and in-function timestamps are preserved.
Metadata and comments call the frozen v1 function unchanged; only output
`recipe_version` becomes `host-capture-v2`. Comment limit, Unicode rules, open
shadow-root access, geometry bounds and absence semantics remain v1's.

## Offline verification / proof boundary

`node scripts/host_capture_v2_smoke.cjs` executes the actual composed closure,
exhaustively checks all 18 pure relation inputs, and covers bad domains/types,
ambiguous/duplicate/missing/hidden/wrong-shape headings, no-skip-first behavior,
unsafe hrefs, exact observed `/en/` raw href, ten-card/count/text/time bounds,
URL changes, no-global mutation, legacy equivalence, metadata/comments
regression and unchanged Python semantic-URL validation.

This is a bounded relation and synthetic DOM regression check, not a browser
proof or new end-to-end formal verification claim. Existing abstract model,
Python receipt validators, contracts, ledger, kernel and facade are unchanged.
New imports are only CLI→`hashlib`, existing `facade.adapter.ROOT`, and fixed
composer; composer imports `hashlib` and `pathlib`. No third-party dependencies,
new kernel injections or expanded business ports. The relation has 18 states;
existing state/runtime/memory/import budgets are rechecked separately without
modifying historical manifests.

Bounds caveat: output card/thread/text caps do not bound enumeration of every
recognized DOM card or thread. Geometry/display/visibility checks do not prove
opacity or occlusion, and host authorization/context checks remain mandatory.
