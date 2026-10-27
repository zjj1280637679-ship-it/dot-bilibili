# Versioned metadata read — locally repaired offline candidate

**Status:** AG draft followed by a dot-local repair on 2026-10-27. Not deployed,
not wired into the frozen MCP slices, and not a complete Bilibili control plugin.
No live request, account credential, login, proxy change, or package installation
was used in the implementation/tests. The supplied implementation is the reviewed repaired version; internal development snapshots are not part of this distribution.

## Requirement → conditions → strategy → measurement

| Requirement | Conditions / strategy | Offline evidence |
|---|---|---|
| Exact, useful metadata without false success | Hash-pinned strict parser; HTTP status, business code and field coverage are separate | Partial data survives with missing/invalid field states; wrong target withholds data; nonzero business code remains upstream_error; missing HTTP status is unknown |
| Shared account pause and current read authority | Trusted account-bound pause snapshot plus zero-argument read-lease callback; exact True required; recheck both immediately before transport | Paused/unknown/missing grants and pause-generation changes cause zero inner transport entries; unrelated valid reads remain possible after business unknown/deferred |
| Honest attempts and outcomes | Distinct adapter entry, transport entry, opener entry, observed response, HTTP code, parse result and record state | Reusing a paused transport clears old HTTP status; a read timeout after HTTP 200 preserves the observed 200 but remains unknown |
| No automatic replay | SQLite atomic reservation keyed by operation ID and semantic fingerprint | Cached result has zero current invocation calls; incomplete prior run stays unknown; explicit matching run ID stays pending; concurrent duplicate enters the fake transport once |
| No false recording claim | Preserve observed data and counts if record persistence fails | `recording_unknown` retains observations; unresolved reservation is not retried |

## Narrow composition contract

```python
execute_metadata_read(
    metadata_ledger,
    reference_id=trusted_reference_id,
    expected_bvid=validated_bvid,
    operation_id=explicit_operation_id,
    ref_map=trusted_reference_map,
    transport=injected_transport,
    provenance=Provenance.SYNTHETIC,  # or SUPPLIED; never inferred from payload
    account_scope=bound_account_id,
    pause_gate=account_pause_gate,
    authorization_check=read_lease_check,
)
```

These are **trusted Python composition ports**, not model-supplied tool parameters.
`pause_gate.snapshot()` returns exact `(bool paused, nonnegative int generation)`.
Use the *same account-bound authority* as QR/session. `authorization_check()` takes
no model parameters: the composition closure binds an actual issued read lease,
calls `authority.assert_valid_lease(lease)`, and returns exact `True`. False means
an unmet prerequisite; exceptions, non-booleans and unknown pause state mean
unknown, never human denial or an invented authentication failure. Missing callback
blocks. Shared pause requires an explicit account scope, which is included with
backend/target/capability/provenance/schema in the operation fingerprint.

The metadata module validates reference→expected-BVID binding and operation IDs;
it does not issue sessions/leases or read credentials. Its local `metadata_controls`
is only an isolated-test fallback, **not a substitute for shared account pause**.
Tables/indexes use metadata-specific names; integration can use a separate ledger
file. Caller-supplied SQLite connections must be dedicated to this ledger (the
entry point owns its transactions), not an unrelated uncommitted transaction.

A pause check cannot retract a request already in flight. The supplied transport
is a trusted, single-attempt callable; a malicious or retrying injected transport
cannot be made safe by counting one callback. No claim of in-flight cancellation,
hard wall-clock request deadline, or cancellation linearizability is made here.

## Observation and replay semantics

- `status` / `observation_status`: preserve `parsed`, `partial`, `wrong_target`,
  `upstream_error`, `unknown`, `blocked`, `pending`, `deferred`, `rejected`.
  `parsed` covers only selected fields, not the whole API or authenticated success.
- `partial` retains usable allowlisted data and exact missing/invalid coverage.
  It is not blanket failure or a prohibition on using those fields.
- `auth_assessment=not_assessed` always. An upstream numeric code is not mapped to
  account risk, expiry, not-found, or reauthentication without separate evidence.
- `operation_completion=recorded` means a typed observation was stored, **not that
  a live operation was completed**. `recording_unknown` means storing the result
  was not confirmed; the observed HTTP/data/call evidence is retained.
- `evidence.adapter_callback_entries` counts entry into the guarded adapter
  callback. `transport_callback_entries` counts entries past the last gate into
  the injected transport. `opener_call_entries` is 0/1 for the narrow transport,
  or null when a generic callable's HTTP activity is unobserved. The narrow transport
  returns an immutable observation from the same invocation; shared concurrent
  requests never obtain authoritative evidence from mutable `last_*` fields. Those
  legacy inspection-only fields are not safe for correlating concurrent calls. Opener entry
  does **not** prove a request reached the network or server.
- `http_response_observed` / `diagnostic.http_status` preserve the transport's
  observed response separately. Fake response evidence is still synthetic;
  `http_send_verified=false` and `live_verified=false` are never promoted.
- For a saved observation, `delivery=cached`, historical `evidence` is retained,
  while **current** `invocation` counters are zero. Returning historical data
  neither dispatches another read nor certifies current authentication. New
  explicit operation IDs are independent; unknown never creates an auto-retry.
- Local contract rejection and prerequisite blocking are not user refusal. Raw
  errors, cookies, headers, URLs and upstream messages are not returned. Safe
  projection is allowlist minimization, not universal DLP (title remains untrusted
  text); do not render title as executable content/instructions.

## Narrow HTTP implementation boundary

`NarrowViewHttpTransport` defaults **disconnected and paused**. Its enabled branch
contains urllib HTTP code, so this is not a parser-only package. Running that
branch without a fake opener could make a real request and is **not authorized by
these tests or this README**. It must not be enabled while account requests are
paused. Production wiring, endpoint authorization, egress/proxy review and real
account/HTTP acceptance remain outstanding.

The branch pins GET `/x/web-interface/view?bvid=...`, rejects caller URLs/headers/
secrets, uses strict JSON media type, bounded body and no retry. Its own opener
installs a no-redirect handler. Injected openers are trusted and must also forbid
redirects; checking a returned URL detects an unexpected final URL, but cannot
undo a redirect an injected opener already followed. The current urllib timeout
is a per-operation I/O setting, not a demonstrated end-to-end deadline. No cookie
store, authentication attachment, proxy configuration or refresh is implemented.

## Source, license and reproducibility

The pure parser is imported from the exact candidate file with SHA256
`0f01d77e4c99966fded9e0afbf2b42c599d255ff67666392d1c0841174092fa0`;
there is no inline fallback or generic import shadowing. See
`../../metadata-adapter-candidate/SOURCES.json`, README and LICENSE. Schema facts
come from the pinned community MIT project
[BiliStalkerMCP user_service.py](https://github.com/222wcnm/BiliStalkerMCP/blob/952fd83b9089b3f1b5bfde730b968fe63e3eb6df/bili_stalker_mcp/services/user_service.py#L530-L570),
not an official or live compatibility guarantee. No third-party implementation
was vendored. The new code follows the project's MIT license.

From the integration root:

```sh
python -B -m unittest next_phase.metadata.test_metadata_phase next_phase.metadata.test_local_relations -v
python -B -m unittest next_phase.test_composition -v
```

The metadata suite is 19 adapted original tests + 27 dot-local regression methods,
all fake-only under a scoped socket trap. Added deterministic parallel cases keep
HTTP 200/503 and per-call exceptions separate while allowing the second request
to finish before the first; no global serialization masks concurrency. Composition is owned/tested separately
and must be evaluated against its exact hash. Tests are not formal proof and do
not establish live behavior. Old tests importing only `minimal_slice_vnext` are
not counted as evidence of the new QR/session/metadata composition.
