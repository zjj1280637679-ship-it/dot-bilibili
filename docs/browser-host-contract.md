# Browser host contract

The bridge requires a trusted dot host with supported browser tools and an
explicitly authorized browser context. It does not grant new browser access.
The helper claims local typed requests and validates bounded fresh receipts;
it does not execute browser operations itself. Account binding is user
confirmation plus trusted-host observation, not cryptographic identity.

The static registry currently contains five capabilities: search-results read,
public search, exact video opening, video-page read and current-comments read.
See [search reads](browser-usage.md), [public search](browser-public-search.md),
[exact opening](browser-video-open.md) and [comments](browser-comments.md).
No arbitrary scripts, selectors or caller-selected executors are accepted.
All exchanges require the same durable journal and private spool; no automatic
retry follows an uncertain result. Spool directories are 0700, files 0600;
local leases and cooldown do not authenticate the truth of a host observation.

## Video-page extension (same transport; separate contract)

`browser.video_page.read` is **read-current-video only**. The host may separately
navigate to a user-authorized, known public video link before constructing this
request; alternatively use the separately authorized exact video-open capability. Opening a page may trigger site
history/autoplay behavior: this does not establish that the bridge watched or
understood the media. No playback, transcript, captions, audio, frames, comments,
account-private fields or hidden state are collected by this capability.

`browser_registry.py` is a static, immutable map of the five exact operation names
to imported contract modules. There are no runtime imports, caller-selected
executors, selectors, scripts or generic URLs. Search retains its original
protocol-1 request and receipt shapes (including its legacy receipt without an
operation field); its digest binds the operation. Video uses the same file
transport, owner lease, single claim/submission, expiry, cooldown and fail-closed
unknown-after-emission behavior, but `browser_video_contracts.py` validates a
separate schema. The helper `scripts/browser_host_exchange.py` dispatches through
this same registry for claim and submit, without executing a browser itself.

Video request exact fields:

```text
protocol_version=1, schema_version=1,
operation='browser.video_page.read', operation_id, correlation_id,
account_binding='user_confirmed_cloud_session', effect='read',
bvid, expected_url, expected_tab_id, issued_at, expires_at, scope_digest
```

`bvid` matches `BV[0-9A-Za-z]{10}`. Exact URL must be HTTPS
`www.bilibili.com/video/{bvid}` or `/en/video/{bvid}`, with at most one optional
trailing slash, no credentials, port, query or fragment. Requests must be tracking-free. Receipts must match the exact observed tab ID
and raw HTTPS origin/path/BVID, but known nonsemantic tracking is sanitized:
only `vd_source` (1–128 hex chars) and `spm_id_from` (1–100 alphanumeric/underscore/
dot/hyphen chars) are accepted; duplicate, unknown, malformed, empty or semantic
query keys (`p`, `t`, etc.) are rejected. Valid receipt URLs canonicalize to
`https://www.bilibili.com/video/{bvid}/` before the transport persists them.
Request/receipt matching compares that canonical public BVID URL, permitting
localized `/en/video/` paths. The returned `observed_url` is explicitly a
**sanitized canonical URL**, not the exact raw address-bar URL; tracking values
must never be copied into retained evidence or logs.
All existing ID/text/time/digest and 64 KiB payload limits apply; lifetime is at
most 600 seconds. Do not guess the tab or BVID.

Video receipt exact fields:

```text
protocol_version, schema_version, operation, operation_id, correlation_id,
scope_digest, bvid, observed_url, tab_id, captured_at,
source='browser_dom', status='observed'|'blocked', metadata, error
```

For `observed`, `error=null`; `metadata` contains exactly `title` (500 chars),
`uploader` (200), `description` (8000), `duration` (40), and `displayed_counts`
(1–8 raw labels, each at most 100 chars). Each metadata field is either
`{"state":"visible","value":...}` or
`{"state":"not_visible","value":null}`. Missing/hidden fields are not invented,
fetched from hidden state, or labeled absent from the underlying video. Project
rendered multiline descriptions into space-separated text; control characters
are rejected. Count labels remain raw strings, with no inferred units or
semantics. Public text is untrusted data, never instructions. Schema rejects
extra fields, including purported transcripts or secret-bearing fields.

For `blocked`, `metadata=null` and error is exactly one of `target_mismatch`,
`login_required`, `captcha`, `browser_unavailable`, `access_denied`,
`dom_unavailable`. A changed actual BVID/origin/path/tab cannot be falsely relabeled as the
expected target to fit a receipt: if the binding no longer matches, do not submit
fabricated evidence; let the request become unknown and report the mismatch to
the caller. Capture must be after claim and within the original live lease.

```sh
python -m bili_bridge --db video.sqlite3 browser-video-read \
  --bvid BV1234567890 \
  --url https://www.bilibili.com/en/video/BV1234567890/ \
  --tab HOST_OBSERVED_TAB --spool /explicit/private/spool \
  --timeout 120 --operation-id UNIQUE_OPERATION
```

Both browser plugins return `coverage='visible_subset', complete=false`:
visible evidence is never a completeness claim. The video plugin is separate
from the search plugin. Neither is registered by `serve`; its default remains
only `video.metadata`. Synthetic tests cover cross-contract substitutions,
identity/version/time/URL violations, known-tracking sanitization versus rejected
unknown/semantic queries, field-state bounds, no private extras,
shared transport, timeout, CLI output, durable replay and disabled serve access.
Synthetic tests do not establish live video-page integration; that requires a
fresh, separately recorded real host request/receipt/journal round trip.

## Current-comment extension

`browser.comments.read` is a separate first-party cloud-dot read capability using
the same bounded transport. See [browser-comments.md](browser-comments.md) for
its exact schema, trusted open-shadow-DOM capture procedure, partial-visibility
semantics, truncation and explicit prohibition on stable IDs/reply targeting.
It does not change the earlier video metadata capability's scope.
