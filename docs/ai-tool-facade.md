# Minimal AI tool facade — offline adapter, not registered tools

Two classic snake_case tool descriptions are exported as
`facade.contracts.TOOL_DEFINITIONS`. These are portable JSON-schema contracts, not
an installed plugin or a fabricated dot SDK. The real adapter invokes the existing
`scripts/read_workflow.py` subprocess. A trusted supported browser host must service
its spool **concurrently**; calling this synchronously from the only host dispatcher
would deadlock until timeout. A shell alone cannot make this a working browser tool.

## Model arguments

```json
{"query":"公开搜索词","select":"first_visible","comments":false}
```

`query` and `select` are required. `select` is exactly `first_visible` or a BVID
matching `BV[0-9A-Za-z]{10}`. No implicit target selection. Exact BVID absent from
the fresh result list stops without selecting a substitute. `comments` defaults
to false. Unknown keys, wrong types, invalid Unicode/control characters, blank
queries, and oversized queries/encoded destinations fail before spawning.

`bili_status` takes only `{"request_id":"RETURNED_REFERENCE"}`. Copy the returned
handle; do not manufacture an internal operation ID.

Default reading consumes at most **4 existing semantic operations**; comments
consumes at most **5**. Each uses the same existing budget, cooldown and freshness
rules. Search projection is at most 10 results; comments at most 3 intersecting
threads, each text at most 2000 code points with the existing truncation markers.
No pagination/cursor, arbitrary URL read, scrolling, replies, account writes,
autoplay control, or video comprehension is implemented. Navigation can cause
history/autoplay effects. This is not a side-effect-free browser read.

## Trusted integration, not model arguments

From the repository root, an existing host integration can call:

```python
from facade import HostProfile, search_read, status

# These values come ONLY from the trusted host's existing authorized session.
profile = HostProfile(db=absolute_designated_db, spool=absolute_private_spool,
                      source_url=freshly_observed_source_url,
                      tab=freshly_observed_tab_id)
result = search_read(model_arguments, profile=profile,
                     invocation_id=durably_saved_host_invocation_id)
recorded = status({"request_id": result["request_id"]}, profile=profile)
```

The default executor is a real fixed subprocess with argument vectors and no
shell. The injected `runner` seam is for offline testing, not a model argument.
The host must bind the invocation ID to the authorized session/call, persist it,
and reuse it for transport retries. **Never generate a fresh UUID on every retry.**
The returned opaque ID is a deterministic hash of that host identity. Model input
never includes paths, timeout, tab, source URL, code, commands, scope digests,
operation IDs or a meaningless confirmation boolean.

The existing workflow ledger is the sole operation state. Cached calls compare
business intent and return prior results without spawning or refreshing evidence;
changed model intent is `request_conflict`. Host profile changes do not rewrite
old intent. A new intended read needs a new authorized invocation, only after any
previous uncertainty is reconciled. This adapter deliberately has no resume,
reset, retry or cancellation API. Host cancellation cannot roll back navigation;
interrupted records stay unknown rather than being replayed.

## State reader boundary

`status()` does not spawn a process, access the browser, create directories or
write state. It uses the existing workflow `load()` helper (O_NOFOLLOW, regular
file and size checks), a private nonsymlink directory, a strict handle grammar,
and checks stored ID/DB/spool/source-root bindings. State is read only from the
fixed `DESIGNATED_DB.workflows` layout used by that exact script. No arbitrary
path is accepted from the model.

**This is version-coupled to a prototype's ledger, not a stable public status
API.** No supported workflow-status CLI exists yet. The dependency is isolated
in `_read`; changes to workflow layout/schema require adapter review/tests.
The host-controlled filesystem is a trust assumption, not a hostile-process
sandbox. A ledger marked running is reported unknown because it does not prove
that a process remains active. Status never attempts reconciliation by itself.

## Results and errors

All results have `request_id`, `status`, `data`, `coverage`, `error`, `next_action`.
Status is succeeded/partial/failed/unknown. `data` contains only accepted observed
search results/video metadata/comments and selected BVID, never raw steps,
host paths or spool receipts. Coverage is none or visible_subset and always
`complete=false`; zero visible comments is not evidence of no comments.
Existing not_visible and truncation markers are preserved. Output is bounded to
256 KiB; oversized results fail closed rather than silently truncating evidence.

Errors use a consistent `{code,message}` object with safe vocabulary, including
invalid_arguments, request_conflict, selection_not_found, session_busy,
host_binding_conflict, state_unavailable, request_not_found, workflow_stopped,
outcome_unknown and result_too_large. No arbitrary child exception is exposed.
`next_action` is none, correct_arguments or contact_host. Uncertainty never
instructs the AI to create a new identity and retry. Detailed low-level diagnoses
remain in the trusted workflow ledger for the host, not model-facing output.

## Acceptance boundary

```sh
python -m unittest discover -s tests -p test_tool_facade.py -v
```

Offline coverage includes real subprocess fail-closed startup (no browser), fixed
command mapping, opt-in comments, strict validation, cached no-spawn retries,
intent conflict, interrupted no replay, state symlink rejection, missing state
without directory creation and safe error envelopes. Fake executor tests are
not live browser evidence or formal verification. The two required business
arguments, finite output shapes, and pure validation/projection seams reduce
proof scope but do not establish a refinement proof.

The facade is outside `bili_bridge/` and does not modify frozen runtime/workflow
sources. The workflow source digest therefore does **not** cover this adapter;
release verification must separately hash/version the facade files. Real host
registration, concurrent dispatcher wiring and end-to-end acceptance of this
new entry point are still required before claiming it is usable in a target host.

### Reviewed hardening

The adapter additionally rejects queries starting with `-`: the frozen underlying
CLI cannot represent them consistently through its nested argparse invocation.
This is a documented limitation, not permission to rewrite a query. Ledger
schema_version and the exact current workflow source digest must match; mismatches
fail closed. A successful child result must match its bound durable ledger and
contain all 4/5 observed steps. Nested public fields are explicitly allowlisted;
per-stage capture timestamps/coverage and safe blocked codes (including captcha
and login_required) are preserved without internal IDs. The default subprocess
runner incrementally caps stdout at the workflow's 12 MiB state limit, before
buffering more; model-facing output remains capped at 256 KiB. Terminating a
workflow process does not prove every already-started child/browser action stopped;
unknown outcomes still require host reconciliation, never automatic replay.
