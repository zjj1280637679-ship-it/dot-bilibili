# dot-bilibili: skill-only ChatGPT upload

This is the repo-owned plugin in `plugin/`, not a personal skills installation.
It does not register native `bili_*` tools, start a server, or grant account access.
The plugin and the separately installed host runtime are different deliverables.

## Current acceptance (2026-10-25)

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
