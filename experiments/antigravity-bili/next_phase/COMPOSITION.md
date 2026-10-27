# Actual synthetic composition (not installed, no live Bilibili)

`composition.py` is a dot-local trusted harness connecting the new QR, session and metadata modules. It is not the earlier `minimal_slice_vnext` fixture service, and the old acceptance test importing only that fixture service is not counted as this integration proof.

Flow: an injected fake generate/poll transport produces a synthetic challenge and fake cookie envelope → an account-bound `SyntheticMarkerSessionPort` validates that envelope and stores only its opaque random marker → actual SessionAuthority restoration is UNVERIFIED → a newly issued owner/epoch/pause-version ticket binds verification to the configured expected MID → an actual issued AUTH_READ lease is checked by the metadata dispatcher via a trusted boolean callback → an explicit synthetic metadata transport returns a bounded response → typed partial/unknown results preserve provenance and authentication remains separate.

The cookie value is discarded. Persisting a marker is NOT persisting usable credentials. The production private credential store, account-wide durable pending-login owner and actual network login/read adapters remain unconnected. All default state is paused, no constructor creates a network client, and tests pass only fake transports. QR SMS/phone support remains unimplemented, not prohibited.

One account-bound pause port is shared across QR/session/metadata; metadata has a separate observation ledger file, avoiding incompatible controls-table schemas. A closed session can be explicitly staged into a fresh unverified generation, but stale evidence/leases cannot revive it. Unknown metadata observations never trigger automatic retry; unrelated reads are not disabled as if authentication had expired.

Run: `python -B -m unittest next_phase.test_composition -v`.

The local composition suite and independent relationship tests pass on the manifest hashes. This remains an offline synthetic candidate: it does not add public MCP tools or alter the separately released fixture milestone.
