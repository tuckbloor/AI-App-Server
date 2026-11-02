"""Application access controls separate from control-plane administrator permissions.

Production applications require an explicit high-entropy shared app access secret,
configured only on the host (never shipped in the ZIP). A separate identity provider
or fine-grained application roles remain the developer's responsibility.
"""
from __future__ import annotations
import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import HTTPException


def configured_origin() -> str:
    return os.environ.get('AI_APP_SERVER_PUBLIC_ORIGIN', '').rstrip('/')


def production_checks(store, *, local_only: bool) -> list[dict]:
    """Non-secret preflight results; safe to display to an authenticated administrator."""
    origin = configured_origin()
    parsed = urlsplit(origin)
    try:
        host_port = parsed.hostname + (f':{parsed.port}' if parsed.port else '') if parsed.hostname else ''
    except ValueError:  # Invalid port supplied by the operator
        host_port = ''
    valid_origin = (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.path
                    and not parsed.username and not parsed.password and not parsed.query
                    and not parsed.fragment and parsed.netloc == host_port)
    with store.db() as db:
        users = db.execute('SELECT password_hash,must_change_password,is_active FROM users').fetchall()
    from .storage import verify_password
    active = [u for u in users if u['is_active']]
    return [
        {'id':'tls_proxy', 'ok': os.environ.get('AI_APP_SERVER_BEHIND_TLS_PROXY') == '1',
         'message':'Configure TLS reverse proxy (AI_APP_SERVER_BEHIND_TLS_PROXY=1)'},
        {'id':'origin','ok': valid_origin, 'message':'Set AI_APP_SERVER_PUBLIC_ORIGIN to your real HTTPS origin'},
        {'id':'loopback','ok': local_only, 'message':'Bind Python to 127.0.0.1 behind the reverse proxy'},
        {'id':'app_users', 'ok': bool(store.list_app_users()) and any(u['is_active'] for u in store.list_app_users()),
         'message':'Create at least one active application user under Admin > App Users'},
        {'id':'admin','ok': bool(active) and all(not u['must_change_password'] and not verify_password('password', u['password_hash']) for u in active),
         'message':'Change the initial administrator password and have an active admin'},
    ]


def validate_production(store, *, local_only: bool) -> None:
    failures = [row['message'] for row in production_checks(store, local_only=local_only) if not row['ok']]
    if failures:
        raise ValueError('Production checks failed: ' + '; '.join(failures))


def request_ip(request) -> str:
    """Use proxy source IP only for production requests from the trusted loopback proxy."""
    peer = request.client.host if request.client else 'unknown'
    if getattr(request.app.state, 'production', False) and peer in ('127.0.0.1', '::1'):
        forwarded = request.headers.get('x-forwarded-for', '').split(',')[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer
