"""Pure bounded schemas for the single host-browser read primitive."""
import hashlib
import json
import math
import re
import time
from urllib.parse import urlsplit, parse_qsl, urlencode

MAX_BYTES = 65536
OPERATION = 'browser.search_results.read'
BINDING = 'user_confirmed_cloud_session'

class HostError(ValueError):
    pass

def fail(code):
    raise HostError(code)

def text_value(value, limit, empty=False):
    if not isinstance(value, str) or (not empty and not value) or len(value) > limit:
        fail('invalid_text')
    try:
        value.encode('utf-8', 'strict')
    except UnicodeError:
        fail('invalid_unicode')
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        fail('invalid_text')
    return value

def search_url(url, query):
    text_value(url, 2048)
    try:
        p = urlsplit(url)
        pairs = parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)
        if (p.scheme != 'https' or p.netloc != 'search.bilibili.com' or p.path not in ('/all', '/video', '/en/all', '/en/video')
                or p.fragment or len(pairs) != len(dict(pairs))
                or dict(pairs).get('keyword') != query
                or set(dict(pairs)) - {'keyword', 'from_source', 'spm_id_from', 'search_source'}
                or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', v) for k,v in pairs if k != 'keyword')
                or re.search(r'%(?![0-9A-Fa-f]{2})', p.query)):
            fail('invalid_search_url')
    except (ValueError, UnicodeError):
        fail('invalid_search_url')
    return url

def video_url(url, bvid):
    if not isinstance(bvid, str) or not re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid):
        fail('invalid_bvid')
    text_value(url, 2048)
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'www.bilibili.com' or p.path.rstrip('/') not in ('/video/'+bvid, '/en/video/'+bvid) or p.query or p.fragment:
        fail('invalid_video_url')
    return 'https://www.bilibili.com/video/'+bvid+'/'

def encoded(obj):
    try:
        stack = [(obj, 0)]
        while stack:
            value, depth = stack.pop()
            if depth > 16:
                fail('invalid_json_depth')
            if isinstance(value, dict):
                stack.extend((v, depth+1) for v in value.values())
            elif isinstance(value, (list, tuple)):
                stack.extend((v, depth+1) for v in value)
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail('invalid_json')
    if len(raw) > MAX_BYTES:
        fail('payload_too_large')
    return raw

def decode(raw):
    if len(raw) > MAX_BYTES:
        fail('payload_too_large')
    def pairs(values):
        out = {}
        for k, v in values:
            if k in out:
                fail('duplicate_json_key')
            out[k] = v
        return out
    try:
        obj = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=pairs,
                         parse_constant=lambda _: fail('invalid_json'))
        encoded(obj)
        return obj
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, HostError):
            raise
        fail('invalid_json')

def timestamp(value):
    if type(value) not in (int, float):
        fail('invalid_timestamp')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        fail('invalid_timestamp')
    if not finite:
        fail('invalid_timestamp')
    return value

def digest(req):
    return hashlib.sha256(encoded({k:v for k,v in req.items() if k != 'scope_digest'})).hexdigest()

def validate_request(req, now=None):
    keys = {'protocol_version','operation_id','correlation_id','operation','account_binding','effect','query','expected_url','expected_tab_id','issued_at','expires_at','scope_digest'}
    if not isinstance(req, dict) or set(req) != keys:
        fail('request_schema')
    if type(req['protocol_version']) is not int or req['protocol_version'] != 1 or req['operation'] != OPERATION or req['account_binding'] != BINDING or req['effect'] != 'read':
        fail('request_scope')
    for key in ('operation_id','correlation_id','expected_tab_id'):
        text_value(req[key], 200)
    text_value(req['query'], 200)
    search_url(req['expected_url'], req['query'])
    start, end = timestamp(req['issued_at']), timestamp(req['expires_at'])
    if not 0 < end-start <= 600 or req['scope_digest'] != digest(req):
        fail('request_integrity')
    if now is not None and not start <= now < end:
        fail('request_expired')
    return req

def validate_receipt(receipt, req, now=None):
    now = time.time() if now is None else now
    encoded(receipt)
    keys = {'protocol_version','operation_id','correlation_id','scope_digest','observed_url','tab_id','query','captured_at','source','status','items','error'}
    if not isinstance(receipt, dict) or set(receipt) != keys:
        fail('receipt_schema')
    for k in ('protocol_version','operation_id','correlation_id','scope_digest'):
        if type(receipt[k]) != type(req[k]) or receipt[k] != req[k]:
            fail('receipt_identity')
    if receipt['source'] != 'browser_dom' or receipt['status'] not in ('observed','blocked'):
        fail('receipt_source')
    if receipt['query'] != req['query'] or receipt['tab_id'] != req['expected_tab_id'] or receipt['observed_url'] != req['expected_url']:
        fail('receipt_target')
    search_url(receipt['observed_url'], receipt['query'])
    captured = timestamp(receipt['captured_at'])
    if not req['issued_at'] <= captured <= now < req['expires_at']:
        fail('receipt_stale')
    if not isinstance(receipt['items'], list) or len(receipt['items']) > 10:
        fail('receipt_items')
    if receipt['status'] == 'blocked':
        if receipt['items'] or receipt['error'] not in ('target_mismatch','login_required','captcha','browser_unavailable','access_denied','dom_unavailable'):
            fail('receipt_error')
    elif receipt['error'] is not None:
        fail('receipt_error')
    out = dict(receipt)
    out['items'] = []
    seen = set()
    for item in receipt['items']:
        if not isinstance(item, dict) or set(item) != {'title','url','bvid','uploader','duration','displayed_counts'}:
            fail('item_schema')
        for field, limit in [('title',500), ('uploader',200), ('duration',40)]:
            text_value(item[field], limit, empty=field != 'title')
        if not isinstance(item['displayed_counts'], list) or len(item['displayed_counts']) > 5:
            fail('item_counts')
        for label in item['displayed_counts']:
            text_value(label, 100)
        url = video_url(item['url'], item['bvid'])
        if item['bvid'] in seen:
            fail('duplicate_item')
        seen.add(item['bvid'])
        out['items'].append(dict(item, url=url))
    return out

