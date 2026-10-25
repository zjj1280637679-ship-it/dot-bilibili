"""Opt-in single-call video-reference CLI; not a browser host or MCP server."""
import argparse
import hashlib
import json
import os
import sys

from bili_integration.cli import MAX_REQUEST_BYTES, decode, load_profile
from facade.contracts import envelope
from facade.adapter import ROOT
from bili_distribution.resources import resource_path
from scripts.compose_host_capture_v2 import PINNED_SHA256, compose
from .adapter import read_video
from .contracts import TOOL_DEFINITION


def dispatch(request, *, profile, invocation_id=None):
    if (not isinstance(request, dict) or set(request) != {'tool', 'arguments'}
            or not isinstance(request['arguments'], dict)):
        return envelope(None, code='invalid_arguments', action='correct_arguments')
    if request['tool'] != 'bili_read_video':
        return envelope(None, code='unknown_tool', action='correct_arguments')
    if (not isinstance(invocation_id, str) or not invocation_id
            or len(invocation_id) > 1000):
        return envelope(None, code='host_invocation_required', action='contact_host')
    try:
        invocation_id.encode('utf-8', 'strict')
    except UnicodeError:
        return envelope(None, code='host_invocation_required', action='contact_host')
    return read_video(request['arguments'], profile=profile, invocation_id=invocation_id)


def instructions():
    """Locate/hash the fixed new-route capture only; no browser or ledger I/O."""
    function = compose()
    return {
        'recipe_version': 'host-capture-v2',
        'resources': {
            'capture_recipe': str(ROOT / 'scripts/host_capture_recipes_v2.js'),
            'capture_composer': str(ROOT / 'scripts/compose_host_capture_v2.py'),
            'capture_protocol': str(resource_path('docs/host-capture-recipes-v2.md')),
            'video_reference_guide': str(resource_path('docs/video-reference-v1.md')),
        },
        'capture_recipe_sha256': PINNED_SHA256['host_capture_recipes_v2.js'],
        'components': [dict(path=str(ROOT / 'scripts' / name), sha256=digest)
                       for name, digest in PINNED_SHA256.items()],
        'composed_function_sha256': hashlib.sha256(function.encode('utf-8')).hexdigest(),
        'composition': 'Run the fixed composer locally; evaluate its single returned function with only kind/limit. Never install page globals.',
        'receipt_validation': 'Unchanged Python validators; preserve full observed URL, raw hrefs and capture timestamp.',
        'runtime_root': str(ROOT),
        'native_tool_registration': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['schemas', 'instructions', 'call'])
    parser.add_argument('--profile', default=os.environ.get('BILI_HOST_PROFILE'),
                        help='trusted private JSON profile (0600)')
    parser.add_argument('--invocation-id', help='durably saved trusted host invocation ID')
    args = parser.parse_args(argv)
    if args.action == 'schemas':
        result = [TOOL_DEFINITION]
    elif args.action == 'instructions':
        result = instructions()
    else:
        if not args.profile:
            parser.error('call requires --profile')
        try:
            profile = load_profile(args.profile)
        except (OSError, ValueError, TypeError, RecursionError):
            result = envelope(None, code='host_profile_unavailable', action='contact_host')
        else:
            try:
                request = decode(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
            except (ValueError, UnicodeError, RecursionError):
                result = envelope(None, code='invalid_arguments', action='correct_arguments')
            else:
                result = dispatch(request, profile=profile, invocation_id=args.invocation_id)
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
