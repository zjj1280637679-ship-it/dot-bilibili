"""
next_phase/session - Session Authority, Opaque Credential Storage,
Persistent Pause Gate, and Semantic NAV Verification.

Part of the Bilibili Modular Control Integration.
Python standard library only. Zero platform calls, zero live credentials.
"""

from .session_authority import (
    CapabilityFlag,
    CredentialHandle,
    CredentialStorePort,
    NavVerificationResult,
    PauseManager,
    SecurityViolationError,
    SessionAuthority,
    SessionLease,
    SessionState,
    SessionStateError,
    StorageState,
    SyntheticCredentialStore,
    assert_no_secret_keys,
    verify_nav_response,
)

__all__ = [
    "CapabilityFlag",
    "CredentialHandle",
    "CredentialStorePort",
    "NavVerificationResult",
    "PauseManager",
    "SecurityViolationError",
    "SessionAuthority",
    "SessionLease",
    "SessionState",
    "SessionStateError",
    "StorageState",
    "SyntheticCredentialStore",
    "assert_no_secret_keys",
    "verify_nav_response",
]
