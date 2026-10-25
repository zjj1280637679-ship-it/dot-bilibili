# Opt-in v3: bounded mixed search-card selection

**Status: implementation and synthetic offline checks only. Not released, not a
successful live-page capture.** The original real-page `target_mismatch` remains
failed; neither its evidence nor historical source manifests are rewritten.

## Positive contract

The fixed adapter inspects the first **10 intersecting recognized cards**, in DOM
order. It does not scan farther to replace exclusions. Each inspected card must
first have exactly one recognized, visible, nonempty, bounded title using the
unchanged 18-input v2 heading relation. Its nearest anchor must be contained in
that same card. This ties identity to the title actually read, rather than a
nearby or fabricated URL. It does not assert that every decorative/cover link in
the card agrees, or inspect off-window cards.

`search_card_scope_v3.classify(raw, titleReady, containedAnchor)` is pure:

| Evidence | Result | Invariant protected |
|---|---|---|
| Exact HTTPS `www.bilibili.com/(en/)?video/BV<10 ASCII alphanumerics>[/]` | `{kind:video,url,bvid}` | BV derives from the title anchor; only existing public-video targets enter selection |
| Exact HTTPS `cm.bilibili.com/cm/api/fees/pc/sync/v2`, optional opaque query | `{kind:advertisement}` | Positively identified advertising surface stays outside video authority |
| Exact HTTPS `www.bilibili.com/cheese/play/ss<1–20 digits, positive>[/]`, optional opaque query | `{kind:course}` | Positively identified course surface stays outside video authority |
| Any other URL, malformed type, whitespace/control/backslash, fragment, >8192 code units | `target_mismatch` | Unknown or normalization-dependent identity cannot be silently lost |
| Missing/ambiguous/hidden/unbound/empty/overbound title | `dom_unavailable` | Exclusion is based on recognizable visible card evidence, not an error-catching fallback |

Protocol-relative `//` spelling is resolved only by prefixing `https:`. There is
no URL parser normalization, redirect following, query decoding, network call,
click or enlarged navigation-domain allowlist. Non-video query bytes are opaque:
they cannot supply a BV and are not returned. These URLs identify exclusions,
not evidence that a remote destination or tracking payload is safe. The private
failure showed the `sync/v2` and `ss` structures; public fixtures use synthetic
identities and query text. Other ad paths and `ep` courses remain unknown.

Selected items and selected `raw_hrefs` preserve order. One unknown card anywhere
inside the window rejects the whole capture, even between known exclusions.
Diagnostics contain `coverage.scope=visible_subset`, intersecting/inspected counts,
window truncation, selected source indices, and exclusion indices/reasons only.
Indices are zero-based within the intersecting-card window. No excluded title,
URL, tracking value or BV is emitted. All-excluded yields an empty visible subset,
not an assertion that the search has no videos. No cards remains unavailable.

The card window bounds classification/output, **not** `querySelectorAll`, viewport
filtering or browser layout cost. The source URL must remain unchanged during
capture. Metadata/comments delegate to frozen v1 and only change recipe label.

## Adoption and relation boundary

Run `python scripts/compose_host_capture_v3.py` locally to obtain one pinned,
self-contained read-only closure. Call it with the existing `{kind,limit}` only.
`limit` is the inherited **comments-only count bound** (1..3), not a search
result limit. Search always inspects the first ten intersecting recognized cards
and may return 0..10 selected public videos; `{kind:'search',limit:3}` does **not**
promise at most three items. Video mode reads one page's metadata fields, not a
list bounded by `limit`. The common request shape validates `limit` for every
kind for compatibility; only comments uses it to cap returned threads.

No paths, selectors, callbacks, arbitrary code, profile or authority enter the
business API. Composer verifies four fixed source hashes before emitting code;
CommonJS globals are shadowed. Preserve selected raw hrefs, full observed URL,
timestamp and private diagnostics; build only existing closed receipt fields.
Diagnostics must **not** be inserted into Python receipts. Public projection
remains `visible_subset`. Exact selected BV, freshness, context/preflight,
operation budget and shared ledger remain enforced by the unchanged downstream
contracts; this module grants no independent navigation or retry capability.

The default `bili_video_reference.cli instructions` still names v2. This is an
explicit opt-in source candidate for the separately authorized browser task;
release/default-route changes belong to root after that task. No account/shared
state, plugin bundle, checksum manifest or published evidence was changed.

v1/v2 source and composer bytes are frozen to keep previous hashes replayable.
v3 reuses v1 non-search capture and v2 heading relation, replacing only search
composition. It does not load the v2 search collector. Historical sources are
compatibility artifacts, not templates to clone indefinitely: subsequent scope
rules should evolve this small pure module with a versioned pin/manifest;
shared search DOM utilities can be extracted with equivalence tests when a
later change justifies that migration. Old evidence proves only its pinned old
source; new evidence below covers only the new pins and listed offline cases.

## Verification budget and limits

Run `PYTHONPATH=.:tests python -m unittest tests.test_host_capture_v3
 tests.test_host_capture_v2 tests.test_browser_public_search
 tests.test_browser_video_open tests.test_video_reference
 tests.test_video_reference_relation` (join as one command).

- Pure heading relation: exhaustive 18 inputs, unchanged.
- Scope/selection correspondence: all 1,364 nonempty sequences of four abstract
  classes (video/ad/course/unknown), lengths 1–5, run through actual composed DOM
  adapter; concrete tests cover window edge 10/11, hostile URLs, malformed title,
  exclusions-only, mixed order, cross-card anchor, URL changes and privacy.
- Five actual source mutations must fail independent assertions: unknown skip,
  reorder, excluded-href leak, window expansion, unbound title.
- Selected items pass unchanged Python public-search receipt validation; an
  injected URL/BVID disagreement is rejected. Existing navigation/core suites
  retain the downstream authority checks.
- Engineering gate: Node old-space cap 64 MiB; Python subprocess timeout 10 s.
  Exceeding either fails. Heap cap is not total RSS; timeout covers the composed
  synthetic test process, not browser DOM execution. Four pinned JS components,
  zero third-party dependencies/new kernel injections; no product model growth.

These are finite synthetic correspondence and mutation tests, not exhaustive
string-space, DOM, browser, end-to-end formal proofs or live acceptance. A new
real mixed-page run must separately establish visible geometry, classification,
selection, receipt acceptance, public coverage and cleanup under existing
account/ledger constraints. Preserve the original failure alongside that run.

### Complete ten-card quotient argument (additional deliverable gate)

`formal/search_card_scope_model.py` enumerates all 2,047 normal states `(n,mask)`:
`0 <= n <= 10`, with a bit for each processed video position, plus one rejecting
absorbing state. Exclusion positions are the complement. Ad/course reason labels,
raw strings and video identity values are quotiented away **only** for these
properties: ordered selection, unknown rejection, excluded-payload non-disclosure,
and no replacement scan beyond ten input cards. Distinct reason labels are still
checked by classifier/source tests; arbitrary strings, URL grammar and DOM mapping
are not proven by this quotient.

Each of the 2,048 states has four checked next-class transitions: **8,192 edges**.
The initial empty state satisfies the invariant. Each normal edge either appends
only the current video index, appends only an exclusion index with no payload, or
rejects the entire output. Every edge preserves the partition and increasing
selection order. Rejection is absorbing. At `n=10` all four inputs leave state
unchanged, so by induction any length/type of suffix also leaves output unchanged.
Thus the quotient covers all sequences through the full ten-card window, not just
length five, without enumerating every concrete history. Five model mutations
(unknown skip, reordering, payload leak, backfill, resuming rejection) must fail.

The composed **source**, separately, is tested on all 8,188 normal representative
prefix/next-class edges. Every `n/mask` is exercised; representative prefix
exclusions alternate ad/course, and each next-class includes both. At n=10 this
explicitly checks an eleventh video/ad/course/unknown card is not consumed. These
are concrete correspondence tests, not an implementation refinement proof: they
do not quantify over every DOM, string or ad/course history. The model proof and
finite source tests must not be conflated.

`python scripts/check_search_card_scope_model.py` enforces 10,000 states, 5 seconds,
and 32 MiB traced Python allocations for the full base+mutation model check;
traced allocations are not RSS. Actual source correspondence retains the separate
10-second subprocess and 64-MiB Node old-space gate. Measured results are recorded
in `host-capture-v3-offline-validation.json`. The browser handoff is
`host-capture-v3-browser-runbook.md`; candidate component and closure pins are
unchanged by these additional tests.

### Future API simplification (not this live candidate)

A future separately versioned API could expose `limit` only on comments and omit
it from search/video requests, or name it `comment_limit` in a discriminated
request schema. That would make the actual bound explicit without introducing a
second search budget. This is a design suggestion only: no current signature,
receipt, production source, source pin or live candidate behavior changed.
