# Installed skill acceptance — 2026-10-25

## Observed result

The plugin UI showed `dot-bilibili` version 0.1.0 installed with its skill enabled.
The installed `dot-bilibili:bilibili` skill was loaded through the skill reader.
An independent worker then followed that skill with the additive JSON CLI,
the existing canonical source runtime and shared journal, and the authorized
supported browser host. No ledger relocation or replacement was performed.

The fresh four-operation chain succeeded:

1. `browser.public_search`
2. `browser.search_results.read`
3. `browser.video.open`
4. `browser.video_page.read`

This read visible metadata only: `complete=false`, `comments_requested=false`.
An ordinary UI pause of incidental autoplay was ancillary, not a fifth semantic
operation or evidence of video/audio understanding.

Status lookup and same-invocation replay each succeeded with the same parsed JSON
result, zero new operation or reservation records and an unchanged spool. Raw
serialized bytes differed due to object-key ordering; byte equality is not claimed. The observed journal count was
28 after the live chain, after status, and after replay; this is a historical
total, not the number of new operations (four).

## Evidence and limits

[Sanitized acceptance summary](evidence/installed-skill.json) records the observed
sequence, source digests and hashes of privately retained evidence. It is a
reported execution record, not independently replayable raw evidence or a formal
proof. Queries, video identities/titles, browser tabs, account/plugin identifiers,
private paths, host binding contents and raw receipts are deliberately omitted.

This establishes an **installed skill-based, host-mediated integration**. The
JSON names `bili_search_read` and `bili_status` are not registered native chat
functions or MCP tools. The skill still requires separately configured shell,
canonical runtime/state and concurrent supported browser service. It is not an
unattended standalone host, account automation, complete comments access, or
video/audio understanding.

The optional 0.3.1 wheel has separate offline installation checks; this live run
used the canonical source deployment, not a migrated installed-wheel ledger.
Skill loading and the independent worker run do not establish availability in
every future fresh conversation or every machine. Historical acceptance files
and hashes remain unchanged. No GitHub Actions CI run was present at publication;
local tests and source checks must not be described as GitHub CI.
