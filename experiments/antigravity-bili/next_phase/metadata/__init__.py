"""
next_phase/metadata - Versioned metadata observation, narrow transport, and gated read tool.

Part of the Bilibili Modular Control Integration (Offline Implementation).
"""

from .versioned_adapter import (
    BVID,
    FIELDS,
    FORBIDDEN_ARG_KEYS,
    MAX_BODY_BYTES,
    MetadataAdapter,
    MetadataResult,
    NarrowViewHttpTransport,
    NoRedirectHandler,
    Provenance,
    ReadRequest,
    RedirectBlockedError,
    SCHEMA_VERSION,
    TransportReply,
    compute_semantic_fingerprint,
    execute_metadata_read,
    init_metadata_ledger,
    make_blocked_observation,
    make_rejected_observation,
    make_versioned_observation,
    parse_metadata,
    valid_bvid,
)

__all__ = [
    "BVID",
    "FIELDS",
    "FORBIDDEN_ARG_KEYS",
    "MAX_BODY_BYTES",
    "MetadataAdapter",
    "MetadataResult",
    "NarrowViewHttpTransport",
    "NoRedirectHandler",
    "Provenance",
    "ReadRequest",
    "RedirectBlockedError",
    "SCHEMA_VERSION",
    "TransportReply",
    "compute_semantic_fingerprint",
    "execute_metadata_read",
    "init_metadata_ledger",
    "make_blocked_observation",
    "make_rejected_observation",
    "make_versioned_observation",
    "parse_metadata",
    "valid_bvid",
]
