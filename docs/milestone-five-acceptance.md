# Five browser primitives: frozen acceptance contract

This milestone targets **strict 5/5**, not all 122 catalogued business leaves.
Current bounded milestone result: **strict 5/5 accepted**, with 67/67 offline
cases, 18/18 live cases and G01–G10 passing. This is not all-122 completion.
The machine companion `milestone-five-acceptance.json` records every required
case, exact unittest IDs, baseline hashes and implementation/test source hashes.
The original proposed-v1 inventory is unchanged. Current 0.3.0 candidate adds a
narrow SelectionConsumer port and versioned fixed host/workflow scripts; the
kernel's shared execution/policy behavior is unchanged. The earlier all-24-files
identity snapshot is retained as `milestone-five-source-compatibility-pre-port.json`
and applies **only to the pre-port candidate**, not current live acceptance.
Current comparisons are in `milestone-five-source-compatibility.json`. Historical
captures remain historical; current release requires fresh version-bound cases.

## Common contract and trust boundary

These are five CLI-only, read-effect host-browser operations. The trusted host
must establish the user-confirmed current cloud/browser session, exact tab and
public target before collecting DOM evidence. The `account_binding` constant
and digest bind an envelope; **neither authenticates a user nor proves DOM
visibility**. A forged receipt from a malicious trusted host remains outside
this bounded protocol's guarantees. Caller-selected scripts/selectors/imports,
private account routes and generic navigation are not exposed.

All envelopes have closed schemas; UTF-8 JSON is bounded to 65,536 bytes/depth 16;
operation/correlation IDs, scope digest, target/tab and issue/expiry/capture times
must agree. Request lifetime is >0 and <=600 seconds. Navigation additionally
requires fresh preflight and a durable start checkpoint before authority is
returned. Result statuses distinguish observed from blocked; the kernel exposes
applied/blocked/unknown without fixture fallback. An execution timeout, lost
executor or orphaned pending operation stays unknown and is not replayed.
Repeated operation IDs return their immutable journal outcome, not fresh evidence.
Shared persistent budgets and cooldowns apply before execution.

Blocked errors are bounded enums (`target_mismatch`, `login_required`, `captcha`,
`browser_unavailable`, `access_denied`, `dom_unavailable`; navigation also allows
`context_changed`/`context_unavailable`). Validation failures use bounded protocol
error codes in the source contracts, never arbitrary page errors as authority.

## Exact leaf contracts

| Semantic ID | Runtime operation | Bounded observable |
|---|---|---|
| search.query.submit | browser.public_search | Nonblank query <=200 characters; source must be supported public homepage/search/video URL plus exact tab. Construct fixed public `/en/all?keyword=…`; confirmed preflight, durable navigation, exact destination capture. No arbitrary destinations or filters. Empty items are allowed and mean only no captured visible items. |
| search.results.visible.read | browser.search_results.read | Exact query/search URL/tab; <=10 video items; title <=500, uploader <=200, duration <=40, <=5 displayed counts <=100 characters. BVID and canonical public URL agree, no duplicates. Optional uploader/duration can be empty; no claim of complete search page, ad classification or unseen results. |
| video.search_result.open | browser.video.open | Select BVID from an applied journal search snapshot, <=600 seconds old; exact source operation/digest/time/query/URL/tab; unchanged visible selected anchor and current source. Single-use snapshot, invalidated by intervening exchange, consumed even when attempt becomes blocked/unknown. Exact canonical destination only; missing destination cannot become observed success. |
| video.metadata.visible.read | browser.video_page.read | Exact BVID/public URL/tab. Exactly title/uploader/description/duration/displayed_counts, each `{state: visible, value: …}` or `{state: not_visible, value: null}`. Text bounds 500/200/8000/40; counts 1–8 labels <=100. Visible subset only, not video understanding, captions or transcript. |
| comments.viewport.read | browser.comments.read | Exact BVID/public URL/tab; integer limit 1–3; open-shadow DOM currently viewport-intersecting threads only. Explicit visible/not_visible fields and truncation; ordered snapshot positions are not stable comment IDs; `complete=false`. Empty threads do not assert the video has no comments. |

Canonicalization strips only specifically allowed tracking parameters, never
semantic query parameters. Metadata and comments accept approved tracking only
on observed URLs, not request targets. All public/page text stays untrusted data.

## Frozen matrix and legitimate reuse

Every leaf requires O01–O12. Submit additionally requires N01–N03; open requires
N01–N04. All require L01–L03. Only the three reads require L04. Submit N04 is
predeclared not applicable because it does not consume a selected-result snapshot;
L04 is not assigned to either navigation leaf by the frozen source lists. No
required case is removed, weakened or passed by treating blocked as success.

The machine manifest enumerates each case and its runnable tests. O01/O02/O03/
O04/O05/O09/O12 run synthetic inputs through **each** of the five production
registry contracts. O11 combines envelope rejection with existing allowed-field
malicious-title/comment tests. Open has no arbitrary page-text field; its only
selection authority is validated BVID/URL and journal provenance, not page text.
Submit reuses the same bounded item validation as results read.

O06–O08/O10 reuse common `Kernel` and `FileBrowserHost` tests: all five plugins
execute via those same durable dispatch, host lease, timeout, replay and budget
paths, not five independent implementations. Navigation adds real temporary-file
checkpoint/transport-loss tests; open adds consumed-source persistence. These
are actual production-path synthetic tests, not model-only proofs. Formal tests
remain supporting evidence and do not add business numerator points.

G01–G10 each map positive and negative assertions in the manifest. G02 includes
synthetic exact-grant tests and rejecting changed binding/context; external-write
authorization cases S/W/A do not apply to these read-effect operations. The
trusted-session prerequisite is still mandatory in live testing. G10 explicitly
asserts a successful search record survives a later open unknown and both remain
traceable after reopening the journal. G07 tests closed fields, sanitization and
safe error handling, not magical identification of secrets embedded in arbitrary
text a compromised host claims is public.

## Live acceptance completed for this bounded version

- L01: ordinary representative object/parameter, current version, bridge receipt.
- L02: second legal object/parameter, independent fresh operation IDs.
- L03: **another genuinely new host execution session**, with new trusted binding
  and fresh operations. Predeclared procedure: a fork-none native worker first calls
  `cua.getState`, binds a browser handle without inherited REPL handles, freshly
  observes the tab, and obtains a new FileBrowserHost owner using the same durable
  DB/spool. This is not an authentication/profile turnover claim. Refreshing a tab
  or restarting only a CLI is insufficient.
- L04 (reads only): actual empty/missing-field object observed by the bridge.
  A blocked challenge is not an empty result. If no legitimate object can be
  found, retain blocked; never inject fixture text into a live receipt.

Each live record must identify version hashes, session distinction, operation
IDs, target, time, receipt and checks. Historical manual UI/source evidence is
not automatically accepted. Two fresh five-step chains passed independent raw-capture/journal review. Chain A
supplies L01; chain B supplies L02 and separately initialized host-session L03.
The same B evidence can satisfy these distinct conditions; it is not counted as
two executions. Chain A supplies L04: a real result card has hidden duration and
empty displayed counts; metadata title/uploader are offviewport; accessible
comments have four rendered threads but zero intersecting the viewport.
Public summaries are `evidence/strict-chain-a.json` and `evidence/strict-chain-b.json`,
referenced by SHA-256 and operation binding in the machine manifest. They omit raw
URLs/hrefs, queries, object IDs, tab/account identifiers and page text. Their
hashes establish file linkage, not an independent cryptographic DOM proof.

The prior ten ad hoc observations remain excluded because their host procedure
canonicalized URLs before validation. Fresh strict captures replaced that evidence;
the earlier defect is not relabelled as a pass. Both accepted chains returned an
empty comments viewport: **positive comment-content live extraction is not
established**. Incidental autoplay was paused; no explicit comment scroll,
account write, private read or auth action is claimed. Chain B used the real local
facade and a read-only status check with zero added reservations, not native chat
tool registration.
Strict completion requires every applicable offline/live case and G01–G10 pass,
no unresolved high-severity defect, and version-applicable evidence. No statistical
uptime or all-platform completeness is claimed.

## Reproduce

From repository root:

```sh
python -m unittest discover -s tests -v
python scripts/check_milestone_five.py
```

`milestone-five-offline-tests.txt` is the captured 261-test run. Manifest source
hashes bind the frozen execution candidate; this 261-test run remains dated offline
evidence. Subsequent additive facade/boundary tests are separate supplementary
evidence and do not rewrite that run. The post-live administrative checker now
verifies actual public proof files/hashes and operation/source bindings; it does
not independently prove trusted-host DOM claims.

## Final aggregate and current AI entry status

The final 0.3.0 aggregate suite independently passed **295 tests** after adding facade and both four/five-stage delivery-model checks. This supplements, rather than rewrites, the preserved 261-test execution-freeze log. All model/budget/boundary checks and both Node capture smoke checks passed. See release-0.3-validation.json.

The real Python facade was exercised by chain B, including zero-new-reservation status lookup. Native chat-tool registration remains unimplemented. docs/ai-tool-facade.md is deliberately preserved as the pre-live interface snapshot bound in facade/SHA256SUMS; its former pending-live wording describes that snapshot, not the current accepted result. Current usage/status: [AI tool usage](ai-tool-usage.md).
