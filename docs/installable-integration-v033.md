# Candidate runtime 0.3.3 / instruction plugin 0.2.2

This release selects the same pinned `host-capture-v3` for public search/read and
given-video read. Business tool names, schemas, navigation authority, state and
receipt contracts are unchanged. This is a skill plus local runtime; **not** native
MCP registration or an autonomous background browser service. An authorized
supported host must concurrently service the existing spool.

Use `bili-tools instructions` and `bili-video-reference instructions`, or module
forms `python -m bili_distribution.current_cli instructions` and
`python -m bili_distribution.video_cli instructions`. Both return the same fixed
recipe version, four component pins, composed-function pin and resource paths.
Run that returned composer locally and verify the hash of its function string
(without the CLI terminal newline); evaluate once with only kind/limit. This is
normal installed-host bootstrap, not manual source selection. Do not reconstruct
or substitute code. Keep recipe diagnostics out of closed receipts.

`bili-tools schemas/call` delegates to the existing search/status transport;
`bili-video-reference schemas/call` delegates to the existing exact-video transport.
Search inspects first ten intersecting recognized cards, returning at most ten
videos. `limit` caps comments only, not search results. Ad/course exclusions never
become targets. Unknown/unsafe/ambiguous cards still fail closed. Results remain
`visible_subset`; metadata is not video/audio understanding.

Historical `bili_distribution.cli` and `bili_video_reference.cli` keep their old
v1/v2 instructions for reproducibility. They are not the current bootstrap route.
The version map is shared in `bili_distribution.capture`; business implementations
are not copied. Future candidate fixes can be layered on this allowlisted source
and must rerun package/pin/contract gates.

Never reset, replace or silently relocate host db/spool/journal bindings during
an upgrade. Preserve canonical runtime root and state identity. Installation into
a disposable verification venv is not authorization to move a live ledger or
upgrade a bound host. Existing relocation conflicts remain fail-closed; any real
migration requires a separately authorized continuity plan and rollback evidence.
No plugin upload, user-list installation or production migration is performed by
this candidate build.

See [v3 capture contract](host-capture-recipes-v033.md),
[workflow](read-workflow.md), [host protocol](browser-host-contract.md), and
[reviewed acceptance scope](release-v033-acceptance-scope.md).
