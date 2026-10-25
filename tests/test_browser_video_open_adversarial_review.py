"""Independent offline adversarial review; host observations below are synthetic."""
import tempfile
import unittest
from pathlib import Path
from bili_bridge import browser_video_open_contracts as c
from bili_bridge.browser_contracts import BINDING, HostError, digest
from bili_bridge.browser_registry import NAVIGATION_CONTRACTS
from bili_bridge.browser_video_open_plugin import BrowserVideoOpenPlugin
from bili_bridge.contracts import Request, Result
from bili_bridge.kernel import Kernel
from bili_bridge.selection_consumer import JournalSelectionConsumer

BVID = 'BV1234567890'
URL = 'https://www.bilibili.com/video/' + BVID + '/'


def request():
    selection = dict(source_operation_id='source', source_scope_digest='a'*64,
                     source_captured_at=90, query='test',
                     source_url='https://search.bilibili.com/en/all?keyword=test', source_tab_id='7')
    return c.make_request('open', 'open', BVID, URL, '7', 100, 100, selection)


def preflight(req):
    out = {key: req[key] for key in ('protocol_version', 'schema_version', 'operation',
                                     'operation_id', 'correlation_id', 'scope_digest')}
    out.update(observed_source_url=req['source_url'], tab_id='7', checked_at=110,
               context='confirmed', selected_bvid=BVID, selected_url=URL, selection_visible=True)
    return out


class VideoOpenIndependentReviewTests(unittest.TestCase):
    def test_exact_preflight_rejects_type_and_context_confusion(self):
        req = request()
        c.validate_preflight(preflight(req), req, 120)
        for key, values in {
            'selection_visible': [1, 'true', [], None, False],
            'schema_version': [True, 1.0, '1'],
            'protocol_version': [True, 1.0, '1'],
            'tab_id': [7, True, '8'],
            'checked_at': [True, '110', 99, 121, float('nan')],
            'selected_bvid': ['BV1234567891', None],
            'selected_url': [URL+'?p=2', URL.replace(BVID, 'BV1234567891')],
            'observed_source_url': [req['source_url'].replace('test', 'other'),
                                    req['source_url'].replace('/en/all', '/all'),
                                    req['source_url']+'&keyword=other'],
            'context': ['changed', 'unavailable', True],
            'operation_id': ['source'],
            'scope_digest': ['b'*64],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(HostError):
                    out = preflight(req); out[key] = value
                    c.validate_preflight(out, req, 120)

    def test_request_lifetime_cannot_outlive_source(self):
        for key, value in [('source_captured_at', True), ('source_captured_at', 101),
                           ('source_captured_at', -501), ('expires_at', 691),
                           ('source_tab_id', 7), ('bvid', True),
                           ('source_url', 'https://www.bilibili.com/'),
                           ('query', 'different'), ('effect', 'write'), ('schema_version', True)]:
            with self.subTest(key=key, value=value), self.assertRaises(HostError):
                req = request(); req[key] = value; req['scope_digest'] = digest(req)
                c.validate_request(req, 120)
        req = request()
        for extra in ('selector', 'script', 'items', 'cookie'):
            with self.subTest(extra=extra), self.assertRaises(HostError):
                altered = dict(req, **{extra: 'untrusted'})
                altered['scope_digest'] = digest(altered)
                c.validate_request(altered, 120)

    def test_navigation_registry_is_closed_and_immutable(self):
        self.assertEqual(set(NAVIGATION_CONTRACTS), {'browser.public_search', 'browser.video.open'})
        with self.assertRaises(TypeError):
            NAVIGATION_CONTRACTS['browser.video.read'] = c

    def test_malformed_historic_source_blocks_before_host(self):
        class Source:
            name = 'synthetic-legacy-source'
            capabilities = frozenset({'browser.search_results.read'})
            mutating = frozenset()
            def execute(self, _):
                return Result('applied', self.data)
        class NeverHost:
            calls = 0
            def open_video(self, *_):
                self.calls += 1
                raise AssertionError('malformed provenance reached host')
        valid = dict(source='browser_dom', status='observed', captured_at=90,
                     scope_digest='a'*64, query='test',
                     observed_url='https://search.bilibili.com/en/all?keyword=test',
                     tab_id='7', items=[dict(bvid=BVID, url=URL)])
        mutations = [('items', None), ('items', [None]), ('items', [{}]),
                     ('captured_at', True), ('tab_id', 7), ('query', None)]
        cases = [dict(valid, **{key: value}) for key, value in mutations]
        cases.extend({key: value for key, value in valid.items() if key != missing}
                     for missing in valid)
        for index, data in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                kernel = Kernel(Path(directory)/'journal.db', min_interval=0,
                                hourly_budget=100, clock=lambda: 100)
                source, host = Source(), NeverHost()
                source.data = data
                try:
                    kernel.register(source); kernel.register(BrowserVideoOpenPlugin(host, JournalSelectionConsumer(kernel.consume_browser_selection)))
                    kernel.dispatch(Request('source', BINDING, 'browser.search_results.read', 'test', {}))
                    result = kernel.dispatch(Request('open', BINDING, c.OPERATION, BVID,
                                                     {'source_operation_id': 'source'}))
                    self.assertEqual(result.status, 'blocked', result)
                    self.assertEqual(result.error, 'selection_source_invalid', result)
                    self.assertEqual(host.calls, 0)
                    self.assertEqual(kernel._db.execute('SELECT COUNT(*) FROM browser_selections').fetchone()[0], 0)
                finally:
                    kernel.close()

    def test_consumed_source_survives_block_unknown_and_kernel_reopen(self):
        class Source:
            name = 'synthetic-source'
            capabilities = frozenset({'browser.search_results.read'})
            mutating = frozenset()
            def execute(self, _):
                return Result('applied', dict(source='browser_dom', status='observed',
                    captured_at=90, scope_digest='a'*64, query='test',
                    observed_url='https://search.bilibili.com/en/all?keyword=test', tab_id='7',
                    items=[dict(bvid=BVID, url=URL)]))
        class Host:
            calls = 0
            def __init__(self, error): self.error = error
            def open_video(self, *_):
                self.calls += 1
                raise HostError(self.error)
        for error in ('preflight_target_or_context', 'host_outcome_unknown'):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'journal.db'
                host = Host(error)
                kernel = Kernel(path, min_interval=0, hourly_budget=100, clock=lambda: 100)
                kernel.register(Source()); kernel.register(BrowserVideoOpenPlugin(host, JournalSelectionConsumer(kernel.consume_browser_selection)))
                source = Request('source', BINDING, 'browser.search_results.read', 'test', {})
                self.assertEqual(kernel.dispatch(source).status, 'applied')
                opening = Request('open', BINDING, c.OPERATION, BVID, {'source_operation_id': 'source'})
                first = kernel.dispatch(opening)
                self.assertEqual(first.status, 'unknown' if error == 'host_outcome_unknown' else 'blocked')
                self.assertEqual(kernel.dispatch(opening), first)
                self.assertEqual(host.calls, 1)
                kernel.close()
                kernel = Kernel(path, min_interval=0, hourly_budget=100, clock=lambda: 100)
                try:
                    kernel.register(BrowserVideoOpenPlugin(host, JournalSelectionConsumer(kernel.consume_browser_selection)))
                    again = kernel.dispatch(Request('open-again', BINDING, c.OPERATION, BVID,
                                                    {'source_operation_id': 'source'}))
                    self.assertEqual(again.error, 'selection_already_consumed')
                    self.assertEqual(host.calls, 1)
                finally:
                    kernel.close()
