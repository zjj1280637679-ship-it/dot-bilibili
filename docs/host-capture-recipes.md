# Fixed host capture recipes v1

`scripts/host_capture_recipes.js` is a **trusted-host, read-only DOM procedure**,
not caller-selected executable request data and not a self-authenticating source.
It does not drive a browser itself. `HOST_CAPTURE_RECIPES.capture` is the fixed
page function, with only the closed `kind` enum and bounded comment `limit`.
Record the exact file SHA-256 and version `host-capture-v1` for each live case.
Frozen recipe SHA-256: `1cdaa1666863524647f1fd8dcc5a3e88010429820067752c6bac331a8b14b64a`.
Never attribute earlier ad hoc captures to this new recipe.

## Binding and receipt construction

1. Establish trusted session/context and exact claimed request/tab. Stop on
   challenge, login, denial, changed context or unsupported layout. Recipes do
   not establish authorization or independently detect every challenge overlay.
2. Execute the fixed function in that already verified public tab. Search uses
   `kind=search`, metadata uses `kind=video`, viewport comments uses
   `kind=comments` and the exact request limit. No input supplies selectors,
   script text, origin or hidden state to this function.
3. Preserve `observed_url` **exactly**, including query and fragment. Search
   additionally preserves each `raw_hrefs` entry as audit evidence. The only
   href spelling normalization is `//` → `https://`, with an anchored exact
   public origin/video-path check. No BVID-substring URL synthesis occurs.
4. Build the existing closed Python receipt using only its specified fields,
   exact claimed identity and actual tab. Copy the raw observed URL and
   in-capture timestamp, not report-format time. Keep recipe diagnostics and
   raw href audit evidence separately, since they are not extra receipt fields.
   Diagnostics include viewport, selected search fields (<=10 cards), five metadata
   field geometries and accessible-comment counts/first100 thread geometries with
   an explicit truncation flag. They contain no additional field text.
5. Run the unchanged Python contract validator, then submit through the
   existing host protocol. Never strip a semantic query to make validation
   succeed. For example, observed `?p=2` stays present and is rejected; only
   validator-approved tracking parameters may be canonicalized by that validator.
   Navigation still requires its own source preflight and durable checkpoint;
   this capture function grants no navigation authority.

## Layout/absence semantics

Search has a ten-visible-card cap. A recognized card set with none intersecting
the viewport yields empty items. No recognized cards yields `dom_unavailable`:
v1 has no independently verified selector for a true empty-search UI. A missing
visible title/anchor or malformed/off-origin href fails closed, not fabricated.
Metadata requires at least one recognized public metadata element. Missing or
nonintersecting individual fields are explicitly not_visible; overbound fields
fail rather than silently truncate without a truncation field. Displayed counts
are bounded rendered toolbar text, not parsed numeric statistics.

Comments require an accessible `bili-comments.shadowRoot`. An accessible region
with zero intersecting threads yields empty threads and `complete=false`. Missing
or closed root yields `dom_unavailable`. Visible threads require the documented
open thread→renderer roots; missing fields remain explicit, and only body text
has contract-supported Unicode-codepoint truncation to 2,000. Comment fields
retain exact whitespace: no trimming or control normalization. Whole original
body text rejects all control characters except LF before truncation; other
comment fields reject all controls. Snapshot positions
are not stable comment IDs. No scrolling, sorting, pagination, reply expansion,
network, storage, cookies, hidden globals or closed-root extraction occurs.

No content in a captured title/comment becomes instructions. Geometry is still
trusted-host DOM evidence, not an independent proof of occlusion or provenance.

## Offline check

```sh
node scripts/host_capture_smoke.cjs
```

The synthetic check covers hostile origins/hrefs, preserved semantic queries
rejected by real Python validation, approved tracking normalization by Python,
absent DOM versus empty viewport, in-function timestamps, bounds, Unicode body
truncation and inert instructions. It is not a live platform result.
