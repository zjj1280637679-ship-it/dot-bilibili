"""
Cross-Module & MCP Protocol Acceptance Test Suite (MCP Version 2025-06-18)
Location: next_phase/acceptance/test_cross_module_mcp.py

Verifies:
1. MCP Protocol framing compliance for 2025-06-18:
   - initialize / notifications/initialized lifecycle gating.
   - tools/list schema parity.
   - tools/call: optional arguments, _meta parsing, rejection of unknown top-level keys.
   - Strict JSON-RPC parse and error handling.
2. End-to-end synthetic workflow:
   - Session pause gate (zero backend calls when paused).
   - Strict reference resolution (syntactic BVID and canonical URL).
   - Metadata reading outcomes: completed, not_found, wrong_target/stale, upstream exceptions.
   - Zero platform calls and zero replay in operation.status.
3. Server restart simulation:
   - Persistence of pause state across process lifecycles.
   - Invalidation of old process-local reference_ids (zero backend calls).
   - Durable status cache preservation across restarts.
   - Interrupted/crash reservation handling (reports unknown, zero replay).
4. Non-poisoning invariant:
   - Blocked, unsupported, rejected, or unknown operations do not corrupt state or block subsequent reads.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from minimal_slice_vnext.server import Protocol, SCHEMAS, VERSION
from minimal_slice_vnext.service import Service, fixture_metadata, resolve_bvid, envelope

FIXTURE_BVID = "BV17x411w7KC"
SYNTHETIC_BVID_2 = "BV1xx411c7mD"


class CrossModuleMcpProtocolTests(unittest.TestCase):
    """MCP JSON-RPC 2.0 protocol framing and lifecycle verification."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "protocol_test.sqlite3"
        self.backend_calls = []

        def tracking_backend(bvid):
            self.backend_calls.append(bvid)
            return fixture_metadata(bvid)

        self.service = Service(self.db_path, backend=tracking_backend, initial_paused=False)
        self.protocol = Protocol(self.service)

    def tearDown(self):
        self.tmp.cleanup()

    def _rpc(self, method, params=None, req_id=1):
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        return self.protocol.receive(json.dumps(payload))

    def _notify(self, method, params=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        return self.protocol.receive(json.dumps(payload))

    def _handshake(self):
        init_res = self._rpc("initialize", {"protocolVersion": "2025-06-18"}, req_id="init-1")
        self.assertIn("result", init_res)
        self.assertIsNone(self._notify("notifications/initialized"))

    def test_lifecycle_and_readiness_gate(self):
        """Calling tools before notifications/initialized must be rejected with -32000."""
        # Pre-initialize call rejected
        res = self._rpc("tools/list", req_id=1)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32000)

        # Initialize
        init = self._rpc("initialize", {"protocolVersion": "2025-06-18"}, req_id=2)
        self.assertIn("result", init)
        self.assertEqual(init["result"]["protocolVersion"], VERSION)
        self.assertEqual(init["result"]["serverInfo"]["name"], "bili-offline-fixture-slice")

        # Duplicate initialize rejected with -32600
        dup = self._rpc("initialize", {"protocolVersion": "2025-06-18"}, req_id=3)
        self.assertIn("error", dup)
        self.assertEqual(dup["error"]["code"], -32600)

        # Still not ready before notification
        res_before_notify = self._rpc("tools/list", req_id=4)
        self.assertIn("error", res_before_notify)
        self.assertEqual(res_before_notify["error"]["code"], -32000)

        # Send notification
        notify_res = self._notify("notifications/initialized")
        self.assertIsNone(notify_res)
        self.assertTrue(self.protocol.ready)

        # Now ready
        tools_res = self._rpc("tools/list", req_id=5)
        self.assertIn("result", tools_res)
        tool_names = [t["name"] for t in tools_res["result"]["tools"]]
        self.assertEqual(set(tool_names), {"capabilities.list", "video.reference.resolve", "video.metadata.read", "operation.status"})

    def test_tools_call_optional_arguments(self):
        """Optional arguments field defaults to empty dictionary."""
        self._handshake()
        res = self._rpc("tools/call", {"name": "capabilities.list"}, req_id=10)
        self.assertIn("result", res)
        content = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(content["status"], "completed")
        self.assertEqual(content["data"]["tools"], list(SCHEMAS.keys()))

    def test_tools_call_meta_handling_and_no_authority(self):
        """_meta object is accepted per MCP 2025-06-18 but not passed as tool arguments or authority."""
        self._handshake()
        call_params = {
            "name": "video.reference.resolve",
            "arguments": {"value": FIXTURE_BVID},
            "_meta": {"progressToken": "token-123", "authorized": True}
        }
        res = self._rpc("tools/call", call_params, req_id=11)
        self.assertIn("result", res)
        content = json.loads(res["result"]["content"][0]["text"])
        self.assertEqual(content["status"], "completed")
        self.assertEqual(content["data"]["bvid"], FIXTURE_BVID)

    def test_tools_call_rejects_unknown_top_level_params(self):
        """Unknown top-level parameters in tools/call are rejected with -32602 with zero dispatch."""
        self._handshake()
        # Injected 'approved' or 'admin' top-level keys must fail validation
        call_params = {
            "name": "capabilities.list",
            "approved": True
        }
        res = self._rpc("tools/call", call_params, req_id=12)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32602)
        self.assertEqual(self.backend_calls, [])

    def test_tools_call_type_validation_zero_calls(self):
        """Invalid types for arguments, _meta, or name fail pre-flight."""
        self._handshake()
        invalid_cases = [
            {"name": "capabilities.list", "arguments": "string_not_dict"},
            {"name": "capabilities.list", "arguments": [1, 2, 3]},
            {"name": "capabilities.list", "_meta": "meta_not_dict"},
            {"name": 12345, "arguments": {}},
            {"arguments": {}},  # Missing name
        ]
        for case in invalid_cases:
            res = self._rpc("tools/call", case)
            self.assertIn("error", res)
            self.assertEqual(res["error"]["code"], -32602)
        self.assertEqual(self.backend_calls, [])

    def test_strict_json_rpc_parse_errors(self):
        """Strict JSON parser rejects malformed JSON, duplicate keys, and non-standard literals."""
        bad_frames = [
            '{"jsonrpc": "2.0", "method": "ping", "dup": 1, "dup": 2}',  # duplicate key
            '{"jsonrpc": "2.0", "method": "ping", "val": NaN}',          # NaN forbidden
            '{"jsonrpc": "2.0", "method": "ping", "val": Infinity}',     # Infinity forbidden
            'not-json-content',
            '{"jsonrpc": "2.0", "id": ' + 'x' * 200 + ', "method": "ping"}', # oversized ID
        ]
        for bad in bad_frames:
            res = self.protocol.receive(bad)
            self.assertIn("error", res)
            self.assertIn(res["error"]["code"], (-32700, -32600))


class CrossModuleSyntheticWorkflowTests(unittest.TestCase):
    """End-to-end synthetic workflow tests across pause gate, reference resolver, metadata read, and status."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "workflow_test.sqlite3"
        self.backend_calls = []

        def tracking_backend(bvid):
            self.backend_calls.append(bvid)
            return fixture_metadata(bvid)

        self.service = Service(self.db_path, backend=tracking_backend, initial_paused=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pause_gate_blocks_metadata_with_zero_backend_calls(self):
        """When paused=True, metadata read must return blocked and dispatch zero backend calls."""
        self.service.set_pause(True)
        self.assertTrue(self.service.paused())

        # Resolve reference (pure syntax, permitted while paused)
        resolve_out = self.service.resolve(FIXTURE_BVID)
        self.assertEqual(resolve_out["status"], "completed")
        ref_id = resolve_out["data"]["reference_id"]

        # Attempt metadata read while paused
        meta_out = self.service.metadata(
            reference_id=ref_id,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-paused-01",
            backend="fixture"
        )
        self.assertEqual(meta_out["status"], "blocked")
        self.assertEqual(meta_out["error"], "account_operations_paused")
        self.assertEqual(self.backend_calls, [])

        # operation.status for blocked attempt
        status_out = self.service.status("op-paused-01")
        self.assertEqual(status_out["status"], "not_found")  # Never reserved or inserted

    def test_reference_resolution_strictness(self):
        """Strict reference validation: valid BVID and canonical URL succeed, invalid rejected."""
        # Valid BVID
        r1 = self.service.resolve(FIXTURE_BVID)
        self.assertEqual(r1["status"], "completed")
        self.assertEqual(r1["data"]["bvid"], FIXTURE_BVID)

        # Valid Canonical HTTPS URL
        r2 = self.service.resolve(f"https://www.bilibili.com/video/{FIXTURE_BVID}/")
        self.assertEqual(r2["status"], "completed")
        self.assertEqual(r2["data"]["bvid"], FIXTURE_BVID)

        # Invalid URLs
        invalid_inputs = [
            f"http://www.bilibili.com/video/{FIXTURE_BVID}/",          # Insecure HTTP
            f"https://b23.tv/{FIXTURE_BVID}",                          # Shortlink rejected
            f"https://www.bilibili.com/video/{FIXTURE_BVID}/?spm_id=1",# Query parameter rejected
            f"https://www.bilibili.com/video/{FIXTURE_BVID}/#reply",   # Fragment rejected
            f"https://attacker.com/video/{FIXTURE_BVID}/",             # Wrong domain
            "BVinvalidchar!",
            "",
            "   ",
        ]
        for bad in invalid_inputs:
            with self.assertRaises(ValueError):
                resolve_bvid(bad)
            call_res = self.service.call("video.reference.resolve", {"value": bad})
            self.assertEqual(call_res["status"], "rejected")

    def test_metadata_reading_completed_and_cached(self):
        """Successful metadata read dispatches backend once, subsequent reads with same ID return cached result."""
        res_ref = self.service.resolve(FIXTURE_BVID)
        ref_id = res_ref["data"]["reference_id"]

        # First dispatch
        res1 = self.service.metadata(
            reference_id=ref_id,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-meta-001",
            backend="fixture"
        )
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(res1["data"]["bvid"], FIXTURE_BVID)
        self.assertEqual(self.backend_calls, [FIXTURE_BVID])

        # Second dispatch with identical operation_id and target -> cached result, zero additional backend calls
        res2 = self.service.metadata(
            reference_id=ref_id,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-meta-001",
            backend="fixture"
        )
        self.assertEqual(res1, res2)
        self.assertEqual(len(self.backend_calls), 1)

        # operation.status returns exact completed result with zero backend calls
        res_stat = self.service.status("op-meta-001")
        self.assertEqual(res_stat["status"], "completed")
        self.assertEqual(res_stat["data"]["title"], "Synthetic fixture video")
        self.assertEqual(len(self.backend_calls), 1)

    def test_metadata_not_found_fixture(self):
        """Syntactically valid BVID without fixture data returns status not_found."""
        res_ref = self.service.resolve(SYNTHETIC_BVID_2)
        ref_id = res_ref["data"]["reference_id"]

        res = self.service.metadata(
            reference_id=ref_id,
            expected_bvid=SYNTHETIC_BVID_2,
            operation_id="op-meta-notfound",
            backend="fixture"
        )
        self.assertEqual(res["status"], "not_found")
        self.assertEqual(self.backend_calls, [SYNTHETIC_BVID_2])

    def test_metadata_stale_or_wrong_target_reference(self):
        """Mismatched expected_bvid vs resolved reference is blocked with zero backend calls."""
        res_ref = self.service.resolve(FIXTURE_BVID)
        ref_id = res_ref["data"]["reference_id"]

        # Passing SYNTHETIC_BVID_2 with ref_id created for FIXTURE_BVID
        res = self.service.metadata(
            reference_id=ref_id,
            expected_bvid=SYNTHETIC_BVID_2,
            operation_id="op-meta-mismatch",
            backend="fixture"
        )
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(res["error"], "stale_or_wrong_target_reference")
        self.assertEqual(self.backend_calls, [])

    def test_upstream_backend_exception_safely_quarantined(self):
        """Backend exceptions produce status 'unknown', never echo secret tokens, and do not replay."""
        exception_calls = []

        def exploding_backend(bvid):
            exception_calls.append(bvid)
            raise RuntimeError("CRITICAL_INTERNAL_SECRET_KEY_MUST_NOT_LEAK")

        exploding_service = Service(self.db_path, backend=exploding_backend, initial_paused=False)
        ref_res = exploding_service.resolve(FIXTURE_BVID)
        ref_id = ref_res["data"]["reference_id"]

        res = exploding_service.metadata(
            reference_id=ref_id,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-exploding-01",
            backend="fixture"
        )
        self.assertEqual(res["status"], "unknown")
        self.assertEqual(res["error"], "backend_outcome_unknown")

        # Secret must not appear in result or status JSON
        self.assertNotIn("SECRET", json.dumps(res))
        status_res = exploding_service.status("op-exploding-01")
        self.assertNotIn("SECRET", json.dumps(status_res))

        # Re-attempt with same ID must not replay the exploding backend
        res_repeat = exploding_service.metadata(
            reference_id=ref_id,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-exploding-01",
            backend="fixture"
        )
        self.assertEqual(res_repeat["status"], "unknown")
        self.assertEqual(len(exception_calls), 1)


class ServerRestartSimulationTests(unittest.TestCase):
    """Verifies behavior across simulated server restarts using the same SQLite database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "restart_test.sqlite3"
        self.calls_srv1 = []
        self.calls_srv2 = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_restart_preserves_pause_state(self):
        """A paused database remains paused across process restart, even if --fixture-ready flag is attempted."""
        # Server 1 sets pause
        srv1 = Service(self.db_path, initial_paused=True)
        self.assertTrue(srv1.paused())

        # Server 2 starts with initial_paused=False (simulating launch flag)
        # Invariable rule: existing SQLite control table is NOT overwritten
        srv2 = Service(self.db_path, initial_paused=False)
        self.assertTrue(srv2.paused())

    def test_restart_invalidates_process_local_reference_ids(self):
        """Process-local reference_ids generated in run 1 become stale in run 2 (zero backend calls)."""
        # Server 1 creates reference and performs read
        srv1 = Service(self.db_path, backend=lambda b: self.calls_srv1.append(b) or fixture_metadata(b), initial_paused=False)
        ref_res = srv1.resolve(FIXTURE_BVID)
        ref_id_run1 = ref_res["data"]["reference_id"]

        meta_res1 = srv1.metadata(
            reference_id=ref_id_run1,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-run1-01",
            backend="fixture"
        )
        self.assertEqual(meta_res1["status"], "completed")
        self.assertEqual(len(self.calls_srv1), 1)

        # Server 2 restarts on same DB
        srv2 = Service(self.db_path, backend=lambda b: self.calls_srv2.append(b) or fixture_metadata(b), initial_paused=False)

        # Using ref_id_run1 on srv2 must be blocked as stale
        meta_res2 = srv2.metadata(
            reference_id=ref_id_run1,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-run2-02",
            backend="fixture"
        )
        self.assertEqual(meta_res2["status"], "blocked")
        self.assertEqual(meta_res2["error"], "stale_or_wrong_target_reference")
        self.assertEqual(self.calls_srv2, [])

    def test_restart_preserves_completed_status(self):
        """Completed operation in run 1 is immediately queryable in run 2 with zero backend calls."""
        srv1 = Service(self.db_path, backend=lambda b: self.calls_srv1.append(b) or fixture_metadata(b), initial_paused=False)
        ref_id = srv1.resolve(FIXTURE_BVID)["data"]["reference_id"]
        srv1.metadata(reference_id=ref_id, expected_bvid=FIXTURE_BVID, operation_id="op-persist-01", backend="fixture")

        # Server 2 starts
        srv2 = Service(self.db_path, backend=lambda b: self.calls_srv2.append(b) or fixture_metadata(b), initial_paused=False)
        status_res = srv2.status("op-persist-01")
        self.assertEqual(status_res["status"], "completed")
        self.assertEqual(status_res["data"]["bvid"], FIXTURE_BVID)
        self.assertEqual(self.calls_srv2, [])

    def test_restart_handles_crash_incomplete_reservation(self):
        """An operation reserved by a crashed process is classified as 'unknown' and never replayed."""
        srv1 = Service(self.db_path, initial_paused=False)
        # Directly simulate an unfinished reservation from run 1
        import hashlib
        fingerprint = hashlib.sha256(json.dumps(["fixture", "video.metadata.read", FIXTURE_BVID]).encode()).hexdigest()
        with srv1.connect() as c:
            c.execute("INSERT INTO operations VALUES(?,?,?,NULL)", ("op-crashed-01", fingerprint, "crashed-run-id"))

        # Server 2 inspects status
        srv2 = Service(self.db_path, backend=lambda b: self.calls_srv2.append(b) or fixture_metadata(b), initial_paused=False)
        status_res = srv2.status("op-crashed-01")
        self.assertEqual(status_res["status"], "unknown")
        self.assertEqual(status_res["error"], "previous_run_incomplete")

        # Attempt to run metadata with that crashed operation_id
        ref_id_new = srv2.resolve(FIXTURE_BVID)["data"]["reference_id"]
        meta_res = srv2.metadata(
            reference_id=ref_id_new,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-crashed-01",
            backend="fixture"
        )
        self.assertEqual(meta_res["status"], "unknown")
        self.assertEqual(self.calls_srv2, [])  # Zero replay


class NonPoisoningInvariantTests(unittest.TestCase):
    """Verifies that failed, blocked, or unwired calls never corrupt session state or block other reads."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "non_poisoning_test.sqlite3"
        self.calls = []

        def tracking_backend(bvid):
            self.calls.append(bvid)
            return fixture_metadata(bvid)

        self.service = Service(self.db_path, backend=tracking_backend, initial_paused=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unsupported_backend_does_not_poison_service(self):
        """Requesting an unwired backend returns unsupported without poisoning subsequent reads."""
        ref_id = self.service.resolve(FIXTURE_BVID)["data"]["reference_id"]

        # Call with unwired backend
        res_unsupported = self.service.metadata(
            reference_id=ref_id,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-unwired-backend",
            backend="real"
        )
        self.assertEqual(res_unsupported["status"], "unsupported")
        self.assertEqual(res_unsupported["error"], "backend_unwired")
        self.assertFalse(self.service.paused())

        # Valid read succeeds immediately
        res_valid = self.service.metadata(
            reference_id=ref_id,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-valid-after-unsupported",
            backend="fixture"
        )
        self.assertEqual(res_valid["status"], "completed")

    def test_conflict_error_does_not_poison_ledger(self):
        """Operation ID collision returns rejected conflict error without blocking other operations."""
        ref1 = self.service.resolve(FIXTURE_BVID)["data"]["reference_id"]
        ref2 = self.service.resolve(SYNTHETIC_BVID_2)["data"]["reference_id"]

        # Execute op-1 for FIXTURE_BVID
        res1 = self.service.metadata(
            reference_id=ref1,
            expected_bvid=FIXTURE_BVID,
            operation_id="op-shared-id",
            backend="fixture"
        )
        self.assertEqual(res1["status"], "completed")

        # Attempt to reuse op-shared-id for SYNTHETIC_BVID_2 -> conflict
        res_conflict = self.service.metadata(
            reference_id=ref2,
            expected_bvid=SYNTHETIC_BVID_2,
            operation_id="op-shared-id",
            backend="fixture"
        )
        self.assertEqual(res_conflict["status"], "rejected")
        self.assertEqual(res_conflict["error"], "operation_id_conflict")

        # Independent operation with fresh ID succeeds
        res_fresh = self.service.metadata(
            reference_id=ref2,
            expected_bvid=SYNTHETIC_BVID_2,
            operation_id="op-fresh-id",
            backend="fixture"
        )
        self.assertEqual(res_fresh["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
