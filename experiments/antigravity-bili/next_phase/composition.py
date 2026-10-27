"""Synthetic cross-module composition, authored locally by dot.

Connects actual QR/session/metadata modules with fake injected responses only.
Does not acquire or persist real credentials, create HTTP clients, or expose grants
as model-supplied tool arguments. Not installed into the frozen MCP fixture slice.
"""
import secrets
from pathlib import Path
from .qr.qr_login import QRLoginCoordinator,OpaqueSessionPort
from .session.session_authority import (SyntheticCredentialStore,PauseManager,
    AccountPauseGate,SessionAuthority,SessionStateError,CapabilityFlag,StorageState)

class SyntheticMarkerSessionPort:
    """Store an opaque synthetic marker in a bound account; discard fake cookies."""
    def __init__(self,store,account_id):self.store=store;self.account_id=account_id
    def extract_opaque_handle(self,headers):
        handle=OpaqueSessionPort.extract_opaque_handle(headers)
        saved=self.store.save_handle(self.account_id,handle.handle_id,1,metadata={'source':'synthetic'})
        if saved.storage_state is not StorageState.PRESENT:raise RuntimeError('synthetic_marker_not_saved')
        return handle

class SyntheticComposition:
    """Trusted harness, not a live product login or public all-purpose tool."""
    def __init__(self,directory,account_id,expected_mid,qr_transport):
        root=Path(directory);root.mkdir(parents=True,exist_ok=True)
        self.account_id=account_id
        self.store=SyntheticCredentialStore(str(root/'opaque-markers.sqlite3'))
        self.pause=PauseManager(str(root/'account-pause.sqlite3'))
        self.pause.init_pause_state(account_id,initial_paused=True)
        self.gate=AccountPauseGate(self.pause,account_id)
        self.authority=SessionAuthority(account_id,expected_mid,self.pause,self.store)
        self.qr=QRLoginCoordinator(qr_transport,self.gate,SyntheticMarkerSessionPort(self.store,account_id))
        # Deliberately separate ledger namespace from account pause/store tables.
        self.ledger=str(root/'metadata-observations.sqlite3')
        self.references={}

    def poll_once(self):
        result=self.qr.poll_once()
        if result['status']=='session_received':
            saved=self.authority.restore_from_store()
            if saved.handle_id!=result['session_handle'].handle_id:
                self.authority.close();raise RuntimeError('synthetic_marker_binding_mismatch')
            result=dict(result,session_state=self.authority.state.value,
                        marker_persisted=True,credential_persisted=False,live=False)
        return result

    def resolve_fixture_reference(self,bvid):
        from .metadata.versioned_adapter import valid_bvid
        if not valid_bvid(bvid):raise ValueError('invalid_bvid')
        reference=secrets.token_hex(16);self.references[reference]=bvid
        return reference

    def read_fixture_metadata(self,reference_id,expected_bvid,operation_id,transport):
        from .metadata.versioned_adapter import execute_metadata_read,Provenance,make_blocked_observation
        try:lease=self.authority.acquire_lease(CapabilityFlag.AUTH_READ)
        except SessionStateError:
            # An unmet authentication/pause prerequisite, not a human rejection.
            return make_blocked_observation('session_prerequisite_unmet')
        def current_authority():
            self.authority.assert_valid_lease(lease)
            return True
        return execute_metadata_read(self.ledger,reference_id=reference_id,
            expected_bvid=expected_bvid,operation_id=operation_id,backend='web_view_v1',
            ref_map=self.references,transport=transport,provenance=Provenance.SYNTHETIC,
            pause_gate=self.gate,authorization_check=current_authority,account_scope=self.account_id)
