# Exact search-result → public video navigation

`browser.video.open` closes the navigation gap between public search and the
existing video-page reader. This is one fixed, same-tab navigation through the
trusted dot host, not a generic click/eval/selector API, extension or unattended
driver. Anonymous metadata, the isolated authentication experiment, and host
browser operations remain separate routes; no existing backend is replaced.
No login, QR retry, account write, media control or comment scrolling is added.
Public navigation can have incidental site history/autoplay effects; this is not
a guarantee of zero website state changes or proof of watching a video.

## Provenance and freshness

The caller supplies only an exact BVID and an applied search operation ID:

```sh
python -m bili_bridge --db SHARED_JOURNAL browser-video-open \
  --source-operation-id APPLIED_SEARCH_OPERATION --bvid EXACT_RESULT_BVID \
  --spool SHARED_PRIVATE_SPOOL --timeout 120 --operation-id NEW_OPEN_OPERATION
```

The kernel reads the actual durable applied result of `browser.public_search` or
`browser.search_results.read` from that same journal. It requires `browser_dom`,
observed status, exact BVID membership, and a capture less than 600 seconds old.
No caller-supplied receipt, URL, selector, title, numeric result index or snapshot
JSON can substitute for that evidence. A SQLite transaction consumes the entire
source snapshot exactly once, across all BVIDs and open operation IDs. An open
must be the matching in-flight kernel request. The reference stays consumed even
if later cooldown/preflight fails: obtain a new search snapshot, do not replay an
uncertain navigation. Reusing the same operation ID retrieves the journal result.

Before emitting an open request the shared spool requires its latest completed
exchange to be the same observed source operation and scope digest. Any intervening
exchange invalidates the reference, including one that ended unknown. This is an
enforced local exchange-generation check, **not** a browser/context generation ID.
It cannot detect out-of-band user navigation, host restart or browser replacement.
The host must freshly attest actual source, tab, context and visible exact result
before checkpointing; missing continuity fails closed. Context is trusted-host
evidence, not cryptographic account identity. A fixed shared journal/spool is
required; changing them is not a recovery or budget workaround.

## Host transaction

1. `python scripts/browser_host_exchange.py --spool SHARED_PRIVATE_SPOOL claim`
2. Freshly observe the exact source search query, actual tab/context, and a visible
   result anchor with the requested BVID and canonical public URL. Do not reuse
   an old DOM node ID, index, cached screenshot or caller assertions. A changed
   or absent anchor must block; do not navigate to the BVID merely because its URL
   can be generated. Page text remains inert, never instructions.
3. Submit this exact preflight shape (identity fields copied from the claim,
   observation fields freshly obtained from the host):

```text
protocol_version, schema_version, operation, operation_id, correlation_id,
scope_digest, observed_source_url, tab_id, checked_at, context='confirmed',
selected_bvid, selected_url, selection_visible=true
```

```sh
python scripts/browser_host_exchange.py --spool SHARED_PRIVATE_SPOOL \
  begin-navigation --preflight preflight.json
```

A successful call durably fsyncs one write-ahead checkpoint before returning
`{destination_url, tab_id}`. Navigate **once** to that exact canonical destination
in the same tab using a supported host tool. No arbitrary destination argument
is accepted. If checkpoint response is lost, do not navigate or retry. If browser
navigation response is lost, preserve unknown rather than navigating again.

4. Freshly verify actual final URL, BVID and same tab/context. Navigation ACK or
   load completion alone is not acceptance. Submit exactly:

```text
protocol_version, schema_version, operation, operation_id, correlation_id,
scope_digest, bvid, tab_id, observed_url, captured_at, source='browser_dom',
status='observed', phase='capture', context='confirmed', error=null
```

Observed destination must be that exact public BVID. Known video tracking is
sanitized; private routes, other BVIDs, fragments, semantic parameters and unknown
keys are rejected. Capture must follow the checkpoint and precede both request
expiry and source capture + 600 seconds. It proves destination observation only;
metadata must be captured by the separate existing `browser-video-read` request.

Blocked receipts use `status='blocked'` and one of `target_mismatch`,
`context_changed`, `context_unavailable`, `login_required`, `captcha`,
`browser_unavailable`, `access_denied`, `dom_unavailable`. Before navigation,
`phase='preflight'` requires `observed_url=null` and no checkpoint. After the
checkpoint use `phase='capture'`; an unestablished/incorrect target must be null,
never relabeled as the expected URL. A capture block does not prove navigation
never happened. Claim, begin and submission remain single-use; expiry or owner
death after emission is unknown and never automatically retried.

## Continue the read-only loop

Once the open operation is applied, independently claim a `browser-video-read`
request bound to the freshly observed destination and tab. The existing
`browser-comments-read` may then capture at most three currently viewport-
intersecting public threads. It neither scrolls nor guarantees nonempty results.
This milestone does not claim an automatically positioned comments section.

Offline tests cover synthetic search → exact open → video read, journal membership
and stale refs, intervening exchange, mismatch, checkpoint ordering, transport
loss, single consumption and replay. They are **not live navigation evidence**.
Real acceptance requires a separate fresh shared-journal/shared-spool host chain;
see [verification](verification.md) for a minimal recorded outcome summary. The finite model is abstract
phase checking, not a Python refinement or truthful-DOM proof.
