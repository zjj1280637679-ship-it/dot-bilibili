"""
Domestic QR Login Protocol and Coordinator.
Phase: next_phase/qr/qr_login.py

Offline, fail-closed contract implementation grounded in public-reference/bili_bridge.
Features:
- Fail-closed UTF-8 JSON parsing (duplicate keys rejected, NaN/Inf rejected, max 65536 bytes).
- Exact integer code validation (type(code) is int and not bool).
- Strict URL and key validation for QR generation challenge.
- Single pending login state machine (no auto-refresh/recreation).
- State regression rejection (waiting_confirmation -> waiting_scan -> unexpected_protocol).
- Account pause gate integration (returns typed blocked with 0 transport calls).
- Opaque session handle isolation (no SESSDATA/bili_jct leaked).
- Explicitly unsupported phone login stub.
"""

from __future__ import annotations

import json
import math
import threading
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 65536
KEY_REGEX = re.compile(r'^[A-Za-z0-9_-]{16,128}\Z')

POLL_STATES = {
    86101: 'waiting_scan',
    86090: 'waiting_confirmation',
    86038: 'expired',
    0: 'authenticated'
}

SAFE_ERROR_REASONS = frozenset({
    'unexpected_protocol',
    'unexpected_qr_url',
    'invalid_transport_request',
    'consent_or_state_required',
    'single_pending_login_enforced',
    'invalid_state',
    'account_operations_paused',
    'missing_or_invalid_session',
    'internal_failure'
})


class QRProtocolError(Exception):
    """Fail-closed exception preserving constant reason strings."""
    def __init__(self, reason: str = 'internal_failure'):
        safe_reason = reason if reason in SAFE_ERROR_REASONS else 'internal_failure'
        super().__init__(safe_reason)
        self.reason = safe_reason


@dataclass(frozen=True, repr=False)
class QRChallenge:
    """Challenge container for validated QR code generation payload."""
    url: str = field(repr=False)
    qrcode_key: str = field(repr=False)

    def __repr__(self) -> str:
        return '<QRChallenge redacted>'


@dataclass(repr=False)
class QRPollResult:
    """Typed result from parsing a QR poll response."""
    code: int
    status: str
    message: str = field(default='', repr=False)

    def __repr__(self) -> str:
        return f'<QRPollResult status={self.status}>'


@dataclass(repr=False)
class OpaqueSessionHandle:
    """
    Opaque synthetic session handle.
    Never exposes raw SESSDATA or bili_jct in repr, dict, or logs.
    """
    handle_id: str
    created_at: str
    _internal_vault_ref: Optional[str] = field(default=None, repr=False)

    def __repr__(self) -> str:
        return f'<OpaqueSessionHandle id={self.handle_id[:8]}... redacted>'

    def to_safe_dict(self) -> Dict[str, str]:
        return {
            'handle_id': self.handle_id,
            'created_at': self.created_at,
            'type': 'synthetic_session_handle',
            'credential_persisted': False
        }


# ---------------------------------------------------------------------------
# Fail-closed JSON Parser
# ---------------------------------------------------------------------------

def parse_fail_closed_json(body: bytes) -> Dict[str, Any]:
    """
    Fail-closed JSON parser:
    - Max body length: 65536 bytes
    - Valid UTF-8 bytes required
    - Duplicate keys rejected
    - NaN, Infinity, -Infinity rejected
    - Exact integer code == 0 check (type(code) is int, not bool)
    - Returns inner 'data' dict
    """
    if not isinstance(body, bytes) or len(body) > MAX_BODY:
        raise QRProtocolError('unexpected_protocol')

    def _unique_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError(f"duplicate_key: {k}")
            result[k] = v
        return result

    def _invalid_constant(c: str) -> None:
        raise ValueError(f"nan_or_infinity: {c}")

    def _finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("nonfinite_number")
        return value

    try:
        decoded = body.decode('utf-8')
        obj = json.loads(
            decoded,
            object_pairs_hook=_unique_pairs,
            parse_float=lambda text: _finite_float(text),
            parse_constant=_invalid_constant
        )
    except Exception:
        raise QRProtocolError('unexpected_protocol') from None

    if not isinstance(obj, dict):
        raise QRProtocolError('unexpected_protocol')

    code = obj.get('code')
    # Exact integer code == 0 (must not be bool, must be int)
    if type(code) is not int or isinstance(code, bool) or code != 0:
        raise QRProtocolError('unexpected_protocol')

    data = obj.get('data')
    if not isinstance(data, dict):
        raise QRProtocolError('unexpected_protocol')

    return data


def parse_qr_generate(body: bytes) -> QRChallenge:
    """
    Parse and validate domestic QR generation response.
    Validates:
      - Fail-closed JSON envelope
      - qrcode_key matches [A-Za-z0-9_-]{16,128}
      - url strictly: https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=<key>
      - No fragment, no extra query parameters, exact key match.
    """
    data = parse_fail_closed_json(body)
    qrcode_key = data.get('qrcode_key')
    if not isinstance(qrcode_key, str) or not KEY_REGEX.fullmatch(qrcode_key):
        raise QRProtocolError('unexpected_protocol')

    url = data.get('url')
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in url):
        raise QRProtocolError('unexpected_qr_url')

    p = urlsplit(url)
    if (p.scheme != 'https' or
            p.netloc != 'passport.bilibili.com' or
            p.path != '/h5-app/passport/login/scan' or
            p.fragment):
        raise QRProtocolError('unexpected_qr_url')

    try:
        q = parse_qs(p.query, strict_parsing=True, keep_blank_values=True, max_num_fields=2)
    except Exception:
        raise QRProtocolError('unexpected_qr_url') from None

    if (set(q.keys()) != {'navhide', 'qrcode_key'} or
            q.get('navhide') != ['1'] or
            q.get('qrcode_key') != [qrcode_key]):
        raise QRProtocolError('unexpected_qr_url')

    return QRChallenge(url=url, qrcode_key=qrcode_key)


def parse_qr_poll(body: bytes) -> QRPollResult:
    """
    Parse and validate domestic QR poll response.
    Validates inner data.code as exact int in {86101, 86090, 86038, 0}.
    """
    data = parse_fail_closed_json(body)
    code = data.get('code')
    if type(code) is not int or isinstance(code, bool) or code not in POLL_STATES:
        raise QRProtocolError('unexpected_protocol')

    status = POLL_STATES[code]
    # Upstream messages are untrusted and not part of this bounded projection.
    return QRPollResult(code=code, status=status)


# ---------------------------------------------------------------------------
# Phone Login Explicitly Unsupported Stub
# ---------------------------------------------------------------------------

def request_phone_login(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """
    Domestic phone SMS/password login is intentionally unsupported in this slice.
    Returns typed unsupported result.
    """
    return {
        'status': 'unsupported',
        'error': 'phone_login_unsupported_until_grounded',
        'live': False
    }


# ---------------------------------------------------------------------------
# Injected Session Port / Credential Isolation
# ---------------------------------------------------------------------------

class OpaqueSessionPort:
    """
    Synthetic validation seam only: creates a marker, DOES NOT store credentials.
    Not a production vault or proof of persisted/login-verified state.
    Raw cookie strings are never exposed or returned in logs or string representations.
    """
    @staticmethod
    def extract_opaque_handle(headers: List[str]) -> OpaqueSessionHandle:
        if not isinstance(headers, (list, tuple)) or len(headers) > 32 or any(type(h) is not str for h in headers) or sum(len(h) for h in headers) > 16384:
            raise QRProtocolError('missing_or_invalid_session')

        found_sessdata = False
        try:
            for raw in headers:
                if not isinstance(raw, str):
                    raise ValueError
                c = SimpleCookie()
                c.load(raw)
                if 'SESSDATA' in c:
                    val = c['SESSDATA'].value
                    if val and len(val) <= 4096 and not any(ord(x) <= 32 or ord(x) >= 127 or x in ';,' for x in val):
                        found_sessdata = True
        except Exception:
            raise QRProtocolError('missing_or_invalid_session') from None

        if not found_sessdata:
            raise QRProtocolError('missing_or_invalid_session')

        # Return strictly opaque handle with synthetic token id
        return OpaqueSessionHandle(
            handle_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            _internal_vault_ref='vault://redacted'
        )


# ---------------------------------------------------------------------------
# QR Login Coordinator (Single-Pending-Login State Contract)
# ---------------------------------------------------------------------------

class QRLoginCoordinator:
    """One pending synthetic login. Every transport admission rechecks pause.

    Calls occur outside the lock so close() can invalidate an in-flight request.
    A generation token binds each response to the still-current attempt. No
    retries/recreation, production credential persistence, or identity proof.
    Caller approval inputs are a trusted operator seam, not model tool arguments.
    """
    def __init__(self, transport=None, pause_gate=None, session_port=None):
        self._transport=transport
        self._pause_gate=pause_gate
        self._session_port=session_port or OpaqueSessionPort()
        self._lock=threading.RLock()
        self._generation=0
        self._inflight=False
        self._generate_attempted=False
        self._has_confirmed=False
        self._challenge=None
        self._session_handle=None
        self.state='new'

    def _gate_snapshot(self):
        try:
            gate=self._pause_gate
            value=(gate,0) if type(gate) is bool else gate.snapshot()
            if type(value) is not tuple or len(value)!=2 or type(value[0]) is not bool or type(value[1]) is not int:
                return ('pause_state_unknown',None)
            return ('account_operations_paused' if value[0] else None,value[1])
        except Exception:
            return ('pause_state_unknown',None)

    @staticmethod
    def _blocked(reason, called=False):
        return {'status':'blocked','reason':reason,'transport_called':called}

    def close(self):
        with self._lock:
            self._generation+=1
            self._challenge=None
            self._session_handle=None
            self.state='closed'

    def _accept_response(self, generation, pause_version):
        if generation != self._generation or self.state=='closed':
            return self._blocked('stale_attempt', True)
        reason,current_version=self._gate_snapshot()
        if current_version!=pause_version and not reason: reason='pause_generation_changed'
        if reason:
            self.close()
            return self._blocked(reason, True)
        return None

    def generate(self, *, approved, consent_ref):
        with self._lock:
            reason,pause_version=self._gate_snapshot()
            if reason: return self._blocked(reason)
            if self._generate_attempted or self.state!='new' or self._inflight:
                raise QRProtocolError('single_pending_login_enforced')
            if approved is not True or type(consent_ref) is not str or not consent_ref.strip() or len(consent_ref)>200:
                raise QRProtocolError('consent_or_state_required')
            if self._transport is None:
                raise QRProtocolError('invalid_transport_request')
            self._generate_attempted=True
            self._inflight=True
            self.state='generating'
            generation=self._generation
        try:
            body,_=self._transport.request('generate')
            challenge=parse_qr_generate(body)
            with self._lock:
                blocked=self._accept_response(generation,pause_version)
                if blocked: return blocked
                self._challenge=challenge
                self.state='ready'
                return {'status':'ready','challenge':challenge,'transport_called':True}
        except QRProtocolError:
            self.close(); raise
        except Exception:
            self.close(); raise QRProtocolError('internal_failure') from None
        finally:
            with self._lock: self._inflight=False

    def poll_once(self):
        with self._lock:
            reason,pause_version=self._gate_snapshot()
            if reason: return self._blocked(reason)
            if self._inflight or self.state not in ('ready','waiting_scan','waiting_confirmation') or self._challenge is None:
                raise QRProtocolError('invalid_state')
            generation=self._generation
            key=self._challenge.qrcode_key
            self._inflight=True
        try:
            body,headers=self._transport.request('poll',key=key)
            result=parse_qr_poll(body)
            with self._lock:
                blocked=self._accept_response(generation,pause_version)
                if blocked: return blocked
                if self._has_confirmed and result.status=='waiting_scan':
                    raise QRProtocolError('unexpected_protocol')
                if result.status=='waiting_confirmation': self._has_confirmed=True
                if result.status=='authenticated':
                    # Trusted synthetic port may itself reenter close(); check again.
                    handle=self._session_port.extract_opaque_handle(headers)
                    blocked=self._accept_response(generation,pause_version)
                    if blocked: return blocked
                    self._session_handle=handle
                    self._challenge=None
                    self.state='session_received'
                    return {'status':'session_received','poll_result':result,'session_handle':handle,
                            'credential_persisted':False,'auth_assessment':'not_assessed'}
                self.state=result.status
                if result.status=='expired': self._challenge=None
                return {'status':result.status,'poll_result':result}
        except QRProtocolError:
            self.close(); raise
        except Exception:
            self.close(); raise QRProtocolError('internal_failure') from None
        finally:
            with self._lock: self._inflight=False
