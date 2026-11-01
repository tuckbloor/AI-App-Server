#!/usr/bin/env python3
"""External, unauthenticated, read-only checks for a deployed HTTPS AI App Server.

This does not certify security; requires an externally reachable real TLS hostname.
No admin or app passwords are needed. Uses only Python's standard library.
"""
import argparse
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(url, *, method='GET', headers=None, body=None, timeout=10):
    req = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.status, r.headers, r.read(16384)
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read(16384)


def check(base):
    if not base.startswith('https://') or '/' in base[8:].rstrip('/'):
        raise ValueError('Pass the exact public HTTPS origin, e.g. https://ai.example.com')
    base = base.rstrip('/')
    outcomes = []
    status, headers, body = fetch(base + '/health')
    outcomes.append(('TLS and health', status == 200 and json.loads(body).get('status') == 'ok'))
    status, headers, _ = fetch(base + '/api/admin/me')
    outcomes.append(('Anonymous admin denied', status == 401))
    status, headers, _ = fetch(base + '/api/admin/dashboard')
    outcomes.append(('Anonymous dashboard denied', status in (401, 403)))
    status, headers, _ = fetch(base + '/mcp', method='POST',
        headers={'Accept':'application/json, text/event-stream', 'Content-Type':'application/json'},
        body=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
    outcomes.append(('Anonymous MCP denied', status == 401))
    status, headers, _ = fetch(base + '/static/app.js')
    outcomes.append(('UI assets served', status == 200 and len(_) > 0))
    status, headers, body = fetch(base + '/app-login')
    outcomes.append(('Production access gate available', status == 200))
    for name, ok in outcomes:
        print(('PASS' if ok else 'FAIL') + ' ' + name)
    return 0 if all(ok for _, ok in outcomes) else 2


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('origin')
    args = p.parse_args()
    try:
        raise SystemExit(check(args.origin))
    except (URLError, ValueError, OSError, json.JSONDecodeError) as exc:
        print('FAILED: unreachable or unsafe deployment: ' + str(exc))
        raise SystemExit(2)
