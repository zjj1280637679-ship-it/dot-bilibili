"""
next_phase/metadata/versioned_adapter.py - Versioned Metadata Observation & Gated Narrow HTTP Transport

Schema Version: metadata-observation/v2-candidate
Part of the Bilibili Modular Control Integration (Offline Implementation).

Guarantees:
1. Versioned typed result mapping (SCHEMA_VERSION = "metadata-observation/v2-candidate").
2. Defensive observation envelope:
   - status in ('parsed', 'partial', 'wrong_target', 'upstream_error', 'unknown', 'rejected', 'blocked', 'pending', 'deferred')
   - partial keeps exact field_states (present, missing, invalid) and projection_complete=False
   - wrong_target withholds all response metadata (data={})
   - upstream_error preserves numeric upstream_code without guessing auth/login/not-found
   - auth_assessment is strictly 'not_assessed'
   - live_verified is strictly False for synthetic/supplied data
3. NarrowViewHttpTransport:
   - Pinned strictly to https://api.bilibili.com/x/web-interface/view?bvid=<bvid>
   - Defaults to network_enabled=False and paused=True (TransportReply('blocked'), zero network calls)
   - When injected with a mock opener in tests:
     * NoRedirectHandler (HTTP 301/302/303/307/308 blocked, mapped to unknown, zero redirect follow)
     * MAX_BODY_BYTES = 512 * 1024 bounded read
     * Requires Content-Type: application/json
     * ZERO retries on timeout or HTTP error
     * Strictly rejects any caller-supplied URLs, headers, cookies, or secrets
4. Gated Tool Entrypoint (execute_metadata_read):
   - Strictly rejects any secret or transport-override keys (cookie, token, headers, url, etc.)
   - Checks persistent pause gate and reference binding
   - Binds to durable SQLite operation ledger (operation_id + semantic fingerprint)
   - Idempotent replay for identical fingerprint; conflict error for differing target; zero auto-replay on crash/unknown.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import secrets
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# dot local patch 2026-10-27; original AG bytes are snapshotted separately.
# Exact file/hash import, no shadowable generic import or inline fallback.
CANDIDATE_DIR = Path(__file__).resolve().parent.parent.parent / "metadata-adapter-candidate"
PARSER_SHA256 = "0f01d77e4c99966fded9e0afbf2b42c599d255ff67666392d1c0841174092fa0"
_parser_path = CANDIDATE_DIR / "metadata_adapter.py"
if hashlib.sha256(_parser_path.read_bytes()).hexdigest() != PARSER_SHA256:
    raise ImportError("metadata_parser_integrity_mismatch")
_parser_name = "_bili_metadata_parser_" + PARSER_SHA256
if _parser_name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_parser_name, _parser_path)
    _parser = importlib.util.module_from_spec(_spec)
    sys.modules[_parser_name] = _parser
    _spec.loader.exec_module(_parser)
else:
    _parser = sys.modules[_parser_name]
for _name in ("BVID", "FIELDS", "MAX_BODY_BYTES", "MetadataAdapter", "MetadataResult",
              "Provenance", "ReadRequest", "Transport", "TransportReply", "parse_metadata", "valid_bvid"):
    globals()[_name] = getattr(_parser, _name)


SCHEMA_VERSION = "metadata-observation/v2-candidate"

# Secret and transport-override keys that must be strictly rejected
FORBIDDEN_ARG_KEYS = frozenset({
    "cookie",
    "cookies",
    "token",
    "sessdata",
    "bili_jct",
    "headers",
    "url",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "password",
    "secret",
})

OPERATION_ID_REGEX = re.compile(r"[A-Za-z0-9_-]{1,128}")


# ============================================================================
# Layer 1: Versioned Typed Result Mapping
# ============================================================================

def make_versioned_observation(
    result: MetadataResult,
    *,
    transport_status: Optional[str] = None,
    http_status: Optional[int] = None,
    opener_call_entries: Optional[int] = None,
    response_observed: Optional[bool] = None,
    transport_callback_entries: Optional[int] = None,
    operation_completion: str = "not_assigned",
) -> Dict[str, Any]:
    """
    Transforms a raw MetadataResult into a frozen, defensive, versioned observation
    envelope adhering strictly to SCHEMA_VERSION = 'metadata-observation/v2-candidate'.
    """
    r = result.to_dict()
    obs_status = r["status"]

    # Defensive invariant: wrong_target must withhold all response metadata
    if obs_status == "wrong_target":
        data: Dict[str, Any] = {}
    else:
        # Create a fresh deep-copy to prevent external mutation
        data = json.loads(json.dumps(r.get("data", {})))

    coverage = {
        "projection_fields": list(FIELDS),
        "projection_complete": bool(obs_status == "parsed"),
        "full_api_response": False,
    }

    # Layered diagnostics
    layer_status = transport_status or ("unobserved" if r["transport_calls"] > 0 else "none")
    diagnostic = {
        "code": r["error"],
        "upstream_code": r["upstream_code"],
        "transport_layer_status": layer_status,
        "http_status": http_status,
    }

    evidence = {
        "adapter_callback_entries": r["transport_calls"],
        "transport_callback_entries": r["transport_calls"] if transport_callback_entries is None else transport_callback_entries,
        "opener_call_entries": opener_call_entries,
        "http_response_observed": response_observed,
        "http_send_verified": False,
        "live_verified": False,
    }

    return {
        "schema": SCHEMA_VERSION,
        "status": obs_status,
        "observation_status": obs_status,
        "data": data,
        "field_states": dict(r.get("field_states", {})),
        "coverage": coverage,
        "source": r["source"],
        "diagnostic": diagnostic,
        "evidence": evidence,
        "auth_assessment": "not_assessed",
        "operation_completion": operation_completion,
    }


def make_rejected_observation(
    error_code: str,
    *,
    expected_bvid: Optional[str] = None,
    operation_completion: str = "rejected",
) -> Dict[str, Any]:
    """Generates a defensive observation envelope for pre-dispatch rejections."""
    return {
        "schema": SCHEMA_VERSION,
        "status": "rejected",
        "observation_status": "rejected",
        "data": {},
        "field_states": {},
        "coverage": {
            "projection_fields": list(FIELDS),
            "projection_complete": False,
            "full_api_response": False,
        },
        "source": Provenance.SYNTHETIC.value,
        "diagnostic": {
            "code": error_code,
            "upstream_code": None,
            "transport_layer_status": "none",
            "http_status": None,
        },
        "evidence": {
            "transport_callback_entries": 0,
            "adapter_callback_entries": 0,
            "opener_call_entries": 0,
            "http_response_observed": False,
            "http_send_verified": False,
            "live_verified": False,
        },
        "auth_assessment": "not_assessed",
        "operation_completion": operation_completion,
    }


def make_blocked_observation(
    error_code: str,
    *,
    operation_completion: str = "blocked",
) -> Dict[str, Any]:
    """Generates a defensive observation envelope for pre-dispatch blocks (e.g. pause gate)."""
    return {
        "schema": SCHEMA_VERSION,
        "status": "blocked",
        "observation_status": "blocked",
        "data": {},
        "field_states": {},
        "coverage": {
            "projection_fields": list(FIELDS),
            "projection_complete": False,
            "full_api_response": False,
        },
        "source": Provenance.SYNTHETIC.value,
        "diagnostic": {
            "code": error_code,
            "upstream_code": None,
            "transport_layer_status": "none",
            "http_status": None,
        },
        "evidence": {
            "transport_callback_entries": 0,
            "adapter_callback_entries": 0,
            "opener_call_entries": 0,
            "http_response_observed": False,
            "http_send_verified": False,
            "live_verified": False,
        },
        "auth_assessment": "not_assessed",
        "operation_completion": operation_completion,
    }


# ============================================================================
# Layer 2: Narrow HTTP Transport (Mock-Testable, Default Disconnected/Paused)
# ============================================================================

class RedirectBlockedError(urllib.error.HTTPError):
    """Raised when an HTTP redirect is detected; redirection following is strictly forbidden."""
    pass


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Handler that intercepts and rejects any HTTP 3xx redirection attempts."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectBlockedError(
            req.full_url, code, "redirect_blocked", headers, fp
        )


@dataclass(frozen=True)
class _HttpObservation:
    """Immutable evidence returned by the same invocation, never shared latest state."""
    request_bvid: Optional[str]
    transport_status: Optional[str]
    http_status: Optional[int]
    opener_call_entries: int
    response_observed: bool


class NarrowViewHttpTransport:
    """
    Mock-testable, default-disconnected, zero-live-network HTTP transport.
    Strictly pinned to endpoint: https://api.bilibili.com/x/web-interface/view?bvid=<bvid>
    
    Invariants:
    - Defaults to network_enabled=False and paused=True.
    - Zero network or opener calls made when paused or network disabled.
    - When invoked with an injected opener in tests:
      * Enforces NoRedirectHandler (zero redirect follow, maps 3xx to unknown).
      * Enforces MAX_BODY_BYTES = 512 * 1024 bounded read.
      * Requires Content-Type: application/json.
      * Zero retries on timeout, connection reset, or HTTP error.
      * Rejects any caller-supplied URLs, headers, cookies, or secrets.
    """
    PINNED_HOST = "api.bilibili.com"
    PINNED_PATH = "/x/web-interface/view"
    MAX_BODY_BYTES = MAX_BODY_BYTES

    def __init__(
        self,
        *,
        network_enabled: bool = False,
        paused: bool = True,
        opener: Optional[urllib.request.OpenerDirector] = None,
    ):
        if type(network_enabled) is not bool or type(paused) is not bool:
            raise ValueError("boolean_transport_gates_required")
        self.network_enabled = network_enabled
        self.paused = paused
        self._opener = opener
        self.last_transport_status: Optional[str] = None
        self.last_http_status: Optional[int] = None
        self.last_opener_call_entries = 0
        self.last_response_observed = False

    def invoke_with_evidence(self, request: ReadRequest):
        """One reply and its immutable call-local evidence; safe for shared transport.

        No global serialization is needed. An injected opener must itself support
        its owner's concurrency policy and must not retry/follow redirects.
        """
        observed = {}
        reply = self._invoke(request, observed)
        return reply, _HttpObservation(
            request.bvid if type(request) is ReadRequest else None, **observed)

    def __call__(self, request: ReadRequest) -> TransportReply:
        # Legacy inspection-only last_* fields; never used by execute_metadata_read.
        # Concurrent callers requiring accurate evidence use invoke_with_evidence.
        reply, observed = self.invoke_with_evidence(request)
        self.last_transport_status = observed.transport_status
        self.last_http_status = observed.http_status
        self.last_opener_call_entries = observed.opener_call_entries
        self.last_response_observed = observed.response_observed
        return reply

    def _invoke(self, request: ReadRequest, observed: dict) -> TransportReply:
        observed["transport_status"] = None
        observed["http_status"] = None
        observed["opener_call_entries"] = 0
        observed["response_observed"] = False
        if type(self.network_enabled) is not bool or type(self.paused) is not bool:
            observed["transport_status"] = "invalid_gate_state"
            return TransportReply("blocked")
        # Validate ReadRequest shape
        if type(request) is not ReadRequest:
            observed["transport_status"] = "invalid_request_type"
            return TransportReply("unknown")
        if request.operation != "video.metadata.read":
            observed["transport_status"] = "invalid_operation"
            return TransportReply("unknown")
        if request.endpoint_key != "web_view_v1":
            observed["transport_status"] = "invalid_endpoint_key"
            return TransportReply("unknown")
        if not valid_bvid(request.bvid):
            observed["transport_status"] = "invalid_bvid"
            return TransportReply("blocked")

        # Zero platform calls when paused or network disabled
        if self.paused:
            observed["transport_status"] = "blocked_paused"
            return TransportReply("blocked")
        if not self.network_enabled:
            observed["transport_status"] = "blocked_network_disabled"
            return TransportReply("blocked")

        # Construct strict pinned URL with validated BVID query parameter
        url = f"https://{self.PINNED_HOST}{self.PINNED_PATH}?bvid={urllib.parse.quote(request.bvid)}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Antigravity-Bilibili-Offline-Control/20261027",
                "Accept": "application/json",
            },
            method="GET",
        )

        opener = self._opener
        if opener is None:
            opener = urllib.request.build_opener(NoRedirectHandler)

        try:
            # Perform single bounded HTTP request; NO RETRIES
            observed["opener_call_entries"] = 1
            resp = opener.open(req, timeout=10.0)
            observed["response_observed"] = True
            ctx = resp if hasattr(resp, "__enter__") else None

            try:
                if ctx is not None:
                    resp = ctx.__enter__()

                http_status = getattr(resp, "status", None)
                if http_status is None:
                    http_status = getattr(resp, "code", None)
                if type(http_status) is not int or not 100 <= http_status <= 599:
                    observed["transport_status"] = "missing_or_invalid_http_status"
                    return TransportReply("unknown")
                observed["http_status"] = http_status

                if hasattr(resp, "geturl") and resp.geturl() != url:
                    observed["transport_status"] = "unexpected_response_url"
                    return TransportReply("unknown", http_status=http_status)

                # Check if redirect code was returned without exception
                if http_status in (301, 302, 303, 307, 308):
                    observed["transport_status"] = "redirect_blocked"
                    return TransportReply("unknown", http_status=http_status)

                # Validate Content-Type: application/json
                headers = getattr(resp, "headers", None)
                content_type = ""
                if headers is not None:
                    if hasattr(headers, "get"):
                        content_type = headers.get("Content-Type", "") or ""
                    elif isinstance(headers, dict):
                        content_type = headers.get("Content-Type", "") or ""

                if type(content_type) is not str or content_type.split(";", 1)[0].strip().lower() != "application/json":
                    observed["transport_status"] = "non_json_content_type"
                    return TransportReply("unknown", http_status=http_status)

                # Bounded read: read at most MAX_BODY_BYTES + 1
                encoding = headers.get("Content-Encoding", "identity") if headers is not None else "identity"
                if type(encoding) is not str or encoding.strip().lower() not in ("", "identity"):
                    observed["transport_status"] = "unsupported_content_encoding"
                    return TransportReply("unknown", http_status=http_status)
                body = resp.read(self.MAX_BODY_BYTES + 1)
                if type(body) is not bytes:
                    observed["transport_status"] = "invalid_body_type"
                    return TransportReply("unknown", http_status=http_status)
                if len(body) > self.MAX_BODY_BYTES:
                    observed["transport_status"] = "oversize_body"
                    return TransportReply("unknown", http_status=http_status)

                observed["transport_status"] = "response"
                return TransportReply("response", http_status=http_status, body=body)

            finally:
                if ctx is not None:
                    ctx.__exit__(None, None, None)
                elif hasattr(resp, "close"):
                    resp.close()

        except (RedirectBlockedError, urllib.error.HTTPError) as err:
            code = getattr(err, "code", getattr(err, "status", None))
            code = code if type(code) is int and 100 <= code <= 599 else None
            observed["http_status"] = code
            observed["response_observed"] = code is not None
            observed["transport_status"] = "http_error"
            # Zero retries on 504 Gateway Timeout or 302 Redirect
            return TransportReply("unknown", http_status=code)

        except (urllib.error.URLError, TimeoutError, OSError, ConnectionError) as err:
            observed["transport_status"] = "network_error"
            # Zero retries on transport/network drop
            return TransportReply("unknown", http_status=None)

        except Exception as err:
            observed["transport_status"] = "unexpected_transport_error"
            return TransportReply("unknown", http_status=None)


# ============================================================================
# Layer 3: Durable SQLite Ledger & Gated Tool Entrypoint
# ============================================================================

def init_metadata_ledger(conn: sqlite3.Connection, initial_paused: bool = True) -> None:
    """Initializes controls and operations tables with SQLite WAL mode."""
    if type(initial_paused) is not bool:
        raise ValueError("boolean_initial_pause_required")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata_controls (
            id INTEGER PRIMARY KEY CHECK(id=1),
            paused INTEGER NOT NULL
        );
    """)
    conn.execute("INSERT OR IGNORE INTO metadata_controls VALUES(1, ?);", (int(initial_paused),))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata_operations (
            id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            owner TEXT NOT NULL,
            result TEXT
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metadata_operations_fp ON metadata_operations(fingerprint);")
    conn.commit()


def compute_semantic_fingerprint(backend: str, capability: str, target: str, *,
                                 provenance=Provenance.SUPPLIED,
                                 account_scope="offline_unbound") -> str:
    canonical = json.dumps([SCHEMA_VERSION, backend, capability, target,
                            provenance.value, account_scope], separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _gate_snapshot(conn, pause_gate):
    if pause_gate is not None:
        state = pause_gate.snapshot()
        if (type(state) is not tuple or len(state) != 2 or type(state[0]) is not bool
                or type(state[1]) is not int or state[1] < 0):
            raise ValueError("invalid_pause_snapshot")
        return state
    # Legacy local-only test control. It is NOT a shared account authority.
    row = conn.execute("SELECT paused FROM metadata_controls WHERE id=1").fetchone()
    if row is None or type(row[0]) is not int or row[0] not in (0, 1):
        raise ValueError("invalid_local_pause_state")
    return bool(row[0]), 0


def _gate_observation(status, code, provenance):
    return make_versioned_observation(
        MetadataResult(status, {}, {}, code, provenance), transport_status="none",
        opener_call_entries=0, response_observed=False, transport_callback_entries=0,
        operation_completion=status)


def _delivery(record, *, cached):
    result = json.loads(json.dumps(record, allow_nan=False))
    result["delivery"] = "cached" if cached else "current"
    evidence = result["evidence"]
    result["invocation"] = {
        "transport_callback_entries": 0 if cached else evidence["transport_callback_entries"],
        "opener_call_entries": 0 if cached else evidence.get("opener_call_entries"),
        "http_send_verified": False,
    }
    return result


def execute_metadata_read(
    db: Union[str, Path, sqlite3.Connection], *, reference_id: str,
    expected_bvid: str, operation_id: str, backend: str = "web_view_v1",
    ref_map: Optional[Dict[str, str]] = None, transport: Optional[Transport] = None,
    provenance: Provenance = Provenance.SUPPLIED, run_id: Optional[str] = None,
    pause_gate=None, authorization_check: Optional[Callable[[], bool]] = None,
    account_scope: str = "offline_unbound", **kwargs: Any,
) -> Dict[str, Any]:
    """Narrow metadata relation, not a generic dispatcher or authorization issuer.

    pause_gate.snapshot() is the shared account authority when supplied; otherwise
    only isolated local test pause exists. authorization_check is a trusted zero-
    argument closure binding the caller's read lease; missing/unknown never grants.
    Neither port is an agent-supplied boolean/tool argument. Both are rechecked
    immediately before the injected transport. No in-flight cancellation claim.
    """
    if kwargs:
        code = ("secret_or_transport_override_forbidden"
                if any(k.lower() in FORBIDDEN_ARG_KEYS for k in kwargs)
                else "unknown_arguments")
        return make_rejected_observation(code)
    if type(operation_id) is not str or not OPERATION_ID_REGEX.fullmatch(operation_id):
        return make_rejected_observation("invalid_operation_id")
    if not valid_bvid(expected_bvid):
        return make_rejected_observation("invalid_bvid")
    if backend != "web_view_v1" or type(backend) is not str:
        return make_rejected_observation("unsupported_backend")
    if type(provenance) is not Provenance:
        return make_rejected_observation("invalid_provenance")
    if type(account_scope) is not str or not OPERATION_ID_REGEX.fullmatch(account_scope):
        return make_rejected_observation("invalid_account_scope")
    if pause_gate is not None and account_scope == "offline_unbound":
        return make_rejected_observation("shared_account_scope_required")
    if (type(reference_id) is not str or type(ref_map) is not dict
            or ref_map.get(reference_id) != expected_bvid):
        return make_blocked_observation("stale_or_wrong_target_reference")
    if not callable(authorization_check):
        return make_blocked_observation("authorization_check_required")
    if transport is not None and not callable(transport):
        return make_rejected_observation("invalid_transport")
    if run_id is not None and (type(run_id) is not str or not OPERATION_ID_REGEX.fullmatch(run_id)):
        return make_rejected_observation("invalid_run_id")

    should_close = isinstance(db, (str, Path))
    conn = None
    observation = None
    try:
        conn = sqlite3.connect(str(db), timeout=10.0) if should_close else db
        if not isinstance(conn, sqlite3.Connection):
            return make_rejected_observation("invalid_ledger")
        init_metadata_ledger(conn)
        active_run_id = run_id or secrets.token_hex(16)
        fingerprint = compute_semantic_fingerprint(backend, "video.metadata.read", expected_bvid,
                                                   provenance=provenance, account_scope=account_scope)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT fingerprint, owner, result FROM metadata_operations WHERE id=?",
                               (operation_id,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    return make_rejected_observation("operation_id_conflict")
                if row[2] is not None:
                    return _delivery(json.loads(row[2]), cached=True)
                # Only an explicitly matching active run can identify pending work.
                pending = run_id is not None and row[1] == run_id
                return _gate_observation("pending" if pending else "unknown",
                                         "operation_in_progress" if pending else "previous_run_incomplete", provenance)
            try:
                initial_snapshot = _gate_snapshot(conn, pause_gate)
            except Exception:
                return _gate_observation("unknown", "pause_state_unknown", provenance)
            if initial_snapshot[0]:
                return _gate_observation("blocked", "account_operations_paused", provenance)
            try:
                allowed = authorization_check()
            except Exception:
                return _gate_observation("unknown", "authorization_unknown", provenance)
            if allowed is not True:
                return _gate_observation("blocked" if allowed is False else "unknown",
                                         "read_prerequisite_blocked" if allowed is False else "authorization_unknown", provenance)
            conn.execute("INSERT INTO metadata_operations VALUES(?,?,?,NULL)",
                         (operation_id, fingerprint, active_run_id))

        if transport is None:
            transport = NarrowViewHttpTransport()  # Remains disconnected and paused.
        seen = {"entries": 0, "status": "none", "http": None, "response": False,
                "opener": 0, "gate_code": None}

        def observed_transport(request):
            try:
                current = _gate_snapshot(conn, pause_gate)
                if current[0] or current[1] != initial_snapshot[1]:
                    seen["gate_code"] = "account_operations_paused" if current[0] else "pause_generation_changed"
                    seen["status"] = "blocked"
                    return TransportReply("blocked")
            except Exception:
                seen["gate_code"] = "pause_state_unknown"; seen["status"] = "unknown"
                return TransportReply("unknown")
            try:
                allowed_now = authorization_check()
            except Exception:
                allowed_now = None
            if allowed_now is not True:
                seen["gate_code"] = "read_prerequisite_blocked" if allowed_now is False else "authorization_unknown"
                seen["status"] = "blocked" if allowed_now is False else "unknown"
                return TransportReply(seen["status"])
            # The authorization callback may itself invalidate pause/generation.
            try:
                final_snapshot = _gate_snapshot(conn, pause_gate)
                if final_snapshot != initial_snapshot or final_snapshot[0]:
                    seen["gate_code"] = "pause_generation_changed"; seen["status"] = "blocked"
                    return TransportReply("blocked")
            except Exception:
                seen["gate_code"] = "pause_state_unknown"; seen["status"] = "unknown"
                return TransportReply("unknown")
            seen["entries"] += 1
            seen["opener"] = None  # Generic callable has no observed HTTP opener.
            try:
                if type(transport) is NarrowViewHttpTransport:
                    reply, call_evidence = transport.invoke_with_evidence(request)
                    seen["status"] = call_evidence.transport_status or "unknown"
                    seen["http"] = call_evidence.http_status
                    seen["response"] = call_evidence.response_observed
                    seen["opener"] = call_evidence.opener_call_entries
                    return reply
                reply = transport(request)
                if type(reply) is TransportReply:
                    seen["status"] = reply.disposition if reply.disposition in ("response", "blocked", "pending", "deferred", "unknown") else "unknown"
                    if type(reply.http_status) is int and 100 <= reply.http_status <= 599:
                        seen["http"] = reply.http_status; seen["response"] = True
                else:
                    seen["status"] = "unknown"
                return reply
            except Exception:
                seen["status"] = "unknown"
                raise

        meta_result = MetadataAdapter(observed_transport, provenance=provenance).read(expected_bvid)
        observation = make_versioned_observation(
            meta_result, transport_status=seen["status"], http_status=seen["http"],
            opener_call_entries=seen["opener"], response_observed=seen["response"],
            transport_callback_entries=seen["entries"], operation_completion="recorded")
        if seen["gate_code"] is not None:
            observation["diagnostic"]["gate_code"] = seen["gate_code"]
        with conn:
            updated = conn.execute("UPDATE metadata_operations SET result=? WHERE id=? AND owner=? AND result IS NULL",
                                   (json.dumps(observation, allow_nan=False), operation_id, active_run_id))
            if updated.rowcount != 1:
                raise ValueError("metadata_record_not_confirmed")
        return _delivery(observation, cached=False)
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        # A durable reservation, if created, remains unresolved: never retry here.
        if observation is not None:
            # Persistence uncertainty cannot erase an already observed callback,
            # HTTP status, or partial data, nor turn it into a confirmed record.
            observation["operation_completion"] = "recording_unknown"
            observation["diagnostic"]["ledger_code"] = "metadata_record_not_confirmed"
            return _delivery(observation, cached=False)
        return _gate_observation("unknown", "metadata_ledger_or_contract_unknown", provenance)
    finally:
        if should_close and conn is not None:
            conn.close()
