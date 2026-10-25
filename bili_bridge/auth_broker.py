"""Isolated memory-only broker; not registered in any bridge kernel or scheduler."""
import os
import math
import signal
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from pathlib import Path
from .auth_contracts import (MAX_BODY, KEY, TrialStopped, generated, polled,
                             logged_in, validate_challenge)

ENDPOINTS = {
    'generate': 'https://passport.bilibili.com/x/passport-login/web/qrcode/generate',
    'poll': 'https://passport.bilibili.com/x/passport-login/web/qrcode/poll',
    'nav': 'https://api.bilibili.com/x/web-interface/nav',
}
COOKIE_NAMES = frozenset({'SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5', 'sid', 'buvid3'})


class MemoryCredentials:
    __slots__ = ('_cookies',)
    def __init__(self):
        self._cookies = {}
    def __repr__(self):
        return '<MemoryCredentials redacted>'
    def clear(self):
        self._cookies.clear()
    def accept(self, headers):
        candidate = {}
        try:
            if len(headers) > 32 or sum(len(h) for h in headers) > 16384:
                raise ValueError
            for raw in headers:
                # One cookie per Set-Cookie; reject parser overwrite ambiguities.
                attributes = set()
                for attribute in raw.split(';')[1:]:
                    attribute_name = attribute.strip().split('=', 1)[0].lower()
                    if attribute_name not in {'domain', 'path', 'secure', 'httponly', 'expires',
                                              'max-age', 'samesite', 'priority', 'partitioned'} or attribute_name in attributes:
                        raise ValueError
                    attributes.add(attribute_name)
                c = SimpleCookie()
                c.load(raw)
                if len(c) != 1:
                    raise ValueError
                for name, morsel in c.items():
                    domain = morsel['domain'].removeprefix('.').lower()
                    if domain and domain not in {'bilibili.com', 'passport.bilibili.com'}:
                        raise ValueError
                    if name in COOKIE_NAMES:
                        if (name in candidate or domain != 'bilibili.com' or morsel['path'] != '/'
                                or not morsel['secure']):
                            raise ValueError
                        if morsel['max-age'] and int(morsel['max-age']) <= 0:
                            raise ValueError
                        if morsel['expires']:
                            expiry = parsedate_to_datetime(morsel['expires'])
                            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                                raise ValueError
                        val = morsel.value
                        if not val or len(val) > 4096 or any(ord(x) <= 32 or ord(x) >= 127 or x in ';,' for x in val):
                            raise ValueError
                        candidate[name] = val
            if not candidate.get('SESSDATA'):
                raise ValueError
        except Exception:
            raise TrialStopped('missing_or_invalid_session') from None
        self._cookies = candidate
    def _nav_header(self):
        # Never returned by the broker's public interface.
        return '; '.join(k + '=' + v for k, v in self._cookies.items())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TrialStopped('redirect_denied')


@contextmanager
def request_deadline(seconds):
    """POSIX main-thread wall-clock bound, including proxy/DNS/TLS/body reads."""
    if threading.current_thread() is not threading.main_thread() or signal.getitimer(signal.ITIMER_REAL)[0]:
        raise TrialStopped('invalid_transport_request')
    previous = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise TrialStopped('request_timeout')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class AuthTransport:
    """No URL/header injection API, redirects, retries, or cookie persistence.

    urllib's default ProxyHandler deliberately preserves managed proxy settings.
    """
    def __init__(self):
        self._opener = urllib.request.build_opener(NoRedirect())
    def __repr__(self):
        return '<AuthTransport>'
    def request(self, operation, *, key=None, credentials=None, timeout=10):
        if (not isinstance(operation, str) or operation not in ENDPOINTS
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10):
            raise TrialStopped('invalid_transport_request')
        if operation == 'poll':
            if not isinstance(key, str) or not KEY.fullmatch(key) or credentials is not None:
                raise TrialStopped('invalid_transport_request')
            query = urllib.parse.urlencode({'qrcode_key': key, 'source': 'main-fe-header'})
        elif operation == 'generate':
            if key is not None or credentials is not None:
                raise TrialStopped('invalid_transport_request')
            query = 'source=main-fe-header'
        else:
            if key is not None or not isinstance(credentials, MemoryCredentials):
                raise TrialStopped('invalid_transport_request')
            query = ''
        headers = {'User-Agent': 'dot-bilibili-readonly-qr-trial/0.1 (cloud; Python urllib)',
                   'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        if operation == 'nav':
            headers['Cookie'] = credentials._nav_header()
        request = urllib.request.Request(ENDPOINTS[operation] + ('?' + query if query else ''),
                                         headers=headers, method='GET')
        try:
            deadline = time.monotonic() + timeout
            with request_deadline(timeout), self._opener.open(request, timeout=timeout) as response:
                if response.status != 200:
                    raise TrialStopped('http_denied')
                if response.headers.get_content_type() != 'application/json' or response.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise TrialStopped('unexpected_content')
                cookies = response.headers.get_all('Set-Cookie', [])
                if len(cookies) > 32 or sum(map(len, cookies)) > 16384:
                    raise TrialStopped('oversized_headers')
                chunks, size = [], 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TrialStopped('request_timeout')
                    chunk = response.read1(min(4096, MAX_BODY + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise TrialStopped('oversized_response')
                return b''.join(chunks), cookies
        except TrialStopped:
            raise
        except urllib.error.HTTPError:
            raise TrialStopped('http_denied') from None
        except Exception:
            raise TrialStopped('network_failure') from None


def render_qr(challenge, directory):
    """Writes only the validated short-lived challenge image, never cookies."""
    validate_challenge(challenge)
    import qrcode  # A separately pinned dependency, not the original plugin.
    parent = Path(directory)
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = parent.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.getuid():
        raise TrialStopped('unsafe_qr_directory')
    fd, path = tempfile.mkstemp(prefix='qr-', suffix='.png', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            qrcode.make(challenge.url).save(out, format='PNG')
        return Path(path)
    except Exception:
        os.unlink(path)
        raise TrialStopped('qr_render_failed') from None


class QRBroker:
    def __init__(self, transport=None, *, clock=time.monotonic, sleep=time.sleep):
        self._transport = transport if transport is not None else AuthTransport()
        self._clock, self._sleep = clock, sleep
        self._credentials = MemoryCredentials()
        self._challenge = None
        self._deadline = None
        self._nav_used = False
        self.state = 'new'
    def __repr__(self):
        return '<QRBroker redacted>'
    def close(self):
        self._credentials.clear()
        self._challenge = None
        self.state = 'closed'
    def generate(self, *, approved, consent_ref):
        if self.state != 'new' or approved is not True or not isinstance(consent_ref, str) or not consent_ref.strip() or len(consent_ref) > 200:
            raise TrialStopped('consent_or_state_required')
        self.state = 'generating'  # Latches one attempt even on failure.
        self._deadline = self._clock() + 180
        try:
            body, _ = self._transport.request('generate')
            self._challenge = generated(body)
            self.state = 'ready'
            return self._challenge
        except TrialStopped:
            self.close()
            raise
        except Exception:
            self.close()
            raise TrialStopped('internal_failure') from None
    def poll(self, notify=lambda state: None):
        if self.state != 'ready':
            raise TrialStopped('invalid_state')
        try:
            count = 0
            confirmed = False
            while count < 35 and self._clock() + 5 < self._deadline:
                self._sleep(5)
                remaining = self._deadline - self._clock()
                if remaining <= 0:
                    break
                count += 1
                body, cookies = self._transport.request('poll', key=self._challenge.key, timeout=min(10, remaining))
                self.state = polled(body)
                if confirmed and self.state == 'waiting_scan':
                    raise TrialStopped('unexpected_protocol')
                confirmed = confirmed or self.state == 'waiting_confirmation'
                if self.state == 'authenticated':
                    self._credentials.accept(cookies)
                    self.state = 'session_received'
                    self._challenge = None
                    notify(self.state)
                    return self.state
                notify(self.state)
                if self.state == 'expired':
                    self.close()
                    return 'expired'
            self.close()
            return 'expired'
        except TrialStopped:
            self.close()
            raise
        except Exception:
            self.close()
            raise TrialStopped('internal_failure') from None
    def verify_once(self):
        if self.state != 'session_received' or self._nav_used:
            raise TrialStopped('invalid_state')
        self._nav_used = True
        try:
            body, _ = self._transport.request('nav', credentials=self._credentials)
            result = logged_in(body)
            if not result:
                self.close()
            else:
                self.state = 'authenticated'
            return result
        except TrialStopped:
            self.close()
            raise
        except Exception:
            self.close()
            raise TrialStopped('internal_failure') from None
