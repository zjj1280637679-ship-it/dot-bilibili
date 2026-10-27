# Offline QR contract: AG draft + dot local corrective patches

No real QR request, SMS login, account session or cookie persistence is performed. The transport is injected and all current tests use fake responses. Phone login remains explicitly unsupported, not forbidden.

A coordinator represents one login attempt. Repeated generate calls do not recreate a challenge. To start a separately authorized attempt, create a new coordinator through a supervising account-level owner. This module alone does not provide a durable cross-process single-login lock; that remains an integration requirement before live login.

The trusted pause port supplies snapshot() -> (exact bool, integer generation). It is checked before each callback and after responses; unknown ports block without sending. A changed pause generation invalidates a late response even after pause is lifted. Constant bool gates are only explicit synthetic fixtures. Calls run outside a state lock; close advances the local generation, so an in-flight response cannot revive it. Parallel calls cannot duplicate the same attempt. QRChallenge is immutable. Upstream messages are not projected; nonfinite values, including exponent overflow, are rejected.

OpaqueSessionPort is deliberately synthetic: it validates a fake cookie envelope and creates a marker, but DOES NOT save credentials or prove identity. The composition test stores only the opaque marker in SyntheticCredentialStore. A production private credential backend is absent. Consent arguments are a trusted operator seam, not proof supplied by arbitrary model text. No tool exposes them as a universal permission switch.

Tests: python -B -m unittest next_phase.qr.test_qr next_phase.qr.test_local_relations -v
