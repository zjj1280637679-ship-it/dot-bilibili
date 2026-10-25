"""Offline CLI tests only; mock receipts are not live browser evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from bili_bridge.browser_host import FileBrowserHost, HostError
from bili_bridge.cli import main, manifest


QUERY = 'Synthetic Search 哔哩哔哩'
URL = 'https://search.bilibili.com/en/all?keyword=Synthetic%20Search%20%E5%93%94%E5%93%A9%E5%93%94%E5%93%A9&from_source=web_search&spm_id_from=333.1007&search_source=5'


class BrowserCliTests(unittest.TestCase):
    def args(self, directory, timeout='2'):
        return ['--db', str(Path(directory) / 'journal.db'), 'browser-read',
                '--query', QUERY, '--url', URL, '--tab', '6',
                '--spool', str(Path(directory) / 'spool'), '--timeout', timeout,
                '--operation-id', 'offline-cli-test']

    def test_full_command_mock_host_and_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(directory)
            host = FileBrowserHost(Path(directory) / 'spool')
            errors = []
            def mock_host():
                try:
                    deadline = time.monotonic() + 2
                    while True:
                        try:
                            req = host.claim()
                            break
                        except HostError as exc:
                            if str(exc) != 'no_active_request' or time.monotonic() >= deadline:
                                raise
                            time.sleep(.01)
                    receipt = {key: req[key] for key in ('protocol_version', 'operation_id', 'correlation_id', 'scope_digest')}
                    receipt.update(observed_url=req['expected_url'], tab_id=req['expected_tab_id'],
                                   query=req['query'], captured_at=time.time(), source='browser_dom',
                                   status='observed', items=[{'title': 'OFFLINE MOCK ONLY',
                                   'url': 'https://www.bilibili.com/en/video/BV1xx411c7mD',
                                   'bvid': 'BV1xx411c7mD', 'uploader': 'Synthetic',
                                   'duration': '', 'displayed_counts': []}], error=None)
                    host.submit(receipt)
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=mock_host)
            worker.start()
            try:
                with patch('bili_bridge.plugins.anonymous_html_transport', side_effect=AssertionError('network forbidden')), contextlib.redirect_stdout(io.StringIO()) as output:
                    code = main(args)
                worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                value = json.loads(output.getvalue())
                self.assertEqual(code, 0, value)
                self.assertEqual(value['status'], 'applied')
                self.assertEqual(value['data']['source'], 'browser_dom')
                self.assertEqual(value['data']['query'], QUERY)
                self.assertEqual(value['data']['items'][0]['url'], 'https://www.bilibili.com/video/BV1xx411c7mD/')
                self.assertIn('browser.host.read', value['data']['relay_trace'])
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(args[:2] + ['status', 'offline-cli-test']), 0)
                record = json.loads(output.getvalue())['record']
                self.assertEqual(record['state'], 'applied')
                self.assertEqual(record['capability'], 'browser.search_results.read')
                # Durable replay never asks the host to execute again.
                with patch.object(FileBrowserHost, 'read', side_effect=AssertionError('must not replay')), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(args), 0)
                self.assertEqual(json.loads(output.getvalue())['data']['captured_at'], value['data']['captured_at'])
            finally:
                worker.join(3)
                host.close()

    def test_no_host_fails_without_fixture_fallback(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(self.args(directory, '.02')), 1)
        value = json.loads(output.getvalue())
        self.assertNotEqual(value['status'], 'applied')
        self.assertEqual(value['data']['source'], 'browser_dom')
        self.assertEqual(value['data']['items'], [])

    def test_missing_or_invalid_timeout_rejected_before_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.args(directory)
            for value in ('0', '-1', 'nan', 'inf', '601'):
                modified = list(args)
                modified[modified.index('--timeout') + 1] = value
                with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    main(modified)
                self.assertEqual(caught.exception.code, 2)
            self.assertFalse((Path(directory) / 'journal.db').exists())
            for flag in ('--query', '--url', '--tab', '--spool', '--timeout'):
                modified = list(args)
                offset = modified.index(flag)
                del modified[offset:offset + 2]
                with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    main(modified)

    def test_unsafe_spool_has_safe_error(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'spool').mkdir(mode=0o755)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(self.args(directory)), 1)
            value = json.loads(output.getvalue())
            self.assertEqual(value['error'], 'host_setup_failed')
            self.assertNotIn(directory, output.getvalue())

    def test_serve_does_not_expose_browser_or_grants(self):
        request = {'operation_id': 'forbidden', 'account': 'anonymous',
                   'capability': 'browser.search_results.read', 'target': QUERY,
                   'payload': {'expected_url': URL, 'expected_tab_id': '6'}}
        with tempfile.TemporaryDirectory() as directory, patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')), contextlib.redirect_stdout(io.StringIO()) as output:
            main(['--db', str(Path(directory) / 'journal.db'), 'serve'])
        self.assertEqual(json.loads(output.getvalue())['status'], 'unsupported')
        value = manifest()
        self.assertEqual(value['serve_capabilities'], ['video.metadata'])
        self.assertNotIn('browser.public_search', value['planned_unsupported'])
        self.assertIn('browser.public_search', [item['capability'] for item in value['implemented']])
        self.assertIn('writes', value['planned_unsupported'])
        self.assertFalse(value['grant_issuer_exposed'])


if __name__ == '__main__':
    unittest.main()
