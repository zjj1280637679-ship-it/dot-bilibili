"""
Comprehensive Unit Test Suite for Domestic QR Login Module.
Phase: next_phase/qr/test_qr.py

Verifies:
1. Valid generate & poll payload parsing.
2. Fail-closed JSON validation (malformed bytes, oversized payloads, duplicate keys, NaN/Infinity).
3. Bool-as-int envelope and status code rejection.
4. Tampered QR URL rejection (host, path, fragment, query params, key mismatch).
5. State regression rejection (waiting_confirmation -> waiting_scan).
6. Single pending login enforcement (second generate call / restart blocked).
7. Account pause gate enforcement (typed blocked, 0 transport calls).
8. Phone login unsupported status check.
9. Opaque session handle credential isolation (no raw SESSDATA leaked).
"""

from __future__ import annotations

import json
import unittest
from typing import Any, List, Optional, Tuple

from .qr_login import (
    OpaqueSessionHandle,
    OpaqueSessionPort,
    QRChallenge,
    QRLoginCoordinator,
    QRPollResult,
    QRProtocolError,
    parse_fail_closed_json,
    parse_qr_generate,
    parse_qr_poll,
    request_phone_login,
)


class FakeTransport:
    """Injected fake transport simulating domestic Bilibili gateway responses."""

    def __init__(self) -> None:
        self.call_count: int = 0
        self.generate_queue: List[Tuple[bytes, List[str]]] = []
        self.poll_queue: List[Tuple[bytes, List[str]]] = []
        self.last_poll_key: Optional[str] = None

    def request(
        self,
        operation: str,
        *,
        key: Optional[str] = None
    ) -> Tuple[bytes, List[str]]:
        self.call_count += 1
        if operation == 'generate':
            if not self.generate_queue:
                raise RuntimeError("No queued fake generate response")
            return self.generate_queue.pop(0)
        elif operation == 'poll':
            self.last_poll_key = key
            if not self.poll_queue:
                raise RuntimeError("No queued fake poll response")
            return self.poll_queue.pop(0)
        raise RuntimeError(f"Unknown fake transport operation: {operation}")


class FakePauseGate:
    """Mock pause gate for account operations."""

    def __init__(self, paused: bool = True) -> None:
        self._paused = paused
        self._generation = 0

    def is_paused(self) -> bool:
        return self._paused

    def set_paused(self, val: bool) -> None:
        self._generation += 1
        self._paused = val

    def snapshot(self):
        return (self._paused,self._generation)


class TestQRLogin(unittest.TestCase):
    """Test suite covering QR login contract, state coordination, and security constraints."""

    def setUp(self) -> None:
        self.transport = FakeTransport()
        self.pause_gate = FakePauseGate(paused=False)
        self.valid_key = "a1b2c3d4e5f6g7h8i9j0k1l2"
        self.valid_url = f"https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key={self.valid_key}"

    # -----------------------------------------------------------------------
    # 1. Fail-closed JSON & Envelope Parsing Tests
    # -----------------------------------------------------------------------

    def test_json_parser_rejects_duplicate_keys(self) -> None:
        # JSON with duplicate 'code' keys
        raw = b'{"code": 0, "code": 0, "data": {}}'
        with self.assertRaises(QRProtocolError) as ctx:
            parse_fail_closed_json(raw)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

        # JSON with duplicate keys inside data
        raw_inner = b'{"code": 0, "data": {"qrcode_key": "123", "qrcode_key": "456"}}'
        with self.assertRaises(QRProtocolError) as ctx:
            parse_fail_closed_json(raw_inner)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

    def test_json_parser_rejects_nan_and_infinity(self) -> None:
        raw_nan = b'{"code": 0, "data": {"val": NaN}}'
        with self.assertRaises(QRProtocolError) as ctx:
            parse_fail_closed_json(raw_nan)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

        raw_inf = b'{"code": 0, "data": {"val": Infinity}}'
        with self.assertRaises(QRProtocolError) as ctx:
            parse_fail_closed_json(raw_inf)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

    def test_json_parser_rejects_oversized_payload(self) -> None:
        # Exceeds MAX_BODY (65536 bytes)
        big_body = b'{"code": 0, "data": {"pad": "' + (b'x' * 65540) + b'"}}'
        with self.assertRaises(QRProtocolError) as ctx:
            parse_fail_closed_json(big_body)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

    def test_code_exact_int_check_rejects_bool(self) -> None:
        # In Python, isinstance(True, int) is True; verify bool True is strictly rejected
        raw_bool_code = b'{"code": true, "data": {}}'
        with self.assertRaises(QRProtocolError) as ctx:
            parse_fail_closed_json(raw_bool_code)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

        raw_bool_zero = b'{"code": false, "data": {}}'
        with self.assertRaises(QRProtocolError) as ctx:
            parse_fail_closed_json(raw_bool_zero)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

    # -----------------------------------------------------------------------
    # 2. QR Generate Parsing & URL Grounding Tests
    # -----------------------------------------------------------------------

    def test_parse_qr_generate_valid(self) -> None:
        body = json.dumps({
            "code": 0,
            "data": {
                "qrcode_key": self.valid_key,
                "url": self.valid_url
            }
        }).encode('utf-8')

        challenge = parse_qr_generate(body)
        self.assertEqual(challenge.qrcode_key, self.valid_key)
        self.assertEqual(challenge.url, self.valid_url)
        # Redacted repr check
        self.assertEqual(repr(challenge), '<QRChallenge redacted>')

    def test_parse_qr_generate_rejects_tampered_urls(self) -> None:
        # A: Wrong scheme (http instead of https)
        bad_scheme = f"http://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key={self.valid_key}"
        body_a = json.dumps({"code": 0, "data": {"qrcode_key": self.valid_key, "url": bad_scheme}}).encode('utf-8')
        with self.assertRaises(QRProtocolError) as ctx:
            parse_qr_generate(body_a)
        self.assertEqual(ctx.exception.reason, 'unexpected_qr_url')

        # B: Wrong domain (evil.com)
        bad_domain = f"https://passport.evil.com/h5-app/passport/login/scan?navhide=1&qrcode_key={self.valid_key}"
        body_b = json.dumps({"code": 0, "data": {"qrcode_key": self.valid_key, "url": bad_domain}}).encode('utf-8')
        with self.assertRaises(QRProtocolError) as ctx:
            parse_qr_generate(body_b)
        self.assertEqual(ctx.exception.reason, 'unexpected_qr_url')

        # C: Extra query parameter
        bad_query = f"https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key={self.valid_key}&extra=1"
        body_c = json.dumps({"code": 0, "data": {"qrcode_key": self.valid_key, "url": bad_query}}).encode('utf-8')
        with self.assertRaises(QRProtocolError) as ctx:
            parse_qr_generate(body_c)
        self.assertEqual(ctx.exception.reason, 'unexpected_qr_url')

        # D: Fragment presence
        bad_frag = f"https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key={self.valid_key}#target"
        body_d = json.dumps({"code": 0, "data": {"qrcode_key": self.valid_key, "url": bad_frag}}).encode('utf-8')
        with self.assertRaises(QRProtocolError) as ctx:
            parse_qr_generate(body_d)
        self.assertEqual(ctx.exception.reason, 'unexpected_qr_url')

        # E: Key mismatch between payload and query param
        mismatched_url = f"https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=different_key_12345"
        body_e = json.dumps({"code": 0, "data": {"qrcode_key": self.valid_key, "url": mismatched_url}}).encode('utf-8')
        with self.assertRaises(QRProtocolError) as ctx:
            parse_qr_generate(body_e)
        self.assertEqual(ctx.exception.reason, 'unexpected_qr_url')

    # -----------------------------------------------------------------------
    # 3. QR Poll Parsing Tests
    # -----------------------------------------------------------------------

    def test_parse_qr_poll_states(self) -> None:
        # 86101: waiting_scan
        body_scan = json.dumps({"code": 0, "data": {"code": 86101, "message": "未扫码"}}).encode('utf-8')
        res_scan = parse_qr_poll(body_scan)
        self.assertEqual(res_scan.code, 86101)
        self.assertEqual(res_scan.status, 'waiting_scan')

        # 86090: waiting_confirmation
        body_conf = json.dumps({"code": 0, "data": {"code": 86090, "message": "扫码未确认"}}).encode('utf-8')
        res_conf = parse_qr_poll(body_conf)
        self.assertEqual(res_conf.code, 86090)
        self.assertEqual(res_conf.status, 'waiting_confirmation')

        # 86038: expired
        body_exp = json.dumps({"code": 0, "data": {"code": 86038, "message": "二维码已失效"}}).encode('utf-8')
        res_exp = parse_qr_poll(body_exp)
        self.assertEqual(res_exp.code, 86038)
        self.assertEqual(res_exp.status, 'expired')

        # 0: authenticated
        body_auth = json.dumps({"code": 0, "data": {"code": 0, "message": "已登录"}}).encode('utf-8')
        res_auth = parse_qr_poll(body_auth)
        self.assertEqual(res_auth.code, 0)
        self.assertEqual(res_auth.status, 'authenticated')

    def test_parse_qr_poll_rejects_bool_status_code(self) -> None:
        body_bool = json.dumps({"code": 0, "data": {"code": True, "message": ""}}).encode('utf-8')
        with self.assertRaises(QRProtocolError) as ctx:
            parse_qr_poll(body_bool)
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')

    # -----------------------------------------------------------------------
    # 4. Account Operations Pause Gate Tests
    # -----------------------------------------------------------------------

    def test_pause_gate_blocks_generate_with_zero_transport_calls(self) -> None:
        self.pause_gate.set_paused(True)
        coordinator = QRLoginCoordinator(transport=self.transport, pause_gate=self.pause_gate)

        result = coordinator.generate(approved=True, consent_ref="operator-test-01")
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'account_operations_paused')
        self.assertFalse(result['transport_called'])
        self.assertEqual(self.transport.call_count, 0)
        # State remains unchanged
        self.assertEqual(coordinator.state, 'new')

    # -----------------------------------------------------------------------
    # 5. Single Pending Login State Machine & No Auto-Recreate Tests
    # -----------------------------------------------------------------------

    def test_single_pending_login_lifecycle(self) -> None:
        coordinator = QRLoginCoordinator(transport=self.transport, pause_gate=self.pause_gate)
        self.assertEqual(coordinator.state, 'new')

        # Stage fake generate response
        gen_body = json.dumps({
            "code": 0,
            "data": {"qrcode_key": self.valid_key, "url": self.valid_url}
        }).encode('utf-8')
        self.transport.generate_queue.append((gen_body, []))

        # Generate challenge
        res_gen = coordinator.generate(approved=True, consent_ref="consent-valid-01")
        self.assertEqual(res_gen['status'], 'ready')
        self.assertEqual(coordinator.state, 'ready')
        self.assertEqual(self.transport.call_count, 1)

        # Stage poll waiting_scan
        poll_scan = json.dumps({"code": 0, "data": {"code": 86101}}).encode('utf-8')
        self.transport.poll_queue.append((poll_scan, []))
        coordinator.poll_once()
        self.assertEqual(coordinator.state, 'waiting_scan')

        # Stage poll waiting_confirmation
        poll_conf = json.dumps({"code": 0, "data": {"code": 86090}}).encode('utf-8')
        self.transport.poll_queue.append((poll_conf, []))
        coordinator.poll_once()
        self.assertEqual(coordinator.state, 'waiting_confirmation')

        # Stage poll authenticated with Set-Cookie headers
        poll_auth = json.dumps({"code": 0, "data": {"code": 0}}).encode('utf-8')
        cookies = [
            'SESSDATA=mock_sessdata_token_12345; Domain=.bilibili.com; Path=/; Secure; HttpOnly',
            'bili_jct=abcdef0123456789abcdef0123456789; Domain=.bilibili.com; Path=/; Secure'
        ]
        self.transport.poll_queue.append((poll_auth, cookies))
        res_auth = coordinator.poll_once()
        self.assertEqual(coordinator.state, 'session_received')
        self.assertIn('session_handle', res_auth)

        # Verify handle is opaque and redacts raw secrets
        handle: OpaqueSessionHandle = res_auth['session_handle']
        self.assertNotIn('mock_sessdata', repr(handle))
        self.assertNotIn('abcdef0123456789', repr(handle))
        safe_dict = handle.to_safe_dict()
        self.assertNotIn('mock_sessdata', str(safe_dict))

        # LATCH GUARANTEE: Calling generate a second time MUST be rejected
        with self.assertRaises(QRProtocolError) as ctx:
            coordinator.generate(approved=True, consent_ref="second-call-rejected")
        self.assertEqual(ctx.exception.reason, 'single_pending_login_enforced')

    def test_recreate_rejected_after_expired(self) -> None:
        coordinator = QRLoginCoordinator(transport=self.transport, pause_gate=self.pause_gate)
        gen_body = json.dumps({
            "code": 0,
            "data": {"qrcode_key": self.valid_key, "url": self.valid_url}
        }).encode('utf-8')
        self.transport.generate_queue.append((gen_body, []))
        coordinator.generate(approved=True, consent_ref="consent-01")

        # Poll returns expired
        poll_exp = json.dumps({"code": 0, "data": {"code": 86038}}).encode('utf-8')
        self.transport.poll_queue.append((poll_exp, []))
        res = coordinator.poll_once()
        self.assertEqual(res['status'], 'expired')
        self.assertEqual(coordinator.state, 'expired')

        # NO AUTO-RECREATE: calling generate again must fail
        with self.assertRaises(QRProtocolError) as ctx:
            coordinator.generate(approved=True, consent_ref="recreate-attempt")
        self.assertEqual(ctx.exception.reason, 'single_pending_login_enforced')

    # -----------------------------------------------------------------------
    # 6. Anti-Regression & Protocol Error Handling Tests
    # -----------------------------------------------------------------------

    def test_state_regression_from_confirmation_to_scan_rejected(self) -> None:
        coordinator = QRLoginCoordinator(transport=self.transport, pause_gate=self.pause_gate)
        gen_body = json.dumps({
            "code": 0,
            "data": {"qrcode_key": self.valid_key, "url": self.valid_url}
        }).encode('utf-8')
        self.transport.generate_queue.append((gen_body, []))
        coordinator.generate(approved=True, consent_ref="consent-01")

        # Step 1: waiting_confirmation
        poll_conf = json.dumps({"code": 0, "data": {"code": 86090}}).encode('utf-8')
        self.transport.poll_queue.append((poll_conf, []))
        coordinator.poll_once()
        self.assertEqual(coordinator.state, 'waiting_confirmation')

        # Step 2: Anomaly - backend reports waiting_scan after confirmation!
        poll_scan_regression = json.dumps({"code": 0, "data": {"code": 86101}}).encode('utf-8')
        self.transport.poll_queue.append((poll_scan_regression, []))
        with self.assertRaises(QRProtocolError) as ctx:
            coordinator.poll_once()
        self.assertEqual(ctx.exception.reason, 'unexpected_protocol')
        # Coordinator must be closed
        self.assertEqual(coordinator.state, 'closed')

    # -----------------------------------------------------------------------
    # 7. Phone Login Explicitly Unsupported Tests
    # -----------------------------------------------------------------------

    def test_request_phone_login_unsupported(self) -> None:
        res = request_phone_login(phone="13800138000", code="123456")
        self.assertEqual(res['status'], 'unsupported')
        self.assertEqual(res['error'], 'phone_login_unsupported_until_grounded')
        self.assertFalse(res['live'])


if __name__ == '__main__':
    unittest.main()
