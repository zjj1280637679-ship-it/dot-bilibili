"""Open one exact result from a journal-backed, single-use search snapshot."""
import time
import re
from .browser_contracts import BINDING, encoded, digest, fail, text_value, timestamp
from .browser_video_contracts import video_url
from .browser_public_search_contracts import source_url, identity
from .browser_contracts import search_url

OPERATION = 'browser.video.open'
SCHEMA_VERSION = 1
MAX_SNAPSHOT_AGE = 600
SELECTION_KEYS = {'source_operation_id', 'source_scope_digest', 'source_captured_at',
                  'query', 'source_url', 'source_tab_id'}


def make_request(operation_id, correlation_id, bvid, url, tab, now, timeout, selection):
    if not isinstance(selection, dict) or set(selection) != SELECTION_KEYS:
        fail('selection_schema')
    req = dict(protocol_version=1, schema_version=1, operation=OPERATION,
        operation_id=operation_id, correlation_id=correlation_id, account_binding=BINDING,
        effect='read', bvid=bvid, destination_url=video_url(url, bvid),
        issued_at=now, expires_at=min(now+timeout, selection['source_captured_at']+MAX_SNAPSHOT_AGE),
        **selection)
    if tab != req['source_tab_id']:
        fail('selection_target')
    req['scope_digest'] = digest(req)
    return validate_request(req, now)


def validate_request(req, now=None):
    encoded(req)
    keys = SELECTION_KEYS | {'protocol_version','schema_version','operation','operation_id',
        'correlation_id','account_binding','effect','bvid','destination_url','issued_at','expires_at','scope_digest'}
    if not isinstance(req, dict) or set(req) != keys:
        fail('request_schema')
    if (type(req['protocol_version']) is not int or req['protocol_version'] != 1
        or type(req['schema_version']) is not int or req['schema_version'] != 1
        or req['operation'] != OPERATION or req['account_binding'] != BINDING or req['effect'] != 'read'):
        fail('request_scope')
    for key in ('operation_id','correlation_id','source_operation_id','source_scope_digest','source_tab_id'):
        text_value(req[key],200)
    if not re.fullmatch(r'[0-9a-f]{64}',req['source_scope_digest']):
        fail('selection_digest')
    text_value(req['query'],200)
    search_url(req['source_url'],req['query'])
    if req['source_url'] != source_url(req['source_url']) or req['destination_url'] != video_url(req['destination_url'],req['bvid']):
        fail('request_target')
    start,end,captured = timestamp(req['issued_at']),timestamp(req['expires_at']),timestamp(req['source_captured_at'])
    if not captured <= start < end <= captured+MAX_SNAPSHOT_AGE or end-start > 600 or req['scope_digest'] != digest(req):
        fail('request_integrity')
    if now is not None and not start <= now < end:
        fail('request_expired')
    return req


def validate_preflight(value, req, now):
    encoded(value)
    keys = {'protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest',
        'observed_source_url','tab_id','checked_at','context','selected_bvid','selected_url','selection_visible'}
    if not isinstance(value,dict) or set(value) != keys:
        fail('preflight_schema')
    identity(value,req)
    if (value['context'] != 'confirmed' or value['tab_id'] != req['source_tab_id']
        or source_url(value['observed_source_url']) != req['source_url']
        or value['selected_bvid'] != req['bvid'] or value['selection_visible'] is not True
        or video_url(value['selected_url'],req['bvid'],allow_tracking=True) != req['destination_url']):
        fail('preflight_target_or_context')
    if not req['issued_at'] <= timestamp(value['checked_at']) <= now < req['expires_at']:
        fail('preflight_stale')
    return dict(value,observed_source_url=req['source_url'],selected_url=req['destination_url'])


def validate_receipt(value, req, now=None):
    now = time.time() if now is None else now
    validate_request(req,now); encoded(value)
    keys = {'protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest',
        'bvid','tab_id','observed_url','captured_at','source','status','phase','context','error'}
    if not isinstance(value,dict) or set(value) != keys:
        fail('receipt_schema')
    identity(value,req)
    if value['bvid'] != req['bvid'] or value['tab_id'] != req['source_tab_id']:
        fail('receipt_target')
    if value['source'] != 'browser_dom' or value['status'] not in ('observed','blocked') or value['phase'] not in ('preflight','capture') or value['context'] not in ('confirmed','changed','unavailable'):
        fail('receipt_source')
    if not req['issued_at'] <= timestamp(value['captured_at']) <= now < req['expires_at']:
        fail('receipt_stale')
    if value['status'] == 'blocked':
        if value['error'] not in ('target_mismatch','context_changed','context_unavailable','login_required','captcha','browser_unavailable','access_denied','dom_unavailable'):
            fail('receipt_error')
        if value['phase'] == 'preflight' and value['observed_url'] is not None:
            fail('receipt_target')
    elif value['phase'] != 'capture' or value['context'] != 'confirmed' or value['error'] is not None or value['observed_url'] is None:
        fail('receipt_phase_or_context')
    canonical = None if value['observed_url'] is None else video_url(value['observed_url'],req['bvid'],allow_tracking=True)
    return dict(value,observed_url=canonical)
