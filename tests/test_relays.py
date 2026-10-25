from dataclasses import FrozenInstanceError, replace
import threading
import concurrent.futures
import unittest
from bili_bridge.contracts import Request, Result
from bili_bridge.relays import RelayEnvelope, RelayStation, BudgetRelay, GrantRelay, current_envelope
import test_kernel
from test_kernel import Adapter


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.request = Request('op', 'public', 'video.metadata', 'BV1xx411c7mD', {})
        self.envelope = RelayEnvelope.from_request(self.request)

    def test_frozen_envelope(self):
        with self.assertRaises(FrozenInstanceError):
            self.envelope.account = 'other'

    def test_scope_effect_version_mutations_rejected(self):
        station = RelayStation('kernel.schema', None)
        for key, value in [('account', 'other'), ('capability', 'write'), ('target', 'other'),
                           ('correlation_id', 'other'), ('payload_digest', 'bad'),
                           ('schema_version', 2), ('effect', 'write')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                station.forward(replace(self.envelope, **{key: value}), self.request)

    def test_canonical_order_and_skipped_prefix_rejected(self):
        with self.assertRaises(ValueError):
            RelayStation('kernel.execute', 'kernel.journal').forward(
                replace(self.envelope, path=('kernel.journal',)), self.request)
        with self.assertRaises(ValueError):
            RelayStation('metadata.normalize', 'metadata.parse').forward(
                replace(self.envelope, path=('metadata.parse',)), self.request)
        e = self.envelope
        previous = None
        for name in ('kernel.schema', 'kernel.grant', 'kernel.budget', 'kernel.journal',
                     'kernel.execute', 'metadata.fetch', 'metadata.parse', 'metadata.normalize'):
            e = RelayStation(name, previous).forward(e, self.request)
            previous = name
        self.assertEqual(len(e.path), 8)
        self.assertEqual(e.account, self.envelope.account)
        with self.assertRaises(ValueError):
            RelayStation('metadata.normalize', 'metadata.normalize').forward(e, self.request)

    def test_read_only_module_rejects_write(self):
        e = RelayEnvelope.from_request(self.request, True)
        with self.assertRaises(ValueError):
            RelayStation('metadata.fetch', None, frozenset({'read'})).forward(e, self.request)

    def test_guard_primitives(self):
        self.assertEqual(GrantRelay.rejection(None, self.envelope, 1), 'grant_invalid')
        grant = {'used': 0, 'operation_id': 'op', 'digest': self.envelope.payload_digest, 'expires': 2}
        self.assertIsNone(GrantRelay.rejection(grant, self.envelope, 1))
        self.assertEqual(GrantRelay.rejection(grant, self.envelope, 2), 'grant_invalid')
        args = dict(now=2, high_water=1, count=0, last_start=None, budget=1, interval=3)
        self.assertIsNone(BudgetRelay.rejection(**args))
        self.assertEqual(BudgetRelay.rejection(**dict(args, count=1)), 'hourly_budget')


class RelayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_kernel.KernelTests()
        self.helper.setUp()

    def tearDown(self):
        self.helper.tearDown()

    def test_kernel_propagates_and_resets_context(self):
        k = self.helper.kernel()
        seen = []
        def effect(request):
            e = current_envelope()
            seen.append(e)
            self.assertEqual(e.path[-1], 'kernel.execute')
            module = RelayStation('metadata.fetch', 'kernel.execute', frozenset({'read'})).forward(e, request)
            self.assertEqual(module.path[-1], 'metadata.fetch')
            return Result('applied', {})
        k.register(Adapter(effect=effect))
        self.assertEqual(k.dispatch(self.helper.req()).status, 'applied')
        self.assertIsNone(current_envelope())
        self.assertEqual(len(seen), 1)
        self.assertEqual(k.status('one')['relay_trace'], list(seen[0].path))

    def test_close_waits_active_dispatch(self):
        k = self.helper.kernel()
        entered, release, close_started = threading.Event(), threading.Event(), threading.Event()
        def effect(r):
            entered.set()
            release.wait(5)
            return Result('applied', {})
        k.register(Adapter(effect=effect))
        def close():
            close_started.set()
            k.close()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            send = pool.submit(k.dispatch, self.helper.req())
            self.assertTrue(entered.wait(5))
            closer = pool.submit(close)
            self.assertTrue(close_started.wait(5))
            self.assertFalse(closer.done())
            release.set()
            self.assertEqual(send.result(5).status, 'applied')
            closer.result(5)
        self.assertEqual(k.dispatch(self.helper.req('new')).error, 'kernel_closed')

    def test_nested_dispatch_and_close_rejected(self):
        k = self.helper.kernel()
        def effect(r):
            self.assertEqual(k.dispatch(self.helper.req('nested')).error, 'nested_dispatch_forbidden')
            k.close()
        k.register(Adapter(effect=effect))
        self.assertEqual(k.dispatch(self.helper.req()).status, 'unknown')

    def test_capacity_fails_closed_without_deleting_unknown(self):
        k = self.helper.kernel()
        k.MAX_RECORDS = 1
        p = Adapter(effect=lambda r: Result('unknown', {}))
        k.register(p)
        self.assertEqual(k.dispatch(self.helper.req()).status, 'unknown')
        self.assertEqual(k.dispatch(self.helper.req('next')).error, 'journal_capacity')
        self.assertEqual(k.status('one')['state'], 'unknown')
        k.issue_grant(self.helper.req())
        with self.assertRaisesRegex(RuntimeError, 'journal_capacity'):
            k.issue_grant(self.helper.req('next'))
        self.assertEqual(len(p.calls), 1)

    def test_cooldown_longer_than_hour_preserved(self):
        k = self.helper.kernel(min_interval=7200)
        k.register(Adapter())
        k.dispatch(self.helper.req())
        self.helper.now += 3601
        self.assertEqual(k.dispatch(self.helper.req('next')).error, 'cooldown')
