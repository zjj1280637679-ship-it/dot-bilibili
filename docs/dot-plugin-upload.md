# dot-bilibili: skill-only ChatGPT upload

> **使用前必读：[使用前提与联网/浏览器授权](prerequisites.md)。** 插件需要已获授权且可联网的云浏览器及已配置的宿主；不要求全局“始终允许”。

This is the repo-owned plugin in `plugin/`, not a personal skills installation.
It does not register native `bili_*` tools, start a server, or grant account access.
The plugin and the separately installed host runtime are different deliverables.

## Current 0.2.1 status (2026-10-25)

The installed, enabled skill and a fresh host-mediated given-video metadata read
were verified. Read the [scoped status and retained failure history](readonly-usability-status.md)
for the exact acceptance, replay checks and limitations.

## Earlier 0.1.0 acceptance (2026-10-25)

The 0.1.0 skill-only plugin was installed and its enabled skill loaded. A fresh
host-mediated metadata read through that installed skill and the additive CLI
succeeded on the existing canonical source runtime. See
[acceptance scope and evidence](dot-plugin-acceptance.md). This is not native
function registration or an installed-wheel live migration.

## Build and inspect

```sh
python scripts/build_dot_plugin.py
python -m unittest discover -s tests -p 'test_dot_plugin_bundle.py' -v
unzip -l dist/dot-bilibili-plugin.zip
```

The deterministic ZIP contains exactly root `plugin.json` and
`skills/bilibili/SKILL.md`; the builder rejects extra files and symlinks.
No Python distribution, database, private host binding, receipts, credentials,
account identifiers or historical evidence is uploaded. The console output
reports bytes and SHA-256. Review both source files before uploading; leak
tripwires do not prove arbitrary text contains no sensitive information.

## Host prerequisites and continuity

An authorized host must have the local runtime installed, a private binding to
its canonical runtime root / existing database / existing spool, and supported
native browser tools. Never copy an existing ledger to a newly installed runtime
and call that continuity; source-root binding is deliberate. Browser context
must be freshly observed, not trusted from an old profile. The plugin uses the
host's discovery convention rather than embedding machine-specific paths.

The skill is self-contained text. It relies on installed host resources only
after checking their availability; it does not assume cloud-uploaded scripts
are executable local files. The host must concurrently service spool requests
through supported CUA while the facade call waits. No host means blocked, not
an invented result or fallback cookie/CDP extraction.

## Installation acceptance is separate

Use the ChatGPT Plugins upload UI with the generated archive. Confirm its parsed
name/skill and inspect requested permissions before final installation. The
observed UI accepts ZIP/tar archives up to 100 MB. A local passing package test
is not proof the cloud parser accepted it. After installation, verify the skill
is discoverable in a fresh conversation and first run its read-only diagnosis.
A fresh authorized browser round-trip is a separate runtime acceptance check;
previous source-checkout success must not be relabeled as plugin success.

## Format basis

- [OpenAI: Package your plugin](https://developers.openai.com/plugins/build/plugins)
- [OpenAI: Build skills](https://developers.openai.com/plugins/build/skills)

Checked 2026-10-25: portable root manifest and auto-discovered `skills/`; a
skill-only plugin need not declare MCP. We intentionally omit optional hooks,
apps, dependency declarations and UI assets.

## Version 0.2.0 update (superseded)

Build an explicitly versioned candidate without replacing the prior ZIP:

```sh
python scripts/build_dot_plugin.py --output dist/dot-bilibili-plugin-0.2.0.zip
```

The manifest keeps the same plugin name and raises version from 0.1.0 to 0.2.0.
Its description now mentions supplied BVIDs/canonical video links. The skill:

- Adds given-video discovery and `bili_read_video(video, comments=false)` routing.
- Accepts only the literal BVID or exact canonical HTTPS video URL, optional
  trailing slash; rejects short links, queries/fragments and other URL forms.
- Explains the existing search-by-BVID/exact-fresh-result selection path, its
  four/five-operation cost, and possible `selection_not_found`; no direct-link
  navigation or first-result fallback is introduced.
- Routes this one name to `python -m bili_video_reference.cli schemas|call` in
  the same canonical source root. Missing additive source module is a host
  update blocker, not a reason to switch roots or install the frozen wheel.
- Keeps search/status on `bili_integration.cli`; the original status route also
  checks request IDs returned by the new route. All names remain JSON dispatch
  names, not native/MCP tool declarations.
- Explicitly states comments do not auto-scroll and an empty viewport does not
  establish that a video has no comments. Existing read-only, partial-coverage,
  durable invocation and concurrent supported-CUA requirements remain intact.

This version still uploads only the manifest and self-contained skill text.
Local validation is not live acceptance or proof of an installed update. The
0.2.0 live reference attempt failed closed; its result remains historical evidence.

## Version 0.2.1: given-video capture selection only

```sh
python scripts/build_dot_plugin.py --output dist/dot-bilibili-plugin-0.2.1.zip
```

No business schema or URL/selection semantics change from 0.2.0. Only the
`bili_read_video` host recipe instructions change: load that CLI's `instructions`,
require its explicit v2 recipe metadata, execute the deterministic fixed-file
composer, and verify its emitted function hash before supported read-only DOM
capture. Missing/mismatched module, components or hashes block browser work;
there is no hand-written browser-code or selector/path fallback. The emitted
function is evaluated as one closure with only kind/limit, not installed into
page globals. Legacy search remains on its original CLI instructions/v1 recipe.
Historical failed reads stay failed; this packaging update is not acceptance of
a new live read. The unrelated installable distribution's readiness is not
asserted here. Prior 0.1.0/0.2.0 ZIPs are preserved. The 0.2.1 update was installed
and its enabled cloud skill loaded; current runtime acceptance is tracked in
[the scoped status note](readonly-usability-status.md).

The 0.2.1 skill also uses `python -m bili_distribution.cli diagnose` and
`python -m bili_distribution.cli instructions` for its global resource-closure
bootstrap. Business schemas/calls still use the original integration module;
given-video capture still uses its own v2 instructions. The old integration
instruction locator alone is not the current complete resource bootstrap.
