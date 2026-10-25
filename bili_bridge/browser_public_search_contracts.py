"""Fixed public search navigation; host attestations are not DOM/auth proofs."""
import time
from urllib.parse import urlsplit, parse_qsl, urlencode
from . import browser_contracts as legacy
from .browser_contracts import BINDING, encoded, digest, fail, text_value, timestamp
from .browser_video_contracts import video_url

OPERATION = 'browser.public_search'
SCHEMA_VERSION = 1


def destination(query):
    text_value(query, 200)
    if not query.strip():
        fail('invalid_query')
    return text_value('https://search.bilibili.com/en/all?' + urlencode({'keyword': query}), 2048)


def search_url(url, query):
    legacy.search_url(url, query)
    if urlsplit(url).path not in ('/all', '/en/all'):
        fail('invalid_search_destination')
    return destination(query)


def source_url(url):
    text_value(url, 2048)
    try:
        p = urlsplit(url)
        if p.netloc == 'search.bilibili.com':
            query = dict(parse_qsl(p.query, keep_blank_values=True, strict_parsing=True)).get('keyword')
            # Source may be a public video-search tab; destination never is.
            legacy.search_url(url, query)
            text_value(query, 200)
            return 'https://search.bilibili.com' + p.path + '?' + urlencode({'keyword': query})
        if p.netloc == 'www.bilibili.com':
            if p.path in ('/', '/en', '/en/'):
                # Exact public homepage spellings only; retain locale identity.
                if url not in ('https://www.bilibili.com/', 'https://www.bilibili.com/en', 'https://www.bilibili.com/en/'):
                    fail('invalid_source_url')
                return 'https://www.bilibili.com/en' if p.path.startswith('/en') else url
            return video_url(url, p.path.rstrip('/').split('/')[-1], allow_tracking=True)
    except (ValueError, UnicodeError):
        fail('invalid_source_url')
    fail('invalid_source_url')


def make_request(operation_id, correlation_id, query, url, tab, now, timeout):
    req = dict(protocol_version=1, schema_version=1, operation=OPERATION,
        operation_id=operation_id, correlation_id=correlation_id,
        account_binding=BINDING, effect='read', query=query,
        source_url=source_url(url), source_tab_id=tab, destination_url=destination(query),
        issued_at=now, expires_at=now+timeout)
    req['scope_digest'] = digest(req)
    return validate_request(req, now)


def validate_request(req, now=None):
    encoded(req)
    keys = {'protocol_version','schema_version','operation','operation_id','correlation_id','account_binding','effect','query','source_url','source_tab_id','destination_url','issued_at','expires_at','scope_digest'}
    if not isinstance(req, dict) or set(req) != keys:
        fail('request_schema')
    if (type(req['protocol_version']) is not int or req['protocol_version'] != 1
        or type(req['schema_version']) is not int or req['schema_version'] != 1
        or req['operation'] != OPERATION or req['account_binding'] != BINDING or req['effect'] != 'read'):
        fail('request_scope')
    for key in ('operation_id','correlation_id','source_tab_id'):
        text_value(req[key], 200)
    if req['source_url'] != source_url(req['source_url']) or req['destination_url'] != destination(req['query']):
        fail('request_target')
    start, end = timestamp(req['issued_at']), timestamp(req['expires_at'])
    if not 0 < end-start <= 600 or req['scope_digest'] != digest(req):
        fail('request_integrity')
    if now is not None and not start <= now < end:
        fail('request_expired')
    return req


def identity(value, req):
    for key in ('protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest'):
        if type(value[key]) != type(req[key]) or value[key] != req[key]:
            fail('receipt_identity')


def validate_preflight(value, req, now):
    encoded(value)
    keys = {'protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','observed_source_url','tab_id','checked_at','context'}
    if not isinstance(value, dict) or set(value) != keys:
        fail('preflight_schema')
    identity(value, req)
    if value['context'] != 'confirmed' or value['tab_id'] != req['source_tab_id'] or source_url(value['observed_source_url']) != req['source_url']:
        fail('preflight_target_or_context')
    if not req['issued_at'] <= timestamp(value['checked_at']) <= now < req['expires_at']:
        fail('preflight_stale')
    return dict(value, observed_source_url=req['source_url'])


def validate_receipt(value, req, now=None):
    now = time.time() if now is None else now
    validate_request(req, now)
    encoded(value)
    keys = {'protocol_version','schema_version','operation','operation_id','correlation_id','scope_digest','query','tab_id','observed_url','captured_at','source','status','phase','context','items','error'}
    if not isinstance(value, dict) or set(value) != keys:
        fail('receipt_schema')
    identity(value, req)
    if value['query'] != req['query'] or value['tab_id'] != req['source_tab_id']:
        fail('receipt_target')
    if value['source'] != 'browser_dom' or value['status'] not in ('observed','blocked') or value['phase'] not in ('preflight','capture') or value['context'] not in ('confirmed','changed','unavailable'):
        fail('receipt_source')
    if not req['issued_at'] <= timestamp(value['captured_at']) <= now < req['expires_at']:
        fail('receipt_stale')
    if value['status'] == 'blocked':
        if value['items'] != [] or value['error'] not in ('target_mismatch','context_changed','context_unavailable','login_required','captcha','browser_unavailable','access_denied','dom_unavailable'):
            fail('receipt_error')
        if value['phase'] == 'preflight' and value['observed_url'] is not None:
            fail('receipt_target')
        if value['observed_url'] is not None:
            search_url(value['observed_url'], req['query'])
        return dict(value, observed_url=None if value['observed_url'] is None else req['destination_url'])
    if value['phase'] != 'capture' or value['context'] != 'confirmed' or value['error'] is not None:
        fail('receipt_phase_or_context')
    canonical = search_url(value['observed_url'], req['query'])
    # Reuse unchanged legacy item validation with a locally projected legacy envelope.
    old_req = dict(req, expected_url=canonical, expected_tab_id=req['source_tab_id'])
    old = {k:value[k] for k in ('protocol_version','operation_id','correlation_id','scope_digest','query','tab_id','captured_at','source','status','items','error')}
    old['observed_url'] = canonical
    validated = legacy.validate_receipt(old, old_req, now)
    return dict(value, observed_url=canonical, items=validated['items'])
