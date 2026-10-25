# Video reference entry v1 (additive, offline-tested)

`bili_video_reference.read_video(arguments, profile=trusted_profile,
invocation_id=durable_host_id)` accepts:

```json
{"video":"https://www.bilibili.com/video/BV1xx411c7mD/","comments":false}
```

`video` also accepts the exact BVID `BV1xx411c7mD`. The example is a
syntactic fixture, not evidence that that video was read. `comments` defaults
to false; no other business arguments are accepted. Only the exact lowercase
HTTPS origin `www.bilibili.com`, `/video/`, case-sensitive BVID, and optional final `/`
are accepted. No whitespace trimming, URL decoding, query or fragment removal,
HTTP, ports, userinfo, alternate hosts, AV IDs, share text, short-link expansion,
or redirect following is performed. Invalid input does not invoke the facade: malformed arguments return
`invalid_arguments`, unsupported reference forms return
`unsupported_video_reference`.

## What it actually does

This is **not direct URL navigation**. It translates the reference into existing
`bili_search_read` arguments: `query=BVID`, `select=BVID`, same comments flag.
The existing trusted workflow searches public pages and requires an exact BVID
in fresh results before opening it. A valid but unlisted reference can therefore
return `selection_not_found`; there is no direct-navigation fallback.

The original four-operation metadata / five-operation optional-comments budget
is unchanged. Comments remain at most three current-viewport threads, with
visibility and truncation markers—not all comments, replies, or pagination.
Returned envelopes and public evidence projections are unchanged. The entry
neither adds observations nor claims media comprehension or complete coverage.
Navigation can affect history and autoplay in the host-authorized tab.

The host must persist and reuse invocation IDs. BVID and canonical URL aliases
normalize to the same workflow intent; retrying either representation with the
same ID uses the same authoritative workflow ledger and cached evidence.
Changing the BVID or comments flag with that ID conflicts. Running/unknown
outcomes are not automatically retried; status uses the existing `bili_status`.
There is no separate cache, operation ledger, budget, or browser authority.

## Integration boundary

This package only exports a callable and portable `TOOL_DEFINITION`; it does not
register a tool, install an MCP server, or modify the frozen legacy dispatcher.
A separately reviewed versioned host dispatcher may route `bili_read_video`
to this callable after the same trusted invocation-ID checks used for
`bili_search_read`. Existing host setup/permission requirements still apply.
Tests are offline contract and delegation checks, not live browser proof.

## Runnable opt-in CLI (source checkout)

From the project root, inspect the portable definition:

```sh
python -m bili_video_reference.cli schemas
```

The trusted host persists an invocation ID, supplies its existing private
profile, and concurrently services the existing spool protocol:

```sh
printf '%s\n' '{"tool":"bili_read_video","arguments":{"video":"BV1xx411c7mD"}}' |
  python -m bili_video_reference.cli call \
    --profile /absolute/private/host-profile.json --invocation-id SAVED_HOST_ID
```

`BILI_HOST_PROFILE` is the same optional trusted profile locator as the original
CLI. Duplicate JSON keys, non-finite JSON numbers, oversized input, extra
transport keys, and model-supplied authority fields are rejected. This entry
accepts only `bili_read_video`; use the original `bili-tools call` (or
`python -m bili_integration.cli call`) for `bili_status`. It is a single call,
not a service, and is not automatically registered or included in old wheels.

### Additive fixed capture for the new route

Use `python -m bili_video_reference.cli instructions` to locate the pinned
`host-capture-v2` components and deterministic single-function composer.
The [v2 capture runbook](host-capture-recipes-v2.md) specifies the two explicit
search-card variants and unchanged Python receipt validation. This new route
alone selects v2; the old integration's instructions continue selecting v1.
