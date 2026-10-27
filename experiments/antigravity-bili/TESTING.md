# Offline verification

Run `python -B scripts/test_offline.py` from this directory. Each group runs in its own process, so test audit hooks do not accidentally affect another group's subprocess tests. The actual tested interpreter is Python 3.12.14 on Linux/POSIX (fork and stdio/select are used). Syntax uses Python 3.10+ features; other interpreter versions remain unverified. Tests use temporary state and do not install dependencies or enable real account transports.

| Included suite | Passing methods |
|---|---:|
| Fixture MCP service and compatibility | 27 |
| Pure metadata parser | 26 |
| QR/session module and local relations | 65 |
| Versioned metadata and local relations | 46 |
| Actual new three-module composition | 7 |
| Legacy fixture-only MCP acceptance, not new composition proof | 18 |
| Independent actual-composition relations | 10 |
| Independent fixture real-stdio protocol | 14 |
| Independent fixture behavior | 19 |
| Independent QR/session relations | 19 |
| **Previous milestone subtotal** | **251** |
| New standalone credential-store owner suite | 35 |
| New independent credential-store relations | 18 |
| **Methods executed by the updated runner** | **304** |

Method count measures executed regressions, not distinct platform capabilities or overall completion. The 136-method next_phase discovery combines 118 new-module methods and 18 old-fixture methods; the actual new composition has 7 owner methods plus 10 independent methods.

## Important relation evidence

- Real local Python stdio processes accept optional arguments and object `_meta` without elevating permission; unknown fields are rejected.
- Restart preserves pause, invalidates old process references, and does not repeat a reserved or unknown operation.
- A real test child exits with code71 after reservation; subsequent access remains unknown without replay. This is local process-failure evidence, not a website action.
- Wrong expected identity, forged/cross-owner/reused tickets and old pause-generation leases cannot authorize business calls.
- Actual QR → account-bound marker → unverified restoration → fresh identity ticket → issued read lease → metadata composition is exercised, without real credentials.
- Shared transport concurrent HTTP200/503 observations retain the correct per-invocation status; the earlier mutable-latest-evidence defect has a regression.
- Partial usable metadata is preserved; cached evidence is historical and current-invocation counters are zero. Unknown business results do not invalidate unrelated authentication.
- In-flight pause/close does not pretend to cancel an admitted callback and cannot revive authority afterward. A deliberate new session generation must reverify.

The metadata and composition tests trap socket construction and use fake openers. Independent fixture stdio tests also apply network/process guards inside the server child. Inputs with cookie/token-like names are synthetic sentinels only. No real endpoint, identity, write action or restoration was tested.

## Host evidence is a separate layer

The fixture milestone previously demonstrated all four tools through an actual Antigravity CLI host and pause retention after restart. After removal of temporary protocol-shape diagnostics, the final clean server was rechecked with cached operation.status. This does not assert that the new QR/session/metadata modules are registered in that host, that all final-clean tools were freshly exercised there, or that any real Bilibili action succeeded.

The included fixture source is unchanged from that clean milestone. Main SHA256 values are recorded in MANIFEST.json. Passing local tests cannot establish installation in another context, real accounts, current endpoint behavior, or full MCP conformance.

## Standalone credential-file addition (not connected to login)

The original 251-method milestone is preserved as a subtotal. The updated runner
actually executes 35 standalone owner methods plus 18 independent relations,
for 304 passing methods. The source tree was relocated to an unrelated temporary
directory and tested there; no runtime material is included in this distribution.

New evidence covers separate-process creation/rotation contention, complete-handle
CAS, held shared-lock use, pre-replace partial-write exit73, immediate post-replace
exit74, unknown commit observation without retry, corrupt versus I/O unknown,
symlink/hardlink/permission boundaries and opaque-only public receipts. Owner
exit71/72 scenarios remain separate. All material is fixed FAKE_ONLY data.

These tests do not connect the file port to QR/session/metadata, certify encryption,
prove power-loss/cloud-disk retention, authorize saving real material, or establish
real credential restart/NAV reuse. A callback entry is not a business outcome.
