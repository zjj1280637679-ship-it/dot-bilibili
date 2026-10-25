"""Narrow authority and preservation checks, not a sandbox/refinement proof."""
import unittest
from bili_bridge.browser_video_open_plugin import BrowserVideoOpenPlugin
from bili_bridge.contracts import Request
from bili_bridge.selection_consumer import JournalSelectionConsumer


class SelectionConsumerTests(unittest.TestCase):
    def test_adapter_calls_once_preserves_request_and_scalar_result(self):
        request = Request('open', 'dot-browser', 'browser.video.open', 'BV1234567890', {'source_operation_id': 'source'})
        source = {'source_operation_id': 'source', 'source_scope_digest': 'a'*64,
                  'source_captured_at': 90.0, 'query': 'test',
                  'source_url': 'https://search.bilibili.com/all?keyword=test', 'source_tab_id': '7'}
        calls = []
        port = JournalSelectionConsumer(lambda value: calls.append(value) or source)
        result = port.consume_browser_selection(request)
        self.assertEqual(calls, [request])
        self.assertEqual(dict(result), source)
        with self.assertRaises(TypeError):
            result['query'] = 'different'
        source['query'] = 'later mutation'
        self.assertEqual(result['query'], 'test')
        for name in ('dispatch', 'issue_grant', 'recover', 'status', '_db', 'kernel'):
            self.assertFalse(hasattr(port, name), name)

    def test_exception_identity_preserved_without_retry(self):
        error = ValueError('selection_already_consumed')
        calls = []
        def fail(request):
            calls.append(request)
            raise error
        with self.assertRaises(ValueError) as caught:
            JournalSelectionConsumer(fail).consume_browser_selection('request')
        self.assertIs(caught.exception, error)
        self.assertEqual(calls, ['request'])

    def test_business_plugin_needs_only_one_method_fake_port(self):
        from bili_bridge.browser_contracts import BINDING
        from bili_bridge.browser_video_open_contracts import OPERATION
        calls = []
        class OneMethodPort:
            __slots__ = ()
            def consume_browser_selection(self, request):
                calls.append(request)
                return {'source_operation_id': 'source'}
        class Host:
            def open_video(self, operation, correlation, target, selection):
                self.selection = selection
                return {'status': 'observed', 'error': None}
        host, port = Host(), OneMethodPort()
        plugin = BrowserVideoOpenPlugin(host, port)
        request = Request('open', BINDING, OPERATION, 'BV1234567890', {'source_operation_id': 'source'})
        result = plugin.execute(request)
        self.assertEqual(result.status, 'applied')
        self.assertEqual(calls, [request])
        self.assertEqual(host.selection, {'source_operation_id': 'source'})
        self.assertFalse(hasattr(plugin, 'kernel'))
        self.assertFalse(hasattr(plugin.selection_consumer, 'dispatch'))
