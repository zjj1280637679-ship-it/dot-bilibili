# Current AI tool usage — 0.3.0

**Current source-checkout acceptance:** `facade.search_read` ran the actual five-stage browser workflow in an independent supported dot host session; `facade.status` returned the same result with no new journal reservation. See [audited evidence](milestone-five-acceptance.md). This is not native chat-tool registration or a standalone browser service.

Two tools: `bili_search_read(query, select, comments=false)` and `bili_status(request_id)`. There are only two required business arguments for the first tool. `select` is explicitly `first_visible` or an exact BVID present in the new search snapshot. The optional comments flag chooses four or five semantic operations; neither choice silently sends account content.

From the repository root, import `HostProfile`, `search_read`, and `status` from `facade`. The trusted host injects the shared database/spool and freshly observed tab/source context; keeps a durable, stable invocation ID; and concurrently services requests through supported browser tools. The model cannot supply paths, code, digests, or shell commands. The function calls and schemas are shown in the [README](../README.md).

The synchronized Python call waits for the host; missing host access is a genuine blocker, not a reason to fabricate a result. Repeated calls reuse the original persisted intent. `status` never starts/resumes a workflow; stale running ledgers without reliable activity evidence are reported as unknown. Exact output scope and safe errors stay visible.

[The detailed interface contract](ai-tool-facade.md) is the deliberately preserved pre-live snapshot hashed in `facade/SHA256SUMS`. Its final paragraph's pending-live wording refers to that earlier stage; the current accepted status is recorded here and in the five-primitive acceptance file. Preserving it avoids rewriting the historical hash proof. Runtime facade code and tool schemas are unchanged from the successful live execution.

The public package is a source-checkout integration kit. Installing the basic `bili-bridge` CLI alone does not package/register the facade scripts or grant dot browser access. Do not claim a new native tool appears merely because this directory exists.
