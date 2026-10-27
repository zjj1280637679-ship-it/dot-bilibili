"""
Domestic QR Login Module for Bilibili Control Integration.
Phase: next_phase/qr/
Offline, fail-closed contract implementation.
"""

from .qr_login import (
    QRChallenge,
    QRPollResult,
    OpaqueSessionHandle,
    QRProtocolError,
    QRLoginCoordinator,
    parse_qr_generate,
    parse_qr_poll,
    parse_fail_closed_json,
    request_phone_login,
)

__all__ = [
    "QRChallenge",
    "QRPollResult",
    "OpaqueSessionHandle",
    "QRProtocolError",
    "QRLoginCoordinator",
    "parse_qr_generate",
    "parse_qr_poll",
    "parse_fail_closed_json",
    "request_phone_login",
]
