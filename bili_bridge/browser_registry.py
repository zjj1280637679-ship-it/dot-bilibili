"""Closed, explicit operation registry; no caller-selected imports or executors."""
from types import MappingProxyType
from . import browser_contracts as search
from . import browser_video_contracts as video
from . import browser_comments_contracts as comments
from . import browser_public_search_contracts as public_search
from . import browser_video_open_contracts as video_open

CONTRACTS = MappingProxyType({search.OPERATION: search, video.OPERATION: video, comments.OPERATION: comments, public_search.OPERATION: public_search, video_open.OPERATION: video_open})
NAVIGATION_CONTRACTS = MappingProxyType({public_search.OPERATION: public_search, video_open.OPERATION: video_open})


def contract(operation):
    if not isinstance(operation, str) or operation not in CONTRACTS:
        search.fail('unsupported_browser_operation')
    return CONTRACTS[operation]


def validate_request(req, now=None):
    if not isinstance(req, dict):
        search.fail('request_schema')
    return contract(req.get('operation')).validate_request(req, now)


def validate_receipt(receipt, req, now=None):
    validate_request(req, now)
    return contract(req['operation']).validate_receipt(receipt, req, now)


def make_request(operation, operation_id, correlation_id, target, url, tab, now, timeout, *, limit=None, selection=None):
    schema = contract(operation)
    if limit is not None and schema is not comments:
        search.fail('request_scope')
    if schema is video_open:
        return video_open.make_request(operation_id, correlation_id, target, url, tab, now, timeout, selection)
    if selection is not None:
        search.fail('request_scope')
    if schema is public_search:
        return public_search.make_request(operation_id, correlation_id, target, url, tab, now, timeout)
    req = dict(protocol_version=1, operation_id=operation_id, correlation_id=correlation_id,
               operation=operation, account_binding=search.BINDING, effect='read',
               expected_url=url, expected_tab_id=tab, issued_at=now, expires_at=now+timeout)
    req['bvid' if schema in (video, comments) else 'query'] = target
    if schema in (video, comments):
        req['schema_version'] = schema.SCHEMA_VERSION
    if schema is comments:
        req['limit'] = limit
    req['scope_digest'] = search.digest(req)
    return validate_request(req, now)
