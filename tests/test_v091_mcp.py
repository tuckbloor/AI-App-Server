"""MCP opt-in, authentication and real JSON-RPC HTTP tool exercises."""
import json
from pathlib import Path
import hashlib

import pytest
from fastapi.testclient import TestClient
from ai_app_server.mcp_module import enable, disable, authentic, read_config
from ai_app_server.server import create_app
from ai_app_server.recovery import create_snapshot, verify_snapshot, restore_snapshot


def rpc(method, params=None, ident=1):
    return {"jsonrpc":"2.0", "id":ident, "method":method, "params":params or {
        "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}


def setup(tmp_path):
    project = tmp_path/'project'
    (project/'app').mkdir(parents=True)
    script=project/'app/app.py'
    script.write_text('import ai_app_server as ui\nui.title("MCP demo")\n',encoding='utf-8')
    return project, script


def test_disabled_by_default_and_token_rotation(tmp_path):
    data=tmp_path/'data'
    assert not read_config(data)['enabled']
    assert not authentic(data, 'Bearer something')
    token=enable(data)
    assert authentic(data, 'Bearer '+token)
    assert token not in (data/'mcp.json').read_text()
    assert hashlib.sha256(token.encode()).hexdigest() in (data/'mcp.json').read_text()
    second=enable(data)
    assert second!=token
    assert not authentic(data,'Bearer '+token)
    assert authentic(data,'Bearer '+second)
    disable(data)
    assert not authentic(data,'Bearer '+second)


def test_mcp_endpoint_requires_token_origin_and_content_type(tmp_path):
    project,script=setup(tmp_path)
    with TestClient(create_app(script,data_dir=project/'data')) as c:
        assert c.post('/mcp',json=rpc('server/discover')).status_code==401
        assert c.get('/mcp').status_code==405
        token=enable(project/'data')
        headers={'Authorization':'Bearer '+token}
        assert c.post('/mcp',json=rpc('server/discover'),headers={**headers,'Origin':'https://bad.example'}).status_code==403
        assert c.post('/mcp',content=b'abc',headers={**headers,'Content-Type':'text/plain'}).status_code==415
        assert c.post('/mcp',content=b'{'*70000,headers={**headers,'Content-Type':'application/json'}).status_code==413
        resp=c.post('/mcp',json=rpc('server/discover'),headers=headers)
        assert resp.status_code==200
        assert '2026-07-28' in resp.json()['result']['supportedVersions']
        assert c.post('/mcp',json=rpc('tools/list'),headers=headers).json()['result']['tools']==[]
        assert c.post('/mcp',json=rpc('tools/call',{'name':'unknown','arguments':{}}),headers=headers).json()['error']['code']==-32602
        assert c.post('/mcp',json=rpc('ping'),headers=headers).status_code==200
        assert c.post('/mcp',json=rpc('ping',{'_meta':{'io.modelcontextprotocol/protocolVersion':'2025-11-25'}}),headers=headers).status_code==200


def test_explicit_project_tool_invoked_and_validated(tmp_path):
    project,script=setup(tmp_path)
    (project/'app/mcp_tools.py').write_text('''def register_tools(registry):
    @registry.tool(name="welcome", description="Return a friendly greeting", input_schema={"type":"object","properties":{"name":{"type":"string","maxLength":30}},"required":["name"]})
    def welcome(name: str):
        return "Hello, " + name

    @registry.tool(name="unsafe_write", description="Not available", input_schema={"type":"object","properties":{}}, read_only=False)
    def unsafe_write():
        return "Should never execute"
''')
    token=enable(project/'data')
    with TestClient(create_app(script,data_dir=project/'data')) as c:
        headers={'Authorization':'Bearer '+token}
        names=[x['name'] for x in c.post('/mcp',json=rpc('tools/list'),headers=headers).json()['result']['tools']]
        assert names==['welcome']
        good=c.post('/mcp',json=rpc('tools/call',{'name':'welcome','arguments':{'name':'Alice'}}),headers=headers)
        assert good.json()['result']['content'][0]['text']=='Hello, Alice'
        bad=c.post('/mcp',json=rpc('tools/call',{'name':'welcome','arguments':{'name':'a'*31}}),headers=headers)
        assert bad.json()['result']['isError'] is True
        assert c.post('/mcp',json=rpc('tools/call',{'name':'unsafe_write','arguments':{}}),headers=headers).json()['error']['code']==-32602


def test_snapshot_includes_mcp_config(tmp_path):
    project,script=setup(tmp_path)
    from ai_app_server.storage import Store
    Store(project/'data')
    token=enable(project/'data')
    snapshot=project/'backups/snapshot'
    files=create_snapshot(project,snapshot)['files']
    assert 'data/mcp.json' in files
    assert verify_snapshot(snapshot)['files']==files
    disable(project/'data')
    restore_snapshot(project,snapshot)
    assert authentic(project/'data','Bearer '+token)


def test_bad_tool_file_does_not_take_down_app(tmp_path):
    project,script=setup(tmp_path)
    (project/'app/mcp_tools.py').write_text('raise RuntimeError("Developer made a mistake")\n')
    with TestClient(create_app(script,data_dir=project/'data')) as c:
        assert c.get('/health').status_code==200
        # Disabled MCP must not import or execute untrusted tool modules.
        assert c.app.state.mcp_load_error is False
        assert c.app.state.mcp_loaded is False
        assert c.get('/api/admin/me').status_code==401
