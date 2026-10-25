# Read-only usability status — 2026-10-25

> **使用前必读：[联网、浏览器授权与宿主前提](prerequisites.md)。**

## Installed entry and terminal acceptance

The same skill-only plugin was updated to 0.2.1, enabled and loaded from the
cloud skill reader. The opt-in `bili_read_video` JSON entry accepts only a literal
BVID or exact canonical HTTPS video URL, then searches that BVID and selects an
exact match in fresh results. This is not direct URL navigation or a registered
native/MCP function; the original search/status route remains separate.

The [first live attempt](evidence/video-reference-initial-failure.json) failed
closed with `dom_unavailable` at the existing v1 search capture. Its failed
receipt, ledger and cached outcome remain unchanged. Status and same-ID alias
replay returned that failure without new operations or spool changes.

After a narrow, independently reviewed search-layout fix, a **separate explicitly
authorized invocation** using installed skill 0.2.1, the additive CLI and pinned
v2 composed capture [succeeded](evidence/video-reference-v2-acceptance.json):
public search → search-results read → exact video open → visible metadata read.
It added four operations, four reservations and one selection to the existing
shared journal. Search observed ten visible items (one featured, nine legacy).
Metadata fields were visible; `complete=false`, `comments_requested=false`.

Status and same-invocation canonical-URL/BVID alias replay returned equal parsed
JSON, with zero new operations/reservations/selections and unchanged spool bytes
and modification times. Serialized bytes differed by object-key order; this is
not byte equality or a fresh read. The live run used the existing canonical
source deployment, not a relocated ledger or installed-wheel browser run.

Evidence is temporal: after the workflow ended the site autoplayed a related
video. One ordinary visible play/pause click stopped it; that page was not used
as business evidence. Navigation can affect history and playback. No claim of
side-effect-free browsing, unattended operation or media understanding is made.

## Separate positive comments coverage

The [existing comments primitive check](evidence/positive-comments-visible-subset.json)
observed three body texts: two full and one partial thread. Author, timestamp and
like-count fields remained `not_visible`; extraction is not a complete comments
feed or an occlusion proof. A separate one-time host UI scroll of 0.75 pages
preceded the claim; scrolling is **not** a plugin feature or part of the primitive.
This was not a new five-stage `comments=true` business chain and adds no business
leaf. No comment bodies or video/operation identifiers are published.

## Bounded verification and packaging

- 360 local tests pass; frozen historical runtime and integration hashes remain
  unchanged. Existing business-leaf inventory remains five out of 122, not a
  claim of all-platform completion.
- Reference composition: 193-state finite relation and five detected mutations,
  plus concrete delegation/alias tests; not a whole-program refinement proof.
- Search-card selection: all 18 finite inputs checked; the v2 DOM adapter delegates
  metadata/comments to the frozen v1 recipe and is selected only for the new route.
- Distribution 0.3.2 checks explicit installed resource closure, separated v1/v2
  instructions, origins, no-host failure, no-replay/status and relocation refusal.
  See [packaging scope](installable-integration-v032.md) and
  [offline evidence](distribution-v032-evidence.json). Browser/network authority
  is external to package installation.

The public records are sanitized execution summaries, not raw receipts or
independently replayable browser evidence. Private binding/state, account data,
queries, real video identities, titles, tab IDs and raw observations are omitted.
Historical proofs and earlier failed attempts are not rewritten as successful.
No GitHub Actions CI run is implied by these local checks.
