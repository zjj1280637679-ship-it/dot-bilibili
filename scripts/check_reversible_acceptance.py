#!/usr/bin/env python3
"""Offline, fail-closed evidence gate. Does not execute or authenticate live actions."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path

PHASES = ('before', 'action', 'after', 'restore', 'final')
CLASSES = {'reversible_ui', 'state_restorable_external_with_residual_effects',
           'irreversible', 'unknown', 'observation_only'}
CATALOG_IDS_SHA256 = '0a711f779d2bf62507f898d0e5ed794f253606895117dce59502ca5d4ea3b43b'
DEFAULT = Path(__file__).resolve().parents[1] / 'acceptance/reversible-v1.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def artifact(ref, root):
    """Accept only explicitly supplied local files, never URLs or arbitrary paths."""
    require(isinstance(ref, dict), 'artifact reference required')
    path = Path(ref['path'])
    require(not path.is_absolute() and '..' not in path.parts, 'unsafe artifact path')
    path = (root / path).resolve()
    require(path.is_relative_to(root.resolve()), 'artifact escapes evidence root')
    raw = path.read_bytes()
    require(bool(raw), 'empty artifact')
    require(hashlib.sha256(raw).hexdigest() == ref['sha256'], 'artifact digest mismatch')
    return raw


def round_trip(leaf, root):
    require(leaf['scope'] == 'included', 'not included')
    require(leaf['classification_status'] == 'reviewed', 'classification not reviewed')
    require(leaf['classification'] in CLASSES - {'irreversible', 'unknown'}, 'not reversible')
    observation_only = leaf['classification'] == 'observation_only'
    require(leaf['operation_kind'] == ('read_or_derive' if observation_only else 'state_change'),
            'operation kind and classification disagree')
    auth = leaf['authorization']
    require(auth['status'] == 'approved' and auth['target'], 'authorization missing')
    artifact(auth['reference'], root)
    contract = leaf['state_contract']
    require(isinstance(contract, dict) and contract.get('route') and contract.get('state_keys')
            and contract.get('action') and contract.get('inverse') and contract.get('residual_effects') is not None,
            'exact state contract required')
    require(len(set(contract['state_keys'])) == len(contract['state_keys']), 'duplicate state keys')
    if contract['residual_effects'] or leaf['classification'] == 'state_restorable_external_with_residual_effects':
        require(auth['residual_effects_approved'] is True, 'residual effects not approved')
    review = leaf['review']
    require(review['status'] == 'approved' and review['reviewer'], 'review required')
    artifact(review['reference'], root)
    events = []
    for phase in PHASES:
        raw = artifact(leaf['evidence'][phase], root)
        event = json.loads(raw)
        require(event['phase'] == phase and event['leaf_id'] == leaf['id'], 'phase/leaf mismatch')
        require(event['mode'] == 'live' and event['outcome'] == 'success', 'not successful live evidence')
        require(event['target'] == auth['target'] and event['route'] == contract['route'], 'target/route mismatch')
        require(bool(event['run_id']), 'run identity missing')
        timestamp = datetime.fromisoformat(event['observed_at'].replace('Z', '+00:00'))
        require(timestamp.tzinfo is not None, 'timestamp must be timezone-aware')
        capture = json.loads(artifact(event['observation'], root))
        require(capture['source'] in {'host_dom', 'api_response'}, 'structured observation required')
        require(capture['target'] == event['target'] and capture['observed_at'] == event['observed_at']
                and capture['run_id'] == event['run_id'], 'observation identity mismatch')
        if phase in {'before', 'after', 'final'}:
            require(set(event['state']) == set(contract['state_keys']), 'state projection mismatch')
            require(capture['state'] == event['state'], 'observation state mismatch')
        else:
            require(bool(event['operation']), 'operation record missing')
            require(capture['operation'] == event['operation'] and capture['outcome'] == 'success',
                    'observation operation mismatch')
        events.append((event, timestamp))
    require(len({e['run_id'] for e, _ in events}) == 1, 'mixed runs')
    require(all(a[1] < b[1] for a, b in zip(events, events[1:])), 'non-sequential observations')
    before, after, final = (events[i][0]['state'] for i in (0, 2, 4))
    if observation_only:
        require(before == after and contract['inverse'] == 'verified_no_op', 'read changed scoped state')
    else:
        require(before != after, 'no-op is not a state-change trial')
    require(after == contract['expected_after'], 'action postcondition mismatch')
    require(before == final, 'original scoped state not restored')
    require(events[1][0]['operation'] == contract['action'], 'action mismatch')
    require(events[3][0]['operation'] == contract['inverse'], 'inverse mismatch')


def check(data, evidence_root):
    if not isinstance(data, dict) or not isinstance(data.get('leaves'), list) or not all(isinstance(x, dict) for x in data['leaves']):
        return {'schema_valid': False, 'acceptance_complete': False, 'errors': ['matrix object with leaf objects required']}
    errors = []
    leaves = data.get('leaves', [])
    try:
        require(data['schema_version'] == 1 and data['metric'] == 'scoped_live_round_trip_v1', 'unsupported schema')
        require(data['source_inventory']['leaf_count'] == len(leaves) == 122, 'catalog must retain 122 leaves')
        require(len({x['id'] for x in leaves}) == len(leaves), 'duplicate leaf ID')
        require(hashlib.sha256('\n'.join(sorted(x['id'] for x in leaves)).encode()).hexdigest() == CATALOG_IDS_SHA256,
                'catalog leaf IDs differ from frozen inventory')
        require(data['scope_status'] in {'unresolved', 'reviewed'}, 'invalid scope status')
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    accepted = 0
    for leaf in leaves:
        try:
            require(isinstance(leaf['id'], str) and bool(leaf['id']), 'leaf ID required')
            require(leaf['classification'] in CLASSES, 'invalid classification')
            require(bool(leaf.get('restoration_scope')), 'restoration scope required')
            require(isinstance(leaf.get('irreversible_residuals'), list), 'residual list required')
            require(leaf['classification_status'] in {'provisional', 'reviewed'}, 'invalid classification status')
            require(leaf['scope'] in {'unresolved', 'included', 'excluded'}, 'invalid scope')
            require(leaf['status'] in {'not_run', 'blocked', 'failed', 'accepted'}, 'invalid execution status')
            require(leaf['historical_evidence_carried_forward'] is False, 'historical acceptance cannot be promoted')
            require(set(leaf['evidence']) == set(PHASES), 'five evidence slots required')
            if leaf['scope'] == 'excluded':
                require(bool(leaf.get('exclusion_reason')), 'exclusion reason required')
            if leaf['status'] == 'accepted':
                round_trip(leaf, evidence_root)
                accepted += 1
            else:
                require(bool(leaf['blocker']), 'unfinished leaf needs blocker')
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"{leaf.get('id', '?')}: {exc}")
    unresolved = sum(x.get('scope') == 'unresolved' or x.get('classification_status') != 'reviewed' for x in leaves)
    included = sum(x.get('scope') == 'included' for x in leaves)
    finalized = data.get('scope_status') == 'reviewed' and unresolved == 0
    for leaf in leaves:
        if leaf.get('scope') == 'included' and (leaf.get('classification') in {'unknown', 'irreversible'}
                                               or (leaf.get('operation_kind') != 'state_change' and leaf.get('classification') != 'observation_only')):
            errors.append(f"{leaf['id']}: included leaf is not a reviewed reversible state change")
    if data.get('scope_status') == 'reviewed' and unresolved:
        errors.append('scope marked reviewed with unresolved leaves')
    reviewed_subset = sum(x.get('scope') == 'included' and x.get('classification_status') == 'reviewed'
                          and x.get('classification') not in {'unknown', 'irreversible'} for x in leaves)
    denominator = included if finalized and not errors else None
    return {'schema_valid': not errors, 'errors': errors,
            'classification_counts': dict(Counter(x.get('classification') for x in leaves)),
            'unresolved_leaves': unresolved, 'proposed_included': included,
            'reviewed_subset_denominator': reviewed_subset,
            'reviewed_subset_observation_only': sum(x.get('scope') == 'included' and x.get('classification_status') == 'reviewed' and x.get('classification') == 'observation_only' for x in leaves),
            'accepted_evidence_records': accepted, 'reversible_denominator': denominator,
            'acceptance_complete': not errors and denominator is not None and denominator > 0 and accepted == denominator,
            'live_authenticity': 'Requires independent observation/review; hashes prove file integrity only.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('matrix', nargs='?', type=Path, default=DEFAULT)
    parser.add_argument('--evidence-root', type=Path, default=DEFAULT.parent / 'evidence')
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args()
    try:
        result = check(json.loads(args.matrix.read_text()), args.evidence_root)
    except (OSError, ValueError, TypeError) as exc:
        result = {'schema_valid': False, 'acceptance_complete': False, 'errors': [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['schema_valid'] and (not args.require_complete or result['acceptance_complete']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
