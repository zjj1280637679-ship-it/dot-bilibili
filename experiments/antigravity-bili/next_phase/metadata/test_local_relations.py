"""dot local regression relations; synthetic inputs, fake opener, socket trap."""
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from . import versioned_adapter as m
from .test_metadata_phase import MockOpener, MockHTTPResponse, socket_guard

BVID = 'BV17x411w7KC'
OTHER = 'BV1xx411c7X8'

def body(**changes):
    data = dict(bvid=BVID, title='Fixture title', aid=1, duration=0, pubdate=0)
    data.update(changes)
    return json.dumps({'code': 0, 'data': data}).encode()

class Gate:
    def __init__(self): self.paused = False; self.generation = 0
    def snapshot(self): return self.paused, self.generation

class LocalRelations(unittest.TestCase):
    def setUp(self):
        guard = socket_guard(); guard.__enter__(); self.addCleanup(guard.__exit__, None, None, None)
        self.conn = sqlite3.connect(':memory:'); self.addCleanup(self.conn.close)
        m.init_metadata_ledger(self.conn, initial_paused=False)
        self.gate = Gate(); self.calls = 0
    def transport(self, req):
        self.calls += 1
        return m.TransportReply('response', 200, body())
    def execute(self, **overrides):
        args = dict(reference_id='ref', expected_bvid=BVID, operation_id='op',
                    ref_map={'ref': BVID}, transport=self.transport,
                    provenance=m.Provenance.SYNTHETIC, authorization_check=lambda: True,
                    pause_gate=self.gate, account_scope='account-fixture')
        args.update(overrides)
        return m.execute_metadata_read(self.conn, **args)
    def narrow(self, factory):
        opener = MockOpener(factory)
        return m.NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener), opener

    def test_missing_invalid_status_never_assumed_200(self):
        for status in (None, True, 200.0, '200', 99, 600):
            with self.subTest(status=status):
                t, opener = self.narrow(lambda req: MockHTTPResponse(body(), status=status))
                r = self.execute(operation_id='status-' + str(status).replace('.', '_'), transport=t)
                self.assertEqual(r['status'], 'unknown'); self.assertIsNone(r['diagnostic']['http_status'])
                self.assertEqual(opener.call_count, 1); self.assertEqual(r['evidence']['opener_call_entries'], 1)
                self.assertTrue(r['evidence']['http_response_observed'])

    def test_no_status_attributes_remains_unknown(self):
        def response(req):
            r = MockHTTPResponse(body()); del r.status; del r.code; return r
        t, _ = self.narrow(response)
        r = self.execute(transport=t)
        self.assertEqual(r['status'], 'unknown'); self.assertIsNone(r['diagnostic']['http_status'])

    def test_reused_transport_clears_prior_response_before_paused_call(self):
        t, opener = self.narrow(lambda req: MockHTTPResponse(body()))
        a = self.execute(transport=t); t.paused = True
        b = self.execute(operation_id='next', transport=t)
        self.assertEqual(a['status'], 'parsed'); self.assertEqual(b['status'], 'blocked')
        self.assertIsNone(b['diagnostic']['http_status']); self.assertFalse(b['evidence']['http_response_observed'])
        self.assertEqual(b['evidence']['transport_callback_entries'], 1)
        self.assertEqual(b['evidence']['opener_call_entries'], 0); self.assertEqual(opener.call_count, 1)

    def test_disabled_transport_and_callback_are_not_http_send(self):
        r = self.execute(transport=m.NarrowViewHttpTransport())
        self.assertEqual(r['status'], 'blocked')
        self.assertEqual(r['evidence']['adapter_callback_entries'], 1)
        self.assertEqual(r['evidence']['transport_callback_entries'], 1)
        self.assertEqual(r['evidence']['opener_call_entries'], 0)
        self.assertFalse(r['evidence']['http_send_verified']); self.assertFalse(r['evidence']['http_response_observed'])

    def test_transport_throw_is_one_entry_no_retry_no_raw_error(self):
        def boom(req): raise TimeoutError('cookie=private_SENTINEL')
        t, opener = self.narrow(boom)
        r = self.execute(transport=t)
        self.assertEqual(r['status'], 'unknown'); self.assertEqual(opener.call_count, 1)
        self.assertIsNone(r['diagnostic']['http_status']); self.assertFalse(r['evidence']['http_response_observed'])
        self.assertNotIn('private_SENTINEL', json.dumps(r))

    def test_response_read_timeout_preserves_observed_http_status(self):
        class SlowBody(MockHTTPResponse):
            def read(self, amt=-1): raise TimeoutError('private_READ_SENTINEL')
        t, opener = self.narrow(lambda req: SlowBody(body()))
        r = self.execute(transport=t)
        self.assertEqual(r['status'], 'unknown'); self.assertEqual(r['diagnostic']['http_status'], 200)
        self.assertTrue(r['evidence']['http_response_observed']); self.assertEqual(opener.call_count, 1)
        self.assertNotIn('private_READ_SENTINEL', json.dumps(r))

    def test_generic_reply_status_separate_from_business_status(self):
        for i, (http, payload, expected) in enumerate(((200, b'{"code":-404,"message":"secret","data":null}', 'upstream_error'), (503, body(), 'unknown'), (200, body(), 'parsed'))):
            r = self.execute(operation_id='layer-'+str(i), transport=lambda req: m.TransportReply('response', http, payload))
            self.assertEqual(r['status'], expected); self.assertEqual(r['diagnostic']['http_status'], http)
            self.assertIsNone(r['evidence']['opener_call_entries']); self.assertFalse(r['evidence']['http_send_verified'])
            self.assertEqual(r['auth_assessment'], 'not_assessed')
            if expected == 'upstream_error': self.assertEqual(r['diagnostic']['upstream_code'], -404)

    def test_partial_retains_usable_fields_and_exact_coverage(self):
        payload = json.dumps({'code': 0, 'data': {'bvid': BVID, 'title': 'Useful', 'aid': True}}).encode()
        r = self.execute(transport=lambda req: m.TransportReply('response', 200, payload))
        self.assertEqual(r['status'], 'partial'); self.assertEqual(r['data'], {'bvid': BVID, 'title': 'Useful'})
        self.assertEqual(r['field_states']['aid'], 'invalid'); self.assertEqual(r['field_states']['duration'], 'missing')
        self.assertFalse(r['coverage']['projection_complete']); self.assertFalse(r['coverage']['full_api_response'])
        self.assertEqual(r['operation_completion'], 'recorded'); self.assertEqual(r['auth_assessment'], 'not_assessed')

    def test_business_outcomes_do_not_poison_unrelated_authorized_reads(self):
        replies = [('pending', m.TransportReply('pending')), ('deferred', m.TransportReply('deferred')),
                   ('unknown', m.TransportReply('unknown')), ('blocked', m.TransportReply('blocked')),
                   ('wrong_target', m.TransportReply('response', 200, body(bvid=OTHER))),
                   ('upstream_error', m.TransportReply('response', 200, b'{"code":-1}'))]
        for i, (status, reply) in enumerate(replies):
            r = self.execute(operation_id='result-'+str(i), transport=lambda req, x=reply: x)
            self.assertEqual(r['status'], status); self.assertEqual(r['auth_assessment'], 'not_assessed')
            if status == 'wrong_target': self.assertEqual(r['data'], {})
            follow = self.execute(operation_id='follow-'+str(i))
            self.assertEqual(follow['status'], 'parsed'); self.assertFalse(self.gate.paused)
        self.assertEqual(self.calls, len(replies))

    def test_invalid_contract_and_missing_authorization_zero_transport(self):
        cases = [({'url': 'https://invalid.test'}, 'rejected'), ({'unexpected': 1}, 'rejected'),
                 ({'backend': 'other'}, 'rejected'), ({'provenance': 'synthetic'}, 'rejected'),
                 ({'authorization_check': None}, 'blocked'), ({'account_scope': 'offline_unbound'}, 'rejected')]
        for args, status in cases:
            with self.subTest(args=args): self.assertEqual(self.execute(**args)['status'], status)
        self.assertEqual(self.calls, 0)

    def test_authorization_false_vs_unknown_not_human_rejection(self):
        for answer, expected in ((False, 'blocked'), (0, 'unknown'), (1, 'unknown'), (None, 'unknown'), ('yes', 'unknown')):
            with self.subTest(answer=answer):
                r = self.execute(authorization_check=lambda x=answer: x)
                self.assertEqual(r['status'], expected); self.assertEqual(r['evidence']['transport_callback_entries'], 0)
                self.assertNotEqual(r['diagnostic']['code'], 'user_denied')
        def bad(): raise RuntimeError('private_AUTH_SENTINEL')
        r = self.execute(authorization_check=bad)
        self.assertEqual(r['diagnostic']['code'], 'authorization_unknown'); self.assertNotIn('private_AUTH_SENTINEL', json.dumps(r))
        self.assertEqual(self.calls, 0)

    def test_authorization_rechecked_before_transport(self):
        answers = iter((True, False))
        r = self.execute(authorization_check=lambda: next(answers))
        self.assertEqual(r['status'], 'blocked'); self.assertEqual(r['diagnostic']['gate_code'], 'read_prerequisite_blocked')
        self.assertEqual(r['evidence']['adapter_callback_entries'], 1)
        self.assertEqual(r['evidence']['transport_callback_entries'], 0); self.assertEqual(self.calls, 0)

    def test_pause_generation_change_inside_auth_callback_blocks_send(self):
        count = 0
        def auth():
            nonlocal count
            count += 1
            if count == 2: self.gate.generation += 1  # pause followed by unpause
            return True
        r = self.execute(authorization_check=auth)
        self.assertEqual(r['status'], 'blocked'); self.assertEqual(r['diagnostic']['gate_code'], 'pause_generation_changed')
        self.assertEqual(self.calls, 0)

    def test_shared_pause_unknown_and_paused_fail_closed(self):
        self.gate.paused = True
        self.assertEqual(self.execute()['status'], 'blocked')
        class BadGate:
            def snapshot(self): return 0, True
        self.assertEqual(self.execute(pause_gate=BadGate())['diagnostic']['code'], 'pause_state_unknown')
        self.assertEqual(self.calls, 0)

    def test_foreign_controls_schema_coexists_not_reused_as_authority(self):
        self.conn.execute('CREATE TABLE controls(account TEXT, paused INTEGER, generation INTEGER, extra TEXT)')
        self.conn.execute('INSERT INTO controls VALUES(?,?,?,?)', ('foreign-account', 1, 4, 'fixture'))
        self.conn.commit()
        r = self.execute(); self.assertEqual(r['status'], 'parsed')
        self.assertEqual(self.conn.execute('SELECT * FROM controls').fetchall(), [('foreign-account', 1, 4, 'fixture')])
        self.assertEqual(self.calls, 1)

    def test_account_and_provenance_part_of_operation_identity(self):
        self.assertEqual(self.execute()['status'], 'parsed')
        self.assertEqual(self.execute(account_scope='another-account')['diagnostic']['code'], 'operation_id_conflict')
        self.assertEqual(self.execute(provenance=m.Provenance.SUPPLIED)['diagnostic']['code'], 'operation_id_conflict')
        self.assertEqual(self.calls, 1)

    def test_cached_delivery_reports_zero_current_calls_retains_old_observation(self):
        a = self.execute(); self.gate.paused = True
        b = self.execute()
        self.assertEqual(a['delivery'], 'current'); self.assertEqual(b['delivery'], 'cached')
        self.assertEqual(a['evidence'], b['evidence']); self.assertEqual(a['data'], b['data'])
        self.assertEqual(b['invocation']['transport_callback_entries'], 0)
        self.assertEqual(b['invocation']['opener_call_entries'], 0); self.assertEqual(self.calls, 1)

    def test_unknown_record_never_auto_replays(self):
        calls = 0
        def unknown(req):
            nonlocal calls
            calls += 1
            raise RuntimeError('private_BACKEND_SENTINEL')
        a = self.execute(transport=unknown); b = self.execute(transport=unknown)
        self.assertEqual(a['status'], 'unknown'); self.assertEqual(b['delivery'], 'cached')
        self.assertEqual(calls, 1); self.assertNotIn('private_BACKEND_SENTINEL', json.dumps(a))

    def test_pending_vs_crash_unknown_preserved_without_replay(self):
        fp = m.compute_semantic_fingerprint('web_view_v1', 'video.metadata.read', BVID,
                                          provenance=m.Provenance.SYNTHETIC, account_scope='account-fixture')
        self.conn.execute('INSERT INTO metadata_operations VALUES(?,?,?,NULL)', ('op', fp, 'owner')); self.conn.commit()
        self.assertEqual(self.execute(run_id='owner')['status'], 'pending')
        self.assertEqual(self.execute(run_id='other')['status'], 'unknown')
        self.assertEqual(self.execute()['status'], 'unknown'); self.assertEqual(self.calls, 0)

    def test_strict_content_type_encoding_and_returned_url(self):
        cases = [{'Content-Type': 'application/json-malicious'}, {'Content-Type': 'text/plain; application/json'},
                 {'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}]
        for i, headers in enumerate(cases):
            t, opener = self.narrow(lambda req, h=headers: MockHTTPResponse(body(), headers=h))
            self.assertEqual(self.execute(operation_id='headers-'+str(i), transport=t)['status'], 'unknown')
            self.assertEqual(opener.call_count, 1)
        def wrong_url(req):
            response = MockHTTPResponse(body()); response.geturl = lambda: 'https://invalid.test/'
            return response
        t, _ = self.narrow(wrong_url)
        self.assertEqual(self.execute(operation_id='url', transport=t)['status'], 'unknown')

    def test_redirect_handler_does_not_return_follow_request(self):
        import urllib.request
        with self.assertRaises(m.RedirectBlockedError):
            m.NoRedirectHandler().redirect_request(urllib.request.Request('https://invalid.test/'), None, 302, 'private_REDIRECT_SENTINEL', {}, 'https://invalid.test/next')

    def test_strict_gate_booleans_not_truthiness(self):
        for args in ({'network_enabled': 1}, {'paused': 0}):
            with self.assertRaises(ValueError): m.NarrowViewHttpTransport(**args)
        t, opener = self.narrow(lambda req: MockHTTPResponse(body())); t.paused = 'false'
        self.assertEqual(self.execute(transport=t)['status'], 'blocked'); self.assertEqual(opener.call_count, 0)

    def test_only_pinned_endpoint_request_no_caller_secrets(self):
        t, opener = self.narrow(lambda req: MockHTTPResponse(body()))
        r = self.execute(transport=t)
        self.assertEqual(r['status'], 'parsed')
        self.assertEqual(opener.last_request.full_url, 'https://api.bilibili.com/x/web-interface/view?bvid='+BVID)
        self.assertEqual(opener.last_request.get_method(), 'GET')
        self.assertIsNone(opener.last_request.get_header('Cookie')); self.assertIsNone(opener.last_request.data)

    def test_atomic_reservation_duplicate_call_enters_transport_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ledger.sqlite3'; entered = threading.Event(); finish = threading.Event(); results = []
            count = 0
            def slow(req):
                nonlocal count
                count += 1; entered.set()
                if not finish.wait(3): raise RuntimeError('test-timeout')
                return m.TransportReply('response', 200, body())
            args = dict(reference_id='ref', expected_bvid=BVID, operation_id='same', ref_map={'ref': BVID},
                        transport=slow, provenance=m.Provenance.SYNTHETIC, authorization_check=lambda: True,
                        pause_gate=self.gate, account_scope='account-fixture')
            worker = threading.Thread(target=lambda: results.append(m.execute_metadata_read(path, **args)))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                second = m.execute_metadata_read(path, **args)
                self.assertEqual(second['status'], 'unknown'); self.assertEqual(second['diagnostic']['code'], 'previous_run_incomplete')
            finally:
                finish.set(); worker.join(3)
            self.assertFalse(worker.is_alive()); self.assertEqual(count, 1); self.assertEqual(results[0]['status'], 'parsed')

    def test_recording_error_keeps_observed_calls_and_does_not_replay(self):
        class FailRecording(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if sql.startswith('UPDATE metadata_operations'):
                    raise sqlite3.OperationalError('private_DB_SENTINEL')
                return super().execute(sql, *args, **kwargs)
        self.conn.close()
        self.conn = sqlite3.connect(':memory:', factory=FailRecording)
        self.addCleanup(self.conn.close)
        m.init_metadata_ledger(self.conn, initial_paused=False)
        a = self.execute(); b = self.execute()
        self.assertEqual(a['status'], 'parsed')
        self.assertEqual(a['operation_completion'], 'recording_unknown')
        self.assertEqual(a['evidence']['transport_callback_entries'], 1)
        self.assertEqual(a['diagnostic']['http_status'], 200)
        self.assertEqual(b['status'], 'unknown'); self.assertEqual(self.calls, 1)
        self.assertNotIn('private_DB_SENTINEL', json.dumps(a))

    def parallel_shared_transport(self, *, first_read_error=False, second_open_error=False):
        """Second call finishes while first is still in read: concurrency is retained."""
        entered = threading.Event(); release = threading.Event(); second_done = threading.Event()
        counts = []; results = {}
        class FirstResponse(MockHTTPResponse):
            def read(inner, amount=-1):
                entered.set()
                if not release.wait(3): raise RuntimeError('fixture-timeout')
                if first_read_error: raise TimeoutError('private_FIRST_SENTINEL')
                return super().read(amount)
        class Opener:
            def open(inner, request, timeout):
                counts.append(request.full_url)
                if request.full_url.endswith(BVID): return FirstResponse(body(), status=200)
                if second_open_error: raise TimeoutError('private_SECOND_SENTINEL')
                return MockHTTPResponse(body(bvid=OTHER), status=503)
        shared = m.NarrowViewHttpTransport(network_enabled=True, paused=False, opener=Opener())
        with tempfile.TemporaryDirectory() as tmp:
            def run(name, target):
                results[name] = m.execute_metadata_read(Path(tmp)/(name+'.sqlite3'),
                    reference_id='ref', expected_bvid=target, operation_id=name,
                    ref_map={'ref': target}, transport=shared, provenance=m.Provenance.SYNTHETIC,
                    pause_gate=self.gate, account_scope='account-fixture', authorization_check=lambda: True)
                if name == 'second': second_done.set()
            first = threading.Thread(target=run, args=('first', BVID))
            second = threading.Thread(target=run, args=('second', OTHER))
            first.start()
            try:
                self.assertTrue(entered.wait(3)); second.start()
                self.assertTrue(second_done.wait(3), 'shared transport must retain legal concurrency')
                self.assertNotIn('first', results)
            finally:
                release.set(); first.join(3)
                if second.ident is not None: second.join(3)
            self.assertFalse(first.is_alive()); self.assertFalse(second.is_alive())
        self.assertEqual(len(counts), 2)
        for r in results.values():
            self.assertEqual(r['evidence']['transport_callback_entries'], 1)
            self.assertEqual(r['evidence']['opener_call_entries'], 1)
            self.assertNotIn('SENTINEL', json.dumps(r))
        return results['first'], results['second']

    def test_shared_transport_parallel_http_status_is_call_local(self):
        first, second = self.parallel_shared_transport()
        self.assertEqual(first['status'], 'parsed'); self.assertEqual(first['diagnostic']['http_status'], 200)
        self.assertEqual(first['data']['bvid'], BVID)
        self.assertEqual(second['status'], 'unknown'); self.assertEqual(second['diagnostic']['http_status'], 503)
        self.assertEqual(first['diagnostic']['transport_layer_status'], 'response')
        self.assertEqual(second['diagnostic']['transport_layer_status'], 'response')

    def test_shared_transport_parallel_exception_evidence_is_call_local(self):
        first, second = self.parallel_shared_transport(first_read_error=True)
        self.assertEqual(first['status'], 'unknown'); self.assertEqual(first['diagnostic']['http_status'], 200)
        self.assertEqual(first['diagnostic']['transport_layer_status'], 'network_error')
        self.assertEqual(second['diagnostic']['http_status'], 503)
        self.assertEqual(second['diagnostic']['transport_layer_status'], 'response')
        first, second = self.parallel_shared_transport(second_open_error=True)
        self.assertEqual(first['status'], 'parsed'); self.assertEqual(first['diagnostic']['http_status'], 200)
        self.assertEqual(first['diagnostic']['transport_layer_status'], 'response')
        self.assertEqual(second['status'], 'unknown'); self.assertIsNone(second['diagnostic']['http_status'])
        self.assertEqual(second['diagnostic']['transport_layer_status'], 'network_error')
        self.assertFalse(second['evidence']['http_response_observed'])

if __name__ == '__main__': unittest.main()
