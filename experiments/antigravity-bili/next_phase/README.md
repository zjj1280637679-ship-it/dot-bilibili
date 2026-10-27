# New modular offline candidate

AG draft code followed by local corrective patches and independent relation review. These modules are separate from the fixture MCP server and do not install new public tools.

- `qr/`: bounded domestic QR generate/poll response parsing and one-attempt coordinator. Shared pause and generation fences prevent late results reviving a closed attempt. Phone/SMS remains unimplemented.
- `session/`: synthetic marker storage, account-bound durable pause, expected-MID verification tickets and issued read leases. Marker storage is not usable credential storage. Verification does not grant writes.
- `metadata/`: versioned typed observations, guarded durable read ledger and a default-disconnected narrow HTTP implementation. Tests use fake openers only. Parser dependency is the sibling `metadata-adapter-candidate` directory.
- `composition.py`: actual QR → account marker → UNVERIFIED restore → fresh identity ticket → actual AUTH_READ lease callback → metadata harness. See `COMPOSITION.md`.
- `acceptance/`: legacy tests for the earlier fixture service. Their 18 methods are not evidence of the new three-module composition; obsolete discovery/skill drafts are intentionally omitted.

From the experiment root:

```sh
python -B -m unittest discover -s next_phase -t . -p 'test*.py' -v
python -B -m unittest next_phase.test_composition -v
```

No live login, NAV, metadata request, production credential backend, write/restoration acceptance or public MCP integration is established. Shared pause controls all transports attached to this synthetic account; a future independent public unauthenticated backend may define its own explicit policy. Business unknown/deferred is not an authentication failure.
