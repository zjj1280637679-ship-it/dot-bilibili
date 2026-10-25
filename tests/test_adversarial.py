"""Independent offline regressions: real kernel paths, no network or account actions."""
import io
from dataclasses import replace
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from bili_bridge.contracts import Request, Result
from bili_bridge.kernel import Kernel
from bili_bridge.plugins import PublicVideoPlugin, anonymous_html_transport, TransportBlocked
from bili_bridge.cli import serve
from bili_bridge.relays import RelayEnvelope, RelayStation


class Probe:
    name = 'probe'
    capabilities = frozenset({'probe.write'})
    mutating = capabilities
    def __init__(self):
        self.calls = []
    def execute(self, request):
        self.calls.append(request)
        return Result('applied', {'ok': True})


class AdversarialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'journal.sqlite3'
        self.kernel = Kernel(self.db, min_interval=0, hourly_budget=100)
        self.probe = Probe()
        self.kernel.register(self.probe)
    def tearDown(self):
        self.kernel.close()
        self.tmp.cleanup()
    def request(self, operation='op', **changes):
        value = dict(operation_id=operation, account='alice', capability='probe.write', target='resource', payload={'text': 'approved'})
        value.update(changes)
        return Request(**value)
    def test_grant_payload_mutation_fails_closed(self):
        request = self.request()
        grant = self.kernel.issue_grant(request)
        request.payload['text'] = 'not approved'
        self.assertEqual(self.kernel.dispatch(request, grant).status, 'blocked')
        self.assertEqual(self.probe.calls, [])
    def test_grant_cannot_cross_account_or_operation(self):
        request = self.request()
        grant = self.kernel.issue_grant(request)
        for other in (self.request('other'), self.request('third', account='bob')):
            self.assertEqual(self.kernel.dispatch(other, grant).status, 'blocked')
        self.assertEqual(self.probe.calls, [])
    def test_shared_database_duplicate_concurrent_send(self):
        other = Kernel(self.db)
        second = Probe()
        other.register(second)
        request = self.request()
        grant = self.kernel.issue_grant(request)
        barrier = threading.Barrier(2)
        results = []
        def send(kernel):
            barrier.wait()
            results.append(kernel.dispatch(request, grant))
        threads = [threading.Thread(target=send, args=(kernel,)) for kernel in (self.kernel, other)]
        try:
            for thread in threads: thread.start()
            for thread in threads: thread.join(5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(len(results), 2)
            self.assertEqual(len(self.probe.calls) + len(second.calls), 1)
        finally:
            other.close()
    def test_secret_named_payload_not_persisted(self):
        request = self.request(payload={'nested': [{'SESSDATA': 'secret-marker'}]})
        self.assertEqual(self.kernel.dispatch(request).status, 'rejected')
        self.assertIsNone(self.kernel.status(request.operation_id))
    def test_uncertain_write_blocks_other_plugin_same_resource(self):
        def fail(request):
            raise RuntimeError('secret-marker')
        self.probe.execute = fail
        request = self.request()
        result = self.kernel.dispatch(request, self.kernel.issue_grant(request))
        self.assertEqual(result.status, 'unknown')
        self.assertNotIn('secret-marker', repr(result))
        second = Probe()
        second.name = 'second'
        second.capabilities = second.mutating = frozenset({'second.write'})
        self.kernel.register(second)
        request = self.request('second', capability='second.write')
        self.assertEqual(self.kernel.dispatch(request, self.kernel.issue_grant(request)).error, 'resource_unresolved')
        self.assertEqual(second.calls, [])
    def test_transport_rejects_ssrf_before_open(self):
        with patch('urllib.request.build_opener') as opener:
            for url in ('http://127.0.0.1/', 'https://www.bilibili.com@localhost/video/BV1xx411c7mD/', 'https://www.bilibili.com/video/../../secret/', 'https://www.bilibili.com/video/BV1xx411c7mD/?redirect=localhost'):
                with self.assertRaises(TransportBlocked): anonymous_html_transport(url)
            opener.assert_not_called()
    def test_adapter_exception_has_no_details(self):
        def fail(url): raise RuntimeError('SESSDATA=secret-marker')
        plugin = PublicVideoPlugin(fail)
        request = self.request(account='anonymous', capability='video.metadata', target='BV1xx411c7mD', payload={})
        result = plugin.execute(request)
        self.assertEqual(result.status, 'blocked')
        self.assertNotIn('secret-marker', repr(result))
    def test_jsonl_surrogate_identifier_fails_closed(self):
        stream = io.StringIO()
        request = {'operation_id': chr(0xD800), 'capability': 'video.metadata', 'target': 'BV1xx411c7mD'}
        serve(self.kernel, stdin=io.StringIO(json.dumps(request)+'\n'), stdout=stream)
        self.assertEqual(json.loads(stream.getvalue())['status'], 'rejected')
        self.assertEqual(self.probe.calls, [])
    def test_malformed_grant_token_fails_closed(self):
        result = self.kernel.dispatch(self.request(), chr(0xD800))
        self.assertEqual(result.status, 'blocked')
        self.assertEqual(self.probe.calls, [])
    def test_relay_rejects_skipped_route_and_scope_escalation(self):
        request = self.request()
        envelope = RelayEnvelope.from_request(request)
        with self.assertRaises(ValueError):
            RelayStation('kernel.execute', 'kernel.journal').forward(replace(envelope, path=('kernel.journal',)), request)
        with self.assertRaises(ValueError):
            RelayStation('kernel.schema', None).forward(replace(envelope, effect='write'), request)
        with self.assertRaises(ValueError):
            RelayStation('kernel.schema', None).forward(replace(envelope, schema_version=2), request)
        with self.assertRaises(ValueError):
            RelayStation('kernel.schema', None).forward(envelope, self.request(account='bob'))
    def test_journal_capacity_preserves_existing_identity(self):
        with patch.object(Kernel, 'MAX_RECORDS', 1):
            first = self.kernel.dispatch(self.request())
            self.assertEqual(first.status, 'blocked')
            second = self.kernel.dispatch(self.request('other'))
            self.assertEqual(second.error, 'journal_capacity')
            self.assertEqual(self.kernel.dispatch(self.request()), first)
            self.assertIsNone(self.kernel.status('other'))
    def test_close_waits_for_active_dispatch(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        results, errors = [], []
        def execute(request):
            entered.set()
            if not release.wait(5): raise RuntimeError('test_timeout')
            return Result('applied', {})
        self.probe.execute = execute
        request = self.request()
        grant = self.kernel.issue_grant(request)
        def dispatch():
            try: results.append(self.kernel.dispatch(request, grant))
            except Exception as error: errors.append(error)
        def close():
            try: self.kernel.close()
            except Exception as error: errors.append(error)
            finally: closed.set()
        worker = threading.Thread(target=dispatch)
        closer = threading.Thread(target=close)
        worker.start()
        self.assertTrue(entered.wait(5))
        closer.start()
        self.assertFalse(closed.wait(0.05))
        release.set()
        worker.join(5); closer.join(5)
        self.assertFalse(worker.is_alive() or closer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0].status, 'applied')
        reopened = Kernel(self.db)
        try: self.assertEqual(reopened.status(request.operation_id)['state'], 'applied')
        finally: reopened.close()
    def test_jsonl_invalid_and_oversize_are_not_sent(self):
        stream = io.StringIO()
        serve(self.kernel, stdin=io.StringIO('[]\n'+json.dumps({'operation_id':'x','capability':'probe.write','target':'r','grant_token':'x'})+'\n'+'x'*65537+'\n'), stdout=stream)
        outcomes = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual([r['status'] for r in outcomes], ['rejected']*3)
        self.assertEqual(self.probe.calls, [])

if __name__ == '__main__': unittest.main()
