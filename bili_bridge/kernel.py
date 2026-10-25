"""Durable conservative dispatcher for trusted first-party adapters.

SQLite FULL synchronous transactions are the durability boundary. All callers must
share this database and obey the broker. Wall-clock rollback blocks new sends;
large forward clock changes are outside the rate guarantee. Recovery is
limited to closed handles or abandoned per-handle flock leases on the shared
filesystem. PID values are diagnostic only, never liveness evidence. Shared
advisory-lock coherence is required; missing/invalid leases preserve pending state. Uncertainty never unlocks a write. There is no exactly-once remote guarantee or automatic replay.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import secrets
import sqlite3
import stat
import tempfile
from pathlib import Path
import threading
import time

from .contracts import Plugin, Request, Result
from .relays import RelayEnvelope, RelayStation, GrantRelay, BudgetRelay, _ACTIVE_ENVELOPE

_STATUSES = frozenset({'applied', 'rejected', 'unknown', 'blocked', 'deferred', 'unsupported'})
_SECRET_KEYS = frozenset({'password', 'passwd', 'secret', 'token', 'access_token',
                          'refresh_token', 'cookie', 'cookies', 'authorization',
                          'credential', 'credentials', 'session', 'sessdata'})


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def _safe_json(value, depth=0):
    if depth > 32:
        raise ValueError('invalid JSON')
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _safe_json(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or key.lower() in _SECRET_KEYS:
                raise ValueError('invalid JSON')
            _safe_json(item, depth + 1)
        return
    raise ValueError('invalid JSON')


def _snapshot(request):
    if not isinstance(request, Request):
        raise ValueError('invalid request')
    for value in (request.operation_id, request.account, request.capability, request.target):
        if type(value) is not str or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
            raise ValueError('invalid request')
        value.encode('utf-8')
    if type(request.payload) is not dict:
        raise ValueError('invalid request')
    _safe_json(request.payload)
    identity = _json([request.account, request.capability, request.target, request.payload])
    if len(identity.encode('utf-8')) > 65536:
        raise ValueError('invalid request')
    digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    return Request(request.operation_id, request.account, request.capability,
                   request.target, json.loads(_json(request.payload))), digest


class Kernel:
    MAX_RECORDS = 100000

    def __init__(self, db_path, *, min_interval=3.0, hourly_budget=20, clock=time.time):
        if (type(min_interval) not in (int, float) or not math.isfinite(min_interval)
                or min_interval < 0 or type(hourly_budget) is not int or hourly_budget < 1):
            raise ValueError('invalid budget policy')
        self.clock = clock
        self._mutex = threading.RLock()
        self._lifecycle = threading.RLock()
        self._active = False
        self._closed = False
        self._plugins = {}
        self._names = set()
        self._owner = secrets.token_hex(16)
        self._discard_lease = True
        self._lease_fd = None
        self._lease_dirfd = None
        self._lease_temp = None
        self._open_lease(db_path)
        try:
            self._db = sqlite3.connect(db_path, timeout=30, isolation_level=None, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute('PRAGMA journal_mode=WAL')
            self._db.execute('PRAGMA synchronous=FULL')
            version = self._db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 2, 3):
                self._db.close()
                self._release_lease()
                raise ValueError('unsupported journal schema')
            self._db.executescript('''
              CREATE TABLE IF NOT EXISTS owners(owner TEXT PRIMARY KEY, pid INTEGER NOT NULL, closed INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), interval REAL NOT NULL,
                budget INTEGER NOT NULL, high_water REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS operations(operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                account TEXT NOT NULL, capability TEXT NOT NULL, target TEXT NOT NULL,
                mutating INTEGER NOT NULL, state TEXT NOT NULL, result TEXT, created REAL NOT NULL, owner TEXT NOT NULL, relay_trace TEXT NOT NULL DEFAULT '[]');
              CREATE TABLE IF NOT EXISTS grants(token_hash TEXT PRIMARY KEY, operation_id TEXT NOT NULL,
                digest TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS browser_selections(
                source_operation_id TEXT PRIMARY KEY, open_operation_id TEXT NOT NULL UNIQUE);
              CREATE TABLE IF NOT EXISTS reservations(operation_id TEXT PRIMARY KEY, started REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS reservation_time ON reservations(started);
            ''')
            with self._transaction():
                self._db.execute('PRAGMA user_version=3')
                retired = self._db.execute("SELECT owner FROM owners WHERE closed=1 AND owner NOT IN (SELECT owner FROM operations WHERE state IN ('prepared','inflight'))").fetchall()
                for row in retired:
                    try:
                        os.unlink(row['owner'] + '.lock', dir_fd=self._lease_dirfd)
                    except FileNotFoundError:
                        pass
                self._db.execute("DELETE FROM owners WHERE closed=1 AND owner NOT IN (SELECT owner FROM operations WHERE state IN ('prepared','inflight'))")
                if self._db.execute('SELECT COUNT(*) FROM owners').fetchone()[0] >= self.MAX_RECORDS:
                    raise RuntimeError('journal_capacity')
                self._db.execute('INSERT INTO owners VALUES(?,?,0)', (self._owner, os.getpid()))
                self._db.execute('INSERT OR IGNORE INTO policy VALUES(1,?,?,?)',
                                 (min_interval, hourly_budget, self._now()))
                # Persisted policy is authoritative: reopening never resets/widens it.
                policy = self._db.execute('SELECT * FROM policy WHERE id=1').fetchone()
                self.min_interval = policy['interval']
                self.hourly_budget = policy['budget']
            self.recover()
            self._discard_lease = False
        except BaseException:
            if hasattr(self, '_db'):
                self._db.close()
            self._release_lease()
            raise

    def _open_lease(self, db_path):
        # The private directory is adjacent to the canonical database pathname,
        # so handles in distinct PID namespaces still refer to the same inode.
        if os.fspath(db_path) == ':memory:':
            self._lease_temp = tempfile.TemporaryDirectory(prefix='bili-kernel-')
            root = Path(self._lease_temp.name)
        else:
            root = Path(str(Path(db_path).resolve()) + '.leases')
            root.mkdir(mode=0o700, exist_ok=True)
        try:
            self._lease_dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(self._lease_dirfd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('unsafe_lease_directory')
            self._lease_fd = os.open(self._owner + '.lock',
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                dir_fd=self._lease_dirfd)
            fcntl.flock(self._lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fsync(self._lease_fd)
            os.fsync(self._lease_dirfd)
        except BaseException:
            self._release_lease()
            raise

    def _release_lease(self):
        if self._lease_fd is not None:
            os.close(self._lease_fd)
            self._lease_fd = None
        if self._lease_dirfd is not None:
            if self._discard_lease or self._closed:
                try:
                    os.unlink(self._owner + '.lock', dir_fd=self._lease_dirfd)
                except FileNotFoundError:
                    pass
            os.close(self._lease_dirfd)
            self._lease_dirfd = None
        if self._lease_temp is not None:
            self._lease_temp.cleanup()
            self._lease_temp = None

    @contextmanager
    def _abandoned_lease(self, owner):
        # Never create a missing lease when probing: a missing file cannot prove
        # absence of an older owner, especially during schema-2 migration.
        fd = None
        abandoned = False
        try:
            if (type(owner) is str and len(owner) == 32
                    and all(c in '0123456789abcdef' for c in owner)):
                fd = os.open(owner + '.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=self._lease_dirfd)
                info = os.fstat(fd)
                if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                        and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    abandoned = True
        except OSError:
            pass  # Held, absent, or uncertain all preserve pending state.
        try:
            yield abandoned
        finally:
            if fd is not None:
                os.close(fd)

    def _now(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError('invalid clock')
        return float(now)

    @contextmanager
    def _transaction(self):
        with self._mutex:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self._db.execute('COMMIT')
            except BaseException:
                self._db.execute('ROLLBACK')
                raise

    def register(self, plugin: Plugin):
        with self._mutex:
            if (not isinstance(plugin.name, str) or not plugin.name
                    or type(plugin.capabilities) is not frozenset or not plugin.capabilities
                    or type(plugin.mutating) is not frozenset
                    or not plugin.mutating <= plugin.capabilities
                    or not all(type(c) is str and c for c in plugin.capabilities)
                    or not callable(getattr(plugin, 'execute', None))):
                raise ValueError('invalid plugin declaration')
            if plugin.name in self._names or any(c in self._plugins for c in plugin.capabilities):
                raise ValueError('duplicate plugin or capability owner')
            self._names.add(plugin.name)
            for capability in plugin.capabilities:
                # Freeze declarations; a mutable plugin cannot widen authority later.
                self._plugins[capability] = (plugin, capability in plugin.mutating)

    def issue_grant(self, request, ttl=60):
        """Trusted OFFLINE TEST issuer. Never expose this method in an agent API."""
        request, digest = _snapshot(request)
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 < ttl <= 3600:
            raise ValueError('invalid grant lifetime')
        token = secrets.token_urlsafe(32)
        with self._transaction():
            now = self._now()
            if self._db.execute('SELECT COUNT(*) FROM grants').fetchone()[0] >= self.MAX_RECORDS:
                raise RuntimeError('journal_capacity')
            self._db.execute('INSERT INTO grants VALUES(?,?,?,?,0)',
                             (self._token_hash(token), request.operation_id, digest, now + ttl))
        return token

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode('utf-8', errors='surrogatepass')).hexdigest()

    def _save(self, operation_id, result):
        self._db.execute('UPDATE operations SET state=?, result=? WHERE operation_id=?',
                         (result.status, _json({'status': result.status, 'data': result.data,
                                               'error': result.error}), operation_id))
        return result

    def dispatch(self, request, grant_token=None):
        with self._lifecycle:
            if self._closed:
                return Result('blocked', {}, 'kernel_closed')
            if self._active:
                return Result('blocked', {}, 'nested_dispatch_forbidden')
            self._active = True
            try:
                return self._dispatch(request, grant_token)
            finally:
                self._active = False

    def _dispatch(self, request, grant_token=None):
        try:
            request, digest = _snapshot(request)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return Result('rejected', {}, 'invalid_request')
        with self._transaction():
            previous = self._db.execute('SELECT * FROM operations WHERE operation_id=?',
                                        (request.operation_id,)).fetchone()
            if previous:
                if previous['digest'] != digest:
                    return Result('rejected', {}, 'operation_identity_conflict')
                if previous['result']:
                    return Result(**json.loads(previous['result']))
                return Result('unknown', {}, 'operation_unresolved')
            if self._db.execute('SELECT COUNT(*) FROM operations').fetchone()[0] >= self.MAX_RECORDS:
                return Result('blocked', {}, 'journal_capacity')
            now = self._now()
            provider = self._plugins.get(request.capability)
            mutating = bool(provider and provider[1])
            self._db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,NULL,?,?,?)',
                             (request.operation_id, digest, request.account, request.capability,
                              request.target, mutating, 'prepared', now, self._owner, '[]'))
            envelope = RelayStation('kernel.schema', None).forward(
                RelayEnvelope.from_request(request, mutating), request)
            def deny(status, code):
                return self._save(request.operation_id, Result(status, {}, code))
            if not provider:
                return deny('unsupported', 'capability_unavailable')
            if mutating:
                conflict = self._db.execute('''SELECT 1 FROM operations WHERE account=? AND target=?
                    AND mutating=1 AND state IN ('prepared','inflight','unknown') AND operation_id<>?''',
                    (request.account, request.target, request.operation_id)).fetchone()
                if conflict:
                    return deny('blocked', 'resource_unresolved')
                if type(grant_token) is not str or len(grant_token) > 512:
                    return deny('blocked', 'grant_required')
                grant = self._db.execute('SELECT * FROM grants WHERE token_hash=?',
                                        (self._token_hash(grant_token),)).fetchone()
                if GrantRelay.rejection(grant, envelope, now):
                    return deny('blocked', 'grant_invalid')
            envelope = RelayStation('kernel.grant', 'kernel.schema').forward(envelope, request)
            policy = self._db.execute('SELECT * FROM policy WHERE id=1').fetchone()
            count = self._db.execute('SELECT COUNT(*) FROM reservations WHERE started>?',
                                     (now - 3600,)).fetchone()[0]
            last_start = self._db.execute('SELECT MAX(started) FROM reservations').fetchone()[0]
            rejection = BudgetRelay.rejection(now=now, high_water=policy['high_water'], count=count,
                last_start=last_start, budget=policy['budget'], interval=policy['interval'])
            if rejection:
                return deny('deferred', rejection)
            self._db.execute('UPDATE policy SET high_water=? WHERE id=1', (now,))
            envelope = RelayStation('kernel.budget', 'kernel.grant').forward(envelope, request)
            # Recheck immediately before the durable send reservation.
            send_time = self._now()
            if send_time < now:
                return deny('deferred', 'clock_rollback')
            if mutating and grant['expires'] <= send_time:
                return deny('blocked', 'grant_expired')
            if mutating:
                self._db.execute('UPDATE grants SET used=1 WHERE token_hash=?',
                                 (self._token_hash(grant_token),))
            self._db.execute('INSERT INTO reservations VALUES(?,?)', (request.operation_id, send_time))
            self._db.execute('UPDATE policy SET high_water=? WHERE id=1', (send_time,))
            self._db.execute("UPDATE operations SET state='inflight' WHERE operation_id=?", (request.operation_id,))
            envelope = RelayStation('kernel.journal', 'kernel.budget').forward(envelope, request)
            self._db.execute('UPDATE operations SET relay_trace=? WHERE operation_id=?',
                             (_json(envelope.path), request.operation_id))
        envelope = RelayStation('kernel.execute', 'kernel.journal').forward(envelope, request)
        # No database transaction is held over potentially slow I/O. Intent and
        # reservation have committed before calling a trusted adapter.
        relay_token = _ACTIVE_ENVELOPE.set(envelope)
        try:
            final_time = self._now()
            if final_time < send_time:
                result = Result('deferred', {}, 'clock_rollback')
            elif mutating and grant['expires'] <= final_time:
                result = Result('blocked', {}, 'grant_expired')
            else:
                result = provider[0].execute(request)
            if not isinstance(result, Result) or result.status not in _STATUSES or type(result.data) is not dict:
                raise ValueError('invalid adapter result')
            _safe_json(result.data)
            if result.error is not None and (type(result.error) is not str
                    or len(result.error) > 128 or not all(c.islower() or c.isdigit() or c == '_' for c in result.error)):
                raise ValueError('invalid adapter error')
            if len(_json(result.data).encode('utf-8')) > 1048576:
                raise ValueError('oversize adapter result')
            result = Result(result.status, json.loads(_json(result.data)), result.error)
        except Exception:
            result = Result('unknown', {}, 'adapter_outcome_unknown')
        finally:
            _ACTIVE_ENVELOPE.reset(relay_token)
        with self._transaction():
            # Another handle may have recovered this in-flight operation. Do not
            # replace conservative uncertainty with an uncoordinated late reply.
            state = self._db.execute('SELECT state FROM operations WHERE operation_id=?',
                                     (request.operation_id,)).fetchone()['state']
            if state != 'inflight':
                return Result(**json.loads(self._db.execute('SELECT result FROM operations WHERE operation_id=?',
                                                            (request.operation_id,)).fetchone()['result']))
            self._db.execute('UPDATE operations SET relay_trace=? WHERE operation_id=?',
                             (_json(envelope.path), request.operation_id))
            return self._save(request.operation_id, result)

    def recover(self):
        recovered = 0
        with self._transaction():
            rows = self._db.execute("""SELECT operations.operation_id, owners.owner, owners.closed
                FROM operations JOIN owners ON operations.owner=owners.owner
                WHERE state IN ('prepared','inflight')""").fetchall()
            for row in rows:
                with self._abandoned_lease(row['owner']) as abandoned:
                    if row['closed'] or abandoned:
                        self._save(row['operation_id'], Result('unknown', {}, 'recovered_uncertain'))
                        self._db.execute('UPDATE owners SET closed=1 WHERE owner=?', (row['owner'],))
                        recovered += 1
        return recovered

    def consume_browser_selection(self, request):
        """Atomically consume a journal-proven snapshot; never accept supplied evidence.

        Trusted adapter only. Consumption is conservative even if later preflight
        blocks: obtain a new search snapshot, never replay an uncertain open.
        """
        from .browser_contracts import BINDING, fail, text_value, timestamp
        from .browser_public_search_contracts import source_url
        from .browser_video_open_contracts import OPERATION, MAX_SNAPSHOT_AGE
        text_value(request.payload['source_operation_id'], 200)
        with self._transaction():
            current = self._db.execute('SELECT * FROM operations WHERE operation_id=?',
                                      (request.operation_id,)).fetchone()
            if (current is None or current['state'] != 'inflight' or current['capability'] != OPERATION
                or current['account'] != BINDING or current['target'] != request.target
                or current['digest'] != _snapshot(request)[1]):
                fail('selection_requires_dispatch')
            row = self._db.execute('SELECT * FROM operations WHERE operation_id=?',
                                  (request.payload['source_operation_id'],)).fetchone()
            if (row is None or row['state'] != 'applied' or row['account'] != BINDING
                or row['capability'] not in ('browser.public_search','browser.search_results.read')):
                fail('selection_source_not_applied')
            try:
                result = json.loads(row['result'])
                data = result['data']
                if not isinstance(data, dict) or not {'source','status','captured_at','items','scope_digest','query','observed_url','tab_id'} <= set(data):
                    fail('selection_source_invalid')
                if not isinstance(data['items'], list) or not all(isinstance(item,dict) and {'bvid','url'} <= set(item) for item in data['items']):
                    fail('selection_source_invalid')
                for key in ('scope_digest','query','observed_url','tab_id'):
                    text_value(data[key],2048 if key=='observed_url' else 200)
                timestamp(data['captured_at'])
            except (KeyError, TypeError, ValueError):
                fail('selection_source_invalid')
            if result['status'] != 'applied' or data.get('source') != 'browser_dom' or data.get('status') != 'observed':
                fail('selection_source_not_applied')
            now = self._now()
            captured = timestamp(data['captured_at'])
            if not captured <= now < captured + MAX_SNAPSHOT_AGE:
                fail('selection_stale')
            items = [item for item in data['items'] if item['bvid'] == request.target]
            if len(items) != 1:
                fail('selection_not_in_snapshot')
            from .browser_video_contracts import video_url
            video_url(items[0]['url'], request.target)
            if self._db.execute('SELECT 1 FROM browser_selections WHERE source_operation_id=?',
                                (row['operation_id'],)).fetchone():
                fail('selection_already_consumed')
            self._db.execute('INSERT INTO browser_selections VALUES(?,?)',
                             (row['operation_id'],request.operation_id))
            return dict(source_operation_id=row['operation_id'],source_scope_digest=data['scope_digest'],
                source_captured_at=captured,query=data['query'],source_url=source_url(data['observed_url']),
                source_tab_id=data['tab_id'])

    def status(self, operation_id):
        with self._mutex:
            row = self._db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result['relay_trace'] = json.loads(result['relay_trace'])
            result['result'] = json.loads(result['result']) if result['result'] else None
            return result

    def close(self):
        # Other threads wait for active dispatch; a plugin attempting to close
        # its own host is rejected rather than deadlocking or closing live I/O.
        with self._lifecycle:
            if self._closed:
                return
            if self._active:
                raise RuntimeError('dispatch_active')
            with self._transaction():
                self._db.execute('UPDATE owners SET closed=1 WHERE owner=?', (self._owner,))
            with self._mutex:
                self._db.close()
                self._closed = True
                self._release_lease()
