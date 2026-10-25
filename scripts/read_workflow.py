#!/usr/bin/env python3
"""Bounded host-mediated workflow. No browser driver; host must serve each request."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import tempfile
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
# Existing CLI always constructs FileBrowserHost with its 5-second cooldown.
COOLDOWN_SECONDS = 5.1


def source_digest():
    paths = sorted((ROOT / 'bili_bridge').glob('*.py')) + [Path(__file__).resolve()]
    return hashlib.sha256(b''.join(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes() for p in paths)).hexdigest()


MAX_OUTPUT = 2 * 1024 * 1024
MAX_STATE = 12 * 1024 * 1024


def load(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('invalid_state_file')
        raw = stream.read(MAX_STATE + 1)
        if len(raw) > MAX_STATE:
            raise ValueError('oversize_state')
        return json.loads(raw)


def save(path, value):
    fd, name = tempfile.mkstemp(prefix='.workflow-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def invoke(args):
    timeout = int(args[args.index('--timeout') + 1]) + 30
    process = subprocess.Popen([sys.executable, '-m', 'bili_bridge', *args], cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('child_timeout')
                for key, _ in selector.select(min(remaining, 1)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_OUTPUT:
                            raise ValueError('oversize_cli_output')
        process.wait(timeout=max(0.01, deadline - time.monotonic()))
        value = json.loads(output)
        if not isinstance(value, dict) or process.returncode not in (0, 1):
            raise ValueError('invalid_cli_result')
        return value
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def observed(value, operation_id):
    data = value.get('data', {})
    return (value.get('operation_id') == operation_id and value.get('status') == 'applied'
            and value.get('error') is None and data.get('source') == 'browser_dom'
            and data.get('status') == 'observed')


def execute(config, path, runner=invoke, sleeper=time.sleep):
    """Caller holds session lock. CLI result is the only business-layer interface."""
    if path.exists():
        record = load(path)
        if record['intent'] != config:
            return {'status': 'failed', 'reason': 'workflow_identity_conflict'}
        if record['status'] == 'running':
            return {**record, 'status': 'unknown', 'reason': 'prior_execution_unresolved_no_replay'}
        return record
    record = {'schema_version': 1, 'intent': config, 'status': 'running',
              'steps': [], 'pending_operation_id': None, 'complete': False}
    save(path, record)
    bvid = config.get('bvid')
    video_url = None
    search_url = None
    commands = ['browser-public-search', 'browser-read', 'browser-video-open', 'browser-video-read']
    if config['comments']:
        commands.append('browser-comments-read')
    for index, command in enumerate(commands):
        if index:
            sleeper(COOLDOWN_SECONDS)  # Before open consumes the source; never replay on deferral.
        operation_id = 'wf-' + hashlib.sha256(config['id'].encode()).hexdigest()[:32] + '-' + str(index)
        args = ['--db', config['db'], command, '--spool', config['spool'],
                '--timeout', str(config['timeout']), '--operation-id', operation_id]
        if index == 0:
            args += ['--query', config['query'], '--source-url', config['source_url'], '--tab', config['tab']]
        elif index == 1:
            args += ['--query', config['query'], '--url', search_url, '--tab', config['tab']]
        elif index == 2:
            args += ['--source-operation-id', record['steps'][1]['operation_id'], '--bvid', bvid]
        else:
            args += ['--bvid', bvid, '--url', video_url, '--tab', config['tab']]
        record['pending_operation_id'] = operation_id
        save(path, record)  # Durable intent MUST precede any possible host emission.
        try:
            value = runner(args)
            if (not isinstance(value, dict) or not isinstance(value.get('data'), dict)
                    or not isinstance(value.get('status'), str)
                    or value.get('operation_id') != operation_id):
                raise ValueError('malformed_cli_result')
        except Exception:
            record.update(status='unknown', reason='child_outcome_unknown_no_replay')
            save(path, record)
            return record
        record['steps'].append(value)
        record['pending_operation_id'] = None
        if not observed(value, operation_id):
            record.update(status='unknown' if value.get('status') == 'unknown' else ('partial' if index else 'failed'),
                          reason='step_not_observed')
            save(path, record)
            return record
        data = value['data']
        if index in (0, 1):
            if (data.get('query') != config['query'] or data.get('tab_id') != config['tab']
                    or not isinstance(data.get('observed_url'), str)
                    or (index == 1 and data['observed_url'] != search_url)):
                record.update(status='unknown', reason='search_handoff_mismatch')
                save(path, record)
                return record
            if index == 0:
                search_url = data['observed_url']
            items = data.get('items')
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                record.update(status='unknown', reason='malformed_search_items')
                save(path, record)
                return record
            if index == 0:
                save(path, record)
                continue  # Explicit fresh read follows; selection uses only that receipt.
            if config['selection'] == 'first-visible-video':
                bvid = items[0].get('bvid') if items else None
            if not bvid or not any(item.get('bvid') == bvid for item in items):
                record.update(status='partial', reason='exact_selection_absent')
                save(path, record)
                return record
            record['selected_bvid'] = bvid
        elif index == 2:
            if data.get('bvid') != bvid or data.get('tab_id') != config['tab']:
                record.update(status='unknown', reason='open_handoff_mismatch')
                save(path, record)
                return record
            video_url = data.get('observed_url')
            if video_url != 'https://www.bilibili.com/video/' + bvid + '/':
                record.update(status='unknown', reason='open_url_handoff_mismatch')
                save(path, record)
                return record
        elif index >= 3:
            if (data.get('bvid') != bvid or data.get('tab_id') != config['tab']
                    or data.get('observed_url') != video_url):
                record.update(status='unknown', reason='read_handoff_mismatch')
                save(path, record)
                return record
        save(path, record)
    record.update(status='succeeded_visible_subset', coverage='visible_subset', reason=None)
    save(path, record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('db', 'spool', 'id', 'query', 'source-url', 'tab'):
        parser.add_argument('--' + key, required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--bvid')
    choice.add_argument('--selection', choices=['first-visible-video'])
    parser.add_argument('--comments', action='store_true', help='also read current viewport, never scroll')
    parser.add_argument('--timeout', type=int, default=120, choices=range(1, 601), metavar='1..600')
    a = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', a.id):
        parser.error('--id must be 1..80 ASCII letters/digits/_/-')
    config = vars(a).copy()
    config.update(db=str(Path(a.db).resolve()), spool=str(Path(a.spool).resolve()),
                  source_root=str(ROOT), source_digest=source_digest())
    # One fixed private workflow store alongside this SAME journal, never inside spool.
    state = Path(config['db'] + '.workflows')
    state.mkdir(mode=0o700, parents=False, exist_ok=True)
    if state.is_symlink() or state.stat().st_mode & 0o077:
        parser.error('workflow state directory must be private and not a symlink')
    fd = os.open(state / 'session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ValueError('invalid_lock_file')
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status': 'failed', 'reason': 'workflow_session_busy'}))
            return 1
        binding = state / 'binding.json'
        expected = {'db': config['db'], 'spool': config['spool']}
        if binding.exists() and load(binding) != expected:
            print(json.dumps({'status': 'failed', 'reason': 'session_binding_conflict'}))
            return 1
        if not binding.exists():
            save(binding, expected)
        result = execute(config, state / (a.id + '.json'))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] == 'succeeded_visible_subset' else 1


if __name__ == '__main__':
    try:
        code = main()
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'status': 'unknown', 'reason': 'workflow_local_state_unavailable_no_replay'}))
        code = 1
    raise SystemExit(code)
