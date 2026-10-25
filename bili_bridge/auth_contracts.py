"""Pure, fail-closed QR protocol validation. No I/O or third-party plugin code."""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 65536
KEY = re.compile(r'[A-Za-z0-9_-]{16,128}\Z')
STATES = {86101: 'waiting_scan', 86090: 'waiting_confirmation', 86038: 'expired', 0: 'authenticated'}


class TrialStopped(Exception):
    """Only constant safe reasons may cross the broker boundary."""
    SAFE = frozenset({'unexpected_protocol', 'unexpected_qr_url', 'invalid_transport_request',
        'redirect_denied', 'http_denied', 'unexpected_content', 'oversized_headers',
        'request_timeout', 'oversized_response', 'network_failure', 'internal_failure',
        'missing_or_invalid_session', 'unsafe_qr_directory', 'qr_render_failed',
        'consent_or_state_required', 'invalid_state'})
    def __init__(self, reason='internal_failure'):
        super().__init__(reason if isinstance(reason, str) and reason in self.SAFE else 'internal_failure')


@dataclass(repr=False)
class Challenge:
    url: str = field(repr=False)
    key: str = field(repr=False)

    def __repr__(self):
        return '<Challenge redacted>'


def payload(body):
    try:
        if not isinstance(body, bytes) or len(body) > MAX_BODY:
            raise ValueError
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        def invalid_constant(value):
            raise ValueError
        obj = json.loads(body, object_pairs_hook=unique, parse_constant=invalid_constant)
        if not isinstance(obj, dict) or type(obj.get('code')) is not int or obj['code'] != 0:
            raise ValueError
        if not isinstance(obj.get('data'), dict):
            raise ValueError
        return obj['data']
    except Exception:
        raise TrialStopped('unexpected_protocol') from None


def validate_challenge(challenge):
    try:
        if not isinstance(challenge, Challenge) or not KEY.fullmatch(challenge.key):
            raise ValueError
        u = challenge.url
        if not isinstance(u, str) or len(u) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in u):
            raise ValueError
        p = urlsplit(u)
        q = parse_qs(p.query, strict_parsing=True, keep_blank_values=True, max_num_fields=2)
        if (p.scheme != 'https' or p.netloc != 'passport.bilibili.com'
                or p.path != '/h5-app/passport/login/scan' or p.fragment
                or set(q) != {'navhide', 'qrcode_key'}
                or q['navhide'] != ['1'] or q['qrcode_key'] != [challenge.key]):
            raise ValueError
        return challenge
    except Exception:
        raise TrialStopped('unexpected_qr_url') from None


def generated(body):
    d = payload(body)
    return validate_challenge(Challenge(d.get('url'), d.get('qrcode_key')))


def polled(body):
    d = payload(body)
    code = d.get('code')
    if type(code) is not int or code not in STATES:
        raise TrialStopped('unexpected_protocol')
    return STATES[code]


def logged_in(body):
    d = payload(body)
    if type(d.get('isLogin')) is not bool:
        raise TrialStopped('unexpected_protocol')
    return d['isLogin']
