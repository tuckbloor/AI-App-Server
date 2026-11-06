"""v1: MCP interoperability, code approval and verifiable disaster recovery."""
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient
from ai_app_server.server import create_app
from ai_app_server.storage import Store
from ai_app_server.mcp_module import enable
from ai_app_server.recovery import create_snapshot, verify_snapshot, rehearse_restore

ORIGIN = 'https://secure.example.test'
VERSION = '2026-07-28'


def fixture_project(tmp_path, monkeypatch, with_tools=True):
    root = tmp_path / 'project'
    app = root / 'app'
    app.mkdir(parents=True)
    script = app / 'app.py'
    script.write_text('import ai_app_server as ui\nui.title("Hello")\n')
    tools = app / 'mcp_tools.py'
    if with_tools:
        tools.write_text('''def register_tools(registry):
    @registry.tool(name="greeting", description="Greet", input_schema={"type":"object","properties":{"name":{"type":"string"}},"required":["name"]})
    def greet(name):
        return "Hello " + name
''')
    data = root / 'data'
    store = Store(data)
    store.update_password(1, 'unique-strong-admin-password-for-testing', email='admin@example.test')
    monkeypatch.setenv('AI_APP_SERVER_BEHIND_TLS_PROXY', '1')
    monkeypatch.setenv('AI_APP_SERVER_PUBLIC_ORIGIN', ORIGIN)
    store.create_app_user('alice', 'Alice Tester', 'unique-strong-application-password-for-test')
    monkeypatch.setenv('AI_APP_SERVER_MCP_TOOLS_APPROVED', '1')
    monkeypatch.setenv('AI_APP_SERVER_MCP_TOOLS_SHA256', hashlib.sha256(tools.read_bytes()).hexdigest() if with_tools else '')
    token = enable(data)
    return root, script, tools, token


def rpc(method, params=None, ident=1):
    return {'jsonrpc':'2.0', 'id':ident, 'method':method, 'params': params or {}}


def headers(token, version=VERSION):
    return {'Authorization': 'Bearer ' + token,
            'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': version}


def test_standard_initialize_protocol_negotiation(tmp_path, monkeypatch):
    root, script, tool, token=fixture_project(tmp_path, monkeypatch)
    with TestClient(create_app(script, data_dir=root/'data', mode='production'), base_url=ORIGIN) as client:
        # Standard initialization contains protocolVersion in params, not _meta.
        request=rpc('initialize', {'protocolVersion':'2025-11-25', 'capabilities':{}, 'clientInfo':{'name':'test','version':'1'}})
        response=client.post('/mcp', json=request, headers={'Authorization':'Bearer '+token, 'Accept':'application/json, text/event-stream'})
        assert response.status_code==200
        info=response.json()['result']
        assert info['protocolVersion']=='2025-11-25'
        assert info['capabilities']['tools']=={'listChanged':False}
        assert info['serverInfo']['version']=='1.0.5'
        assert client.post('/mcp',json=rpc('notifications/initialized', ident=None), headers=headers(token)).status_code==202
        result=client.post('/mcp',json=rpc('tools/list'),headers=headers(token, '2025-11-25'))
        assert result.status_code==200
        assert [x['name'] for x in result.json()['result']['tools']]==['greeting']
        answer=client.post('/mcp',json=rpc('tools/call', {'name':'greeting','arguments':{'name':'Ada'}}),headers=headers(token, '2025-11-25'))
        assert answer.json()['result']['content'][0]['text']=='Hello Ada'
        assert 'resultType' not in answer.json()['result']


def test_production_never_executes_unapproved_tool_code(tmp_path, monkeypatch):
    root, script, tool, token=fixture_project(tmp_path, monkeypatch)
    flag=root/'marker'
    tool.write_text(f'from pathlib import Path\nPath({str(flag)!r}).write_text("ran")\n')
    with TestClient(create_app(script,data_dir=root/'data',mode='production'),base_url=ORIGIN) as client:
        response=client.post('/mcp',json=rpc('tools/list'),headers=headers(token))
        assert response.status_code==503
        assert not flag.exists()
    monkeypatch.setenv('AI_APP_SERVER_MCP_TOOLS_SHA256', hashlib.sha256(tool.read_bytes()).hexdigest())
    with TestClient(create_app(script,data_dir=root/'data',mode='production'),base_url=ORIGIN) as client:
        response=client.post('/mcp',json=rpc('tools/list'),headers=headers(token))
        assert response.status_code==200
        assert flag.exists()
        # Dynamic tool source change is detected on the next request and denied.
        tool.write_text('raise RuntimeError("changed")\n')
        response=client.post('/mcp',json=rpc('tools/list'),headers=headers(token))
        assert response.status_code==503


def test_nonstandard_origin_rejected_even_with_token(tmp_path, monkeypatch):
    root, script, tool, token=fixture_project(tmp_path, monkeypatch)
    with TestClient(create_app(script,data_dir=root/'data',mode='production'),base_url=ORIGIN) as client:
        r=client.post('/mcp',json=rpc('initialize', {'protocolVersion':VERSION}),
                      headers={**headers(token),'Origin':'https://evil.example.test'})
        assert r.status_code==403


def test_full_snapshot_and_restore_rehearsal(tmp_path):
    root=tmp_path/'project'
    (root/'app').mkdir(parents=True)
    (root/'app/app.py').write_text('print("private project")')
    (root/'app/helpers.py').write_text('VALUE=2')
    store=Store(root/'data')
    key_before=(root/'data/.secret-key').read_bytes()
    (root/'config').mkdir()
    (root/'config/hosting.json').write_text('{"port": 8559}')
    snapshot=tmp_path/'offsite'/'snapshot'
    manifest=create_snapshot(root,snapshot,include_app=True)
    assert 'app/helpers.py' in manifest['files']
    assert 'data/server.sqlite3' in manifest['files']
    assert 'config/hosting.json' in manifest['files']
    dest=tmp_path/'restored'
    rehearse_restore(snapshot,dest)
    assert (dest/'data/.secret-key').read_bytes()==key_before
    assert (dest/'app/helpers.py').read_text()=='VALUE=2'
    assert sqlite3.connect(dest/'data/server.sqlite3').execute('PRAGMA quick_check').fetchone()[0]=='ok'
    assert (root/'app/helpers.py').read_text()=='VALUE=2'


def test_snapshot_detects_tampering_and_refuses_overwrite(tmp_path):
    root=tmp_path/'project';(root/'app').mkdir(parents=True)
    (root/'app/app.py').write_text('print("ok")')
    Store(root/'data')
    snapshot=tmp_path/'backup'
    create_snapshot(root,snapshot,include_app=True)
    with pytest.raises(FileExistsError):
        create_snapshot(root,snapshot,include_app=True)
    (snapshot/'app/app.py').write_text('tampered')
    with pytest.raises(RuntimeError,match='integrity'):
        verify_snapshot(snapshot)
    assert not (tmp_path/'restored').exists()


def test_malicious_manifest_paths_rejected(tmp_path):
    root=tmp_path/'project';(root/'app').mkdir(parents=True)
    (root/'app/app.py').write_text('hello')
    Store(root/'data')
    snapshot=tmp_path/'backup'
    create_snapshot(root,snapshot,include_app=True)
    manifest=json.loads((snapshot/'manifest.json').read_text())
    manifest['files']['app/../../bad'] = 'a'*64
    (snapshot/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='unexpected'):
        verify_snapshot(snapshot)


def test_symlinked_app_files_refused(tmp_path):
    root=tmp_path/'project';(root/'app').mkdir(parents=True)
    (root/'app/app.py').write_text('hello')
    try:
        (root/'app/hidden').symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Windows does not allow symlink creation on this account")
    Store(root/'data')
    with pytest.raises(RuntimeError,match='linked'):
        create_snapshot(root,tmp_path/'backups'/'snapshot',include_app=True)
