"""
next_phase/session/session_authority.py - Opaque Credential Store, Persistent Pause,
and Semantic NAV Session Authority.

Part of the Bilibili Control Integration (Next Phase Session Foundation).
Python standard library only. Zero platform calls, zero live credentials, zero network.
"""

from __future__ import annotations

import enum
import json
import math
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, Tuple, Union


# ============================================================================
# Enums and Flags
# ============================================================================

class StorageState(str, enum.Enum):
    """Integrity state of the opaque credential store record."""
    PRESENT = "present"
    MISSING = "missing"
    CORRUPT = "corrupt"
    UNAVAILABLE = "unavailable"


class SessionState(str, enum.Enum):
    """Lifecycle states of the in-memory session authority."""
    UNINITIALIZED = "uninitialized"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    NOT_LOGGED_IN = "not_logged_in"
    IDENTITY_MISMATCH = "identity_mismatch"
    VERIFICATION_UNKNOWN = "verification_unknown"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CLOSED = "closed"


class CapabilityFlag(enum.IntFlag):
    """Operational capability permissions."""
    NONE = 0
    ANONYMOUS_READ = 1 << 0   # Public videos, public comments, search
    AUTH_READ = 1 << 1        # Private history, user dynamic feed
    WRITE_LOW_RISK = 1 << 2   # Like, favorite, coin
    WRITE_HIGH_RISK = 1 << 3  # Post comment, publish dynamic
    ADMIN = 1 << 4            # Revoke session, change credentials


class SecurityViolationError(Exception):
    """Raised when forbidden raw credential tokens or security boundaries are violated."""
    pass


class SessionStateError(Exception):
    """Raised when an operation cannot be performed in the current session state."""
    pass


# Forbidden secret key substrings (case-insensitive)
FORBIDDEN_SECRET_KEYS = {
    "cookie",
    "cookies",
    "sessdata",
    "bili_jct",
    "token",
    "tokens",
    "password",
    "secret",
    "authorization",
}


def assert_no_secret_keys(data: Any, path: str = "root") -> None:
    """
    Recursively verifies that no raw credential keys exist in any dictionary or data structure.
    Rejects raw tokens (SESSDATA, bili_jct, cookies, passwords, tokens) with SecurityViolationError.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = str(key).lower()
            for forbidden in FORBIDDEN_SECRET_KEYS:
                if forbidden in key_lower:
                    raise SecurityViolationError(
                        "forbidden_credential_key"
                    )
            assert_no_secret_keys(value, f"{path}.{key}")
    elif isinstance(data, (list, tuple, set)):
        for idx, item in enumerate(data):
            assert_no_secret_keys(item, f"{path}[{idx}]")


# ============================================================================
# Opaque Credential Handle and Store Protocol
# ============================================================================

@dataclass(frozen=True)
class CredentialHandle:
    """
    Opaque reference to stored credentials.
    Contains ONLY non-secret metadata (account_id, handle_id, version, storage_state).
    NEVER contains, stores, serializes, or logs raw tokens (SESSDATA, bili_jct, cookies).
    """
    account_id: str
    handle_id: str
    version: int
    storage_state: StorageState

    def __post_init__(self):
        assert_no_secret_keys({
            "account_id": self.account_id,
            "handle_id": self.handle_id,
            "version": self.version,
            "storage_state": str(self.storage_state),
        })


class CredentialStorePort(Protocol):
    """Protocol for opaque credential persistence."""

    def save_handle(
        self, account_id: str, handle_id: str, version: int, metadata: Optional[Dict[str, Any]] = None
    ) -> CredentialHandle:
        ...

    def load_handle(self, account_id: str) -> CredentialHandle:
        ...

    def delete_handle(self, account_id: str) -> None:
        ...

    def check_state(self, account_id: str) -> StorageState:
        ...


class SyntheticCredentialStore:
    """
    SQLite-backed synthetic credential store satisfying CredentialStorePort.
    Stores only opaque handle references and non-secret metadata.
    Enforces strict raw-token rejection on save and retrieval.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._db_lock = threading.RLock()
        self._simulate_unavailable = False
        self._persistent_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        with self._db_lock:
            with self._connection_unlocked() as conn:
                yield conn

    @contextmanager
    def _connection_unlocked(self) -> Iterator[sqlite3.Connection]:
        if self._simulate_unavailable:
            raise sqlite3.OperationalError("Simulated credential storage backend unavailable")
        if self._persistent_conn is not None:
            with self._persistent_conn:
                yield self._persistent_conn
            return
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS credential_handles (
                    account_id TEXT PRIMARY KEY,
                    handle_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    metadata_json TEXT,
                    storage_state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.commit()

    def set_simulated_unavailable(self, unavailable: bool) -> None:
        """Testing hook to simulate infrastructure outage."""
        self._simulate_unavailable = unavailable

    def save_handle(
        self, account_id: str, handle_id: str, version: int, metadata: Optional[Dict[str, Any]] = None
    ) -> CredentialHandle:
        if not account_id or not handle_id:
            raise ValueError("account_id and handle_id must be non-empty strings")
        if type(version) is not int or version < 1:
            raise ValueError("version must be a positive integer >= 1")

        if metadata is not None:
            assert_no_secret_keys(metadata, path="metadata")
            meta_json = json.dumps(metadata, sort_keys=True, allow_nan=False)
        else:
            meta_json = "{}"

        now = time.time()
        state_str = StorageState.PRESENT.value

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO credential_handles (
                    account_id, handle_id, version, metadata_json, storage_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    handle_id = excluded.handle_id,
                    version = excluded.version,
                    metadata_json = excluded.metadata_json,
                    storage_state = excluded.storage_state,
                    updated_at = excluded.updated_at;
            """, (account_id, handle_id, version, meta_json, state_str, now, now))
            conn.commit()

        return CredentialHandle(
            account_id=account_id,
            handle_id=handle_id,
            version=version,
            storage_state=StorageState.PRESENT,
        )

    def load_handle(self, account_id: str) -> CredentialHandle:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT account_id, handle_id, version, metadata_json, storage_state "
                    "FROM credential_handles WHERE account_id = ?",
                    (account_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return CredentialHandle(
                        account_id=account_id,
                        handle_id="",
                        version=0,
                        storage_state=StorageState.MISSING,
                    )

                # Integrity verification
                try:
                    meta = json.loads(row["metadata_json"])
                    assert_no_secret_keys(meta, path="stored_metadata")
                except (json.JSONDecodeError, SecurityViolationError):
                    return CredentialHandle(
                        account_id=account_id,
                        handle_id=row["handle_id"] or "",
                        version=row["version"] or 0,
                        storage_state=StorageState.CORRUPT,
                    )

                return CredentialHandle(
                    account_id=row["account_id"],
                    handle_id=row["handle_id"],
                    version=row["version"],
                    storage_state=StorageState(row["storage_state"]),
                )
        except sqlite3.OperationalError:
            return CredentialHandle(
                account_id=account_id,
                handle_id="",
                version=0,
                storage_state=StorageState.UNAVAILABLE,
            )

    def delete_handle(self, account_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM credential_handles WHERE account_id = ?", (account_id,))
            conn.commit()

    def check_state(self, account_id: str) -> StorageState:
        handle = self.load_handle(account_id)
        return handle.storage_state


# ============================================================================
# Persistent Account-Wide Pause Gate
# ============================================================================

class PauseManager:
    """
    Durable, SQLite-backed account pause manager.
    Invariants:
    1. Default is paused=True.
    2. Survives process and service restart.
    3. initial_paused=False applies ONLY when initializing a completely new account record;
       it NEVER clears or overwrites an existing persisted pause state on restart!
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._db_lock = threading.RLock()
        self._persistent_conn: Optional[sqlite3.Connection] = None
        if self.db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        with self._db_lock:
            with self._connection_unlocked() as conn:
                yield conn

    @contextmanager
    def _connection_unlocked(self) -> Iterator[sqlite3.Connection]:
        if self._persistent_conn is not None:
            with self._persistent_conn:
                yield self._persistent_conn
            return
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS controls (
                    account_id TEXT PRIMARY KEY,
                    paused INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    reason TEXT
                );
            """)
            if "generation" not in {r[1] for r in conn.execute("PRAGMA table_info(controls)")}:
                conn.execute("ALTER TABLE controls ADD COLUMN generation INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def init_pause_state(self, account_id: str, initial_paused: bool = True) -> bool:
        """
        Initializes pause state for account.
        If a record already exists, returns the persisted paused state WITHOUT overwriting it!
        If no record exists, inserts the initial_paused setting.
        """
        if type(initial_paused) is not bool: raise ValueError("pause_bool_required")
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT paused FROM controls WHERE account_id = ?", (account_id,))
            row = cursor.fetchone()
            if row is not None:
                # Existing record preserved: restart NEVER clears existing pause state!
                return bool(row["paused"])

            # Brand-new record initialization
            conn.execute("""
                INSERT INTO controls (account_id, paused, updated_at, reason)
                VALUES (?, ?, ?, ?);
            """, (account_id, 1 if initial_paused else 0, now, "initial_setup"))
            conn.commit()
            return initial_paused

    def set_paused(self, account_id: str, paused: bool, reason: str = "") -> None:
        """Trusted local operator seam; not a model tool or account grant."""
        if type(paused) is not bool: raise ValueError("pause_bool_required")
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO controls (account_id, paused, updated_at, reason)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    paused = excluded.paused,
                    updated_at = excluded.updated_at,
                    reason = excluded.reason,
                    generation = controls.generation + 1;
            """, (account_id, 1 if paused else 0, now, reason))
            conn.commit()

    def is_paused(self, account_id: str) -> bool:
        """
        Reads durable pause state.
        Defaults to True (paused) if no record exists.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT paused FROM controls WHERE account_id = ?", (account_id,))
            row = cursor.fetchone()
            if row is None:
                return True
            return bool(row["paused"])


# ============================================================================
    def snapshot(self, account_id):
        with self._get_connection() as conn:
            row=conn.execute('SELECT paused,generation FROM controls WHERE account_id=?',(account_id,)).fetchone()
            return (True,0) if row is None else (bool(row['paused']),row['generation'])


# Semantic NAV Verifier
# ============================================================================

@dataclass(frozen=True)
class NavVerificationResult:
    """Outcome of evaluating a raw semantic NAV response."""
    state: SessionState
    mid: Optional[int] = None
    uname: Optional[str] = None
    is_silenced: bool = False
    raw_code: Optional[int] = None
    reason: str = ""


def _parse_strict_json(raw_body: bytes) -> Dict[str, Any]:
    """Decodes UTF-8 JSON and strictly rejects duplicate keys and non-finite numbers."""
    text = raw_body.decode("utf-8")

    def unique_pairs_hook(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate_json_key")
            result[k] = v
        return result

    def reject_nonfinite(constant: str) -> None:
        raise ValueError(f"Non-finite JSON constant rejected: {constant}")

    def finite_float(text):
        value=float(text)
        if not math.isfinite(value): raise ValueError("nonfinite_number")
        return value
    return json.loads(text, object_pairs_hook=unique_pairs_hook, parse_constant=reject_nonfinite, parse_float=finite_float)


def verify_nav_response(raw_body: bytes, expected_mid: int) -> NavVerificationResult:
    """
    Evaluates raw Bilibili NAV API response with strict semantic verification:
    1. expected_mid must be exact positive int (not bool).
    2. raw_body must be valid UTF-8 JSON with unique keys.
    3. code must be exact int.
    4. If code == -101 or (code == 0 and isLogin is False) -> not_logged_in.
    5. If malformed, missing data, non-bool isLogin, or other nonzero code -> verification_unknown
       (MUST NOT mark as expired or delete credentials!).
    6. If code == 0 and isLogin is True:
       - mid must be exact positive int, uname must be non-empty string.
       - If mid != expected_mid -> identity_mismatch.
       - If silence == 1 -> recorded as silenced (silence != logged_out).
       - Returns verified.
    """
    # 1. Exact type validation on expected_mid (disallowing bool)
    if type(expected_mid) is not int or expected_mid <= 0:
        raise TypeError("expected_mid_invalid")

    # 2. Parse UTF-8 JSON
    if not isinstance(raw_body, (bytes, bytearray)) or len(raw_body)>65536:
        return NavVerificationResult(
            state=SessionState.VERIFICATION_UNKNOWN,
            reason="raw_body must be bytes or bytearray",
        )

    try:
        parsed = _parse_strict_json(bytes(raw_body))
    except Exception as exc:
        return NavVerificationResult(
            state=SessionState.VERIFICATION_UNKNOWN,
            reason="malformed_json_or_encoding",
        )

    if not isinstance(parsed, dict):
        return NavVerificationResult(
            state=SessionState.VERIFICATION_UNKNOWN,
            reason="Response payload root is not a JSON object",
        )

    # 3. Code type check
    code = parsed.get("code")
    if not isinstance(code, int) or isinstance(code, bool):
        return NavVerificationResult(
            state=SessionState.VERIFICATION_UNKNOWN,
            reason="Response envelope 'code' is missing or not an exact integer",
        )

    # 4. Explicit unauthenticated states
    if code == -101:
        return NavVerificationResult(
            state=SessionState.NOT_LOGGED_IN,
            raw_code=code,
            reason="Upstream code -101 indicates account is not logged in",
        )

    if code == 0:
        data = parsed.get("data")
        if not isinstance(data, dict):
            return NavVerificationResult(
                state=SessionState.VERIFICATION_UNKNOWN,
                raw_code=code,
                reason="Envelope data field missing or not a dictionary",
            )

        is_login = data.get("isLogin")
        if not isinstance(is_login, bool):
            return NavVerificationResult(
                state=SessionState.VERIFICATION_UNKNOWN,
                raw_code=code,
                reason="isLogin field missing or not exact boolean",
            )

        if not is_login:
            return NavVerificationResult(
                state=SessionState.NOT_LOGGED_IN,
                raw_code=code,
                reason="Semantic NAV data.isLogin is False",
            )

        # isLogin is True: Validate identity
        mid = data.get("mid")
        if not isinstance(mid, int) or isinstance(mid, bool) or mid <= 0:
            return NavVerificationResult(
                state=SessionState.VERIFICATION_UNKNOWN,
                raw_code=code,
                reason="data.mid missing or not exact positive int",
            )

        uname = data.get("uname")
        if not isinstance(uname, str) or not uname.strip():
            return NavVerificationResult(
                state=SessionState.VERIFICATION_UNKNOWN,
                raw_code=code,
                reason="data.uname missing or empty string",
            )

        # Strict Expected MID assertion
        if mid != expected_mid:
            return NavVerificationResult(
                state=SessionState.IDENTITY_MISMATCH,
                mid=mid,
                uname=uname,
                raw_code=code,
                reason="identity_mismatch",
            )

        # Silence check (restricted, not logged out)
        silence = data.get("silence", 0)
        if type(silence) is not int or silence not in (0,1):
            return NavVerificationResult(state=SessionState.VERIFICATION_UNKNOWN, reason="invalid_silence")
        is_silenced = (silence == 1)

        return NavVerificationResult(
            state=SessionState.VERIFIED,
            mid=mid,
            uname=uname,
            is_silenced=is_silenced,
            raw_code=code,
            reason="Semantic NAV verification succeeded",
        )

    # 5. Other nonzero codes (e.g. -412, -500, etc.) MUST stay verification_unknown
    return NavVerificationResult(
        state=SessionState.VERIFICATION_UNKNOWN,
        raw_code=code,
        reason=f"Nonzero upstream code {code} preserved as verification_unknown without expiring session",
    )


# ============================================================================
# Monotonic Epoch Lease & Session Authority
# ============================================================================

@dataclass(frozen=True)
class SessionLease:
    """
    Monotonic execution lease for concurrency fencing and authorization.
    Tied to an exact epoch; invalidated if session transitions or closes.
    """
    account_id: str
    session_id: str
    epoch: int
    capability: CapabilityFlag
    issued_at: float
    is_silenced: bool = False
    pause_generation: int = 0


@dataclass(frozen=True)
class VerificationTicket:
    owner: str
    epoch: int
    pause_generation: int
    nonce: str


class SessionAuthority:
    """Synthetic account-bound authority, not a production authorization broker.

    Verification uses an issued single-use ticket captured BEFORE work begins.
    A completed parser result alone grants nothing. Pause versions fence in-flight
    results and old leases across pause/unpause. Business outcomes are separate.
    """
    def __init__(self, account_id, expected_mid, pause_manager, store=None):
        if type(expected_mid) is not int or expected_mid<=0: raise TypeError('expected_mid_invalid')
        if type(account_id) is not str or not account_id: raise ValueError('account_id_invalid')
        self.account_id=account_id;self.expected_mid=expected_mid
        self.pause_manager=pause_manager;self.store=store
        self._lock=threading.RLock();self._state=SessionState.UNINITIALIZED;self._epoch=0
        self._session_id=secrets.token_hex(24)
        self._identity=None;self._is_silenced=False;self._explicit_admin_grant=False
        self._business_outcome_log=[];self._tickets={};self._leases=[]

    @property
    def state(self):
        with self._lock:return self._state
    @property
    def epoch(self):
        with self._lock:return self._epoch
    @property
    def is_silenced(self):
        with self._lock:return self._is_silenced
    def _open(self):
        if self._state in (SessionState.CLOSED,SessionState.REVOKED):raise SessionStateError('authority_terminal')
    def _advance(self):
        self._epoch+=1;self._tickets.clear();self._leases.clear()
    def _pause(self):
        try:
            value=self.pause_manager.snapshot(self.account_id)
            if type(value[0]) is not bool or type(value[1]) is not int: raise ValueError()
            return value
        except Exception:raise SessionStateError('pause_state_unknown') from None
    def restore_from_store(self):
        with self._lock:
            self._open()
            if self.store is None:raise SessionStateError('store_not_configured')
            handle=self.store.load_handle(self.account_id)
            if handle.account_id!=self.account_id:raise SessionStateError('store_account_mismatch')
            self._advance();self._identity=None;self._is_silenced=False
            self._state=SessionState.UNVERIFIED if handle.storage_state==StorageState.PRESENT else SessionState.UNINITIALIZED
            return handle
    def stage_unverified(self):
        """Trusted explicit new attempt; may reopen a closed owner as a NEW generation.

        Reopening never revives prior tickets/leases or marks identity verified.
        It does not acquire credentials or authorize a network login.
        """
        with self._lock:
            if self._state in (SessionState.CLOSED,SessionState.REVOKED):
                self._session_id=secrets.token_hex(24)
            self._advance();self._state=SessionState.UNVERIFIED;self._identity=None;self._is_silenced=False;self._explicit_admin_grant=False
    def begin_verification(self):
        with self._lock:
            self._open();paused,version=self._pause()
            if paused:raise SessionStateError('account_operations_paused')
            ticket=VerificationTicket(self._session_id,self._epoch,version,secrets.token_hex(24))
            self._tickets[ticket.nonce]=ticket
            return ticket
    def verify_and_apply(self, raw_body):
        ticket=self.begin_verification()
        return self.apply_nav_verification(verify_nav_response(raw_body,self.expected_mid),ticket=ticket)
    def apply_nav_verification(self,result,*,ticket=None):
        with self._lock:
            self._open()
            if not isinstance(ticket,VerificationTicket) or self._tickets.pop(ticket.nonce,None) is not ticket:
                raise SessionStateError('verification_ticket_required_or_stale')
            paused,version=self._pause()
            if ticket.owner!=self._session_id or ticket.epoch!=self._epoch or ticket.pause_generation!=version or paused:
                raise SessionStateError('verification_fenced')
            if type(result) is not NavVerificationResult or type(result.state) is not SessionState:
                raise SessionStateError('verification_result_invalid')
            if result.state==SessionState.VERIFIED and (type(result.mid) is not int or result.mid!=self.expected_mid):
                self._advance();self._state=SessionState.IDENTITY_MISMATCH;self._identity=None
                raise SessionStateError('verification_identity_mismatch')
            self._advance()
            self._state=result.state;self._identity=None;self._is_silenced=False
            if result.state==SessionState.VERIFIED:
                self._identity={'mid':result.mid,'uname':result.uname};self._is_silenced=result.is_silenced
            return self._state
    def grant_admin_elevation(self,approved):
        """Trusted synthetic operator seam only; no production grant validation."""
        if type(approved) is not bool:raise ValueError('approval_bool_required')
        with self._lock:self._open();self._explicit_admin_grant=approved;self._advance()
    def _check_capability(self,capability):
        if type(capability) is not CapabilityFlag or capability not in tuple(CapabilityFlag):
            raise SessionStateError('capability_invalid')
        self._open()
        if self._state!=SessionState.VERIFIED and capability!=CapabilityFlag.ANONYMOUS_READ:
            raise SessionStateError('verification_required')
        if capability==CapabilityFlag.ADMIN and not self._explicit_admin_grant:
            raise SessionStateError('admin_grant_required')
        if capability in (CapabilityFlag.WRITE_LOW_RISK,CapabilityFlag.WRITE_HIGH_RISK):
            raise SessionStateError('write_authorization_not_implemented')
    def acquire_lease(self,capability):
        with self._lock:
            self._check_capability(capability);paused,version=self._pause()
            if paused:raise SessionStateError('account_operations_paused')
            lease=SessionLease(self.account_id,self._session_id,self._epoch,capability,time.time(),self._is_silenced,version)
            self._leases.append(lease);return lease
    def assert_valid_lease(self,lease):
        with self._lock:
            if not any(issued is lease for issued in self._leases):raise SessionStateError('lease_not_issued')
            self._check_capability(lease.capability);paused,version=self._pause()
            if paused or version!=lease.pause_generation:raise SessionStateError('lease_pause_fenced')
            if lease.account_id!=self.account_id or lease.session_id!=self._session_id or lease.epoch!=self._epoch:
                raise SessionStateError('lease_owner_or_epoch_mismatch')
    def invalidate(self,reason='explicit_invalidation'):
        with self._lock:
            self._open();self._advance();self._state=SessionState.EXPIRED;self._identity=None;self._explicit_admin_grant=False
    def close(self):
        with self._lock:
            self._advance();self._state=SessionState.CLOSED;self._identity=None;self._explicit_admin_grant=False
    def record_business_outcome(self,outcome_status,operation_id=None):
        with self._lock:
            self._business_outcome_log.append({'outcome_status':outcome_status,'operation_id':operation_id,'session_state_preserved':self._state.value})

class AccountPauseGate:
    """Bind one shared durable manager to one trusted account namespace."""
    def __init__(self, manager, account_id):
        self.manager=manager;self.account_id=account_id
    def is_paused(self):
        return self.manager.snapshot(self.account_id)[0]
    def snapshot(self):
        return self.manager.snapshot(self.account_id)
