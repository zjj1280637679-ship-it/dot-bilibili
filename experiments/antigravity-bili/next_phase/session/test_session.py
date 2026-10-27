"""
next_phase/session/test_session.py - Exhaustive Unit Test Suite for Session Architecture.

Part of the Bilibili Control Integration.
Tests all P0 invariants:
- Opaque store without raw tokens (rejects secret keys)
- Restart preserves pause (existing row not overwritten by initial_paused=False)
- Restore is always unverified
- Expected MID exact match & mismatch rejection
- bool rejected as int (expected_mid and NAV data['mid'])
- Malformed/nonzero NAV stays verification_unknown (not expired)
- silence != logged_out
- Lease non-resurrection & monotonic epoch fencing
- Business pending/deferred/unsupported not poisoning auth state
"""

import json
import os
import tempfile
import unittest

from next_phase.session.session_authority import (
    CapabilityFlag,
    CredentialHandle,
    NavVerificationResult,
    PauseManager,
    SecurityViolationError,
    SessionAuthority,
    SessionLease,
    SessionState,
    SessionStateError,
    StorageState,
    SyntheticCredentialStore,
    assert_no_secret_keys,
    verify_nav_response,
)


class TestOpaqueCredentialStore(unittest.TestCase):
    """Tests opaque credential storage and strict boundary enforcement."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "credentials.db")
        self.store = SyntheticCredentialStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_load_opaque_handle_success(self):
        """Opaque handle contains only non-secret metadata."""
        handle = self.store.save_handle(
            account_id="acc_main",
            handle_id="vault_h1001",
            version=1,
            metadata={"label": "primary_test_account", "region": "CN"},
        )
        self.assertEqual(handle.account_id, "acc_main")
        self.assertEqual(handle.handle_id, "vault_h1001")
        self.assertEqual(handle.version, 1)
        self.assertEqual(handle.storage_state, StorageState.PRESENT)

        # Reload from store
        loaded = self.store.load_handle("acc_main")
        self.assertEqual(loaded.account_id, "acc_main")
        self.assertEqual(loaded.handle_id, "vault_h1001")
        self.assertEqual(loaded.version, 1)
        self.assertEqual(loaded.storage_state, StorageState.PRESENT)

    def test_rejection_of_secret_keys_in_metadata(self):
        """Input dictionaries containing secret tokens must raise SecurityViolationError."""
        forbidden_payloads = [
            {"sessdata": "dummy_secret_value"},
            {"bili_jct": "csrf_token_hex_value"},
            {"cookie": "SESSDATA=abc; bili_jct=123"},
            {"cookies": ["cookie1", "cookie2"]},
            {"auth_token": "bearer_secret"},
            {"password": "plain_password"},
            {"nested": {"sub": {"TOKEN": "leaked_token"}}},
        ]

        for payload in forbidden_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(SecurityViolationError):
                    self.store.save_handle("acc_bad", "h_bad", 1, metadata=payload)

    def test_missing_handle_returns_storage_state_missing(self):
        """Querying a non-existent account returns StorageState.MISSING."""
        handle = self.store.load_handle("non_existent_account")
        self.assertEqual(handle.storage_state, StorageState.MISSING)
        self.assertEqual(handle.account_id, "non_existent_account")

    def test_simulated_unavailable_store(self):
        """Infrastructure failure maps to StorageState.UNAVAILABLE."""
        self.store.set_simulated_unavailable(True)
        handle = self.store.load_handle("acc_main")
        self.assertEqual(handle.storage_state, StorageState.UNAVAILABLE)

    def test_delete_handle(self):
        """Deleting a handle sets state to MISSING on subsequent load."""
        self.store.save_handle("acc_temp", "h_temp", 1)
        self.assertEqual(self.store.load_handle("acc_temp").storage_state, StorageState.PRESENT)

        self.store.delete_handle("acc_temp")
        self.assertEqual(self.store.load_handle("acc_temp").storage_state, StorageState.MISSING)


class TestPersistentPauseGate(unittest.TestCase):
    """Tests durable account pause gate and restart preservation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "controls.db")
        self.pause_mgr = PauseManager(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_pause_state_is_true(self):
        """Uninitialized account defaults to paused=True."""
        self.assertTrue(self.pause_mgr.is_paused("acc_unknown"))

    def test_explicit_set_paused_and_unpaused(self):
        """Explicitly toggling pause persists."""
        self.pause_mgr.set_paused("acc_1", True, reason="initial_safe_pause")
        self.assertTrue(self.pause_mgr.is_paused("acc_1"))

        self.pause_mgr.set_paused("acc_1", False, reason="operator_authorized")
        self.assertFalse(self.pause_mgr.is_paused("acc_1"))

    def test_restart_preserves_existing_pause_state(self):
        """
        CRITICAL INVARIANT:
        initial_paused=False MUST NOT overwrite an already existing paused record on restart!
        """
        # Step 1: Account is paused
        self.pause_mgr.set_paused("acc_2", True, reason="quarantined")
        self.assertTrue(self.pause_mgr.is_paused("acc_2"))

        # Step 2: Simulate service restart with new PauseManager instance pointing to same DB
        restarted_mgr = PauseManager(self.db_path)

        # Attempt to initialize with initial_paused=False
        persisted_val = restarted_mgr.init_pause_state("acc_2", initial_paused=False)

        # The existing paused=True state MUST be preserved!
        self.assertTrue(persisted_val)
        self.assertTrue(restarted_mgr.is_paused("acc_2"))

    def test_brand_new_account_honors_initial_paused_flag(self):
        """A brand-new account honors initial_paused parameter upon insertion."""
        # Account acc_brand_new does not exist
        res = self.pause_mgr.init_pause_state("acc_brand_new", initial_paused=False)
        self.assertFalse(res)
        self.assertFalse(self.pause_mgr.is_paused("acc_brand_new"))


class TestSemanticNavVerification(unittest.TestCase):
    """Tests semantic NAV API evaluation and type safety."""

    def test_expected_mid_bool_rejected_as_int(self):
        """bool (True/False) must be strictly rejected as expected_mid."""
        with self.assertRaises(TypeError):
            verify_nav_response(b'{"code":0}', expected_mid=True)

        with self.assertRaises(TypeError):
            verify_nav_response(b'{"code":0}', expected_mid=False)

        with self.assertRaises(TypeError):
            verify_nav_response(b'{"code":0}', expected_mid="12345")

        with self.assertRaises(TypeError):
            verify_nav_response(b'{"code":0}', expected_mid=-100)

    def test_successful_nav_verification(self):
        """Valid response with matching expected_mid verifies successfully."""
        body = json.dumps({
            "code": 0,
            "message": "0",
            "data": {
                "isLogin": True,
                "mid": 170001,
                "uname": "TestBiliUser",
                "silence": 0,
            }
        }).encode("utf-8")

        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.VERIFIED)
        self.assertEqual(result.mid, 170001)
        self.assertEqual(result.uname, "TestBiliUser")
        self.assertFalse(result.is_silenced)

    def test_identity_mismatch_blocks_access(self):
        """Observed mid differing from expected_mid triggers IDENTITY_MISMATCH."""
        body = json.dumps({
            "code": 0,
            "data": {
                "isLogin": True,
                "mid": 999999,  # Different MID
                "uname": "WrongAccount",
            }
        }).encode("utf-8")

        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.IDENTITY_MISMATCH)
        self.assertEqual(result.mid, 999999)
        self.assertEqual(result.reason, "identity_mismatch")

    def test_bool_rejected_as_mid_in_nav_data(self):
        """data.mid == True must be rejected as invalid and map to verification_unknown."""
        body = json.dumps({
            "code": 0,
            "data": {
                "isLogin": True,
                "mid": True,  # bool is not int!
                "uname": "TestUser",
            }
        }).encode("utf-8")

        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.VERIFICATION_UNKNOWN)

    def test_explicit_unauthenticated_code_minus_101(self):
        """code == -101 maps to NOT_LOGGED_IN."""
        body = b'{"code": -101, "message": "\xe8\xb4\xa6\xe5\x8f\xb7\xe6\x9c\xaa\xe7\x99\xbb\xe5\xbd\x95"}'
        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.NOT_LOGGED_IN)
        self.assertEqual(result.raw_code, -101)

    def test_explicit_unauthenticated_is_login_false(self):
        """code == 0 with isLogin == False maps to NOT_LOGGED_IN."""
        body = b'{"code": 0, "data": {"isLogin": false}}'
        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.NOT_LOGGED_IN)

    def test_malformed_json_preserved_as_unknown(self):
        """Malformed JSON stays verification_unknown (does NOT mark as expired or delete keys)."""
        body = b'{"code": 0, "data": { incomplete json'
        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.VERIFICATION_UNKNOWN)

    def test_duplicate_json_keys_rejected_as_unknown(self):
        """Duplicate keys in JSON payload are rejected as verification_unknown."""
        body = b'{"code": 0, "code": 1, "data": {"isLogin": true, "mid": 170001, "uname": "A"}}'
        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.VERIFICATION_UNKNOWN)

    def test_nonzero_upstream_code_preserved_as_unknown(self):
        """Upstream anti-bot (-412) or server error (-500) stays verification_unknown."""
        for code in [-412, -500, 410001]:
            with self.subTest(code=code):
                body = json.dumps({"code": code, "message": "Risk intercept"}).encode("utf-8")
                result = verify_nav_response(body, expected_mid=170001)
                self.assertEqual(result.state, SessionState.VERIFICATION_UNKNOWN)
                self.assertEqual(result.raw_code, code)

    def test_silence_equals_account_restricted_not_logged_out(self):
        """silence == 1 is marked as restricted/silenced, NOT logged out."""
        body = json.dumps({
            "code": 0,
            "data": {
                "isLogin": True,
                "mid": 170001,
                "uname": "SilencedUser",
                "silence": 1,
            }
        }).encode("utf-8")

        result = verify_nav_response(body, expected_mid=170001)
        self.assertEqual(result.state, SessionState.VERIFIED)
        self.assertTrue(result.is_silenced)


class TestSessionAuthorityLifecycle(unittest.TestCase):
    """Tests session authority, restoration, leasing, and concurrency fencing."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "session_test.db")
        self.pause_mgr = PauseManager(self.db_path)
        self.store = SyntheticCredentialStore(self.db_path)
        self.pause_mgr.set_paused("acc_test", False, reason="test_setup")
        self.store.save_handle("acc_test", "handle_001", 1)

        self.authority = SessionAuthority(
            account_id="acc_test",
            expected_mid=170001,
            pause_manager=self.pause_mgr,
            store=self.store,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_restoration_is_always_unverified(self):
        """
        CRITICAL INVARIANT:
        Restoring from store ALWAYS sets state to UNVERIFIED.
        No verified=True is ever persisted or assumed on load.
        """
        handle = self.authority.restore_from_store()
        self.assertEqual(handle.storage_state, StorageState.PRESENT)
        self.assertEqual(self.authority.state, SessionState.UNVERIFIED)

    def test_unverified_session_blocks_authenticated_reads(self):
        """UNVERIFIED session cannot acquire AUTH_READ leases."""
        self.authority.restore_from_store()
        with self.assertRaises(SessionStateError):
            self.authority.acquire_lease(CapabilityFlag.AUTH_READ)

        # But anonymous read is permitted
        lease = self.authority.acquire_lease(CapabilityFlag.ANONYMOUS_READ)
        self.assertEqual(lease.capability, CapabilityFlag.ANONYMOUS_READ)

    def test_successful_verification_and_monotonic_epoch(self):
        """Applying valid verification transitions to VERIFIED and advances epoch."""
        self.authority.restore_from_store()
        epoch_before = self.authority.epoch

        res = NavVerificationResult(
            state=SessionState.VERIFIED,
            mid=170001,
            uname="TestUser",
            is_silenced=False,
        )
        self.authority.apply_nav_verification(res, ticket=self.authority.begin_verification())

        self.assertEqual(self.authority.state, SessionState.VERIFIED)
        self.assertGreater(self.authority.epoch, epoch_before)

    def test_lease_epoch_fencing_prevents_stale_resurrection(self):
        """Transitioning or invalidating session invalidates older leases."""
        # 1. Verify session
        self.authority.stage_unverified()
        self.authority.apply_nav_verification(
            NavVerificationResult(state=SessionState.VERIFIED, mid=170001, uname="U1")
        , ticket=self.authority.begin_verification())
        lease1 = self.authority.acquire_lease(CapabilityFlag.AUTH_READ)
        self.authority.assert_valid_lease(lease1)

        # 2. Invalidate session
        self.authority.invalidate(reason="token_rotation")
        self.assertEqual(self.authority.state, SessionState.EXPIRED)

        # 3. Assert lease1 is now rejected due to epoch mismatch and expired state
        with self.assertRaises(SessionStateError):
            self.authority.assert_valid_lease(lease1)

    def test_verified_never_implicitly_grants_admin(self):
        """VERIFIED session cannot acquire ADMIN lease without explicit elevation."""
        self.authority.stage_unverified()
        self.authority.apply_nav_verification(
            NavVerificationResult(state=SessionState.VERIFIED, mid=170001, uname="U1")
        , ticket=self.authority.begin_verification())

        with self.assertRaises(SessionStateError):
            self.authority.acquire_lease(CapabilityFlag.ADMIN)

        # Grant explicit elevation
        self.authority.grant_admin_elevation(True)
        admin_lease = self.authority.acquire_lease(CapabilityFlag.ADMIN)
        self.assertEqual(admin_lease.capability, CapabilityFlag.ADMIN)

    def test_silenced_account_cannot_acquire_write_leases(self):
        """Silenced account is blocked from WRITE_LOW_RISK and WRITE_HIGH_RISK."""
        self.authority.stage_unverified()
        self.authority.apply_nav_verification(
            NavVerificationResult(state=SessionState.VERIFIED, mid=170001, uname="U1", is_silenced=True)
        , ticket=self.authority.begin_verification())

        # Read is allowed
        read_lease = self.authority.acquire_lease(CapabilityFlag.AUTH_READ)
        self.assertEqual(read_lease.capability, CapabilityFlag.AUTH_READ)

        # Writes are blocked
        with self.assertRaises(SessionStateError):
            self.authority.acquire_lease(CapabilityFlag.WRITE_LOW_RISK)

        with self.assertRaises(SessionStateError):
            self.authority.acquire_lease(CapabilityFlag.WRITE_HIGH_RISK)

    def test_persistent_pause_blocks_non_anonymous_capabilities(self):
        """Pausing the account blocks AUTH_READ and WRITE capabilities."""
        self.authority.stage_unverified()
        self.authority.apply_nav_verification(
            NavVerificationResult(state=SessionState.VERIFIED, mid=170001, uname="U1")
        , ticket=self.authority.begin_verification())

        # Set pause
        self.pause_mgr.set_paused("acc_test", True, reason="emergency_freeze")

        with self.assertRaises(SessionStateError):
            self.authority.acquire_lease(CapabilityFlag.AUTH_READ)

        # This authority is account-bound: pause also blocks anonymous transport.
        with self.assertRaises(SessionStateError):
            self.authority.acquire_lease(CapabilityFlag.ANONYMOUS_READ)


class TestIndependentAuthVsBusinessState(unittest.TestCase):
    """Tests that business outcomes never poison or alter authentication state."""

    def setUp(self):
        self.pause_mgr = PauseManager(":memory:")
        self.pause_mgr.set_paused("acc_indep", False)
        self.authority = SessionAuthority(
            account_id="acc_indep",
            expected_mid=170001,
            pause_manager=self.pause_mgr,
        )
        self.authority.stage_unverified()
        self.authority.apply_nav_verification(
            NavVerificationResult(state=SessionState.VERIFIED, mid=170001, uname="BusinessTestUser")
        , ticket=self.authority.begin_verification())

    def test_business_outcomes_do_not_poison_verified_auth_state(self):
        """
        CRITICAL INVARIANT:
        Outcomes like pending, deferred, blocked, unsupported, wrong_target, upstream_error
        NEVER poison or alter the session's VERIFIED state, and NEVER block unrelated reads!
        """
        business_outcomes = [
            "pending",
            "deferred",
            "blocked",
            "unsupported",
            "wrong_target",
            "upstream_error",
            "rate_limited",
        ]

        for outcome in business_outcomes:
            with self.subTest(outcome=outcome):
                epoch_before = self.authority.epoch

                # Record outcome on business operation
                self.authority.record_business_outcome(outcome, operation_id=f"op_{outcome}")

                # Auth state must remain VERIFIED
                self.assertEqual(self.authority.state, SessionState.VERIFIED)
                # Epoch must remain unchanged (no false invalidation)
                self.assertEqual(self.authority.epoch, epoch_before)

                # Unrelated authenticated read must continue to succeed!
                lease = self.authority.acquire_lease(CapabilityFlag.AUTH_READ)
                self.assertEqual(lease.capability, CapabilityFlag.AUTH_READ)
                self.authority.assert_valid_lease(lease)


if __name__ == "__main__":
    unittest.main()
