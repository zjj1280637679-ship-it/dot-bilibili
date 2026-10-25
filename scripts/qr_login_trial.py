#!/usr/bin/env python3
"""Explicitly gated one-shot QR trial. No imports of third-party plugin code."""
import argparse
import json
import os
from pathlib import Path
import resource
import select
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bili_bridge.auth_broker import QRBroker, render_qr
from bili_bridge.auth_contracts import TrialStopped


def emit(state, **safe_fields):
    print(json.dumps({'state': state, **safe_fields}), flush=True)


def command_until(deadline):
    """Bounded stdin read; partial lines cannot defeat the lifetime limit."""
    data = bytearray()
    while time.monotonic() < deadline:
        ready, _, _ = select.select([sys.stdin], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            return 'timeout'
        char = os.read(sys.stdin.fileno(), 1)
        if not char:
            return 'close'
        if char == b'\n':
            try:
                return data.decode('ascii').strip()
            except UnicodeError:
                return 'invalid'
        data.extend(char)
        if len(data) > 64:
            return 'invalid'
    return 'timeout'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Memory-only, explicitly approved Bilibili QR login trial')
    parser.add_argument('--approved-trial', action='store_true')
    parser.add_argument('--consent-ref', required=True, help='Host-confirmed consent evidence reference, not an authorization token')
    parser.add_argument('--qr-directory', required=True, help='Private 0700 directory for short-lived QR image')
    parser.add_argument('--verify-nav', action='store_true', help='After success, one isLogin-only check')
    args = parser.parse_args(argv)
    if not args.approved_trial or not args.consent_ref.strip() or len(args.consent_ref) > 200:
        emit('stopped', reason='consent_required')
        return 2
    broker, png = None, None
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # Check dependency before generating any real challenge.
        import qrcode
        import PIL
        broker = QRBroker()
        challenge = broker.generate(approved=True, consent_ref=args.consent_ref)
        png = render_qr(challenge, args.qr_directory)
        del challenge
        emit('ready', qr_png=str(png), next_command='start_poll', lifetime_seconds=180)
        while True:
            cmd = command_until(broker._deadline)
            if cmd == 'start_poll':
                break
            if cmd == 'status':
                emit('ready')
                continue
            emit('closed' if cmd == 'close' else 'expired' if cmd == 'timeout' else 'stopped')
            return 0
        state = broker.poll(emit)
        png.unlink(missing_ok=True)
        png = None
        if state != 'session_received':
            emit(state)
            return 0
        if args.verify_nav:
            verified = broker.verify_once()
            emit('session_check', logged_in=verified)
            if not verified:
                return 1
        # Absolute post-login lifetime, not extended by repeated status commands.
        idle_deadline = time.monotonic() + 300
        emit('session_held_in_memory', lifetime_seconds=300, commands=['status', 'close'])
        while True:
            cmd = command_until(idle_deadline)
            if cmd == 'status':
                emit(broker.state)
                continue
            emit('closed', reason='requested' if cmd == 'close' else 'lifetime_expired' if cmd == 'timeout' else 'invalid_command')
            return 0
    except TrialStopped as exc:
        # Broker reasons are constants, not remote messages or exceptions.
        reason = str(exc)
        allowed = {'unexpected_protocol', 'unexpected_qr_url', 'invalid_transport_request',
                   'redirect_denied', 'http_denied', 'unexpected_content', 'oversized_headers',
                   'request_timeout', 'oversized_response', 'network_failure',
                   'missing_or_invalid_session', 'unsafe_qr_directory', 'qr_render_failed',
                   'consent_or_state_required', 'invalid_state'}
        emit('stopped', reason=reason if reason in allowed else 'internal_failure')
        return 1
    except KeyboardInterrupt:
        emit('closed', reason='interrupted')
        return 0
    except BaseException:
        emit('stopped', reason='internal_or_dependency_failure')
        return 1
    finally:
        if broker is not None:
            broker.close()
        if png is not None:
            try:
                png.unlink(missing_ok=True)
            except OSError:
                emit('cleanup_required', artifact='qr_png')


if __name__ == '__main__':
    sys.exit(main())
