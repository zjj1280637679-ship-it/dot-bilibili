"""Bounded visible public video metadata; never transcript or media evidence."""
import re
import time
from urllib.parse import urlsplit, parse_qsl
from .browser_contracts import (BINDING, encoded, digest, fail, text_value, timestamp)

OPERATION = 'browser.video_page.read'
SCHEMA_VERSION = 1
TARGET_FIELD = 'bvid'


def video_url(url, bvid, *, allow_tracking=False):
    if not isinstance(bvid, str) or not re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid):
        fail('invalid_bvid')
    text_value(url, 2048)
    try:
        p = urlsplit(url)
        paths = {'/video/'+bvid, '/video/'+bvid+'/', '/en/video/'+bvid, '/en/video/'+bvid+'/'}
        if p.scheme != 'https' or p.netloc != 'www.bilibili.com' or p.path not in paths or p.fragment:
            fail('invalid_video_url')
        pairs = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
        if (p.query and not allow_tracking) or len(pairs) != len(dict(pairs)) or re.search(r'%(?![0-9A-Fa-f]{2})', p.query):
            fail('invalid_video_url')
        for key, value in pairs:
            pattern = {'vd_source': r'[0-9A-Fa-f]{1,128}', 'spm_id_from': r'[A-Za-z0-9_.-]{1,100}'}.get(key)
            if pattern is None or not re.fullmatch(pattern, value):
                fail('invalid_video_url')
    except ValueError:
        fail('invalid_video_url')
    return 'https://www.bilibili.com/video/'+bvid+'/'


def validate_request(req, now=None):
    encoded(req)
    keys = {'protocol_version','schema_version','operation_id','correlation_id','operation','account_binding','effect','bvid','expected_url','expected_tab_id','issued_at','expires_at','scope_digest'}
    if not isinstance(req, dict) or set(req) != keys:
        fail('request_schema')
    if (type(req['protocol_version']) is not int or req['protocol_version'] != 1
            or type(req['schema_version']) is not int or req['schema_version'] != SCHEMA_VERSION
            or req['operation'] != OPERATION or req['account_binding'] != BINDING or req['effect'] != 'read'):
        fail('request_scope')
    for key in ('operation_id','correlation_id','expected_tab_id'):
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
    keys = {'protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','observed_url','tab_id','bvid','captured_at','source','status','metadata','error'}
    if not isinstance(receipt, dict) or set(receipt) != keys:
        fail('receipt_schema')
    for key in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','bvid'):
        if type(receipt[key]) != type(req[key]) or receipt[key] != req[key]:
            fail('receipt_identity')
    if receipt['source'] != 'browser_dom' or receipt['status'] not in ('observed','blocked'):
        fail('receipt_source')
    observed_url = video_url(receipt['observed_url'], receipt['bvid'], allow_tracking=True)
    if observed_url != video_url(req['expected_url'], req['bvid']) or receipt['tab_id'] != req['expected_tab_id']:
        fail('receipt_target')
    captured = timestamp(receipt['captured_at'])
    if not req['issued_at'] <= captured <= now < req['expires_at']:
        fail('receipt_stale')
    if receipt['status'] == 'blocked':
        if receipt['metadata'] is not None or receipt['error'] not in ('target_mismatch','login_required','captcha','browser_unavailable','access_denied','dom_unavailable'):
            fail('receipt_error')
        return dict(receipt, observed_url=observed_url)
    if receipt['error'] is not None:
        fail('receipt_error')
    metadata = receipt['metadata']
    limits = {'title':500, 'uploader':200, 'description':8000, 'duration':40, 'displayed_counts':100}
    if not isinstance(metadata, dict) or set(metadata) != set(limits):
        fail('metadata_schema')
    for key, limit in limits.items():
        field = metadata[key]
        if not isinstance(field, dict) or set(field) != {'state','value'}:
            fail('field_schema')
        if field['state'] == 'not_visible':
            if field['value'] is not None:
                fail('field_state')
        elif field['state'] == 'visible':
            if key == 'displayed_counts':
                if not isinstance(field['value'], list) or not 1 <= len(field['value']) <= 8:
                    fail('field_counts')
                for label in field['value']:
                    text_value(label, limit)
            else:
                # Host projects rendered multiline text as space-separated text.
                text_value(field['value'], limit)
        else:
            fail('field_state')
    return dict(receipt, observed_url=observed_url)
