"""Local CLI and bounded read-only JSONL protocol; no approval issuer."""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import uuid

from .browser_host import BINDING, OPERATION, FileBrowserHost, HostError
from .browser_plugin import BrowserReadPlugin
from .browser_video_plugin import BrowserVideoReadPlugin
from .browser_video_open_plugin import BrowserVideoOpenPlugin
from .browser_video_open_contracts import OPERATION as VIDEO_OPEN_OPERATION
from .browser_comments_plugin import BrowserCommentsReadPlugin
from .browser_comments_contracts import OPERATION as COMMENTS_OPERATION
from .browser_public_search_plugin import BrowserPublicSearchPlugin
from .browser_public_search_contracts import OPERATION as PUBLIC_SEARCH_OPERATION, source_url as public_source_url
from .browser_video_contracts import OPERATION as VIDEO_OPERATION
from .contracts import Request, Result
from .fixtures import FIXTURE_BVID, UNSUPPORTED, evidence
from .kernel import Kernel
from .plugins import FixtureVideoPlugin, PublicVideoPlugin

MAX_LINE_CHARS = 65536


def manifest(live=False):
    return {"protocol": "bili-bridge-jsonl-v1", "mode": "live_anonymous" if live else "offline_fixture",
            "implemented": [{"capability": "video.metadata", "read_only": True, "parts": True,
                             "transport": "anonymous_shell_https" if live else "offline_fixture"},
                            {"capability": "browser.search_results.read", "read_only": True,
                             "transport": "dot_host_browser_dom", "command": "browser-read",
                             "requires": "explicit target and a trusted dot host claiming and executing the request"},
                            {"capability": VIDEO_OPERATION, "read_only": True,
                             "transport": "dot_host_browser_dom", "command": "browser-video-read",
                             "requires": "already-open exact public video URL and tab; visible metadata only"},
                            {"capability": COMMENTS_OPERATION, "read_only": True,
                             "transport": "dot_host_browser_dom", "command": "browser-comments-read",
                             "requires": "already-open public video; max 3 viewport-intersecting threads; no stable IDs or reply targeting"},
                            {"capability": VIDEO_OPEN_OPERATION, "read_only": True,
                             "transport": "dot_host_browser_dom", "command": "browser-video-open",
                             "requires": "fresh applied search operation in shared journal/spool; one exact result, single-use navigation"},
                            {"capability": PUBLIC_SEARCH_OPERATION, "read_only": True,
                             "transport": "dot_host_browser_dom", "command": "browser-public-search",
                             "requires": "confirmed source tab/context; one fixed public search navigation and visible capture"}],
            "disabled": [item for item in UNSUPPORTED if item not in ("search", "comments")],
            "planned_unsupported": ["writes"],
            "fixture_bvid": FIXTURE_BVID,
            "live_requires": "explicit --live; anonymous shell metadata only; platform permission remains a deployment prerequisite",
            "browser_requires": "explicit browser-read, browser-video-read, browser-comments-read, browser-video-open or browser-public-search; existing user-confirmed cloud browser session; dot runtime executes fresh bounded DOM read",
            "serve_capabilities": ["video.metadata"],
            "automatic_retries": 0, "grant_issuer_exposed": False,
            "warning": "No video watching, private reads or account writes. Public search is one bounded query navigation. Browser relay is not a standalone driver or browser extension."}


def bounded_timeout(value):
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be finite seconds") from None
    if not math.isfinite(seconds) or not 0 < seconds <= 600:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 600 seconds")
    return seconds


def result_object(result, live=False):
    expected_source = "public_html" if live else "offline_fixture"
    if result.data.get("source", expected_source) != expected_source:
        result = Result("rejected", {}, "operation_provenance_mismatch")
    value = dataclasses.asdict(result)
    # Kernel-level guards also retain explicit adapter provenance and limitations.
    for key, item in evidence(None, "public_html" if live else "offline_fixture").items():
        value["data"].setdefault(key, item)
    return value


def emit(value, stream):
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


def decode_request(value):
    if not isinstance(value, dict) or set(value) - {"operation_id", "account", "capability", "target", "payload"}:
        raise ValueError("invalid_request_fields")
    if not all(isinstance(value.get(key), str) and value[key] for key in ("operation_id", "capability", "target")):
        raise ValueError("missing_request_fields")
    if not isinstance(value.get("payload", {}), dict) or value.get("account", "anonymous") != "anonymous":
        raise ValueError("invalid_account_or_payload")
    json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return Request(value["operation_id"], "anonymous", value["capability"], value["target"], value.get("payload", {}))


def serve(kernel, *, live=False, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    while True:
        line = stdin.readline(MAX_LINE_CHARS + 1)
        if not line:
            return
        if len(line) > MAX_LINE_CHARS:
            emit(result_object(Result("rejected", {}, "line_too_large"), live), stdout)
            return  # Never reinterpret fragments of an oversized message.
        try:
            value = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_json")))
            request = decode_request(value)
        except (ValueError, RecursionError):
            emit(result_object(Result("rejected", {}, "invalid_request"), live), stdout)
            continue
        emit(result_object(kernel.dispatch(request), live), stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline-first read-only Bilibili metadata feasibility bridge")
    parser.add_argument("--db", default="bili-bridge.sqlite3", help="local durable operation journal")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("bvid")
    inspect.add_argument("--part", type=int, default=1)
    inspect.add_argument("--operation-id", default=None)
    inspect.add_argument("--live", action="store_true", help="one anonymous HTTPS metadata read; never use cookies")
    server = commands.add_parser("serve")
    server.add_argument("--live", action="store_true", help="anonymous read-only mode, persistent local request budget")
    browser = commands.add_parser("browser-read", help="ask the trusted dot host to read an already-open public results tab")
    browser.add_argument("--query", required=True)
    browser.add_argument("--url", required=True, help="exact HTTPS Bilibili search URL observed by the host")
    browser.add_argument("--tab", required=True, help="exact host-observed tab ID; never guess")
    browser.add_argument("--spool", required=True, help="explicit private local host exchange directory")
    browser.add_argument("--timeout", required=True, type=bounded_timeout)
    browser.add_argument("--operation-id", default=None)
    video = commands.add_parser("browser-video-read", help="read visible metadata from an already-open public video tab")
    video.add_argument("--bvid", required=True)
    video.add_argument("--url", required=True)
    video.add_argument("--tab", required=True)
    video.add_argument("--spool", required=True)
    video.add_argument("--timeout", required=True, type=bounded_timeout)
    video.add_argument("--operation-id", default=None)
    comments = commands.add_parser("browser-comments-read", help="read at most 3 currently visible public comment threads; no navigation or reply targeting")
    comments.add_argument("--bvid", required=True)
    comments.add_argument("--url", required=True)
    comments.add_argument("--tab", required=True)
    comments.add_argument("--limit", type=int, choices=(1, 2, 3), default=3)
    comments.add_argument("--spool", required=True)
    comments.add_argument("--timeout", required=True, type=bounded_timeout)
    comments.add_argument("--operation-id", default=None)
    public = commands.add_parser("browser-public-search", help="one fixed public query navigation and visible capture through the trusted dot host")
    public.add_argument("--query", required=True)
    public.add_argument("--source-url", required=True)
    public.add_argument("--tab", required=True)
    public.add_argument("--spool", required=True)
    public.add_argument("--timeout", required=True, type=bounded_timeout)
    public.add_argument("--operation-id", default=None)
    opening = commands.add_parser("browser-video-open", help="open one exact BVID from a fresh applied search snapshot; no generic URL")
    opening.add_argument("--source-operation-id", required=True)
    opening.add_argument("--bvid", required=True)
    opening.add_argument("--spool", required=True)
    opening.add_argument("--timeout", required=True, type=bounded_timeout)
    opening.add_argument("--operation-id", default=None)
    status = commands.add_parser("status")
    status.add_argument("operation_id")
    args = parser.parse_args(argv)
    if args.command == "capabilities":
        emit(manifest(), sys.stdout)
        return 0
    kernel = Kernel(args.db)
    host = None
    try:
        live = getattr(args, "live", False)
        if args.command in ("browser-read", "browser-video-read", "browser-public-search", "browser-comments-read", "browser-video-open"):
            operation_id = args.operation_id or uuid.uuid4().hex
            try:
                host = FileBrowserHost(args.spool, timeout=args.timeout)
                is_open = args.command == "browser-video-open"
                is_comments = args.command == "browser-comments-read"
                is_video = args.command == "browser-video-read"
                is_public = args.command == "browser-public-search"
                kernel.register(BrowserVideoOpenPlugin(host, kernel) if is_open else BrowserCommentsReadPlugin(host) if is_comments else BrowserPublicSearchPlugin(host) if is_public else BrowserVideoReadPlugin(host) if is_video else BrowserReadPlugin(host))
                payload = {"source_operation_id": args.source_operation_id} if is_open else {"source_url": public_source_url(args.source_url), "source_tab_id": args.tab} if is_public else {"expected_url": args.url, "expected_tab_id": args.tab}
                if is_comments:
                    payload["limit"] = args.limit
                request = Request(operation_id, BINDING, VIDEO_OPEN_OPERATION if is_open else COMMENTS_OPERATION if is_comments else PUBLIC_SEARCH_OPERATION if is_public else VIDEO_OPERATION if is_video else OPERATION,
                                  args.bvid if is_video or is_comments or is_open else args.query, payload)
                result = kernel.dispatch(request)
                if result.status == "applied" and result.data.get("source") != "browser_dom":
                    result = Result("rejected", {}, "operation_provenance_mismatch")
            except (HostError, OSError):
                result = Result("blocked", {}, "host_setup_failed")
            value = dataclasses.asdict(result)
            value["data"].setdefault("coverage", "visible_subset")
            value["data"].setdefault("complete", False)
            value["operation_id"] = operation_id
            emit(value, sys.stdout)
            return 0 if result.status == "applied" else 1
        kernel.register(PublicVideoPlugin() if live else FixtureVideoPlugin())
        if args.command == "status":
            record = kernel.status(args.operation_id)
            emit({"operation_id": args.operation_id, "record": record}, sys.stdout)
        elif args.command == "serve":
            serve(kernel, live=live)
        else:
            request = Request(args.operation_id or uuid.uuid4().hex, "anonymous", "video.metadata", args.bvid, {"part": args.part})
            value = result_object(kernel.dispatch(request), live)
            value["operation_id"] = request.operation_id
            emit(value, sys.stdout)
            return 0 if value["status"] == "applied" else 1
    finally:
        if host is not None:
            host.close()
        kernel.close()
    return 0
