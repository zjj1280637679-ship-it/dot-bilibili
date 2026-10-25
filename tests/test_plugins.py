import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from email.message import Message

from bili_bridge.contracts import Request
from bili_bridge.fixtures import FIXTURE_BVID, MAX_HTML_BYTES, parse_video_html, read_fixture
from bili_bridge.plugins import FixtureVideoPlugin, PublicVideoPlugin, TransportBlocked, anonymous_html_transport


class PluginTests(unittest.TestCase):
    def request(self, target=FIXTURE_BVID, payload=None):
        return Request("test", "anonymous", "video.metadata", target, payload or {})

    def test_fixture_source_and_part_identity(self):
        result = read_fixture(FIXTURE_BVID, part=2)
        self.assertEqual(result.status, "applied")
        self.assertEqual(result.data["source"], "offline_fixture")
        self.assertEqual(result.data["freshness"]["kind"], "synthetic")
        self.assertEqual(result.data["evidence"]["cid"], 102)
        self.assertFalse(result.data["evidence"]["watched_video"])
        self.assertEqual(result.data["video"]["selected_part"]["page"], 2)

    def test_invalid_targets_never_dispatch(self):
        calls = []
        plugin = PublicVideoPlugin(lambda url: calls.append(url))
        for target in ("http://example.com", FIXTURE_BVID + "?p=2", FIXTURE_BVID + "\n", "BV../etc/passwd", "BV1", 42):
            self.assertEqual(plugin.execute(self.request(target)).status, "rejected")
        self.assertEqual(calls, [])

    def test_invalid_part_and_payload(self):
        for payload in ({"part": True}, {"part": 0}, {"url": "https://example.com"}):
            self.assertEqual(FixtureVideoPlugin().execute(self.request(payload=payload)).status, "rejected")

    def test_challenge_missing_unknown_malformed(self):
        cases = [("<title>安全验证</title>", "blocked", "challenge_or_access_restricted"),
                 ("<html></html>", "unsupported", "initial_state_missing"),
                 ("window.__INITIAL_STATE__={\"other\":1};", "unsupported", "unknown_video_schema"),
                 ("window.__INITIAL_STATE__={bad};", "unsupported", "initial_state_malformed"),
                 ("视频不见了", "blocked", "video_unavailable")]
        for html, status, error in cases:
            result = parse_video_html(html, FIXTURE_BVID)
            self.assertEqual((result.status, result.error), (status, error))

    def test_transport_failure_no_fixture_fallback_or_secret(self):
        def fail(url):
            raise OSError("sensitive session token")
        result = PublicVideoPlugin(fail).execute(self.request())
        self.assertEqual((result.status, result.error), ("blocked", "transport_failed"))
        self.assertEqual(result.data["source"], "public_html")
        self.assertNotIn("sensitive", str(result))

    def test_safe_transport_taxonomy_and_unretrieved_evidence(self):
        import socket
        import ssl
        import urllib.error
        cases = [(socket.gaierror("private hostname"), "transport_dns_failed"),
                 (urllib.error.URLError(socket.gaierror("private hostname")), "transport_dns_failed"),
                 (ssl.SSLError("private certificate"), "transport_tls_failed"),
                 (TimeoutError("private URL"), "transport_timeout"),
                 (ConnectionRefusedError("private address"), "transport_connect_failed"),
                 (PermissionError("private credential path"), "transport_permission_denied")]
        for exception, expected in cases:
            def transport(url):
                raise exception
            result = PublicVideoPlugin(transport).execute(self.request())
            self.assertEqual(result.error, expected)
            self.assertEqual(result.data["freshness"]["kind"], "not_retrieved")
            self.assertEqual(result.data["evidence"]["retrieval"], "not_confirmed")
            self.assertIsNone(result.data["freshness"]["retrieved_at"])
            self.assertNotIn(str(exception), str(result))

    def test_canonical_public_source(self):
        html = (Path(__file__).parents[1] / "bili_bridge/fixture_data/video.html").read_text()
        urls = []
        def transport(url):
            urls.append(url)
            return html
        result = PublicVideoPlugin(transport).execute(self.request())
        self.assertEqual(urls, [f"https://www.bilibili.com/video/{FIXTURE_BVID}/"])
        self.assertEqual(result.data["source"], "public_html")
        self.assertIsNotNone(result.data["freshness"]["retrieved_at"])

    def test_oversize_and_wrong_identity(self):
        self.assertEqual(parse_video_html("x" * (MAX_HTML_BYTES + 1), FIXTURE_BVID).status, "blocked")
        html = 'window.__INITIAL_STATE__=' + json.dumps({"videoData": {"bvid": "BV2xx411c7mD"}})
        self.assertEqual(parse_video_html(html, FIXTURE_BVID).error, "video_identity_mismatch")
        self.assertEqual(read_fixture(FIXTURE_BVID, part=3).error, "part_unavailable")

    def test_transport_rejects_arbitrary_urls_without_network(self):
        with patch("urllib.request.build_opener") as opener:
            for url in ("https://evil.example/", "https://www.bilibili.com/video/BV1xx411c7mD/?x=1", "http://www.bilibili.com/video/BV1xx411c7mD/"):
                with self.assertRaises(TransportBlocked):
                    anonymous_html_transport(url)
            opener.assert_not_called()

    def test_transport_limits_and_request_privacy(self):
        response = MagicMock()
        response.status = 200
        response.headers = Message()
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.read1.side_effect = [b"<html></html>", b""]
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            self.assertEqual(anonymous_html_transport(f"https://www.bilibili.com/video/{FIXTURE_BVID}/"), "<html></html>")
        req = opener.open.call_args.args[0]
        self.assertFalse(req.has_header("Cookie"))
        self.assertFalse(req.has_header("Authorization"))
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 3)

    def test_transport_deadline_size_and_encoding_stop(self):
        def fake_response():
            response = MagicMock()
            response.status = 200
            response.headers = Message()
            response.headers["Content-Type"] = "text/html"
            return response
        response = fake_response()
        response.read1.side_effect = [b"x"]
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener), patch("bili_bridge.plugins.time.monotonic", side_effect=[0, 0, 11]):
            with self.assertRaisesRegex(TransportBlocked, "response_timeout"):
                anonymous_html_transport(f"https://www.bilibili.com/video/{FIXTURE_BVID}/")
        response = fake_response()
        response.read1.return_value = b"x" * 16384
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(TransportBlocked, "response_too_large"):
                anonymous_html_transport(f"https://www.bilibili.com/video/{FIXTURE_BVID}/")
        response = fake_response()
        response.headers["Content-Encoding"] = "gzip"
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(TransportBlocked, "unexpected_content_encoding"):
                anonymous_html_transport(f"https://www.bilibili.com/video/{FIXTURE_BVID}/")
        response.read1.assert_not_called()

    def test_redirect_and_transport_codes(self):
        from bili_bridge.plugins import NoRedirect
        with self.assertRaises(TransportBlocked):
            NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example")
        def fail(url):
            raise TransportBlocked("sensitive arbitrary transport message")
        self.assertEqual(PublicVideoPlugin(fail).execute(self.request()).error, "transport_failed")

    def test_nonfinite_json_is_rejected(self):
        self.assertEqual(parse_video_html('window.__INITIAL_STATE__={"x":NaN}', FIXTURE_BVID).error, "initial_state_malformed")


if __name__ == "__main__":
    unittest.main()


class ModuleRelayTests(unittest.TestCase):
    def request(self, **changes):
        values = dict(operation_id="relay-op", account="anonymous", capability="video.metadata", target=FIXTURE_BVID, payload={})
        values.update(changes)
        return Request(**values)

    def test_pipeline_has_all_module_stations(self):
        result = FixtureVideoPlugin().execute(self.request())
        self.assertEqual(result.status, "applied")
        self.assertEqual(result.data["evidence"]["relay"]["path"], ["metadata.fetch", "metadata.parse", "metadata.normalize"])
        self.assertEqual(result.data["evidence"]["relay"]["correlation_id"], "relay-op")

    def test_module_skip_and_changed_scope_rejected(self):
        from bili_bridge.metadata_pipeline import MetadataPipeline, FetchedDocument
        from bili_bridge.relays import RelayEnvelope
        from bili_bridge.fixtures import read_fixture_html
        pipeline = MetadataPipeline(read_fixture_html, source="offline_fixture")
        request = self.request()
        start = RelayEnvelope.from_request(request, mutating=False)
        with self.assertRaises(ValueError):
            pipeline.parse(FetchedDocument(start, "{}"), request, None)
        fetched = pipeline.fetch(start, request)
        with self.assertRaises(ValueError):
            pipeline.normalize(fetched, request, None)
        with self.assertRaises(ValueError):
            pipeline.parse(fetched, self.request(target="BV2xx411c7mD"), None)

    def test_packets_immutable(self):
        from dataclasses import FrozenInstanceError
        from bili_bridge.metadata_pipeline import FetchedDocument
        from bili_bridge.relays import RelayEnvelope
        packet = FetchedDocument(RelayEnvelope.from_request(self.request(), mutating=False), "html")
        with self.assertRaises(FrozenInstanceError):
            packet.html = "changed"
