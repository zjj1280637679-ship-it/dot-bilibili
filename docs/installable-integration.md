# Additive installable host integration

This layer packages the already accepted frozen Python façade and the two fixed
Python runtime scripts. It does **not** register native chat tools, implement MCP,
provide a browser driver, or change browser authority. The fixed JS collectors
remain in the source integration kit for the supported browser host.

## Installation and startup

Python 3.12+, Linux and an already authorized concurrent browser host are required.
From the checkout, with setuptools already available:

```sh
python scripts/check_installed_integration.py --wheel-dir /tmp/bili-wheel
# Install the resulting wheel into the trusted host's chosen environment.
python -m pip install --no-index --no-deps /tmp/bili-wheel/bili_bridge-0.3.1-py3-none-any.whl
bili-tools diagnose
bili-tools schemas
bili-tools instructions
```

`diagnose` checks runtime files, reports their workflow source digest and explicitly
reports browser access as `not_checked`. It never reads or writes a ledger/spool.
`ready_for_host_binding` means package assets exist, **not** that a browser is ready.
The additive wheel is version 0.3.1, built from `integration_dist/pyproject.toml`
in a temporary staging directory. The historical top-level 0.3.0 build metadata
and hash evidence remain untouched. No publication or live migration is implied.

A trusted host supplies a private regular JSON profile file (mode 0600; no symlink):

```json
{"db":"/absolute/private/state.sqlite3","spool":"/absolute/private/spool","source_url":"https://www.bilibili.com/","tab":"HOST_OBSERVED_TAB","timeout":120}
```

These values are examples, not auto-discovery. `source_url` and `tab` must come from
fresh supported-host observation for each new invocation; do not treat a stale
profile as current browser authority. Set `BILI_HOST_PROFILE` to that file or pass
`--profile`. No credentials, cookies or account secrets belong in the profile.
Do not put private state in the checkout or public plugin archive.

The host executes one request per process (EOF terminates stdin):

```sh
printf '%s' '{"tool":"bili_search_read","arguments":{"query":"公开搜索词","select":"first_visible","comments":false}}' |
  bili-tools call --invocation-id "$DURABLY_SAVED_HOST_CALL_ID"
```

`BILI_HOST_PROFILE` and `--invocation-id` are trusted host configuration/metadata,
not model tool arguments. The host must durably save **the complete call intent**
and stable invocation ID before launching this command. A retry reuses that ID;
never generate another ID to escape unknown results. This adapter does not create
a second ledger, issue IDs, queue work, or silently retry. Exit 0 means a JSON
response was emitted; inspect its `status` and `error`, not just the exit code.

While this synchronous call waits, the existing supported browser dispatcher must
claim and service spool requests using the unchanged
[`read-workflow.md`](read-workflow.md) protocol and fixed collectors. The transport
cannot authorize or automate a browser by itself. Shell calls alone are not a
browser dispatcher. The host owns concurrency and must keep its supported browser
session alive. There is no unattended service claimed here.

For status, omit invocation metadata and pass only the recorded request reference:

```sh
printf '%s' '{"tool":"bili_status","arguments":{"request_id":"fr-REPLACE_WITH_64_HEX_DIGITS"}}' | bili-tools call
```

## Identity and timeout boundaries

The old workflow binds persisted intent to the exact absolute `source_root`,
source digest, database and spool. An installed wheel has a different source root
from a checkout even when its bytes/digest match. **Do not switch an existing live
ledger to the wheel or rewrite old intents to force compatibility.** Existing
checkout workflows remain on their original deployment. A host binding conflict
requires deliberate host reconciliation, not replay or ledger reset. No ledger
migration or live-deployment change is included in this package work.

The frozen outer timeout kills its immediate workflow child; it is not proven to
reap every descendant. Unknown is not evidence of cancellation or safe replay.
The host must reconcile activity before any further platform operation.

## Small dependency/assumption inventory

- `bili_integration.dispatcher` → `facade.search_read` OR `facade.status`; exact two
  names, one selected branch, no loops/queue/retry/browser calls. The model envelope
  is exactly `tool` and `arguments`; business fields retain the frozen validators.
- `bili_integration.cli` → dispatcher, frozen schemas and host profile; standard
  library only. One bounded JSON request (8192 bytes), duplicate/nonfinite JSON
  rejection, bounded regular private profile read, one result. No path/command
  can be supplied through the model business schema.
- Diagnostics → frozen workflow digest + two fixed installed-file existence
  checks. This is packaging evidence, not attestation, registration, readiness or
  account authentication proof.
- Existing façade → frozen workflow → fixed CLI → shared ledger/spool → supported
  host. No authority edge is added to this chain. Stable-ID durability, host
  authorization, fresh tab binding and concurrent dispatch are external obligations.
- Existing graph/model checks do not cover this new package. The additive tests
  check dispatch partitions and negative authority cases; they do **not** constitute
  a Python refinement proof or an exhaustive state-space verification.

The separate `bili_integration/SHA256SUMS` records only this new layer. Historical
facade/workflow/source evidence files are not regenerated or reinterpreted.

## Verification

```sh
python -m unittest discover -s tests -p test_installable_integration.py -v
python scripts/check_installed_integration.py
```

The installation check builds offline, uses an isolated venv outside the source
checkout, checks import origins and workflow digest equality, and runs a synthetic
missing-host operation against a newly created temporary ledger. It confirms
fail-closed unknown, same-ID no-replay and read-only status. It never accesses the
live host profile, live ledger or live spool. A real installed-wheel browser run
is a separate acceptance step requiring host binding; the prior checkout browser
acceptance is not automatically transferred to this new distribution.
