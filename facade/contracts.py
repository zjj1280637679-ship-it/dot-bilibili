"""Pure model-facing contract; no host paths or executable arguments."""
import re

SEARCH_READ_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['query', 'select'],
    'properties': {
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 200,
                  'pattern': r'^(?!-)(?!\s*$)[^\u0000-\u001f\u007f]+$'},
        'select': {'type': 'string', 'pattern': r'^(first_visible|BV[0-9A-Za-z]{10})$'},
        'comments': {'type': 'boolean', 'default': False}}}
STATUS_SCHEMA = {'type': 'object', 'additionalProperties': False,
                 'required': ['request_id'], 'properties': {
                     'request_id': {'type': 'string', 'pattern': r'^fr-[0-9a-f]{64}$'}}}

def validate(args):
    if not isinstance(args, dict) or not {'query', 'select'} <= set(args) or set(args) - {'query', 'select', 'comments'}:
        raise ValueError('invalid_arguments')
    q, s = args['query'], args['select']
    if (not isinstance(q, str) or not 1 <= len(q) <= 200 or not q.strip()
            or q.startswith('-')
            or any(ord(c) < 32 or ord(c) == 127 for c in q)
            or not isinstance(s, str) or not re.fullmatch(r'first_visible|BV[0-9A-Za-z]{10}', s)
            or type(args.get('comments', False)) is not bool):
        raise ValueError('invalid_arguments')
    try:
        q.encode('utf-8', 'strict')
    except UnicodeError:
        raise ValueError('invalid_arguments') from None
    return dict(query=q, select=s, comments=args.get('comments', False))

def envelope(request_id, status='failed', data=None, code=None, action='none', comments=False):
    return dict(request_id=request_id, status=status, data=data,
                coverage=dict(scope='visible_subset' if data else 'none', complete=False,
                              comments_requested=comments),
                error=None if code is None else dict(code=code, message=code.replace('_', ' ')),
                next_action=action)

# Portable descriptions only; this does not register tools in any host.
TOOL_DEFINITIONS = [
    {'name': 'bili_search_read', 'description':
     'Search public Bilibili, explicitly select first_visible or an exact BVID from '
     'the fresh results, then read visible video metadata. Uses 4 operations, or 5 '
     'with comments=true (at most 3 current-viewport threads). Navigates the current '
     'host-authorized tab; may affect history/autoplay. No scrolling, replies, '
     'pagination, media comprehension or account writes. Cached retries are not fresh reads.',
     'parameters': SEARCH_READ_SCHEMA},
    {'name': 'bili_status', 'description':
     'Read recorded workflow status using a returned request_id. No browser action, '
     'resume or retry. Interrupted/running ledger entries are unknown without host reconciliation.',
     'parameters': STATUS_SCHEMA}]
