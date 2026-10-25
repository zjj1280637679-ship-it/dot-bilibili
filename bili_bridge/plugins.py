"""First-party anonymous public HTML adapter. No alternate transport or retries."""
from __future__ import annotations

import time
import socket
import ssl
import urllib.error
import urllib.request

from .contracts import Result
from .fixtures import MAX_HTML_BYTES, outcome, read_fixture_html, valid_bvid
from .metadata_pipeline import MetadataPipeline


class TransportBlocked(Exception):
    """Safe public code only; never propagate transport exception details."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportBlocked("redirect_blocked")


def anonymous_html_transport(url: str) -> str:
    prefix = "https://www.bilibili.com/video/"
    if not url.startswith(prefix) or not url.endswith("/") or not valid_bvid(url[len(prefix):-1]):
        raise TransportBlocked("invalid_transport_url")
    # No environment proxy credentials, cookies, auth handler, redirects, or browser session.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": "BiliBridge/0.1 anonymous-read-only", "Accept": "text/html", "Accept-Encoding": "identity"})
    try:
        with opener.open(req, timeout=3) as response:
            if response.status != 200:
                raise TransportBlocked("http_status_blocked")
            if response.headers.get_content_type() != "text/html":
                raise TransportBlocked("unexpected_content_type")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise TransportBlocked("unexpected_content_encoding")
            # read1 returns after one underlying read rather than waiting for a
            # whole large buffer; check an overall body deadline between reads.
            deadline = time.monotonic() + 10
            chunks, size = [], 0
            while True:
                if time.monotonic() >= deadline:
                    raise TransportBlocked("response_timeout")
                chunk = response.read1(min(16384, MAX_HTML_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_HTML_BYTES:
                    raise TransportBlocked("response_too_large")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="strict")
    except urllib.error.HTTPError as exc:
        code = "http_throttled" if exc.code == 429 else "http_access_denied" if exc.code in (401, 403, 412) else "video_unavailable" if exc.code == 404 else "http_error"
        raise TransportBlocked(code) from None


def transport_error_code(exc):
    """Classify local failures without disclosing raw exception text or URLs."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        return "transport_dns_failed"
    if isinstance(reason, ssl.SSLError):
        return "transport_tls_failed"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "transport_timeout"
    if isinstance(reason, (ConnectionError, ConnectionRefusedError)):
        return "transport_connect_failed"
    if isinstance(reason, PermissionError):
        return "transport_permission_denied"
    return "transport_failed"


def request_error(request, source):
    if request.capability != "video.metadata":
        return outcome("unsupported", request.target, source, "capability_unsupported")
    if request.account != "anonymous":
        return outcome("rejected", request.target, source, "anonymous_account_required")
    if not valid_bvid(request.target) or not isinstance(request.payload, dict) or set(request.payload) - {"part"}:
        return outcome("rejected", request.target, source, "invalid_target_or_payload")
    if type(request.payload.get("part", 1)) is not int or request.payload.get("part", 1) < 1:
        return outcome("rejected", request.target, source, "invalid_part")
    return None


class PublicVideoPlugin:
    name = "public-video-html"
    capabilities = frozenset({"video.metadata"})
    mutating = frozenset()

    def __init__(self, transport=None):
        self.transport = transport if transport is not None else anonymous_html_transport

    def execute(self, request):
        error = request_error(request, "public_html")
        if error is not None:
            return error
        try:
            return MetadataPipeline(lambda target: self.transport(f"https://www.bilibili.com/video/{target}/"), source="public_html").execute(request)
        except TransportBlocked as exc:
            code = str(exc)
            allowed = {"redirect_blocked", "invalid_transport_url", "http_status_blocked", "unexpected_content_type", "unexpected_content_encoding", "response_too_large", "response_timeout", "http_throttled", "http_access_denied", "video_unavailable", "http_error"}
            return outcome("blocked", request.target, "public_html", code if code in allowed else "transport_failed")
        except Exception as exc:
            return outcome("blocked", request.target, "public_html", transport_error_code(exc))


class FixtureVideoPlugin:
    name = "synthetic-video-fixture"
    capabilities = frozenset({"video.metadata"})
    mutating = frozenset()

    def execute(self, request):
        error = request_error(request, "offline_fixture")
        return error if error is not None else MetadataPipeline(read_fixture_html, source="offline_fixture").execute(request)
