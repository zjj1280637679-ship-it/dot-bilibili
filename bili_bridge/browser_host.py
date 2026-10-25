"""Bounded local rendezvous with a trusted dot host; not a browser SDK.

Files are not an authentication boundary against another process of this uid.
Only the trusted host may claim and submit visible-DOM evidence.
"""
from __future__ import annotations
import contextlib
import fcntl
import os
from pathlib import Path
import stat
import time

from .browser_contracts import (MAX_BYTES, OPERATION, BINDING, HostError, fail,
    text_value, search_url, video_url, encoded, decode, timestamp, digest,
    validate_request, validate_receipt)
from .browser_registry import validate_request, validate_receipt, make_request, NAVIGATION_CONTRACTS
from . import browser_video_open_contracts as video_open
from .browser_video_contracts import OPERATION as VIDEO_OPERATION
from . import browser_public_search_contracts as public_search
from .browser_comments_contracts import OPERATION as COMMENTS_OPERATION

def owner_identity(pid):
    try:
        return Path('/proc/%d/stat' % pid).read_text().rsplit(')',1)[1].split()[19]
    except (OSError, IndexError):
        return None

class FileBrowserHost:
    def __init__(self, spool, timeout=120, cooldown=5):
        if type(timeout) not in (int,float) or not 0 < timeout <= 600 or type(cooldown) not in (int,float) or not 1 <= cooldown <= 3600:
            fail('invalid_timing')
        self.timeout, self.cooldown = timeout, cooldown
        self.root = Path(spool).absolute()
        # No symlink component, including parent paths.
        for path in (self.root, *self.root.parents):
            if path.is_symlink():
                fail('unsafe_spool')
        self.root.mkdir(mode=0o700, parents=False, exist_ok=True)
        s = self.root.stat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
            fail('unsafe_spool')
        self.dirfd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        if self.dirfd is not None:
            os.close(self.dirfd)
            self.dirfd = None

    def __del__(self):
        self.close() if hasattr(self, 'dirfd') else None

    def _read(self, name, default=None):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.dirfd)
        except FileNotFoundError:
            return default
        with os.fdopen(fd, 'rb') as f:
            s = os.fstat(f.fileno())
            if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600 or s.st_nlink != 1:
                fail('unsafe_file')
            return decode(f.read(MAX_BYTES+1))

    def _write(self, name, value):
        raw = encoded(value)
        temp = '.atomic'
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.dirfd)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            os.replace(temp, name, src_dir_fd=self.dirfd, dst_dir_fd=self.dirfd)
            os.fsync(self.dirfd)
        finally:
            self._unlink(temp)

    def _unlink(self, name):
        try:
            os.unlink(name, dir_fd=self.dirfd)
        except FileNotFoundError:
            pass

    @contextlib.contextmanager
    def _locked(self):
        fd = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.dirfd)
        try:
            s = os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600 or s.st_nlink != 1:
                fail('unsafe_file')
            deadline = time.monotonic() + 1
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        fail('host_busy')
                    time.sleep(.01)
            allowed = {'lock','state.json','request.json','receipt.json','.atomic','owner.lock'}
            if set(os.listdir(self.dirfd)) - allowed:
                fail('unexpected_spool_files')
            # Incomplete atomic write after a crash is never accepted as evidence.
            self._unlink('.atomic')
            yield
        except BlockingIOError:
            fail('host_busy')
        finally:
            os.close(fd)

    def _finish(self, state, now, status):
        state.update(active=False, finished_at=now, status=status,
                     cooldown_until=now + state['cooldown'])
        self._write('state.json', state)
        self._unlink('request.json'); self._unlink('receipt.json')

    def _live(self, state, now):
        if not state or not state.get('active'):
            fail('no_active_request')
        if now < state['issued_at']:
            fail('clock_rollback')
        if now >= state['expires_at'] or not self._owner_live():
            self._finish(state, now, 'unknown')
            fail('request_expired_or_owner_gone')

    def _owner_live(self):
        try:
            fd = os.open('owner.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.dirfd)
        except FileNotFoundError:
            return False
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid() or info.st_nlink != 1:
                fail('unsafe_file')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
        finally:
            os.close(fd)

    def claim(self):
        with self._locked():
            state = self._read('state.json')
            now = time.time()
            self._live(state, now)
            if state['claimed']:
                fail('already_claimed')
            req = validate_request(self._read('request.json'), now)
            if digest(req) != state['digest']:
                fail('request_integrity')
            state['claimed'] = True
            state['claimed_at'] = now
            self._write('state.json', state)
            return req

    def begin_navigation(self, preflight):
        """Write-ahead single-use checkpoint; caller navigates only after success.

        Trusted host must freshly inspect the actual source and context. This
        records an attestation, never independently proves browser state.
        """
        with self._locked():
            state = self._read('state.json')
            now = time.time()
            self._live(state, now)
            req = validate_request(self._read('request.json'), now)
            if (req['operation'] not in NAVIGATION_CONTRACTS or not state['claimed']
                    or state.get('submitted') or state.get('navigation_started_at') is not None):
                fail('navigation_not_expected')
            if digest(req) != state['digest']:
                fail('request_integrity')
            checked = NAVIGATION_CONTRACTS[req['operation']].validate_preflight(preflight, req, now)
            if checked['checked_at'] < state['claimed_at']:
                fail('preflight_predates_claim')
            state.update(navigation_started_at=now, preflight=checked)
            self._write('state.json', state)
            return dict(destination_url=req['destination_url'], tab_id=req['source_tab_id'])

    def submit(self, receipt):
        with self._locked():
            state = self._read('state.json')
            now = time.time()
            self._live(state, now)
            if not state['claimed'] or state.get('submitted'):
                fail('receipt_not_expected')
            req = validate_request(self._read('request.json'), now)
            result = validate_receipt(receipt, req, now)
            if req['operation'] in NAVIGATION_CONTRACTS:
                started = state.get('navigation_started_at')
                if result['phase'] == 'capture':
                    if started is None or result['captured_at'] < started:
                        fail('capture_before_navigation')
                elif started is not None:
                    fail('preflight_after_navigation')
            if result['captured_at'] < state['claimed_at']:
                fail('receipt_predates_claim')
            if digest(req) != state['digest']:
                fail('request_integrity')
            self._write('receipt.json', result)
            state['submitted'] = True
            self._write('state.json', state)

    def open_video(self, operation_id, correlation_id, bvid, selection):
        return self.read(operation_id, correlation_id, bvid,
            video_open.video_url('https://www.bilibili.com/video/'+bvid+'/', bvid),
            selection['source_tab_id'], operation=video_open.OPERATION, selection=selection)

    def public_search(self, operation_id, correlation_id, query, source_url, source_tab_id):
        return self.read(operation_id, correlation_id, query, source_url, source_tab_id, operation=public_search.OPERATION)

    def read_video(self, operation_id, correlation_id, bvid, expected_url, expected_tab_id):
        return self.read(operation_id, correlation_id, bvid, expected_url, expected_tab_id, operation=VIDEO_OPERATION)

    def read_comments(self, operation_id, correlation_id, bvid, expected_url, expected_tab_id, limit):
        return self.read(operation_id, correlation_id, bvid, expected_url, expected_tab_id, operation=COMMENTS_OPERATION, limit=limit)

    def read(self, operation_id, correlation_id, query, expected_url, expected_tab_id, *, operation=OPERATION, limit=None, selection=None):
        fd = os.open('owner.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.dirfd)
        acquired = False
        active_digest = None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid() or info.st_nlink != 1:
                fail('unsafe_file')
            with self._locked():
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    fail('host_busy')
                acquired = True
                self._active_digest = None
                prior = self._read('state.json', {})
                if prior.get('active'):
                    # Acquiring this lock proves the previous reader released it.
                    # Retire the orphan atomically before any host can claim it.
                    self._finish(prior, time.time(), 'unknown')
                    fail('orphaned_request_unknown')
            try:
                return self._read_exchange(operation_id, correlation_id, query, expected_url, expected_tab_id, operation=operation, limit=limit, selection=selection)
            except Exception:
                if self._active_digest is not None:
                    # Once emitted, the host may already have read the DOM.
                    # Never turn an uncertain execution into a replayable block.
                    raise HostError('host_outcome_unknown') from None
                raise
        finally:
            if acquired:
                active_digest = self._active_digest
                if active_digest:
                    try:
                        with self._locked():
                            state = self._read('state.json')
                            if state and state.get('active') and state.get('digest') == active_digest:
                                self._finish(state, time.time(), 'unknown')
                    except (OSError, HostError):
                        # Owner lock release makes claim/submit fail closed even if
                        # terminal state cannot be persisted by this process.
                        pass
            os.close(fd)

    def _read_exchange(self, operation_id, correlation_id, query, expected_url, expected_tab_id, *, operation=OPERATION, limit=None, selection=None):
        now = time.time()
        req = make_request(operation, operation_id, correlation_id, query,
                           expected_url, expected_tab_id, now, self.timeout, limit=limit, selection=selection)
        with self._locked():
            state = self._read('state.json', {})
            if state.get('active'):
                self._live(state, now)
                fail('host_busy')
            if now < state.get('cooldown_until', 0):
                fail('host_cooldown')
            if state.get('operation_id') == operation_id:
                fail('operation_reuse')
            if operation == video_open.OPERATION:
                if (state.get('operation_id') != req['source_operation_id']
                    or state.get('digest') != req['source_scope_digest']
                    or state.get('status') != 'observed'):
                    fail('selection_generation_changed')
            state = dict(active=True, claimed=False, submitted=False, pid=os.getpid(), owner=owner_identity(os.getpid()),
                         issued_at=now, expires_at=req['expires_at'], digest=req['scope_digest'], operation_id=operation_id, cooldown=self.cooldown)
            self._unlink('receipt.json')
            self._active_digest = req['scope_digest']
            self._write('state.json', state)
            self._write('request.json', req)
        deadline = time.monotonic() + self.timeout
        while True:
            with self._locked():
                state = self._read('state.json')
                now = time.time()
                if not state or state.get('digest') != req['scope_digest'] or not state.get('active'):
                    fail('host_outcome_unknown')
                if now < req['issued_at'] or now >= req['expires_at'] or time.monotonic() >= deadline:
                    self._finish(state, now, 'unknown')
                    fail('host_outcome_unknown')
                receipt = self._read('receipt.json')
                if receipt is not None and state['submitted']:
                    result = validate_receipt(receipt, req, now)
                    self._finish(state, now, result['status'])
                    return result
            time.sleep(min(.1, max(0, deadline-time.monotonic())))
