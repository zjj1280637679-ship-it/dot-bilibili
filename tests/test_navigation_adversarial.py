"""Independent public-search audit; local files only, no browser or network."""
import fcntl
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from bili_bridge import browser_contracts as legacy
from bili_bridge import browser_public_search_contracts as nav
from bili_bridge import browser_registry as registry
from bili_bridge.browser_host import FileBrowserHost, HostError
from bili_bridge.browser_public_search_plugin import BrowserPublicSearchPlugin
from bili_bridge.contracts import Request
from bili_bridge.kernel import Kernel

SOURCE = 'https://search.bilibili.com/en/all?keyword=old'


def request():
    return nav.make_request('audit-nav', 'audit-c', 'hello world', SOURCE, '17', 100., 100.)


def preflight(req):
    out = {k: req[k] for k in ('protocol_version', 'schema_version', 'operation', 'operation_id', 'correlation_id', 'scope_digest')}
    return dict(out, observed_source_url=req['source_url'], tab_id=req['source_tab_id'], checked_at=120., context='confirmed')


def receipt(req):
    out = {k: req[k] for k in ('protocol_version', 'schema_version', 'operation', 'operation_id', 'correlation_id', 'scope_digest')}
    return dict(out, query=req['query'], tab_id=req['source_tab_id'], observed_url=req['destination_url'], captured_at=140., source='browser_dom', status='observed', phase='capture', context='confirmed', items=[], error=None)


class NavigationSchemaAdversarialTests(unittest.TestCase):
    def test_preflight_scope_source_and_context_substitution(self):
        req = request()
        for field, bad in [('operation', legacy.OPERATION), ('operation_id', 'other'), ('correlation_id', 'other'), ('scope_digest', '0'*64), ('protocol_version', True), ('schema_version', True), ('tab_id', '18'), ('observed_source_url', SOURCE.replace('old', 'other')), ('context', 'changed'), ('context', 'unavailable'), ('context', True)]:
            with self.subTest(field=field, bad=bad):
                out = preflight(req); out[field] = bad
                with self.assertRaises(HostError): nav.validate_preflight(out, req, 130.)

    def test_preflight_and_capture_staleness(self):
        req = request()
        for bad in (99., 131., True, float('nan'), float('inf'), '120'):
            with self.subTest(bad=bad):
                out = preflight(req); out['checked_at'] = bad
                with self.assertRaises(HostError): nav.validate_preflight(out, req, 130.)
                out = receipt(req); out['captured_at'] = bad
                with self.assertRaises(HostError): registry.validate_receipt(out, req, 130.)
        with self.assertRaises(HostError): registry.validate_receipt(receipt(req), req, 200.)

    def test_tracking_canonicalizes_but_semantics_never_change(self):
        req = request()
        out = receipt(req)
        out['observed_url'] = 'https://search.bilibili.com/all?keyword=hello%20world&from_source=web_search&spm_id_from=333.1'
        self.assertEqual(registry.validate_receipt(out, req, 150.)['observed_url'], req['destination_url'])
        pf = preflight(req); pf['observed_source_url'] += '&search_source=5'
        self.assertEqual(nav.validate_preflight(pf, req, 130.)['observed_source_url'], SOURCE)
        for suffix in ('&page=2', '&order=click', '&keyword=hello+world', '&from_source=', '&from_source=https%3A%2F%2Fevil.test', '#fragment'):
            with self.subTest(suffix=suffix):
                out = receipt(req); out['observed_url'] += suffix
                with self.assertRaises(HostError): registry.validate_receipt(out, req, 150.)
        for url in ('https://search.bilibili.com/en/video?keyword=hello+world', 'https://search.bilibili.com/en/all?keyword=other'):
            out = receipt(req); out['observed_url'] = url
            with self.assertRaises(HostError): registry.validate_receipt(out, req, 150.)

    def test_closed_schema_and_no_arbitrary_destination(self):
        for field in ('script', 'selector', 'command', 'executor', 'cookies', 'token', 'url'):
            for original, validator in ((request(), lambda v: registry.validate_request(v, 130.)), (preflight(request()), lambda v: nav.validate_preflight(v, request(), 130.)), (receipt(request()), lambda v: registry.validate_receipt(v, request(), 150.))):
                with self.subTest(field=field, validator=validator):
                    original[field] = 'arbitrary'
                    with self.assertRaises(HostError): validator(original)
        for url in ('javascript:alert(1)', 'file:///tmp/test', 'https://evil.test/', 'https://search.bilibili.com@evil.test/', 'https://search.bilibili.com:443/en/all?keyword=hello+world'):
            req = request(); req['destination_url'] = url; req['scope_digest'] = legacy.digest(req)
            with self.assertRaises(HostError): registry.validate_request(req, 130.)
            with self.assertRaises(HostError): nav.source_url(url)
        # Executable-looking input remains encoded data in a fixed origin/path.
        query = '$(touch /tmp/never); javascript:alert(1)&keyword=other'
        req = nav.make_request('inert', 'inert', query, SOURCE, '17', 100., 100.)
        self.assertEqual(nav.search_url(req['destination_url'], query), req['destination_url'])
        self.assertNotIn('&keyword=', req['destination_url'])

    def test_encoded_destination_bound_checked_before_issue(self):
        with self.assertRaises(HostError):
            nav.make_request('oversize', 'c', '😀'*200, SOURCE, '17', 100., 100.)

    def test_cross_contract_substitution(self):
        req = request(); out = receipt(req)
        for op in (legacy.OPERATION, 'browser.video_page.read', 'browser.navigate', '__import__'):
            forged = dict(req, operation=op); forged['scope_digest'] = legacy.digest(forged)
            with self.assertRaises(HostError): registry.validate_request(forged, 150.)
            forged = dict(out, operation=op)
            with self.assertRaises(HostError): registry.validate_receipt(forged, req, 150.)
        read_req = registry.make_request(legacy.OPERATION, 'audit-nav', 'audit-c', 'hello world', req['destination_url'], '17', 100., 100.)
        with self.assertRaises(HostError): registry.validate_receipt(out, read_req, 150.)


class NavigationCheckpointAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = FileBrowserHost(Path(self.temp.name)/'spool', timeout=1, cooldown=1)
        self.owner = os.open(self.host.root/'owner.lock', os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.owner, fcntl.LOCK_EX)
        self.req = request()
        self.state = dict(active=True, claimed=False, submitted=False, issued_at=100., expires_at=200., digest=self.req['scope_digest'], operation_id=self.req['operation_id'], cooldown=1)
        with self.host._locked():
            self.host._write('state.json', self.state); self.host._write('request.json', self.req)
        self.clock = patch('bili_bridge.browser_host.time.time', return_value=110.)
        self.now = self.clock.start()

    def tearDown(self):
        self.clock.stop(); os.close(self.owner); self.host.close(); self.temp.cleanup()

    def claim(self):
        self.host.claim(); self.now.return_value = 130.

    def test_checkpoint_order_single_use_durable_and_fresh_capture(self):
        with self.assertRaisesRegex(HostError, 'navigation_not_expected'): self.host.begin_navigation(preflight(self.req))
        self.claim()
        with self.assertRaisesRegex(HostError, 'capture_before_navigation'): self.host.submit(dict(receipt(self.req), captured_at=125.))
        result = self.host.begin_navigation(preflight(self.req))
        self.assertEqual(result, dict(destination_url=self.req['destination_url'], tab_id='17'))
        # A distinct handle reads the persisted checkpoint, not process memory.
        peer = FileBrowserHost(self.host.root)
        try:
            self.assertEqual(peer._read('state.json')['navigation_started_at'], 130.)
            with self.assertRaisesRegex(HostError, 'navigation_not_expected'): peer.begin_navigation(preflight(self.req))
        finally: peer.close()
        with self.assertRaisesRegex(HostError, 'capture_before_navigation'): self.host.submit(dict(receipt(self.req), captured_at=129.))
        self.now.return_value = 150.
        blocked = dict(receipt(self.req), phase='preflight', status='blocked', error='context_changed', observed_url=None)
        with self.assertRaisesRegex(HostError, 'preflight_after_navigation'): self.host.submit(blocked)
        self.host.submit(receipt(self.req))
        with self.assertRaisesRegex(HostError, 'receipt_not_expected'): self.host.submit(receipt(self.req))

    def test_rejected_preflight_never_consumes_checkpoint(self):
        self.claim()
        for mutation in ({'checked_at': 109.}, {'context': 'changed'}, {'tab_id': 'wrong'}, {'observed_source_url': SOURCE.replace('old', 'new')}):
            with self.assertRaises(HostError): self.host.begin_navigation(dict(preflight(self.req), **mutation))
            self.assertNotIn('navigation_started_at', self.host._read('state.json'))
        self.host.begin_navigation(preflight(self.req))

    def test_begin_rechecks_integrity_after_claim(self):
        self.claim()
        changed = dict(self.req, query='changed', destination_url=nav.destination('changed'))
        changed['scope_digest'] = legacy.digest(changed)
        with self.host._locked(): self.host._write('request.json', changed)
        with self.assertRaisesRegex(HostError, 'request_integrity'): self.host.begin_navigation(preflight(changed))
        self.assertNotIn('navigation_started_at', self.host._read('state.json'))

    def test_checkpoint_write_error_never_returns_navigation_authority(self):
        self.claim()
        with patch.object(self.host, '_write', side_effect=OSError('synthetic fsync failure')):
            with self.assertRaises(OSError): self.host.begin_navigation(preflight(self.req))
        self.assertNotIn('navigation_started_at', self.host._read('state.json'))

    def test_legacy_read_contract_cannot_begin_navigation(self):
        req = registry.make_request(legacy.OPERATION, 'read', 'read', 'old', SOURCE, '17', 100., 100.)
        state = dict(self.state, digest=req['scope_digest'], operation_id='read')
        with self.host._locked():
            self.host._write('request.json', req); self.host._write('state.json', state)
        self.claim()
        with self.assertRaisesRegex(HostError, 'navigation_not_expected'): self.host.begin_navigation(preflight(self.req))

    def test_preflight_block_finishes_without_navigation(self):
        self.claim()
        blocked = dict(receipt(self.req), phase='preflight', status='blocked', context='changed', error='context_changed', observed_url=None, captured_at=125.)
        self.host.submit(blocked)
        with self.assertRaisesRegex(HostError, 'navigation_not_expected'): self.host.begin_navigation(preflight(self.req))

    def test_expired_checkpoint_cannot_resume(self):
        self.claim(); self.host.begin_navigation(preflight(self.req)); self.now.return_value = 200.
        with self.assertRaises(HostError): self.host.begin_navigation(preflight(self.req))
        self.assertEqual(self.host._read('state.json')['status'], 'unknown')
        with self.assertRaises(HostError): self.host.submit(receipt(self.req))


class NavigationUnknownOutcomeTests(unittest.TestCase):
    def test_timeout_after_begin_is_unknown_and_kernel_never_replays(self):
        with tempfile.TemporaryDirectory() as root:
            host = FileBrowserHost(Path(root)/'spool', timeout=.5, cooldown=1)
            kernel = Kernel(Path(root)/'journal.sqlite', min_interval=0)
            plugin = BrowserPublicSearchPlugin(host); kernel.register(plugin)
            req = Request('unknown-nav', nav.BINDING, nav.OPERATION, 'hello', {'source_url': SOURCE, 'source_tab_id': '17'})
            results = []
            worker = threading.Thread(target=lambda: results.append(kernel.dispatch(req)))
            try:
                worker.start(); deadline = time.monotonic()+2
                while not (host.root/'request.json').exists() and time.monotonic()<deadline: time.sleep(.005)
                claimed = host.claim()
                host.begin_navigation(dict(preflight(claimed), checked_at=time.time()))
                worker.join(2); self.assertFalse(worker.is_alive())
                self.assertEqual(results[0].status, 'unknown')
                self.assertEqual(host._read('state.json')['status'], 'unknown')
                with patch.object(host, 'public_search', side_effect=AssertionError('replayed')):
                    self.assertEqual(kernel.dispatch(req).status, 'unknown')
                with self.assertRaises(HostError): host.begin_navigation(dict(preflight(claimed), checked_at=time.time()))
                with self.assertRaises(HostError): host.submit(dict(receipt(claimed), captured_at=time.time()))
            finally:
                worker.join(2); kernel.close(); host.close()
