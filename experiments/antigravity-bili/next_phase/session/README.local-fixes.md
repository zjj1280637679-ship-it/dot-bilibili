# Synthetic session authority: AG draft + dot local corrective patches

No network, real credentials or production secret backend. SyntheticCredentialStore persists opaque fixture references and optional test metadata, not a real login. The key-name check is not a universal data-loss-prevention system; trusted callers must never provide secrets under arbitrary keys or values.

Parser result != authority. Capture begin_verification() BEFORE starting verification work; apply_nav_verification(result, ticket=issued_ticket) consumes that same owner/generation/pause-generation-bound ticket once. The authority compares a VERIFIED result with its own expected MID. verify_and_apply(raw) is a synchronous fixture convenience. Pure parser results and model statements alone cannot elevate state.

close invalidates current tickets/leases. A trusted explicit stage_unverified() may open a NEW owner generation afterward; it never restores prior evidence or marks the new generation verified. Fresh verification is required. Restoration also starts unverified. Random owner IDs and actual issued-lease identity prevent cross-owner and altered-capability reuse. Every lease validation reads the shared durable pause generation; pause/unpause never revives an old lease.

This account-bound authority applies pause to all its transport capabilities, including anonymous reads. A future independent public unauthenticated backend may have a different explicit policy; this is not a blanket prohibition of public reading. Write authorization/operation-specific approval is not implemented, so verification does not grant writes. The admin elevation method is a trusted synthetic test seam, not a production approval broker.

AccountPauseGate binds PauseManager to one account for QR and metadata composition. Business pending/deferred/unknown/unsupported outcomes do not mutate auth state. Parser failures use stable reasons and reject overflow/nonfinite numbers. SQLite :memory: uses a retained serialized connection; file connections close after use.

Tests: python -B -m unittest next_phase.session.test_session next_phase.session.test_local_relations -v
