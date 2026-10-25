import concurrent.futures
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from bili_bridge.contracts import Request, Result
from bili_bridge.kernel import Kernel


class Adapter:
    def __init__(self, name='a', capability='read', write=False, effect=None):
        self.name = name
        self.capabilities = frozenset({capability})
        self.mutating = self.capabilities if write else frozenset()
        self.calls = []
        self.effect = effect

    def execute(self, request):
        self.calls.append(request)
        return self.effect(request) if self.effect else Result('applied', {'evidence': 'simulated'})


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, 'journal.sqlite')
        self.now = 10000.0
        self.handles = []

    def tearDown(self):
        for handle in self.handles:
            handle.close()
        self.temp.cleanup()

    def kernel(self, **kwargs):
        k = Kernel(self.path, min_interval=kwargs.pop('min_interval', 0),
                   hourly_budget=kwargs.pop('hourly_budget', 20), clock=lambda: self.now, **kwargs)
        self.handles.append(k)
        return k

    def close(self, k):
        k.close()
        self.handles.remove(k)

    @staticmethod
    def req(op='one', capability='read', account='public', target='video', payload=None):
        return Request(op, account, capability, target, {} if payload is None else payload)

    def test_duplicate_and_immutable_identity(self):
        k = self.kernel()
        p = Adapter()
        k.register(p)
        r = self.req(payload={'b': 2, 'a': 1})
        self.assertEqual(k.dispatch(r).status, 'applied')
        self.assertEqual(k.dispatch(self.req(payload={'a': 1, 'b': 2})).status, 'applied')
        for change in (self.req(payload={'a': 3}), self.req(account='other'), self.req(target='other')):
            self.assertEqual(k.dispatch(change).error, 'operation_identity_conflict')
        self.assertEqual(len(p.calls), 1)

    def test_request_snapshot_cannot_change_saved_identity(self):
        payload = {'nested': [1]}
        def effect(r):
            payload['nested'].append(2)
            r.payload['nested'].append(3)
            return Result('applied', {})
        k = self.kernel()
        k.register(Adapter(effect=effect))
        k.dispatch(self.req(payload=payload))
        self.assertEqual(k.dispatch(self.req(payload=payload)).error, 'operation_identity_conflict')
        self.assertEqual(k.dispatch(self.req(payload={'nested': [1]})).status, 'applied')

    def test_invalid_request_and_secret_key_rejected(self):
        k = self.kernel()
        for r in (None, self.req(payload={'cookie': 'secret'}), self.req(payload={'x': float('nan')}),
                  self.req(payload={1: 'nonstring'}), self.req(op=''), self.req(payload=[])):
            self.assertEqual(k.dispatch(r).status, 'rejected')

    def test_capability_unique_and_mutation_declaration_frozen(self):
        k = self.kernel()
        p = Adapter(write=True)
        k.register(p)
        p.mutating = frozenset()
        with self.assertRaises(ValueError):
            k.register(Adapter('b'))
        self.assertEqual(k.dispatch(self.req()).error, 'grant_required')
        self.assertEqual(len(p.calls), 0)
        self.assertEqual(k.dispatch(self.req('absent', 'absent')).status, 'unsupported')

    def test_exact_grant_account_target_payload_and_operation(self):
        k = self.kernel()
        p = Adapter(write=True)
        k.register(p)
        original = self.req()
        token = k.issue_grant(original)
        for r in (self.req('other'), self.req(account='other'), self.req(target='other'),
                  self.req(payload={'x': 1})):
            self.assertEqual(k.dispatch(r, token).status, 'blocked' if r.operation_id == 'other' or r.account == 'other' else 'rejected')
        # The first mismatched same-ID request permanently binds that identity.
        self.assertEqual(len(p.calls), 0)

    def test_grant_once_and_expiry(self):
        k = self.kernel()
        p = Adapter(write=True)
        k.register(p)
        r = self.req()
        token = k.issue_grant(r, ttl=1)
        self.now += 1
        self.assertEqual(k.dispatch(r, token).status, 'blocked')
        r = self.req('valid')
        token = k.issue_grant(r)
        self.assertEqual(k.dispatch(r, token).status, 'applied')
        self.assertEqual(k.dispatch(r, token).status, 'applied')
        self.assertEqual(len(p.calls), 1)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT SUM(used) FROM grants').fetchone()[0], 1)

    def test_expiry_rechecked_at_reservation(self):
        k = self.kernel()
        k.register(Adapter(write=True))
        r = self.req()
        token = k.issue_grant(r, ttl=1)
        ticks = iter([10000.0, 10001.0])
        k.clock = lambda: next(ticks)
        self.assertEqual(k.dispatch(r, token).error, 'grant_expired')

    def test_grant_expiry_after_durable_prepare_prevents_execute(self):
        k = self.kernel()
        p = Adapter(write=True)
        k.register(p)
        r = self.req()
        token = k.issue_grant(r, ttl=1)
        ticks = iter([10000.0, 10000.5, 10001.0])
        k.clock = lambda: next(ticks)
        self.assertEqual(k.dispatch(r, token).error, 'grant_expired')
        self.assertEqual(p.calls, [])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 1)

    def test_shared_database_multiple_processes_budget(self):
        code = """
import sys
from bili_bridge.kernel import Kernel
from bili_bridge.contracts import Request, Result
class P:
 name='p'; capabilities=frozenset({'read'}); mutating=frozenset()
 def execute(self,r): return Result('applied',{})
k=Kernel(sys.argv[1], min_interval=0, hourly_budget=1, clock=lambda:10000.)
k.register(P())
print(k.dispatch(Request(sys.argv[2],'public','read','v',{})).status)
k.close()
"""
        # Initialize schema once; independent processes contend on reservations.
        self.close(self.kernel(hourly_budget=1))
        children = [subprocess.Popen([sys.executable, '-c', code, self.path, str(i)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
        results = []
        for child in children:
            out, err = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, err)
            results.append(out.strip())
        self.assertEqual(results.count('applied'), 1)
        self.assertEqual(results.count('deferred'), 3)

    def test_exception_after_effect_unknown_and_conflicting_write_blocked(self):
        effects = []
        def fail(r):
            effects.append(r.operation_id)
            raise RuntimeError('credential must not appear')
        k = self.kernel()
        k.register(Adapter('write1', 'write.one', True, fail))
        k.register(Adapter('write2', 'write.two', True))
        r = self.req(capability='write.one')
        result = k.dispatch(r, k.issue_grant(r))
        self.assertEqual(result.status, 'unknown')
        self.assertNotIn('credential', result.error)
        self.assertEqual(k.dispatch(r, k.issue_grant(r)).status, 'unknown')
        conflict = self.req('conflict', 'write.two')
        self.assertEqual(k.dispatch(conflict, k.issue_grant(conflict)).error, 'resource_unresolved')
        independent = self.req('independent', 'write.two', account='other')
        self.assertEqual(k.dispatch(independent, k.issue_grant(independent)).status, 'applied')
        self.assertEqual(effects, ['one'])
        self.close(k)
        reopened = self.kernel()
        reopened.register(Adapter('write1', 'write.one', True, fail))
        self.assertEqual(reopened.dispatch(r).status, 'unknown')
        self.assertEqual(effects, ['one'])

    def test_malformed_or_secret_result_unknown(self):
        k = self.kernel()
        for i, value in enumerate([None, Result('success', {}), Result('applied', {'token': 'secret'}),
                                   Result('rejected', {}, 'raw Exception: secret')]):
            p = Adapter(str(i), str(i), effect=lambda r, v=value: v)
            k.register(p)
            self.assertEqual(k.dispatch(self.req(str(i), str(i))).status, 'unknown')

    def test_shared_budget_cross_plugin_and_persistent(self):
        k = self.kernel(hourly_budget=2)
        for c in ('a', 'b', 'c'):
            k.register(Adapter(c, c))
        self.assertEqual(k.dispatch(self.req('1', 'a')).status, 'applied')
        self.assertEqual(k.dispatch(self.req('2', 'b', account='other')).status, 'applied')
        self.close(k)
        k = self.kernel(hourly_budget=999)
        k.register(Adapter('c', 'c'))
        self.assertEqual(k.hourly_budget, 2)
        self.assertEqual(k.dispatch(self.req('3', 'c')).error, 'hourly_budget')
        self.now += 3600
        self.assertEqual(k.dispatch(self.req('4', 'c')).status, 'applied')

    def test_cooldown_and_clock_rollback(self):
        k = self.kernel(min_interval=3)
        k.register(Adapter())
        k.dispatch(self.req())
        self.now += 2
        self.assertEqual(k.dispatch(self.req('two')).error, 'cooldown')
        self.now -= 10
        self.assertEqual(k.dispatch(self.req('three')).error, 'clock_rollback')
        self.now = 10003
        self.assertEqual(k.dispatch(self.req('four')).status, 'applied')

    def test_shared_db_concurrency_reserves_one(self):
        handles = [self.kernel(hourly_budget=1) for _ in range(8)]
        for k in handles:
            k.register(Adapter())
        barrier = threading.Barrier(len(handles))
        def send(pair):
            i, k = pair
            barrier.wait()
            return k.dispatch(self.req(str(i))).status
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(send, enumerate(handles)))
        self.assertEqual(results.count('applied'), 1)
        self.assertEqual(results.count('deferred'), 7)

    def test_active_peer_not_recovered(self):
        entered, release = threading.Event(), threading.Event()
        def slow(r):
            entered.set()
            release.wait(5)
            return Result('applied', {})
        k = self.kernel()
        k.register(Adapter(effect=slow))
        with concurrent.futures.ThreadPoolExecutor() as executor:
            pending = executor.submit(k.dispatch, self.req())
            self.assertTrue(entered.wait(5))
            peer = self.kernel()
            self.assertEqual(peer.status('one')['state'], 'inflight')
            self.assertEqual(peer.recover(), 0)
            release.set()
            self.assertEqual(pending.result(5).status, 'applied')

    def test_process_crash_recovery_retains_reservation_and_no_replay(self):
        code = '''
import os, sys
from bili_bridge.kernel import Kernel
from bili_bridge.contracts import Request
class P:
 name='p'; capabilities=frozenset({'write'}); mutating=capabilities
 def execute(self,r): os._exit(19)
k=Kernel(sys.argv[1], min_interval=0, hourly_budget=1, clock=lambda:10000.)
k.register(P()); r=Request('crash','a','write','v',{})
k.dispatch(r,k.issue_grant(r))
'''
        child = subprocess.run([sys.executable, '-c', code, self.path], check=False)
        self.assertEqual(child.returncode, 19)
        k = self.kernel()
        self.assertEqual(k.status('crash')['state'], 'unknown')
        p = Adapter('p', 'write', True)
        k.register(p)
        r = self.req('crash', 'write', 'a', 'v')
        self.assertEqual(k.dispatch(r, k.issue_grant(r)).status, 'unknown')
        self.assertEqual(p.calls, [])
        other = self.req('new', 'write', 'other', 'v')
        self.assertEqual(k.dispatch(other, k.issue_grant(other)).error, 'hourly_budget')

    def test_lease_not_pid_is_authoritative_for_active_peer(self):
        from unittest.mock import patch
        entered, release = threading.Event(), threading.Event()
        def slow(r):
            entered.set()
            release.wait(5)
            return Result('applied', {})
        k = self.kernel()
        k.register(Adapter(effect=slow))
        with concurrent.futures.ThreadPoolExecutor() as executor:
            pending = executor.submit(k.dispatch, self.req())
            self.assertTrue(entered.wait(5))
            try:
                with sqlite3.connect(self.path) as db:
                    db.execute('UPDATE owners SET pid=2147483647')
                with patch('os.kill', side_effect=AssertionError('PID must not decide ownership')):
                    peer = self.kernel()
                    self.assertEqual(peer.status('one')['state'], 'inflight')
                    self.assertEqual(peer.recover(), 0)
            finally:
                release.set()
            self.assertEqual(pending.result(5).status, 'applied')

    def test_abandoned_lease_recovers_despite_pid_matching_live_process(self):
        k = self.kernel()
        # Inject durable pending record and release lease as process death would.
        r = self.req()
        k.register(Adapter())
        k.dispatch(r)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE operations SET state='inflight',result=NULL")
            db.execute('UPDATE owners SET pid=?', (os.getpid(),))
        k._release_lease()
        peer = self.kernel()
        self.assertEqual(peer.status('one')['state'], 'unknown')
        self.assertEqual(peer.status('one')['result']['error'], 'recovered_uncertain')
        # The injected old handle is not used for dispatch after lease release.

    def test_missing_legacy_lease_preserves_pending_state(self):
        k = self.kernel()
        k.register(Adapter())
        k.dispatch(self.req())
        owner = k._owner
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE operations SET state='inflight',result=NULL")
            db.execute('PRAGMA user_version=2')
        k._release_lease()
        os.unlink(os.path.join(self.path + '.leases', owner + '.lock'))
        peer = self.kernel()
        self.assertEqual(peer.status('one')['state'], 'inflight')
        self.assertEqual(peer.recover(), 0)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 3)

    def test_unsafe_lease_directory_rejected(self):
        os.mkdir(self.path + '.leases', mode=0o755)
        with self.assertRaisesRegex(ValueError, 'unsafe_lease_directory'):
            self.kernel()

    def test_schema_version_fail_closed(self):
        k = self.kernel()
        self.close(k)
        with sqlite3.connect(self.path) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(ValueError):
            self.kernel()


if __name__ == '__main__':
    unittest.main()
