# Minimal offline Bilibili integration slice

**Author/provenance: dot local implementation**, informed by the four real AG design contributors and independent review. Not AG-generated production code. It intentionally does not import or activate the unreviewed `product/` draft. No GitHub credentials, Bilibili accounts, cookies, NAV requests, QR login, browser access, network clients, dependency installations, hooks, or persistent AG permission changes.

## Current working capabilities
- `capabilities.list`: describes implemented vs unwired functions and durable fixture pause.
- `video.reference.resolve`: pure strict BVID / canonical HTTPS www.bilibili.com video URL validation. No existence check, redirect, shortlink, query or tracking resolution. Returns a process-local opaque reference; restarting makes old references stale. This is process binding, not a universal freshness duration.
- `video.metadata.read`: independent of search, requires a reference plus expected BVID, operation ID and explicit `backend: "fixture"`. Only **BV17x411w7KC** has synthetic fixture metadata. Other syntactically valid BVIDs return `not_found`; no actual video metadata is asserted.
- `operation.status`: reads only the local fixture ledger, never repeats a callback or platform request.

Every result says `backend: fixture`, `live: false`. Source/resolution success does not mean live Bilibili success. Unwired tools return `unsupported`, missing prerequisites return `blocked`; neither means the user refused authorization.

## Run
From the integration workspace root:

```sh
python -m unittest discover -s minimal_slice_vnext/tests -v
python -m minimal_slice_vnext.server --db /absolute/project/local-fixture.sqlite3
```

The stdio server defaults to paused. A trusted local test operator may pass `--fixture-ready` **only to initialize a new fixture DB unpaused**. Existing paused state is never cleared by this flag or restart. `Service.set_pause(bool)` is a local trusted test/operator seam and is not an MCP tool. No account authentication is implemented or asserted: this state controls synthetic callback admission, not real account authorization.

MCP uses newline-delimited UTF-8 JSON-RPC over stdin/stdout, pinned to supported protocol `2025-06-18`. Send initialize, then notifications/initialized, then tools/list or tools/call. Stdout contains only protocol messages. No HTTP listener or port is opened. Actual Antigravity CLI 1.4.8 discovered and invoked all four tools using synthetic fixture data. A server restart preserved pause, blocked a new metadata operation, and retained the original cached status. This is a locally registered offline demonstration, not a live Bilibili integration or a generally deployed plugin.

## Outcome and operation boundaries
The dedicated fixture ledger atomically reserves an operation before callback dispatch. Same operation ID/semantic target reads the recorded result; changed target conflicts. Pending/unknown never triggers automatic replay, including after process restart. A crashed old-run reservation is reported unknown. Status and cached-result observations remain possible when paused; new dispatch is blocked. Pause is an admission gate and cannot undo an already-running callback.

Backend returns use a closed typed contract. An arbitrary object, missing result, HTTP-like `code`, exception, or transport success is not `completed`. Exceptions are reduced to a stable error label; raw messages and parameters are not reflected. Non-auth pending/unsupported results do not poison other operation access. This fixture-only slice deliberately has no write-intent approval broker, no production session store, and no deferred-write resume/reconciliation workflow. Do not reuse it as a complete write ledger or a competing production ledger without a separate integration decision.

The injected backend is trusted local Python, not sandboxed by this module. Default backend is in-memory fixed fixture data and uses no network. This code does not protect against arbitrary malicious injected Python. Database paths are trusted launch configuration, never model tool arguments. Only one fixture namespace is supported; account isolation and durable real credential storage are NOT implemented.

## Evidence
`TEST_RESULTS.txt` records 27 passing tests (20 original behavior tests plus 7 MCP request-envelope compatibility regressions), including a real Python stdio subprocess, restart-preserved pause, malformed JSON, target/stale references, atomic concurrent reservation, typed outcomes, unknown/no-repeat and local-only status. Independent review additionally reports 19 unit and 14 real subprocess protocol tests, including os._exit crash/restart no-repeat; passing these tests does not establish full MCP conformance or real website acceptance.

Provenance for URL validation: public MIT repository `zjj1280637679-ship-it/dot-bilibili`, commit `7d8cd30d9fc842ad3a5cd6863459ec74a11e30f4`, `bili_bridge/browser_video_contracts.py:video_url`. License copied here. This implementation narrows it to canonical video URLs without tracking parameters.

Protocol references:
- https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- https://modelcontextprotocol.io/specification/2025-06-18/server/tools

## Inert setup template
`MCP_CONFIG.INERT.example.json` is disabled and is not an active installation. Replace `/ABSOLUTE/PATH/TO/PROJECT` manually with your project directory and review the Python executable path before using the documented project `.agents/mcp_config.json` setup. Keep only the four named tools. The template uses synthetic fixture data, not a GitHub token, browser account or Bilibili credential. Only the scoped CLI fixture workflow above has been verified; no claim of universal MCP client compatibility is made.

## Protocol compatibility update
Version 0.1.1-candidate accepts optional tools/call arguments (missing means an empty object) and object-valued request `_meta`. Metadata is not passed as tool arguments or treated as permission. Unknown top-level call parameters and invalid argument/metadata types still fail before business dispatch. This fixes the earlier overly strict envelope that rejected legitimate AG requests. Temporary shape diagnostics are removed from this source. The previous release remains a separate frozen baseline.

Reference: https://modelcontextprotocol.io/specification/2025-06-18/schema#calltoolrequest

## Host setup check
In the tested CLI session, editing the project file alone was not sufficient evidence of usable tools. Open `/mcp`, verify the server appears, and use its Restart action if discovery is stale. Then use the host generic MCP call mechanism and verify actual results. The clean build was checked again with read-only cached `operation.status` after restart. Never substitute a fabricated reference when resolution fails. Tool approval remains ordinary per-call review; no persistent auto-allow was enabled.
