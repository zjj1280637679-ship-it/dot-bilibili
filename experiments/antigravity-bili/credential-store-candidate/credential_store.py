"""dot-local POSIX file credential-port candidate, not enabled in any product.

Only trusted internal code may pass SecretMaterial or callbacks. Public receipts
contain opaque references, not material. This is a plaintext local-file boundary,
not encryption, an authorization issuer, a Python sandbox, or live acceptance.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

FORMAT = 'local-credential-port/v1-candidate'
MAX_SECRET_BYTES = 65536  # Local defensive bound, not a platform limit.
MAX_RECORD_BYTES = 100000
MAX_GENERATION = 2**63 - 1
ACCOUNT = re.compile(r'[A-Za-z0-9_-]{1,128}')
HANDLE = re.compile(r'[a-f0-9]{32}')


class StorageState(str, Enum):
    PRESENT = 'present'
    MISSING = 'missing'
    CORRUPT = 'corrupt'
    UNKNOWN = 'unknown'
    CONFLICT = 'conflict'
    REJECTED = 'rejected'


@dataclass(frozen=True)
class TrustedConfig:
    directory: Path = field(repr=False)
    account_id: str

    def __post_init__(self):
        if type(self.account_id) is not str or not ACCOUNT.fullmatch(self.account_id):
            raise ValueError('invalid_account_scope')
        if type(self.directory) not in (str, Path) and not isinstance(self.directory, Path):
            raise ValueError('invalid_trusted_directory')
        path = Path(self.directory)
        if not path.is_absolute() or '..' in path.parts or '\x00' in str(path):
            raise ValueError('absolute_trusted_directory_required')
        object.__setattr__(self, 'directory', path)


@dataclass(frozen=True, repr=False)
class SecretMaterial:
    """Internal opaque bytes. No platform field selection/coercion is performed."""
    _payload: bytes = field(repr=False)

    def __post_init__(self):
        if type(self._payload) is not bytes or not 1 <= len(self._payload) <= MAX_SECRET_BYTES:
            raise ValueError('invalid_secret_material')

    def __repr__(self):
        return 'SecretMaterial(<redacted>)'


@dataclass(frozen=True)
class OpaqueHandle:
    account_id: str
    handle_id: str
    generation: int

    def __post_init__(self):
        if (type(self.account_id) is not str or not ACCOUNT.fullmatch(self.account_id)
                or type(self.handle_id) is not str or not HANDLE.fullmatch(self.handle_id)
                or type(self.generation) is not int or not 1 <= self.generation <= MAX_GENERATION):
            raise ValueError('invalid_opaque_handle')

    def to_dict(self):
        return dict(account_id=self.account_id, handle_id=self.handle_id, generation=self.generation)


@dataclass(frozen=True)
class StoreResult:
    state: StorageState
    code: str
    handle: OpaqueHandle | None = None
    write_outcome: str = 'not_attempted'
    callback_entries: int = 0

    def to_dict(self):
        return dict(state=self.state.value, code=self.code,
                    handle=None if self.handle is None else self.handle.to_dict(),
                    restoration_state='unverified', write_outcome=self.write_outcome,
                    callback_entries=self.callback_entries)


class CredentialStorePort(Protocol):
    def inspect(self) -> StoreResult: ...
    def save(self, material: SecretMaterial, *, expected: OpaqueHandle | None) -> StoreResult: ...
    def with_material(self, handle: OpaqueHandle, consumer: Callable[[bytes], object]) -> StoreResult: ...


class _StoreFault(Exception):
    def __init__(self, state: StorageState, code: str):
        self.state, self.code = state, code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class _Record:
    handle: OpaqueHandle
    material: SecretMaterial = field(repr=False)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_key')
        result[key] = value
    return result


def _decode(raw: bytes, account_id: str) -> _Record:
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        if (type(data) is not dict or set(data) != {'format', 'account_id', 'handle_id',
                'generation', 'material_b64', 'material_sha256'} or data['format'] != FORMAT):
            raise ValueError('invalid_schema')
        handle = OpaqueHandle(data['account_id'], data['handle_id'], data['generation'])
        if handle.account_id != account_id:
            raise ValueError('account_mismatch')
        if type(data['material_b64']) is not str or type(data['material_sha256']) is not str:
            raise ValueError('invalid_material_encoding')
        raw_material = base64.b64decode(data['material_b64'], validate=True)
        if hashlib.sha256(raw_material).hexdigest() != data['material_sha256']:
            raise ValueError('material_checksum_mismatch')
        return _Record(handle, SecretMaterial(raw_material))
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise _StoreFault(StorageState.CORRUPT, 'invalid_record') from None


def _encode(record: _Record) -> bytes:
    return json.dumps(dict(format=FORMAT, **record.handle.to_dict(),
                           material_b64=base64.b64encode(record.material._payload).decode('ascii'),
                           material_sha256=hashlib.sha256(record.material._payload).hexdigest()),
                      sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _check_file(fd: int):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise _StoreFault(StorageState.UNKNOWN, 'unsafe_file_boundary')
    return info


class FileCredentialStore:
    """A dedicated private directory, one account-bound file, cooperating processes.

    The directory must already exist as owned 0700. Existing unsafe permissions
    are refused, never repaired. Advisory locks protect cooperating instances;
    same-UID/root attackers and hostile filesystems are outside this boundary.
    No method is a public model tool, authentication grant, retry or login action.
    """
    def __init__(self, config: TrustedConfig):
        if type(config) is not TrustedConfig:
            raise ValueError('trusted_config_required')
        self._config = config
        name = hashlib.sha256(config.account_id.encode('ascii')).hexdigest()
        self._record_name = name + '.credential.json'
        self._lock_name = name + '.lock'

    @contextmanager
    def _directory(self):
        # Walk without following symlinks in any component, then use dirfd-relative
        # operations so later path-string replacement cannot redirect these opens.
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in self._config.directory.parts[1:]:
                newfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd); fd = newfd
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise _StoreFault(StorageState.UNKNOWN, 'unsafe_directory_boundary')
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _locked(self, dirfd: int, *, exclusive: bool):
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            fd = os.open(self._lock_name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dirfd)
            created = True
        except FileExistsError:
            fd = os.open(self._lock_name, flags, dir_fd=dirfd); created = False
        try:
            if created:
                os.fchmod(fd, 0o600)  # Only a newly created private file, never an existing one.
            _check_file(fd)
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise _StoreFault(StorageState.UNKNOWN, 'store_busy') from None
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read_locked(self, dirfd: int) -> _Record | None:
        try:
            fd = os.open(self._record_name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dirfd)
        except FileNotFoundError:
            return None
        try:
            info = _check_file(fd)
            if not 1 <= info.st_size <= MAX_RECORD_BYTES:
                raise _StoreFault(StorageState.CORRUPT, 'invalid_record_size')
            chunks = []; length = 0
            while length <= MAX_RECORD_BYTES:
                chunk = os.read(fd, min(16384, MAX_RECORD_BYTES + 1 - length))
                if not chunk:
                    break
                chunks.append(chunk); length += len(chunk)
            if length > MAX_RECORD_BYTES:
                raise _StoreFault(StorageState.CORRUPT, 'invalid_record_size')
            return _decode(b''.join(chunks), self._config.account_id)
        finally:
            os.close(fd)

    @staticmethod
    def _failure(error, *, write_outcome='not_attempted', callback_entries=0):
        if isinstance(error, _StoreFault):
            return StoreResult(error.state, error.code, write_outcome=write_outcome, callback_entries=callback_entries)
        return StoreResult(StorageState.UNKNOWN, 'store_io_unknown', write_outcome=write_outcome, callback_entries=callback_entries)

    def inspect(self) -> StoreResult:
        try:
            with self._directory() as dirfd, self._locked(dirfd, exclusive=False):
                record = self._read_locked(dirfd)
                if record is None:
                    return StoreResult(StorageState.MISSING, 'record_missing')
                return StoreResult(StorageState.PRESENT, 'record_observed', record.handle)
        except (_StoreFault, OSError) as error:
            return self._failure(error)

    def save(self, material: SecretMaterial, *, expected: OpaqueHandle | None) -> StoreResult:
        if type(material) is not SecretMaterial:
            return StoreResult(StorageState.REJECTED, 'secret_material_required')
        if expected is not None and (type(expected) is not OpaqueHandle or expected.account_id != self._config.account_id):
            return StoreResult(StorageState.REJECTED, 'account_handle_mismatch')
        temporary = None; committed_possible = False; write_started = False
        try:
            with self._directory() as dirfd, self._locked(dirfd, exclusive=True):
                current = self._read_locked(dirfd)
                if (current is None) != (expected is None) or (current is not None and current.handle != expected):
                    return StoreResult(StorageState.CONFLICT, 'generation_conflict')
                generation = 1 if current is None else current.handle.generation + 1
                if generation > MAX_GENERATION:
                    return StoreResult(StorageState.REJECTED, 'generation_exhausted')
                record = _Record(OpaqueHandle(self._config.account_id, secrets.token_hex(16), generation), material)
                raw = _encode(record)
                temporary = '.' + self._record_name + '.tmp-' + secrets.token_hex(16)
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dirfd)
                write_started = True
                try:
                    try:
                        os.fchmod(fd, 0o600); _check_file(fd)
                        view = memoryview(raw)
                        while view:
                            wrote = os.write(fd, view)
                            if wrote <= 0:
                                raise OSError('short_write')
                            view = view[wrote:]
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    committed_possible = True  # replace/fsync outcome could be uncertain.
                    os.replace(temporary, self._record_name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
                    temporary = None
                    os.fsync(dirfd)
                finally:
                    if temporary is not None:
                        try:
                            os.unlink(temporary, dir_fd=dirfd)
                        except OSError:
                            pass  # Orphan remains private; never sweep other files.
                return StoreResult(StorageState.PRESENT, 'record_saved', record.handle, write_outcome='committed')
        except (_StoreFault, OSError) as error:
            # No retry, no auto-delete of the existing record, no auto-login.
            outcome = 'unknown' if committed_possible else ('not_committed' if write_started else 'not_attempted')
            return self._failure(error, write_outcome=outcome)

    def with_material(self, handle: OpaqueHandle, consumer: Callable[[bytes], object]) -> StoreResult:
        """Trusted callback only; does not grant business authority or return its value.

        Shared lock remains held during the callback, so a cooperating rotation
        cannot replace the checked generation mid-use. Callback exceptions do not
        delete or invalidate stored credentials and must never trigger auto-replay.
        """
        if type(handle) is not OpaqueHandle or handle.account_id != self._config.account_id:
            return StoreResult(StorageState.REJECTED, 'account_handle_mismatch')
        if not callable(consumer):
            return StoreResult(StorageState.REJECTED, 'trusted_consumer_required')
        entries = 0
        try:
            with self._directory() as dirfd, self._locked(dirfd, exclusive=False):
                current = self._read_locked(dirfd)
                if current is None:
                    return StoreResult(StorageState.MISSING, 'record_missing')
                if current.handle != handle:
                    return StoreResult(StorageState.CONFLICT, 'generation_conflict')
                try:
                    entries = 1
                    consumer(current.material._payload)
                except Exception:
                    return StoreResult(StorageState.UNKNOWN, 'consumer_outcome_unknown', callback_entries=1)
                return StoreResult(StorageState.PRESENT, 'material_callback_entered', handle, callback_entries=1)
        except (_StoreFault, OSError) as error:
            return self._failure(error, callback_entries=entries)
