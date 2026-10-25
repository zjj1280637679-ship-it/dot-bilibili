# Reviewed live evidence union (offline, read-only)

`aggregate_reversible_acceptance.py` composes existing evidence; it never executes a
browser operation, writes a ledger, edits evidence, or turns synthetic tests into
live acceptance. Run it from `scripts/`, or invoke its absolute path.

## Inputs and trust boundary

The **private**, operator-curated manifest has `schema_version: 1` and a `cases`
array. Each case contains:

```json
{
  "case_id": "stable-attempt-id",
  "leaf_id": "video.metadata.visible.read",
  "run_id": "actual-run-id",
  "expected_status": "accepted",
  "executor": "actual-executing-observer",
  "evidence_root": "/private/exact/case-directory",
  "matrix": {"path": "candidate-matrix.json", "sha256": "actual-file-digest"},
  "review": {"path": "review.json", "sha256": "actual-file-digest"}
}
```

Do not copy this example into an acceptance manifest as evidence. Real paths,
identities, file digests, failed attempts and raw observations remain private.
`expected_status` must match the selected matrix leaf. Nonaccepted cases need no
approved review; their full candidate matrix, status and blocker remain visible.

```sh
python scripts/aggregate_reversible_acceptance.py /private/manifest.json \
  --trusted-root /private/exact/case-directory \
  --trusted-reviewer /actual/independent/reviewer > /private/union-report.json
```

Repeat trust flags for additional directories/reviewers. The manifest cannot grant
itself trust. Roots must match exact canonical directories explicitly supplied by
the operator, not just reside under a broad shared parent. Matrix, phase,
observation, authorization, review and review evidence references are checked
inside that case's directory using the existing artifact validator, including
SHA-256 and resolved-path containment. Absolute/traversing/escaping symlink
references are rejected. The root itself may have a canonical alias; only its
resolved directory is the security boundary. Do not run against concurrently
writable/untrusted directories: this is not an atomic snapshot or OS sandbox.

The operator must independently authenticate executor and reviewer identities
and approve the manifest/root/reviewer set based on actual observation. Review files are not signed or cryptographically bound to the whole candidate;
the operator must verify that the pinned candidate is the one actually reviewed. Names,
`mode: live`, approval strings and hashes are **not cryptographic proof of live
execution**. A malicious operator or compromised trusted observer can fabricate
a consistent bundle. Preventing that requires trusted tool/host observations and
independent review, not another JSON schema. This program deliberately makes
that dependency explicit rather than claiming that format validity authenticates
physical actions. No additional browser accounting system is introduced.

## Composition contract

* The repository baseline is the sole authoritative scope/denominator. Every
  candidate must pass the complete existing `check_reversible_acceptance.check`,
  retain inventory provenance, and match baseline scope/classification/operation
  fields for **all 122** leaves. Scope changes require separately reviewed baseline
  changes, not a private candidate redefining the denominator.
* Only the manifest's selected leaf can earn credit from a candidate. Accepted
  candidates require approved review content, matching reviewer/leaf/run identity,
  an executor distinct from the trusted reviewer, no remaining review conditions,
  valid review-linked evidence and five matching phase run IDs. Nonaccepted case
  run IDs are registration metadata only (`run_identity_verified: false`). The existing gate
  validates target, route, timestamps, phase observations, action postcondition,
  inverse and equality of declared before/final state.
* Unique stable leaf IDs form the accepted union. Repeated cases/runs never add
  leaf coverage. Duplicate case IDs are rejected. Cases remain separate records,
  so later success does not overwrite a registered failure or invalid trial.
* A malformed/tampered case is ineligible and sets `report_valid: false` and a
  nonzero exit code; independent valid cases remain inspectable in the report.
  Such a report must **not** be advertised as a clean aggregate. A legitimate
  failed/not-run/blocked case is preserved without invalidating another successful
  trial. `acceptance_complete` additionally requires a finalized nonzero denominator.
* The report distinguishes baseline **0/5**, current reviewed unique-leaf union
  **N/5**, and separately labelled historical non-round-trip **5/122** with zero
  reused evidence. The historical field is contextual provenance, not validated
  live evidence. Full reversible denominator remains `null` while scope is
  unresolved (currently 117 leaves). No overall completion percentage is invented.
* The manifest is a curated case index, not an exhaustive discovery mechanism.
  Every known prior failed/blocked trial should be registered when representable
  as a full candidate matrix; otherwise preserve and disclose its source diagnostic
  records in review evidence. Absence from the manifest is not proof no trial failed.

The report includes every baseline leaf and its case IDs, baseline status/blocker,
and union acceptance. This preserves unknown inventory entries rather than
silently reducing the denominator. It does not establish that side effects outside
the declared state projection were undone.

## Verification

```sh
python -m unittest discover -s tests -p 'test*reversible_acceptance.py' -v
```

Synthetic fixtures test composition, failure propagation and rejection boundaries
only. The user's actual completion condition still requires successful **real
execution and observed restoration for every ultimately in-scope reversible leaf**,
with independently reviewed evidence for each.

### Explicit review formats

Manifest `review_format` is `status_evidence_v1` by default (the original metadata
review). The alternative `verdict_checks_v1` accepts an explicit `verdict: approved`,
matching reviewer/leaf/run identities, nonempty execution-order/outcome findings,
and a digest-pinned `checks` artifact. That artifact must have boolean
`all_assertions_passed: true`, or a nonempty `checks` map whose values are all the
boolean `true`; if both boolean assertion forms occur both must pass. When the aggregate boolean
is present, a nonempty string `checks` is descriptive prose only, never a truth
value; aggregate approval still requires `all_assertions_passed is True`. Truthy strings/numbers are not
accepted. Mixed `status`/`verdict` review formats and unknown format selectors fail.
An explicitly nonempty remaining-conditions list fails either format. In the
verdict format, the trusted reviewer's explicit unqualified approved verdict is
the assertion of no blocking conditions; this is not inferred from prose.

For a nonaccepted case, an optional digest-pinned `rejection_review` retains a
trusted matching reviewer/leaf/run `verdict: not_accepted`, reason and checked
`passed_checks_reference` artifact. It cannot earn acceptance even when underlying
browser execution applied successfully. Original candidate/review bytes are never
normalized or rewritten to fit either format.

Approved review artifacts also receive recursive closure validation: every nested
explicit `{path, sha256}` reference is checked under the same exact case root;
JSON artifact descendants are traversed once per reference. This binds a nested
post-run executor attestation without changing its provenance: an attestation is
still a trusted person's retrospective statement, not an original parameter log
or independent automated causal audit. Non-JSON artifacts remain digest-checked.
