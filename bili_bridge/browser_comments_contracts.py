"""Read currently viewport-intersecting public threads, not stable comment IDs.

Visibility/extraction are trusted-host attestations, not verified DOM geometry.
This module contains no browser executor or caller-supplied selectors/scripts.
"""
import time
from .browser_contracts import BINDING, encoded, digest, fail, text_value, timestamp
from .browser_video_contracts import video_url
from .browser_comment_fields import validate_threads

OPERATION = 'browser.comments.read'
SCHEMA_VERSION = 1
TARGET_FIELD = 'bvid'


def validate_request(req, now=None):
    encoded(req)
    keys = {'protocol_version', 'schema_version', 'operation_id', 'correlation_id', 'operation', 'account_binding', 'effect', 'bvid', 'limit', 'expected_url', 'expected_tab_id', 'issued_at', 'expires_at', 'scope_digest'}
    if not isinstance(req, dict) or set(req) != keys:
        fail('request_schema')
    if (type(req['protocol_version']) is not int or req['protocol_version'] != 1
            or type(req['schema_version']) is not int or req['schema_version'] != SCHEMA_VERSION
            or req['operation'] != OPERATION or req['account_binding'] != BINDING or req['effect'] != 'read'):
        fail('request_scope')
    if type(req['limit']) is not int or not 1 <= req['limit'] <= 3:
        fail('invalid_limit')
    for key in ('operation_id', 'correlation_id', 'expected_tab_id'):
        text_value(req[key], 200)
    video_url(req['expected_url'], req['bvid'])
    start, end = timestamp(req['issued_at']), timestamp(req['expires_at'])
    if not 0 < end-start <= 600 or req['scope_digest'] != digest(req):
        fail('request_integrity')
    if now is not None and not start <= now < end:
        fail('request_expired')
    return req


def validate_receipt(receipt, req, now=None):
    now = time.time() if now is None else now
    validate_request(req, now)
    encoded(receipt)
    keys = {'protocol_version', 'schema_version', 'operation', 'operation_id', 'correlation_id', 'scope_digest', 'observed_url', 'tab_id', 'bvid', 'captured_at', 'source', 'extraction', 'complete', 'status', 'threads', 'error'}
    if not isinstance(receipt, dict) or set(receipt) != keys:
        fail('receipt_schema')
    for key in ('protocol_version', 'schema_version', 'operation', 'operation_id', 'correlation_id', 'scope_digest', 'bvid'):
        if type(receipt[key]) != type(req[key]) or receipt[key] != req[key]:
            fail('receipt_identity')
    if (receipt['source'] != 'browser_dom' or receipt['extraction'] != 'open_shadow_dom'
            or receipt['complete'] is not False or receipt['status'] not in ('observed', 'blocked')):
        fail('receipt_source')
    observed_url = video_url(receipt['observed_url'], receipt['bvid'], allow_tracking=True)
    if observed_url != video_url(req['expected_url'], req['bvid']) or receipt['tab_id'] != req['expected_tab_id']:
        fail('receipt_target')
    captured = timestamp(receipt['captured_at'])
    if not req['issued_at'] <= captured <= now < req['expires_at']:
        fail('receipt_stale')
    validate_threads(receipt['threads'], req['limit'])
    if receipt['status'] == 'blocked':
        if receipt['threads'] or receipt['error'] not in ('target_mismatch', 'login_required', 'captcha', 'browser_unavailable', 'access_denied', 'dom_unavailable'):
            fail('receipt_error')
    elif receipt['error'] is not None:
        fail('receipt_error')
    return dict(receipt, observed_url=observed_url)
