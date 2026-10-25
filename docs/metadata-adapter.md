# Anonymous metadata adapter boundary

The implemented live surface is exactly `video.metadata` for a canonical BV ID,
with optional positive integer `part`. Only `anonymous` account is accepted.
This is not a player, transcript extractor, API signer, authenticated adapter,
or declaration of permission from the platform.

Offline uses **synthetic** `BV1xx411c7mD`, not captured or current public data.
It includes two different part/CID pairs to verify source identity. Missing
fixtures fail explicitly. `inspect --live` makes one attempted read; `serve
--live` exposes only reads under the kernel's shared durable rate budget.
Nothing silently substitutes fixture content after a live failure. Replaying
an operation ID from the other provenance mode is rejected by CLI output guards.

All production plugin metadata calls pass through the plugin-local
`MetadataPipeline`: `metadata.fetch` → `metadata.parse` → `metadata.normalize`.
Each stage forwards the shared versioned/correlated/scope-bound `RelayEnvelope`.
Module messages are frozen typed packets; parsed JSON crosses the boundary as
an immutable JSON string rather than a shared mutable dictionary. A kernel
context starts at `kernel.execute`; direct isolated plugin tests start with an
empty path. Skipped or wrong-order transitions and changed request scope fail.
This is a trusted first-party architecture, **not** protection against arbitrary
Python modules that can bypass the host or fabricate envelope objects.

Transport accepts only HTTPS `www.bilibili.com/video/BV…/`; redirects are denied.
It uses no cookie jar, authentication handler, browser session, or environment
proxy credentials. It requests identity encoding, accepts only HTML, and caps
body size at 2 MiB. Socket timeout is 3 seconds; an overall body deadline of 10
seconds is checked around bounded 16 KiB `read1` chunks. DNS resolution and OS
scheduling are not hard-real-time bounded by Python's socket timeout; a final
blocking read may exceed the body deadline by one socket timeout. A production
strict wall-clock bound requires a separately supervised transport process.
There are zero automatic retries and no alternative identity, route or bypass.

Unknown schema, absent initial state, malformed JSON, missing video/part,
identity mismatch, challenge and transport failure remain explicit outcomes.
Only whitelisted scalar video metadata is emitted. Source, timestamp semantics,
part/CID, no-watched-video indicator and unsupported features accompany results.
Page text is untrusted data; no page JavaScript is executed.
