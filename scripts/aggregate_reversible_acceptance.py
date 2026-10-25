#!/usr/bin/env python3
"""Read-only union of pinned, independently reviewed cases; not a live attestor."""
import argparse
import hashlib
import json
from pathlib import Path

import check_reversible_acceptance as gate


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def reviewed_ids(data):
    return {x['id'] for x in data['leaves'] if x['scope'] == 'included'
            and x['classification_status'] == 'reviewed'
            and x['classification'] not in {'unknown', 'irreversible'}}


def review_artifact_closure(value, root, seen=None):
    """Validate nested explicit digest references without rewriting source bytes."""
    seen = set() if seen is None else seen
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            raw = gate.artifact(value, root)
            identity = (value['path'], value['sha256'])
            if identity not in seen:
                seen.add(identity)
                try:
                    nested = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    nested = None  # Binary/text artifacts are still digest-checked.
                review_artifact_closure(nested, root, seen)
        for child in value.values():
            review_artifact_closure(child, root, seen)
    elif isinstance(value, list):
        for child in value:
            review_artifact_closure(child, root, seen)


def review_evidence(review, root, review_format):
    """Two explicit review formats; never infer approval from prose."""
    gate.require(review_format in {'status_evidence_v1', 'verdict_checks_v1'}, 'unsupported review format')
    if review_format == 'status_evidence_v1':
        gate.require('verdict' not in review, 'ambiguous review format')
        gate.require(review['status'] == 'approved', 'review not approved')
        gate.require(review.get('remaining_conditions_for_this_scoped_leaf') == [], 'review has unresolved conditions')
        refs = review.get('evidence')
        gate.require(isinstance(refs, list) and refs, 'review evidence missing')
        for ref in refs:
            gate.artifact(ref, root)
    else:
        gate.require('status' not in review, 'ambiguous review format')
        gate.require(review.get('verdict') == 'approved', 'review verdict not approved')
        gate.require(review.get('remaining_conditions_for_this_scoped_leaf', []) == [], 'review has unresolved conditions')
        checks = json.loads(gate.artifact(review['checks'], root))
        if 'all_assertions_passed' in checks:
            gate.require(checks['all_assertions_passed'] is True, 'review assertions failed')
        if 'all_assertions_passed' in checks and isinstance(checks.get('checks'), str):
            gate.require(bool(checks['checks'].strip()), 'empty descriptive checks')
        elif 'checks' in checks or 'all_assertions_passed' not in checks:
            assertions = checks.get('checks')
            gate.require(isinstance(assertions, dict) and assertions
                         and all(v is True for v in assertions.values()), 'review checks failed')
        gate.require(bool(review.get('execution_order')) and bool(review.get('actual_outcome')),
                     'verdict review lacks execution findings')


def validate_case(case, trusted_roots, trusted_reviewers, baseline):
    """A root and reviewer are trusted out of band, never by manifest assertion."""
    root = Path(case['evidence_root'])
    gate.require(root.is_absolute(), 'absolute evidence root required')
    root = root.resolve(strict=True)
    gate.require(root.is_dir() and any(root == p for p in trusted_roots),
                 'evidence root not explicitly trusted (exact canonical directory required)')
    raw = gate.artifact(case['matrix'], root)
    matrix = json.loads(raw)
    checked = gate.check(matrix, root)
    gate.require(checked['schema_valid'], 'full candidate validator failed: ' + '; '.join(checked['errors']))
    # Candidates cannot silently redefine the authoritative denominator or catalog provenance.
    gate.require(matrix['source_inventory'] == baseline['source_inventory'], 'inventory provenance differs')
    gate.require(matrix['scope_status'] == baseline['scope_status'], 'scope status differs')
    scope_fields = ('scope', 'classification', 'classification_status', 'operation_kind')
    original = {x['id']: x for x in baseline['leaves']}
    for leaf in matrix['leaves']:
        gate.require(all(leaf.get(k) == original[leaf['id']].get(k) for k in scope_fields),
                     'candidate changes authoritative scope: ' + leaf['id'])
    leaf = next(x for x in matrix['leaves'] if x['id'] == case['leaf_id'])
    gate.require(case['expected_status'] == leaf['status'], 'registered status differs from selected leaf')
    result = {'matrix_sha256': digest(raw), 'status': leaf['status'],
              'blocker': leaf.get('blocker'), 'eligible': False, 'run_identity_verified': False}
    if leaf['status'] != 'accepted':
        if case.get('rejection_review'):
            rejection = json.loads(gate.artifact(case['rejection_review'], root))
            gate.require('status' not in rejection, 'ambiguous rejection review format')
            gate.require(rejection.get('verdict') == 'not_accepted', 'rejection verdict required')
            gate.require(isinstance(rejection.get('reason'), str) and rejection['reason'].strip(),
                         'rejection reason required')
            gate.require(rejection.get('reviewer') in trusted_reviewers, 'rejection reviewer not trusted')
            gate.require(rejection.get('leaf_id') == case['leaf_id'] and rejection.get('run_id') == case['run_id'],
                         'rejection identity mismatch')
            gate.artifact(rejection['passed_checks_reference'], root)
            result.update(review_verdict='not_accepted', rejection_reason=rejection.get('reason'),
                          rejection_review=case['rejection_review'])
        return result
    gate.require(case['leaf_id'] in reviewed_ids(baseline), 'leaf outside authoritative reviewed subset')
    gate.require(case['executor'] and case['executor'] != leaf['review']['reviewer'], 'reviewer is executor')
    gate.require(leaf['review']['reviewer'] in trusted_reviewers, 'reviewer not trusted out of band')
    gate.require(case['review'] == leaf['review']['reference'], 'registered review differs from leaf review')
    review = json.loads(gate.artifact(case['review'], root))
    gate.require(review['reviewer'] == leaf['review']['reviewer'], 'reviewer mismatch')
    gate.require(review['leaf_id'] == case['leaf_id'] and review['run_id'] == case['run_id'],
                 'review identity mismatch')
    review_evidence(review, root, case.get('review_format', 'status_evidence_v1'))
    review_artifact_closure(review, root)
    for phase in gate.PHASES:
        event = json.loads(gate.artifact(leaf['evidence'][phase], root))
        gate.require(event['run_id'] == case['run_id'], 'registered run differs from phase run')
    result.update(eligible=True, run_identity_verified=True, reviewer=review['reviewer'], review_sha256=case['review']['sha256'])
    return result


def aggregate(manifest, trusted_roots, trusted_reviewers, baseline=None):
    baseline = baseline if baseline is not None else json.loads(gate.DEFAULT.read_text())
    report = {'schema_version': 1, 'metric': 'independently_reviewed_live_union_v1',
              'report_valid': False, 'acceptance_complete': False, 'errors': [], 'cases': [],
              'accepted_leaf_ids': [], 'accepted_unique_leaves': 0,
              'reversible_denominator': None,
              'trust': 'Local hashes/validators prove consistency, not live execution. Explicit root/reviewer trust and independent physical observation are required.'}
    try:
        base_check = gate.check(baseline, gate.DEFAULT.parent / 'evidence')
        gate.require(base_check['schema_valid'], 'authoritative baseline invalid')
        gate.require(manifest['schema_version'] == 1 and isinstance(manifest['cases'], list), 'invalid manifest')
        roots = {Path(p).resolve(strict=True) for p in trusted_roots}
        gate.require(bool(roots) or not manifest['cases'], 'explicit trusted roots required')
        ids = [c['case_id'] for c in manifest['cases']]
        gate.require(all(isinstance(x, str) and x for x in ids) and len(ids) == len(set(ids)), 'invalid/duplicate case ID')
        report['baseline'] = {'accepted': base_check['accepted_evidence_records'],
                              'reviewed_subset_denominator': base_check['reviewed_subset_denominator']}
        report['historical'] = {'accepted': 5, 'inventory_denominator': 122,
                                'metric': 'historical_non_round_trip_coverage', 'reused': 0}
        report['reviewed_subset_denominator'] = base_check['reviewed_subset_denominator']
        report['unresolved_leaves'] = base_check['unresolved_leaves']
        report['reversible_denominator'] = base_check['reversible_denominator']
        accepted = set()
        for case in manifest['cases']:
            row = {k: case.get(k) for k in ('case_id', 'leaf_id', 'run_id', 'evidence_root', 'matrix', 'review')}
            try:
                gate.require(all(isinstance(case[k], str) and case[k] for k in ('leaf_id', 'run_id')), 'case identity required')
                row.update(validate_case(case, roots, set(trusted_reviewers), baseline))
                row['valid'] = True
                if row['eligible']:
                    accepted.add(case['leaf_id'])
            except (KeyError, ValueError, TypeError, OSError, StopIteration, AttributeError) as exc:
                row.update(valid=False, eligible=False, error=str(exc))
                report['errors'].append(str(case.get('case_id')) + ': ' + str(exc))
            report['cases'].append(row)
        report['accepted_leaf_ids'] = sorted(accepted)
        report['accepted_unique_leaves'] = len(accepted)
        report['leaves'] = [{'leaf_id': leaf['id'], 'accepted': leaf['id'] in accepted,
                             'case_ids': [r['case_id'] for r in report['cases'] if r['leaf_id'] == leaf['id']],
                             'baseline_status': leaf['status'], 'baseline_blocker': leaf.get('blocker')}
                            for leaf in baseline['leaves']]
        report['report_valid'] = not report['errors']
        report['acceptance_complete'] = (report['report_valid'] and report['reversible_denominator'] is not None
                                         and report['reversible_denominator'] > 0
                                         and len(accepted) == report['reversible_denominator'])
    except (KeyError, ValueError, TypeError, OSError, AttributeError) as exc:
        report['errors'].append(str(exc))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--trusted-root', action='append', default=[], type=Path)
    parser.add_argument('--trusted-reviewer', action='append', default=[])
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    try:
        result = aggregate(json.loads(args.manifest.read_text()), args.trusted_root, args.trusted_reviewer)
    except (ValueError, OSError) as exc:
        result = {'report_valid': False, 'acceptance_complete': False, 'errors': [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['report_valid'] and (not args.require_complete or result['acceptance_complete']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
