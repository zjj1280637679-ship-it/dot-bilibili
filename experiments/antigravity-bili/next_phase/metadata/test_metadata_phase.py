"""
next_phase/metadata/test_metadata_phase.py - Unit Test Suite for Versioned Metadata & Narrow Transport

Verifies:
1. Versioned typed result mapping (SCHEMA_VERSION = "metadata-observation/v2-candidate").
2. Defensive observation envelope (parsed, partial, wrong_target withholds data, upstream_error preserves code).
3. Auth assessment is strictly 'not_assessed' and live_verified is False.
4. NarrowViewHttpTransport mock tests:
   - 200 JSON valid body
   - 302 redirect blocked (mapped to unknown, zero redirect follow)
   - 504 timeout / URLError (zero retries)
   - Oversized body (>512KB)
   - Non-JSON Content-Type
5. Default disconnected/paused zero-call behavior.
6. Secret and transport-override key rejection (cookie, token, sessdata, bili_jct, headers, url, authorization).
7. Durable SQLite operation ledger (idempotent replay, conflict on differing target, crashed run never replays).
8. Socket guard ensuring zero live network calls.
"""

from __future__ import annotations

import io
import json
import socket
import sqlite3
import sys
import unittest
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure package imports resolve
CURRENT_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURRENT_DIR.parent.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from next_phase.metadata.versioned_adapter import (
    FIELDS,
    FORBIDDEN_ARG_KEYS,
    MAX_BODY_BYTES,
    NarrowViewHttpTransport,
    NoRedirectHandler,
    Provenance,
    ReadRequest,
    RedirectBlockedError,
    SCHEMA_VERSION,
    TransportReply,
    compute_semantic_fingerprint,
    execute_metadata_read,
    init_metadata_ledger,
    make_versioned_observation,
    parse_metadata,
    valid_bvid,
)


# ============================================================================
# Test Fixtures & Socket Guard
# ============================================================================

SAMPLE_BVID = "BV17x411w7KC"
SAMPLE_OTHER_BVID = "BV1xx411c7X8"

class BlockedSocketError(RuntimeError):
    """Raised when an unauthorized real network socket attempt is detected."""
    pass


@contextmanager
def socket_guard():
    """Context manager replacing socket.socket with a trap to ensure 100% offline tests."""
    orig_socket = socket.socket
    def blocked_socket(*args, **kwargs):
        raise BlockedSocketError("Live network socket creation blocked in offline tests!")
    socket.socket = blocked_socket
    try:
        yield
    finally:
        socket.socket = orig_socket


class MockHTTPResponse:
    """Mock HTTP response object implementing read(), close(), and context manager."""
    def __init__(self, body: bytes, status: int = 200, headers: Optional[Dict[str, str]] = None):
        self._body = io.BytesIO(body)
        self.status = status
        self.code = status
        self.headers = headers or {"Content-Type": "application/json; charset=utf-8"}

    def read(self, amt: int = -1) -> bytes:
        return self._body.read(amt)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class MockOpener:
    """Mock urllib opener director with call tracking."""
    def __init__(self, response_factory=None):
        self.call_count = 0
        self.last_request = None
        self.response_factory = response_factory

    def open(self, request, timeout=10.0):
        self.call_count += 1
        self.last_request = request
        if callable(self.response_factory):
            return self.response_factory(request)
        return MockHTTPResponse(b'{"code":0,"data":{"bvid":"BV17x411w7KC","title":"Fixture Title","aid":1,"duration":100,"pubdate":1600000000}}')


# ============================================================================
# Test Suite
# ============================================================================

class TestMetadataPhase(unittest.TestCase):
    def setUp(self):
        # Enable defensive socket guard during all tests
        self._socket_guard_ctx = socket_guard()
        self._socket_guard_ctx.__enter__()

    def tearDown(self):
        self._socket_guard_ctx.__exit__(None, None, None)

    # ------------------------------------------------------------------------
    # 1. Versioned Typed Result Mapping Tests
    # ------------------------------------------------------------------------

    def test_versioned_observation_complete_parsed(self):
        """Complete projection fields parsed with SCHEMA_VERSION = 'metadata-observation/v2-candidate'."""
        body = json.dumps({
            "code": 0,
            "data": {
                "bvid": SAMPLE_BVID,
                "title": "Clean Test Video",
                "aid": 12345,
                "duration": 300,
                "pubdate": 1690000000,
            }
        }).encode("utf-8")

        parsed = parse_metadata(body, SAMPLE_BVID, provenance=Provenance.SUPPLIED, transport_calls=1)
        obs = make_versioned_observation(parsed, transport_status="response", http_status=200)

        self.assertEqual(obs["schema"], SCHEMA_VERSION)
        self.assertEqual(obs["observation_status"], "parsed")
        self.assertEqual(obs["status"], "parsed")
        self.assertEqual(obs["data"]["bvid"], SAMPLE_BVID)
        self.assertEqual(obs["data"]["title"], "Clean Test Video")
        self.assertEqual(obs["data"]["aid"], 12345)
        self.assertTrue(obs["coverage"]["projection_complete"])
        self.assertFalse(obs["coverage"]["full_api_response"])
        self.assertEqual(obs["coverage"]["projection_fields"], list(FIELDS))
        self.assertEqual(obs["auth_assessment"], "not_assessed")
        self.assertFalse(obs["evidence"]["live_verified"])
        self.assertEqual(obs["evidence"]["transport_callback_entries"], 1)
        self.assertEqual(obs["diagnostic"]["transport_layer_status"], "response")
        self.assertEqual(obs["diagnostic"]["http_status"], 200)

    def test_versioned_observation_partial(self):
        """Partial metadata retains present/missing field_states and projection_complete=False."""
        body = json.dumps({
            "code": 0,
            "data": {
                "bvid": SAMPLE_BVID,
                "title": "Partial Video Title",
                # aid, duration, pubdate omitted
            }
        }).encode("utf-8")

        parsed = parse_metadata(body, SAMPLE_BVID, provenance=Provenance.SUPPLIED, transport_calls=1)
        obs = make_versioned_observation(parsed)

        self.assertEqual(obs["observation_status"], "partial")
        self.assertEqual(obs["data"], {"bvid": SAMPLE_BVID, "title": "Partial Video Title"})
        self.assertFalse(obs["coverage"]["projection_complete"])
        self.assertEqual(obs["field_states"]["title"], "present")
        self.assertEqual(obs["field_states"]["aid"], "missing")
        self.assertEqual(obs["field_states"]["duration"], "missing")
        self.assertEqual(obs["field_states"]["pubdate"], "missing")
        self.assertEqual(obs["auth_assessment"], "not_assessed")

    def test_versioned_observation_wrong_target_withholds_all_data(self):
        """wrong_target must strictly withhold all response data (data={})."""
        body = json.dumps({
            "code": 0,
            "data": {
                "bvid": SAMPLE_OTHER_BVID,
                "title": "Mismatched Video Title",
                "aid": 99999,
            }
        }).encode("utf-8")

        parsed = parse_metadata(body, SAMPLE_BVID, provenance=Provenance.SUPPLIED, transport_calls=1)
        obs = make_versioned_observation(parsed)

        self.assertEqual(obs["observation_status"], "wrong_target")
        self.assertEqual(obs["data"], {})  # Strict withholding invariant
        self.assertFalse(obs["coverage"]["projection_complete"])
        self.assertEqual(obs["diagnostic"]["code"], "response_identity_mismatch")
        self.assertEqual(obs["auth_assessment"], "not_assessed")

    def test_versioned_observation_upstream_error_retains_code_no_auth_diagnosis(self):
        """upstream_error preserves numeric code without guessing auth/login/not-found."""
        body = json.dumps({
            "code": -404,
            "message": "啥都木有",
        }).encode("utf-8")

        parsed = parse_metadata(body, SAMPLE_BVID, provenance=Provenance.SUPPLIED, transport_calls=1)
        obs = make_versioned_observation(parsed)

        self.assertEqual(obs["observation_status"], "upstream_error")
        self.assertEqual(obs["diagnostic"]["upstream_code"], -404)
        self.assertEqual(obs["data"], {})
        # Must NOT invent login or permission diagnosis
        self.assertEqual(obs["auth_assessment"], "not_assessed")

    def test_versioned_observation_defensive_deep_copy(self):
        """Mutating the observation envelope does not mutate future observations."""
        body = json.dumps({
            "code": 0,
            "data": {"bvid": SAMPLE_BVID, "title": "Immutable Title", "aid": 1, "duration": 1, "pubdate": 1}
        }).encode("utf-8")
        parsed = parse_metadata(body, SAMPLE_BVID, provenance=Provenance.SUPPLIED)
        obs1 = make_versioned_observation(parsed)
        obs1["data"]["title"] = "Mutated Title"
        obs2 = make_versioned_observation(parsed)
        self.assertEqual(obs2["data"]["title"], "Immutable Title")

    # ------------------------------------------------------------------------
    # 2. Narrow HTTP Transport Mock Tests
    # ------------------------------------------------------------------------

    def test_narrow_http_transport_default_disconnected_and_paused(self):
        """Default transport is paused & disconnected, making zero network/opener calls."""
        opener = MockOpener()
        transport = NarrowViewHttpTransport(network_enabled=False, paused=True, opener=opener)
        reply = transport(ReadRequest(SAMPLE_BVID))

        self.assertEqual(reply.disposition, "blocked")
        self.assertEqual(opener.call_count, 0)  # Zero calls!

    def test_narrow_http_transport_unpaused_but_network_disabled(self):
        """Unpaused transport with network_enabled=False still returns blocked with zero calls."""
        opener = MockOpener()
        transport = NarrowViewHttpTransport(network_enabled=False, paused=False, opener=opener)
        reply = transport(ReadRequest(SAMPLE_BVID))

        self.assertEqual(reply.disposition, "blocked")
        self.assertEqual(opener.call_count, 0)

    def test_narrow_http_transport_mock_opener_200_json(self):
        """Mock opener with valid 200 JSON returns response disposition."""
        opener = MockOpener()
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)
        reply = transport(ReadRequest(SAMPLE_BVID))

        self.assertEqual(reply.disposition, "response")
        self.assertEqual(reply.http_status, 200)
        self.assertIn(SAMPLE_BVID.encode("utf-8"), reply.body)
        self.assertEqual(opener.call_count, 1)
        # Check pinned URL
        self.assertEqual(
            opener.last_request.full_url,
            f"https://api.bilibili.com/x/web-interface/view?bvid={SAMPLE_BVID}"
        )

    def test_narrow_http_transport_mock_opener_302_redirect_blocked(self):
        """HTTP 302 redirect is caught by NoRedirectHandler and mapped to unknown (zero redirect follow)."""
        def redirect_factory(req):
            headers = {"Location": "https://www.bilibili.com/video/BV_other"}
            raise urllib.error.HTTPError(req.full_url, 302, "Found Redirect", headers, io.BytesIO(b""))

        opener = MockOpener(response_factory=redirect_factory)
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)
        reply = transport(ReadRequest(SAMPLE_BVID))

        self.assertEqual(reply.disposition, "unknown")
        self.assertEqual(reply.http_status, 302)
        self.assertEqual(opener.call_count, 1)  # Only 1 call, zero redirect following!

    def test_narrow_http_transport_mock_opener_504_timeout_zero_retry(self):
        """HTTP 504 Gateway Timeout maps to unknown with ZERO retries."""
        def timeout_factory(req):
            raise urllib.error.HTTPError(req.full_url, 504, "Gateway Timeout", {}, io.BytesIO(b""))

        opener = MockOpener(response_factory=timeout_factory)
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)
        reply = transport(ReadRequest(SAMPLE_BVID))

        self.assertEqual(reply.disposition, "unknown")
        self.assertEqual(reply.http_status, 504)
        self.assertEqual(opener.call_count, 1)  # Strict zero retries!

    def test_narrow_http_transport_mock_opener_oversized_body(self):
        """Responses exceeding MAX_BODY_BYTES (512KB) map to unknown."""
        oversized = b'{"code":0,"data":' + (b"A" * (MAX_BODY_BYTES + 10)) + b"}"
        opener = MockOpener(response_factory=lambda req: MockHTTPResponse(oversized, 200))
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)
        reply = transport(ReadRequest(SAMPLE_BVID))

        self.assertEqual(reply.disposition, "unknown")

    def test_narrow_http_transport_mock_opener_non_json_content_type(self):
        """Non-JSON Content-Type (e.g. text/html) maps to unknown."""
        html_resp = MockHTTPResponse(
            b"<html><body>Block</body></html>",
            200,
            headers={"Content-Type": "text/html; charset=utf-8"}
        )
        opener = MockOpener(response_factory=lambda req: html_resp)
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)
        reply = transport(ReadRequest(SAMPLE_BVID))

        self.assertEqual(reply.disposition, "unknown")

    # ------------------------------------------------------------------------
    # 3. Gated Tool Entrypoint & Security Tests
    # ------------------------------------------------------------------------

    def test_execute_metadata_read_rejects_secret_keys(self):
        """Tool strictly rejects any secret or transport-override keys."""
        mem_db = sqlite3.connect(":memory:")
        init_metadata_ledger(mem_db, initial_paused=False)

        forbidden_samples = [
            {"cookie": "SESSDATA=xyz"},
            {"cookies": {"SESSDATA": "xyz"}},
            {"token": "secret_token"},
            {"sessdata": "secret_session"},
            {"bili_jct": "csrf_val"},
            {"headers": {"User-Agent": "custom"}},
            {"url": "https://evil.com/api"},
            {"authorization": "Bearer xyz"},
        ]

        ref_map = {"ref-123": SAMPLE_BVID}

        for forbidden_kwarg in forbidden_samples:
            with self.subTest(kwarg=list(forbidden_kwarg.keys())[0]):
                res = execute_metadata_read(
                    mem_db,
                    reference_id="ref-123",
                    expected_bvid=SAMPLE_BVID,
                    operation_id="op-secret-test",
                    ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
                    **forbidden_kwarg
                )
                self.assertEqual(res["status"], "rejected")
                self.assertEqual(res["diagnostic"]["code"], "secret_or_transport_override_forbidden")

        mem_db.close()

    def test_execute_metadata_read_stale_or_wrong_reference(self):
        """Mismatch between reference_id and expected_bvid returns blocked."""
        mem_db = sqlite3.connect(":memory:")
        init_metadata_ledger(mem_db, initial_paused=False)

        ref_map = {"ref-123": SAMPLE_BVID}

        # Reference unknown
        res1 = execute_metadata_read(
            mem_db,
            reference_id="ref-unknown",
            expected_bvid=SAMPLE_BVID,
            operation_id="op-ref-test",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
        )
        self.assertEqual(res1["status"], "blocked")
        self.assertEqual(res1["diagnostic"]["code"], "stale_or_wrong_target_reference")

        # Target bvid mismatch
        res2 = execute_metadata_read(
            mem_db,
            reference_id="ref-123",
            expected_bvid=SAMPLE_OTHER_BVID,
            operation_id="op-ref-test-2",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
        )
        self.assertEqual(res2["status"], "blocked")
        self.assertEqual(res2["diagnostic"]["code"], "stale_or_wrong_target_reference")

        mem_db.close()

    def test_execute_metadata_read_paused_gate(self):
        """When ledger controls has paused=1, execution is blocked before transport call."""
        mem_db = sqlite3.connect(":memory:")
        init_metadata_ledger(mem_db, initial_paused=True)  # Paused!

        ref_map = {"ref-123": SAMPLE_BVID}
        opener = MockOpener()
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)

        res = execute_metadata_read(
            mem_db,
            reference_id="ref-123",
            expected_bvid=SAMPLE_BVID,
            operation_id="op-pause-test",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
            transport=transport,
        )

        self.assertEqual(res["status"], "blocked")
        self.assertEqual(res["diagnostic"]["code"], "account_operations_paused")
        self.assertEqual(opener.call_count, 0)  # Zero transport calls

        mem_db.close()

    # ------------------------------------------------------------------------
    # 4. Durable SQLite Ledger Idempotency & Conflict Tests
    # ------------------------------------------------------------------------

    def test_execute_metadata_read_idempotent_replay(self):
        """Second call with same operation_id returns recorded snapshot with zero additional calls."""
        mem_db = sqlite3.connect(":memory:")
        init_metadata_ledger(mem_db, initial_paused=False)

        ref_map = {"ref-123": SAMPLE_BVID}
        opener = MockOpener()
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)

        # First call
        res1 = execute_metadata_read(
            mem_db,
            reference_id="ref-123",
            expected_bvid=SAMPLE_BVID,
            operation_id="op-idemp-1",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
            transport=transport,
        )
        self.assertEqual(res1["status"], "parsed")
        self.assertEqual(opener.call_count, 1)

        # Second call with exact same parameters
        res2 = execute_metadata_read(
            mem_db,
            reference_id="ref-123",
            expected_bvid=SAMPLE_BVID,
            operation_id="op-idemp-1",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
            transport=transport,
        )
        self.assertEqual(res2["status"], "parsed")
        self.assertEqual(res2["data"]["title"], res1["data"]["title"])
        self.assertEqual(opener.call_count, 1)  # STILL 1: Zero additional network calls!

        mem_db.close()

    def test_execute_metadata_read_conflict_differing_target(self):
        """Reusing operation_id with differing expected_bvid raises operation_id_conflict."""
        mem_db = sqlite3.connect(":memory:")
        init_metadata_ledger(mem_db, initial_paused=False)

        ref_map = {
            "ref-123": SAMPLE_BVID,
            "ref-456": SAMPLE_OTHER_BVID,
        }
        opener = MockOpener()
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)

        # Call with SAMPLE_BVID
        res1 = execute_metadata_read(
            mem_db,
            reference_id="ref-123",
            expected_bvid=SAMPLE_BVID,
            operation_id="op-conflict-1",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
            transport=transport,
        )
        self.assertEqual(res1["status"], "parsed")

        # Reuse same operation_id with SAMPLE_OTHER_BVID
        res2 = execute_metadata_read(
            mem_db,
            reference_id="ref-456",
            expected_bvid=SAMPLE_OTHER_BVID,
            operation_id="op-conflict-1",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
            transport=transport,
        )
        self.assertEqual(res2["status"], "rejected")
        self.assertEqual(res2["diagnostic"]["code"], "operation_id_conflict")

        mem_db.close()

    def test_execute_metadata_read_crash_no_replay(self):
        """Incomplete or crashed operation in ledger returns unknown and NEVER replays."""
        mem_db = sqlite3.connect(":memory:")
        init_metadata_ledger(mem_db, initial_paused=False)

        ref_map = {"ref-123": SAMPLE_BVID}
        fp = compute_semantic_fingerprint("web_view_v1", "video.metadata.read", SAMPLE_BVID)

        # Manually stage a crashed reservation (result IS NULL)
        with mem_db:
            mem_db.execute(
                "INSERT INTO metadata_operations (id, fingerprint, owner, result) VALUES (?, ?, ?, NULL)",
                ("op-crashed-1", fp, "crashed_run_id")
            )

        opener = MockOpener()
        transport = NarrowViewHttpTransport(network_enabled=True, paused=False, opener=opener)

        res = execute_metadata_read(
            mem_db,
            reference_id="ref-123",
            expected_bvid=SAMPLE_BVID,
            operation_id="op-crashed-1",
            ref_map=ref_map,
            authorization_check=lambda: True,  # explicit synthetic read authorization
            transport=transport,
        )

        self.assertEqual(res["status"], "unknown")
        self.assertEqual(res["diagnostic"]["code"], "previous_run_incomplete")
        self.assertEqual(opener.call_count, 0)  # Invariant: NEVER replays on crash/incomplete!

        mem_db.close()

    # ------------------------------------------------------------------------
    # 5. Socket Guard Verification
    # ------------------------------------------------------------------------

    def test_socket_guard_blocks_network(self):
        """Verifies that the socket guard actively blocks real socket creations."""
        with self.assertRaises(BlockedSocketError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)


if __name__ == "__main__":
    unittest.main()
