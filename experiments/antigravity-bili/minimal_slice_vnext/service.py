"""Small fixture-only service. No imports from the unreviewed AG product draft."""
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

BVID = re.compile(r'BV[0-9A-Za-z]{10}')
ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
TOOLS = ('capabilities.list', 'video.reference.resolve', 'video.metadata.read', 'operation.status')


def envelope(status, *, data=None, error=None):
    return {'status': status, 'backend': 'fixture', 'live': False, 'data': data, 'error': error}


def resolve_bvid(value):
    """Syntax-only validation, derived from public browser_video_contracts.video_url.
    Existence is NOT verified. No redirects, tracking queries, or shortlinks.
    """
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('invalid_reference')
    if BVID.fullmatch(value):
        return value
    p = urlsplit(value)
    if p.scheme != 'https' or p.netloc != 'www.bilibili.com' or p.query or p.fragment:
        raise ValueError('invalid_reference')
    match = re.fullmatch(r'/video/(BV[0-9A-Za-z]{10})/?', p.path)
    if not match or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError('invalid_reference')
    return match[1]


def fixture_metadata(bvid):
    if bvid != 'BV17x411w7KC':
        return {'status': 'not_found'}
    return {'status': 'completed', 'data': {'bvid': bvid, 'title': 'Synthetic fixture video'}}


class Service:
    """Single fixture namespace, durable local ledger and pause; zero real auth.
    Only trusted local construction can inject a backend or initialize unpaused.
    No MCP method changes pause or authenticates anything.
    """
    def __init__(self, db, *, backend=fixture_metadata, initial_paused=True):
        if type(initial_paused) is not bool or str(db) == ':memory:':
            raise ValueError('requires_file_db_and_boolean_pause')
        self.db = str(Path(db).resolve())
        self.backend = backend
        self.run_id = secrets.token_hex(16)
        self.refs = {}
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS controls (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL)')
            c.execute('INSERT OR IGNORE INTO controls VALUES(1,?)', (int(initial_paused),))
            c.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, owner TEXT NOT NULL, result TEXT)')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=5)
        try:
            with c:
                yield c
        finally:
            c.close()

    def set_pause(self, paused):
        """Trusted operator/test API; intentionally absent from MCP tools."""
        if type(paused) is not bool:
            raise ValueError('invalid_pause')
        with self.connect() as c:
            c.execute('UPDATE controls SET paused=? WHERE id=1', (int(paused),))

    def paused(self):
        with self.connect() as c:
            return c.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0] != 0

    def capabilities(self):
        return envelope('completed', data={'tools': list(TOOLS), 'paused': self.paused(),
            'authentication': 'not_implemented', 'network': 'not_implemented',
            'unwired': ['search.query.submit', 'search.results.visible.read', 'video.search_result.open',
                        'video.metadata.visible.read', 'comments.viewport.read', 'account', 'writes']})

    def resolve(self, value):
        bvid = resolve_bvid(value)
        ref = secrets.token_hex(16)
        self.refs[ref] = bvid
        return envelope('completed', data={'reference_id': ref, 'bvid': bvid,
            'url': 'https://www.bilibili.com/video/' + bvid + '/',
            'existence': 'not_checked', 'freshness_scope': 'this_service_process'})

    def status(self, operation_id):
        if not isinstance(operation_id, str) or not ID.fullmatch(operation_id):
            return envelope('rejected', error='invalid_operation_id')
        with self.connect() as c:
            row = c.execute('SELECT owner,result FROM operations WHERE id=?', (operation_id,)).fetchone()
        if row is None:
            return envelope('not_found', error='operation_not_found')
        if row[1] is None:
            return envelope('pending' if row[0] == self.run_id else 'unknown',
                            error='operation_in_progress' if row[0] == self.run_id else 'previous_run_incomplete')
        return json.loads(row[1])

    def metadata(self, *, reference_id, expected_bvid, operation_id, backend):
        if backend != 'fixture':
            return envelope('unsupported', error='backend_unwired')
        if not isinstance(operation_id, str) or not ID.fullmatch(operation_id):
            return envelope('rejected', error='invalid_operation_id')
        if not isinstance(reference_id, str) or self.refs.get(reference_id) != expected_bvid or expected_bvid is None:
            return envelope('blocked', error='stale_or_wrong_target_reference')
        # Fingerprint semantic action, not process-local reference, so restart retries cannot redeliver.
        fingerprint = hashlib.sha256(json.dumps(['fixture', 'video.metadata.read', expected_bvid]).encode()).hexdigest()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT fingerprint FROM operations WHERE id=?', (operation_id,)).fetchone()
            if old:
                if old[0] != fingerprint:
                    return envelope('rejected', error='operation_id_conflict')
                return self.status(operation_id)
            if c.execute('SELECT paused FROM controls WHERE id=1').fetchone()[0]:
                return envelope('blocked', error='account_operations_paused')
            c.execute('INSERT INTO operations VALUES(?,?,?,NULL)', (operation_id, fingerprint, self.run_id))
        # The reservation is durable before the callback; crash/incomplete never automatically replays.
        try:
            result = self._classify(self.backend(expected_bvid), expected_bvid)
        except Exception:
            result = envelope('unknown', error='backend_outcome_unknown')
        with self.connect() as c:
            c.execute('UPDATE operations SET result=? WHERE id=? AND owner=? AND result IS NULL',
                      (json.dumps(result, allow_nan=False), operation_id, self.run_id))
        return result

    @staticmethod
    def _classify(raw, bvid):
        # Closed schema: transport success, arbitrary dicts, and exception messages are not business evidence.
        if not isinstance(raw, dict) or raw.get('status') not in {'completed','blocked','pending','unsupported','unknown','rejected','not_found'}:
            return envelope('unknown', error='malformed_backend_result')
        if raw['status'] != 'completed':
            return envelope(raw['status'], error='backend_' + raw['status'])
        data = raw.get('data')
        if set(raw) != {'status','data'} or not isinstance(data, dict) or set(data) != {'bvid','title'}:
            return envelope('unknown', error='malformed_backend_result')
        if data['bvid'] != bvid or not isinstance(data['title'], str) or len(data['title']) > 500:
            return envelope('unknown', error='malformed_backend_result')
        return envelope('completed', data=dict(data))

    def call(self, name, args):
        if not isinstance(args, dict):
            return envelope('rejected', error='invalid_arguments')
        expected = {'capabilities.list': set(), 'video.reference.resolve': {'value'},
            'video.metadata.read': {'reference_id','expected_bvid','operation_id','backend'},
            'operation.status': {'operation_id'}}
        if name not in expected:
            return envelope('unsupported', error='tool_unwired')
        if set(args) != expected[name]:
            return envelope('rejected', error='invalid_arguments')
        try:
            if name == 'capabilities.list': return self.capabilities()
            if name == 'video.reference.resolve': return self.resolve(args['value'])
            if name == 'operation.status': return self.status(args['operation_id'])
            return self.metadata(**args)
        except (ValueError, TypeError):
            return envelope('rejected', error='invalid_arguments')
        except Exception:
            return envelope('unknown', error='local_service_error')
