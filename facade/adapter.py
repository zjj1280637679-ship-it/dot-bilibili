"""Fixed-source synchronous subprocess adapter. Trusted host services its spool.

The host must persist/reuse invocation_id. No browser driver or registration is
provided. Workflow ledger is authoritative; there is no second operation ledger.
"""
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
import os
import selectors
import time
from types import SimpleNamespace
from pathlib import Path
import re
import subprocess
import sys
from .contracts import validate, envelope
from . import projection

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_facade_workflow', ROOT / 'scripts/read_workflow.py')
workflow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(workflow)

@dataclass(frozen=True)
class HostProfile:
    db: str
    spool: str
    source_url: str
    tab: str
    timeout: int = 120

    def __post_init__(self):
        if not Path(self.db).is_absolute() or not Path(self.spool).is_absolute():
            raise ValueError('host_paths_must_be_absolute')
        if type(self.timeout) is not int or not 1 <= self.timeout <= 600:
            raise ValueError('invalid_host_timeout')


def _id(invocation_id):
    if not isinstance(invocation_id, str) or not invocation_id or len(invocation_id) > 1000:
        raise ValueError('trusted_invocation_id_required')
    return 'fr-' + hashlib.sha256(invocation_id.encode('utf-8')).hexdigest()


def _read(profile, request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r'fr-[0-9a-f]{64}', request_id):
        raise ValueError('invalid_arguments')
    directory = Path(str(Path(profile.db).resolve()) + '.workflows')
    if not directory.exists():
        return None
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise ValueError('state_unavailable')
    path = directory / (request_id + '.json')
    if not path.exists():
        return None
    record = workflow.load(path)  # Existing O_NOFOLLOW, regular-file and size checks.
    if not isinstance(record, dict) or not isinstance(record.get('intent'), dict):
        raise ValueError('malformed_intent')
    intent = record['intent']
    if (type(record.get('schema_version')) is not int or record.get('schema_version') != 1 or intent.get('source_digest') != workflow.source_digest()):
        raise ValueError('state_version_conflict')
    if (intent['id'] != request_id or intent['db'] != str(Path(profile.db).resolve())
            or intent['spool'] != str(Path(profile.spool).resolve())
            or intent['source_root'] != str(ROOT)):
        raise ValueError('state_binding_conflict')
    return record


def _project(request_id, record, comments=False):
    if not isinstance(record, dict) or not isinstance(record.get('steps', []), list):
        raise ValueError('malformed_record')
    state = record.get('status')
    states = {'succeeded_visible_subset': 'succeeded', 'partial': 'partial',
              'failed': 'failed', 'unknown': 'unknown', 'running': 'unknown'}
    state = states.get(state, 'unknown')
    if not all(isinstance(s, dict) and isinstance(s.get('data'), dict) for s in record.get('steps', [])):
        raise ValueError('malformed_step')
    selected = record.get('selected_bvid')
    if selected is not None and (not isinstance(selected, str) or not re.fullmatch(r'BV[0-9A-Za-z]{10}', selected)):
        raise ValueError('malformed_selection')
    if state == 'succeeded' and (len(record.get('steps', [])) != (5 if comments else 4)
            or not all(workflow.observed(s, s.get('operation_id')) for s in record['steps'])):
        raise ValueError('incomplete_success')
    data = {}
    observations = []
    steps = record.get('steps', [])
    if len(steps) > 5:
        raise ValueError('malformed_steps')
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get('data'), dict):
            raise ValueError('malformed_step')
        d = step['data']
        if not workflow.observed(step, step.get('operation_id')):
            continue
        captured = d.get('captured_at')
        if captured is not None and (type(captured) not in (int, float) or not math.isfinite(captured)):
            raise ValueError('invalid_capture')
        if d.get('coverage', 'visible_subset') not in (('destination_only','visible_subset') if index == 2 else ('visible_subset',)):
            raise ValueError('invalid_coverage')
        observations.append(dict(stage=['search','search_read','open','video','comments'][index],
                                 source='browser_dom', captured_at=captured,
                                 coverage=d.get('coverage','visible_subset'), complete=False))
        if index in (0, 1):
            data['search_items'] = projection.search(d['items'])
        elif index == 3:
            data['video'] = projection.video(d)
        elif index == 4:
            data['comments'] = projection.comments(d['threads'])
    if data:
        data = dict(search_items=[], selected_bvid=record.get('selected_bvid'),
                    video=None, comments=None) | data
    # Never expose arbitrary exception/receipt strings or internal identities.
    reason = record.get('reason')
    codes = {'exact_selection_absent': 'selection_not_found',
             'workflow_identity_conflict': 'request_conflict',
             'workflow_session_busy': 'session_busy',
             'session_binding_conflict': 'host_binding_conflict'}
    code = None if state == 'succeeded' else codes.get(reason, 'outcome_unknown' if state == 'unknown' else 'workflow_stopped')
    if state != 'succeeded':
        for step in reversed(steps):
            if isinstance(step.get('error'), str) and step['error'] in projection.SAFE_ERRORS:
                code = step['error']
                break
    action = 'none' if state == 'succeeded' else 'contact_host'
    out = envelope(request_id, state, data or None, code, action, comments)
    out['coverage']['observations'] = observations
    if len(json.dumps(out, ensure_ascii=False).encode('utf-8')) > 262144:
        return envelope(request_id, 'unknown', code='result_too_large', action='contact_host', comments=comments)
    return out


def status(args, *, profile):
    """bili_status: no subprocess, browser request, resume, or state mutation."""
    request_id = args.get('request_id') if isinstance(args, dict) else None
    if (not isinstance(args, dict) or set(args) != {'request_id'}
            or not isinstance(request_id, str) or not re.fullmatch(r'fr-[0-9a-f]{64}', request_id)):
        return envelope(None, code='invalid_arguments', action='correct_arguments')
    try:
        record = _read(profile, request_id)
        if record is None:
            return envelope(request_id, code='request_not_found', action='contact_host')
        return _project(request_id, record, record['intent']['comments'])
    except (OSError, ValueError, KeyError, TypeError):
        return envelope(request_id, 'unknown', code='state_unavailable', action='contact_host')


def _run_bounded(command, *, cwd, stdout, stderr, timeout, check):
    process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                for key, _ in selector.select(min(remaining, 1)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > workflow.MAX_STATE:
                            raise ValueError('oversize_workflow_output')
        code = process.wait(timeout=max(0.01, deadline-time.monotonic()))
        return SimpleNamespace(returncode=code, stdout=bytes(output))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def search_read(args, *, profile, invocation_id, runner=_run_bounded):
    """bili_search_read: run fixed existing CLI; host must dispatch concurrently."""
    request_id = _id(invocation_id)  # Trusted integration error, not model input.
    try:
        args = validate(args)
        from bili_bridge.browser_public_search_contracts import destination
        destination(args['query'])
    except ValueError:
        return envelope(request_id, code='invalid_arguments', action='correct_arguments')
    comments = args['comments']
    try:
        record = _read(profile, request_id)
        if record is not None:
            intent = record['intent']
            selection = 'first-visible-video' if args['select'] == 'first_visible' else None
            bvid = None if selection else args['select']
            if (intent['query'], intent['selection'], intent['bvid'], intent['comments']) != (args['query'], selection, bvid, comments):
                return envelope(request_id, code='request_conflict', action='contact_host', comments=comments)
            # Cached evidence, not a new read; no child even if source changed.
            return _project(request_id, record, comments)
        command = [sys.executable, str(ROOT / 'scripts/read_workflow.py'),
                   '--db', profile.db, '--spool', profile.spool, '--id', request_id,
                   '--query', args['query'], '--source-url', profile.source_url,
                   '--tab', profile.tab, '--timeout', str(profile.timeout)]
        command += ['--selection', 'first-visible-video'] if args['select'] == 'first_visible' else ['--bvid', args['select']]
        if comments:
            command += ['--comments']
        result = runner(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        timeout=5 * (profile.timeout + 30) + 30, check=False)
        if result.returncode not in (0, 1) or len(result.stdout) > workflow.MAX_STATE:
            raise ValueError('invalid_workflow_output')
        record = json.loads(result.stdout)
        if isinstance(record, dict) and ('intent' in record or record.get('status') == 'succeeded_visible_subset'):
            persisted = _read(profile, request_id)
            if persisted != record:
                raise ValueError('workflow_output_binding')
        return _project(request_id, record, comments)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return envelope(request_id, 'unknown', code='outcome_unknown', action='contact_host', comments=comments)
