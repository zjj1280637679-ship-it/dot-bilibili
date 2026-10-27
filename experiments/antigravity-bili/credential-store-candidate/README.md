# File credential storage port — dot-local offline candidate

**New isolated implementation; not enabled, deployed, connected to login, or tested
with real credentials.** All executed tests use newly generated temporary
`FAKE_ONLY` records. This is not the old fixed-fixture file adapter renamed as a
production backend. It persists exact internal opaque bytes, while public receipts
expose only opaque account/handle/generation metadata and typed state.

Real use requires review of the intended host/private directory and the user's
contemporaneous authorization to save those actual credentials. No such real
save is performed or authorized by this candidate's tests. No existing cookies,
AG settings, released branches or system permission settings were changed.

## Why this small design

An earlier synthetic store prototype supplied a useful replaceable-store idea
and atomic fake JSON replacement, but lacked fsync, multiwriter locking and
rotation/version binding. The newer session store
only persists opaque markers, not usable material. Neither establishes credential
persistence. A private POSIX directory and one file per account is sufficient to
validate this missing seam without a cloud service, new keys or a new login.

This module uses Python's standard library only. No API, web, credential discovery,
QR, proxy, refresh or package installation code exists. Secret material is opaque
bytes: a future private acquisition adapter must serialize the **complete approved
field set** losslessly; this store neither selects Bilibili cookie fields nor
claims that any bytes form a valid/complete session.

## Requirement → conditions → strategy → evidence

| Requirement | Conditions / strategy | Offline checks |
|---|---|---|
| Recover material without exporting it to the model | Trusted Python config and internal callback; public opaque receipt | New Python process recovers exact fake bytes; receipts/repr/errors never return material; callback return value discarded |
| Never restore authentication | No auth/lease/verified fields in persisted schema | Every public receipt labels restoration unverified; unknown/corrupt/missing do not initiate any login |
| Atomic, durable-intent replacement | New 0600 temporary file, full write, file fsync, same-directory replace, directory fsync | Short writes, fsync faults, post-rename uncertainty and child-process exit before/after replace tested |
| Distinct unavailable vs missing vs corrupt | Only a missing record in an accessible safe store is missing | Missing directory, busy lock and I/O failure are unknown; malformed/schema/checksum failures are corrupt; neither overwrites/deletes current data |
| Concurrent rotation and stale-reference safety | Account-specific nonblocking advisory flock plus complete handle CAS | Two fresh processes using the same expected handle produce one winner; stale handle rejected; consumption holds shared lock during trusted callback |
| Minimal filesystem access | Existing owned 0700 root; dirfd/no-follow walk; owned regular 0600 single-link files | Ancestor/record/lock symlinks, hard links, FIFO, unsafe existing modes rejected without fixing their modes |

## Narrow trusted interface

```python
store = FileCredentialStore(TrustedConfig(private_directory, account_id))
observed = store.inspect()
# Private acquisition code only; not an MCP/model argument:
saved = store.save(SecretMaterial(private_bytes), expected=observed.handle)
# Private transport code only, after separate account/pause/lease checks:
receipt = store.with_material(saved.handle, trusted_consumer)
```

The example is a contract, **not an instruction to run it with real material**.
The configured directory must already exist, be absolute, and be owned by the
current UID with exact mode 0700. Paths/accounts are trusted host configuration,
not tool inputs. The constructor performs no I/O. First inspection may create an
empty 0600 account lock file. Existing unsafe files/directories are refused, not
chmod/chown repaired. Only newly created lock/temp files are set to mode 0600.

### Results and comparison semantics

- `present`: exact record observed, or replacement confirmed through directory
  fsync; `code` distinguishes `record_observed`, `record_saved` and
  `material_callback_entered`. This is not platform/authentication success.
- `missing`: safe store opened, record absent. A missing/inaccessible directory is
  **unknown**, not proof the user's session disappeared.
- `corrupt`: bounded record fails exact schema, identity, type, JSON/encoding or
  checksum checks. Existing bytes remain untouched.
- `unknown`: busy lock, permission boundary failure, I/O uncertainty, or callback
  uncertainty. No automatic deletion, retry, rescan, refresh or reauthentication.
- `conflict`: expected account/opaque ID/generation no longer matches. No overwrite.
- `rejected`: locally invalid input. Not human denial or account-risk detection.

Create requires `expected=None` and a genuinely missing record. Update requires
an exact `OpaqueHandle` matching the current account, random opaque ID and
positive generation; replacement increments generation and creates a fresh opaque
ID. Account names are bound into both filename namespace and record validation.
An externally removed record may later restart numbering at 1, but its new random
ID prevents an old handle from matching. Whole-file rollback by an attacker or
backup restore is **not** detected; no external monotonic authority exists.

`write_outcome` distinguishes not attempted, definitely not committed before
replacement, confirmed committed, and unknown once replacement could have begun.
If replace or directory fsync fails, do not assert either successful save or lost
session. An explicitly requested later `inspect()` can observe the current record;
it does not silently repeat a write or authenticate it. An exception after a
rename may leave the new valid record, as the tests demonstrate.

Locks are advisory and nonblocking, per account. Cooperating readers share a lock;
writers take an exclusive lock. Busy is returned, not internally retried.
`with_material` checks the complete handle while holding the shared lock and then
enters the **trusted internal** callback. This prevents a cooperating writer from
rotating that generation during its use. The receipt counts callback entries,
not HTTP sends or business completion; even normal callback return is not proof
of business success. Callback returns are discarded and errors are sanitized.
`consumer_outcome_unknown` does not mean credentials became invalid or were
deleted. Future composition must carry a separate typed business outcome and must
not infer business `completed` from storage `present`. An in-flight callback cannot be undone. Slow callbacks delay
cooperating writers, and explicit scheduling/backoff belongs to a future owner.

This port issues **no authorization**. A handle is a reference, not an auth grant.
Caller composition must enforce account pause, current session verification,
lease/capability scope and request lifecycle before consuming material. The old
QR/session/metadata modules are not connected in this change; independent review
precedes any proposed combination.

## Security, durability and remaining risks

- **Plaintext boundary, not encryption.** Base64 is encoding, and the unkeyed SHA256
  checksum only detects accidental corruption; neither prevents deliberate
  tampering. Disk encryption/backups/OS keychain choices require host review, not
  an invented key service in this patch.
- A trusted Python consumer can retain/leak bytes. Python privacy/repr redaction is
  not isolation from malicious same-UID code or root. No zeroization, secure-memory,
  core-dump control or universal secret scanning is claimed. Do not expose material
  objects or arbitrary callbacks through a public/model tool.
- POSIX/Linux APIs and cooperating local filesystem behavior are assumed.
  Network filesystems, Windows/ACL-specific behavior, storage hardware and actual
  power loss are not validated. fsync ordering is implemented; child-process crash
  tests are **not** proof of power-loss durability on every host/filesystem.
- A process killed before replacement can leave a private temporary file. Normal
  failures clean up only their own created temporary file when possible. No orphan
  sweep or record deletion API exists here; retention, explicit revoke/delete,
  backup policy and authorized cleanup remain separate work.
- Exact record bounds (64 KiB private material, 100000-byte envelope, int64
  generation) are defensive engineering choices, not Bilibili platform limits.
- **Local persistence is not permanent environment retention.** These tests show
  cross-process recovery and local process-crash/normal restart behavior on the
  same filesystem. They do not prove that records survive a dot cloud disk reset,
  replacement machine, rollback or a changed environment snapshot. No permanent disk guarantee is inferred from these tests. The intended real
  host must separately establish retention/restore guarantees. This candidate does
  not back up credentials to Drive, GitHub, Library or any new cloud service, and
  does not authorize doing so.
- Real session field serialization, original login integration, production path
  authorization, real restart/NAV reuse, account-wide pending-login ownership and
  all real credential/network acceptance remain untested and unconnected.

## Reproduce, evidence and license

From this candidate directory:

```sh
PYTHONPATH=. python -B -m unittest discover -s tests -v
cd .. && sha256sum -c SHA256SUMS.txt
```

The owner suite has 35 test methods, with fresh child processes for restore,
concurrent writers, and explicit exits 71/72 at replacement boundaries. Socket
construction is trapped in test processes; this guard is not a security sandbox.
Only temporary fake fixture modes are varied in tests. Method counts are not
formal proof, feature-completion percentages or real-account acceptance.

The parent experiment `MANIFEST.json`, `SHA256SUMS.txt` and `TESTING.md` bind
this included candidate and the combined portable synthetic test results.
Internal development logs and private runtime records are not distributed.

Newly authored by dot locally under the existing project's MIT license (`LICENSE`).
The old first-party `SessionStore` contract informed the shape; no third-party
implementation, package, key material or private login fixture was copied.
Local Python 3.12 runtime API docstrings for `os.replace`, `os.fsync` and
`fcntl.flock` were inspected; this is not a claim of current platform API research.

## Source-only experimental distribution

This directory contains only the standalone implementation, synthetic owner tests,
README and MIT license. The parent experiment also includes 18 independent
relationship tests. No material is wired into the QR/session/metadata composition.
Source inclusion is not authorization to save real credentials or enable login.
Do not recursively archive a production storage directory: runtime records, locks,
temporary files and real material must never enter this public source tree.
