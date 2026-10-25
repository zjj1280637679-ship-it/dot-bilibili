#!/usr/bin/env python3
"""Trusted dot host helper. Does not operate a browser or generate evidence."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bili_bridge.browser_host import FileBrowserHost, HostError, decode, MAX_BYTES

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spool', required=True)
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('claim')
    begin = sub.add_parser('begin-navigation')
    begin.add_argument('--preflight', required=True)
    submit = sub.add_parser('submit')
    submit.add_argument('--receipt', required=True)
    a = p.parse_args()
    try:
        host = FileBrowserHost(a.spool)
        if a.action == 'claim':
            print(json.dumps(host.claim(), ensure_ascii=False))
        elif a.action == 'begin-navigation':
            with open(a.preflight, 'rb') as f:
                preflight = decode(f.read(MAX_BYTES+1))
            print(json.dumps(host.begin_navigation(preflight), ensure_ascii=False))
        else:
            with open(a.receipt, 'rb') as f:
                receipt = decode(f.read(MAX_BYTES+1))
            host.submit(receipt)
            print('{"accepted":true}')
        return 0
    except (HostError, OSError) as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, HostError) else 'host_io_failed'}))
        return 2
if __name__ == '__main__':
    raise SystemExit(main())
