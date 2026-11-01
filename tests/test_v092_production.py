"""Additional v0.9.2 production security regressions."""
from pathlib import Path
import hashlib
import pytest
from fastapi.testclient import TestClient
from ai_app_server.storage import Store
from ai_app_server.server import create_app
from ai_app_server.mcp_module import enable

ORIGIN='https://secure.example.test'
VERSION='2026-07-28'


def prepare(tmp_path, monkeypatch):
    project=tmp_path/'project'
    app_dir=project/'app'
    app_dir.mkdir(parents=True)
    script=app_dir/'app.py'
    script.write_text('import ai_app_server as ui\nui.title("Safe test")\n')
    data=project/'data'
    store=Store(data)
    store.update_password(1, 'not-the-default-and-a-long-private-password', email='admin@example.test')
    monkeypatch.setenv('AI_APP_SERVER_BEHIND_TLS_PROXY','1')
    monkeypatch.setenv('AI_APP_SERVER_PUBLIC_ORIGIN',ORIGIN)
    monkeypatch.setenv('AI_APP_SERVER_APP_PASSWORD','a-really-long-unique-app-password-for-testing')
    return script,data


def rpc(method='tools/list', params=None):
    return {'jsonrpc':'2.0','id':1,'method':method,'params':params or {'_meta': {'io.modelcontextprotocol/protocolVersion': VERSION}}}


def headers(token, **more):
    return {'authorization':f'Bearer {token}', 'accept':'application/json, text/event-stream',
            'mcp-protocol-version': VERSION, **more}


def test_mcp_is_not_imported_at_startup_if_disabled(tmp_path):
    script=tmp_path/'app.py'
    script.write_text('import ai_app_server as ui\nui.title("Okay")')
    marker=tmp_path/'should-not-execute'
    (tmp_path/'mcp_tools.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("oops")\n')
    app=create_app(script,data_dir=tmp_path/'data')
    with TestClient(app) as c:
        assert c.get('/health').status_code==200
    assert not marker.exists()
    assert not app.state.mcp_loaded


def test_hardened_mcp_production_requires_explicit_approval_and_protocol(tmp_path, monkeypatch):
    script,data=prepare(tmp_path,monkeypatch)
    token=enable(data)
    app=create_app(script,data_dir=data,mode='production')
    with TestClient(app,base_url=ORIGIN) as c:
        assert c.post('/mcp',json=rpc(),headers={'authorization':f'Bearer {token}'}).status_code==406
        assert c.post('/mcp',json=rpc(),headers={**headers(token),'mcp-protocol-version':'2025-11-25'}).status_code==400
        assert c.post('/mcp',json=rpc(),headers={'authorization':f'Bearer {token}', 'accept':'application/json, text/event-stream'}).status_code==400
        assert c.post('/mcp',json=rpc(),headers=headers(token)).status_code==503
    monkeypatch.setenv('AI_APP_SERVER_MCP_TOOLS_APPROVED','1')
    app2=create_app(script,data_dir=data,mode='production')
    with TestClient(app2,base_url=ORIGIN) as c:
        r=c.post('/mcp',json=rpc(),headers=headers(token))
        assert r.status_code==200 and r.json()['result']['tools']==[]
        assert c.post('/mcp',json=rpc(),headers=headers(token, origin='https://evil.test')).status_code==403


def test_bounded_chunked_body_and_token_rate_limit(tmp_path):
    script=tmp_path/'app.py';script.write_text('import ai_app_server as ui\nui.title("Test")')
    token=enable(tmp_path/'data')
    with TestClient(create_app(script,data_dir=tmp_path/'data')) as c:
        h={'authorization':f'Bearer {token}', 'content-type':'application/json'}
        def too_big():
            for _ in range(8):
                yield b'a'*9000
        r=c.post('/mcp',content=too_big(),headers=h)
        assert r.status_code==413
        for _ in range(59):
            assert c.post('/mcp',json=rpc(),headers=h).status_code==200
        assert c.post('/mcp',json=rpc(),headers=h).status_code==429


def test_main_app_has_no_inline_scripts_and_csp(tmp_path):
    s=tmp_path/'app.py';s.write_text('import ai_app_server as ui\nui.title("Ok")')
    with TestClient(create_app(s,data_dir=tmp_path/'data')) as c:
        r=c.get('/')
        assert 'src="/static/app.js"' in r.text
        assert '<script>' not in r.text
        assert "script-src 'self'" in r.headers['content-security-policy']
        assert "'unsafe-inline'" not in r.headers['content-security-policy']
        assert c.get('/static/app.js').status_code==200
        assert c.get('/static/app.css').status_code==200
