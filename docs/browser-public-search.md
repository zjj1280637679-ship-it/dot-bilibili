# Public-search navigation primitive

`browser.public_search` adds one bounded public search transaction to the trusted
cloud-browser relay: **source preflight → durable navigation checkpoint → one
same-tab navigation → visible capture**. Existing search-read and video-read
schemas are unchanged. No generic URL, script, selector, extension, cookie,
private route, account mutation, media playback or transcript capability exists.

```sh
python -m bili_bridge --db search.sqlite3 browser-public-search \
  --query '公开搜索词' --source-url 'HOST_OBSERVED_PUBLIC_URL' \
  --tab HOST_OBSERVED_TAB --spool /explicit/private/spool \
  --timeout 120 --operation-id UNIQUE_OPERATION
python scripts/browser_host_exchange.py --spool /explicit/private/spool claim
python scripts/browser_host_exchange.py --spool /explicit/private/spool \
  begin-navigation --preflight preflight.json
# Trusted host now navigates ONCE to the returned destination_url in tab_id.
python scripts/browser_host_exchange.py --spool /explicit/private/spool \
  submit --receipt receipt.json
```

The CLI sanitizes source tracking **before** sending scope to the durable kernel.
Direct programmatic callers must likewise pass canonical `source_url` to Request;
all callers are trusted first-party adapters, not hostile in-process code.
Only explicit public homepage and existing public search/video source routes are allowed.
Homepage sources are exactly `https://www.bilibili.com/`,
`https://www.bilibili.com/en`, or `https://www.bilibili.com/en/`, with no query
(including tracking), fragment, userinfo or port. `/en/` canonicalizes to `/en`;
the English locale is never collapsed into `/`. Private message/history/account
routes remain rejected. The destination is still the same fixed public search URL. The host compares
its freshly observed raw source URL through the strict source canonicalizer,
not a guessed or relabeled expected address. Known tracking is discarded;
unknown or semantic parameters are rejected. Locale video aliases identify the
same public BVID; search source paths remain exact after tracking removal.

## Exact shapes

Request:
```
protocol_version=1, schema_version=1, operation='browser.public_search',
operation_id, correlation_id, scope_digest,
account_binding='user_confirmed_cloud_session', effect='read',
query, source_url, source_tab_id, destination_url, issued_at, expires_at
```

The program generates `destination_url` exactly as
`https://search.bilibili.com/en/all?keyword=<urlencode(query)>`. Query is nonblank,
≤200 characters; URL ≤2048 characters; lifetime ≤600 seconds; payload ≤64 KiB.
No destination argument is accepted by the CLI. The digest binds all fields.

Preflight:
```
protocol_version, schema_version, operation, operation_id, correlation_id,
scope_digest, observed_source_url, tab_id, checked_at, context='confirmed'
```
The trusted host must confirm the existing user-confirmed cloud session/context,
source and tab without reading private account data or exporting identifiers.
`begin-navigation` requires a live owner and claim, matching scope, a fresh
post-claim preflight and no prior checkpoint/submission. It atomically persists
sanitized preflight and `navigation_started_at` with fsync **before** returning
`{destination_url, tab_id}`. This is write-ahead intent, not proof of navigation.
Do not navigate if it fails or its response is lost. Do not retry navigation after
uncertainty. One claim and one begin are allowed per lease. The durable kernel
journal is the cross-operation no-replay boundary; the spool alone only retains
its latest operation ID. Shared DB/spool/lease policy remains required.

Receipt:
```
protocol_version, schema_version, operation, operation_id, correlation_id,
scope_digest, query, tab_id, observed_url, captured_at,
source='browser_dom', status='observed'|'blocked',
phase='preflight'|'capture', context='confirmed'|'changed'|'unavailable',
items, error
```
For observed results: capture must be after the durable checkpoint and within the
lease; phase=capture, context=confirmed, error=null. Recheck actual same tab,
destination query and session/context after navigation. Items reuse the unchanged
search-result schema: ≤10 public videos with title/url/bvid/uploader/duration/
displayed_counts. Capture only the visible subset, never claim completeness.
Destination accepts `/en/all` and `/all` locale-equivalent pages with identical
decoded keyword, plus only existing known tracking `from_source`, `spm_id_from`,
`search_source` (1–100 alphanumeric/underscore/dot/hyphen characters). Receipt
URLs normalize to the generated destination before persistence. Reject duplicate,
unknown or semantic keys (`p`, `page`, `order`, filters), fragments, credentials,
ports and malformed encoding. No page/filter changes, scrolling or pagination.

For blocked: items=[], safe error from `target_mismatch`, `context_changed`,
`context_unavailable`, `login_required`, `captcha`, `browser_unavailable`,
`access_denied`, `dom_unavailable`. Preflight blocking before navigation requires
phase=preflight, observed_url=null and no checkpoint. Capture blocking requires
an existing checkpoint; observed_url may be null when target cannot be established.
Never fabricate the expected URL as observed evidence. A capture-blocked receipt
means no usable results, **not** that navigation did not happen. Transport loss,
expiry or owner death after emission produces unknown, without automatic replay.

## Boundaries and verification

Budget is one semantic public-search transaction (at most one navigation and
bounded capture), not every browser HTTP/asset request. User/background browser
activity lies outside the bound. Completion/unknown cooldown shares the existing
spool. `serve` remains metadata-only. This is host-mediated, not an autonomous
browser service. Public navigation may itself produce site-side history effects;
there is no assertion of zero incidental browser/server state change.

Context and source are trusted-host attestations, not cryptographic account
identity, DOM authentication or proof that a browser actually navigated. The
finite model proves its abstract phase invariants under those assumptions only.
Offline tests and synthetic receipts are not live evidence. Real acceptance
requires a new program request, fresh source observation, successful checkpoint,
one real supported-tool navigation, fresh visible capture, submitted receipt and
an applied durable journal result.


### Recorded integration status

A live host-mediated chain on 2026-10-25 exercised the public homepage source,
public search, exact result opening, independent video metadata reading and
current-viewport comment reading. This is a limited acceptance result, not a
reliability guarantee. See [verification](verification.md). The `/en` and `/en/`
homepage aliases remain covered by offline contract tests, not separate live trials.
