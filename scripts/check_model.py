#!/usr/bin/env python3
"""Reproduce finite model evidence and source hashes, without third-party packages."""
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from formal.model import suite
from formal.relay_model import check_relays
from formal.browser_relay_model import check as check_browser
from formal.browser_public_search_model import check as check_search
from formal.browser_video_open_model import check as check_video_open, MUTANTS as VIDEO_OPEN_MUTANTS

if __name__ == '__main__':
    result = suite()
    result['public_search'] = {str(m): check_search(m) for m in (None, 'bypass_source_check', 'capture_before_navigation', 'implicit_replay', 'accept_invalid_capture')}
    result['video_open'] = {str(m): check_video_open(m) for m in (None,) + VIDEO_OPEN_MUTANTS}
    result['browser'] = {str(m): check_browser(m) for m in (None, 'accept_invalid', 'implicit_replay')}
    result['relay'] = {str(m): check_relays(m) for m in (None, 'widen_scope', 'bypass_relay')}
    result['sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted((ROOT / 'formal').glob('*')) if p.suffix in {'.py', '.tla', '.cfg'}}
    print(json.dumps(result, indent=2))
    good = all(r['ok'] for r in result['safe'].values())
    good &= all(not r['ok'] for r in result['mutations'].values())
    good &= result['relay']['None']['ok'] and not result['relay']['widen_scope']['ok'] and not result['relay']['bypass_relay']['ok']
    good &= result['browser']['None']['ok'] and not result['browser']['accept_invalid']['ok'] and not result['browser']['implicit_replay']['ok']
    good &= result['public_search']['None']['ok'] and all(not v['ok'] for k,v in result['public_search'].items() if k != 'None')
    good &= result['video_open']['None']['ok'] and all(not result['video_open'][m]['ok'] for m in VIDEO_OPEN_MUTANTS)
    raise SystemExit(0 if good else 1)
