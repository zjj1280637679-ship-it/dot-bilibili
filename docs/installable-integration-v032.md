# Installable runtime 0.3.2: explicit resource closure

> **使用前必读：[使用前提与联网/浏览器授权](prerequisites.md)。** 插件需要已获授权且可联网的云浏览器及已配置的宿主；不要求全局“始终允许”。

This is a new distribution, not a rewrite of the historical 0.3.1 build or its
proof records. Build/check offline:

```sh
python scripts/check_installed_integration_v032.py --wheel-dir /tmp/bili-wheel-v032
python -m pip install --no-index --no-deps /tmp/bili-wheel-v032/bili_bridge-0.3.2-py3-none-any.whl
bili-runtime diagnose
bili-runtime instructions
bili-tools schemas
bili-video-reference schemas
bili-video-reference instructions
```

`bili-runtime instructions` is the current complete-resource entrypoint. Installed
`bili-tools instructions/diagnose` route to the same versioned installation wrapper;
`schemas/call` delegate unchanged to the frozen CLI. The historical
`python -m bili_integration.cli instructions` locator is not the installed resource
entrypoint and is not claimed complete; use the versioned command instead.
Source execution uses `python -m bili_distribution.cli` or
`python -m bili_video_reference.cli`; installation grants no browser permissions.

The default instructions preserve `host-capture-v1`: original capture protocol,
hash-pinned capture recipe and projection recipe. Only the explicitly selected
video-reference route asks `bili_video_reference.cli instructions` for v2. Layout
or page content never selects a route or silently upgrades the legacy recipe.

The [host workflow](read-workflow.md) and all local Markdown links reachable from
its installed documents preserve their original directory topology. The public
allowlist is explicit in `bili_distribution.resources.RESOURCE_FILES`; its
`PROTOCOL_EDGES` additionally declares required semantic protocol relationships.
Missing/new links fail the build instead of triggering arbitrary recursive copying.
The check includes local inline and reference-style Markdown links, not anchor
validity, raw HTML links or arbitrary free-text filenames. The known required
protocol relationships are separately enumerated to make this limitation explicit.

Only allowlisted public Python modules, fixture HTML, fixed JS components and
public docs are staged. No private binding, ledger, spool, tests, dist directory or
browser receipt is included. The v2 composer checks three pinned component hashes
and produces a self-contained evaluation function. See
[v2 capture protocol](host-capture-recipes-v2.md),
[video reference](video-reference-v1.md), and
[relationship boundary](video-reference-relationship.md).

The original search/status façade, workflow and journal remain unchanged. Use the
same host profile and durable invocation rules in the
[original integration guide](installable-integration.md). The opt-in video route
remains separately named. No native registration, new authentication, independent
browser service, migration or installed-wheel live-browser acceptance is claimed.
**Never move an existing ledger to another absolute runtime root or reset it to
make installation work.** Keep existing live deployments where they were bound.

The isolated smoke checks installed origins, entire document closure, exact
original workflow digest, v2 composition, tool schemas, missing-host failure,
read-only status, stable-ID no-replay, and source-root conflict preservation. Each
uses temporary synthetic state outside the checkout. These are bounded executable
checks, not a full implementation refinement proof or platform correctness proof.
