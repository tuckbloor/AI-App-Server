"""Additional isolated security-smoke tests for v1.0.2; do not touch real user data."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from ai_app_server.server import create_app
from ai_app_server.mcp_module import enable

@pytest.fixture
def target(tmp_path):
    script=tmp_path/'app.py'
    script.write_text('from ai_app_server import ui\nui.title("Security smoke test")\n',encoding='utf-8')
    app=create_app(script,data_dir=tmp_path/'data')
    with TestClient(app) as client: yield client,app

def test_admin_denies_anonymous_api_access(target):
    client,app=target
    assert client.get('/api/admin/users').status_code==401
    assert client.get('/api/admin/dashboard').status_code==401

def test_mcp_requires_token_and_stays_disabled_initially(target):
    client,app=target
    payload={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}}
    assert client.post('/mcp',json=payload).status_code==401
    token=enable(app.state.store.directory)
    assert client.post('/mcp',json=payload).status_code==401
    ok=client.post('/mcp',json=payload,headers={'Authorization':f'Bearer {token}'})
    assert ok.status_code==200 and ok.json()['result']['tools']==[]

def test_development_rejects_arbitrary_host(target):
    client,_=target
    assert client.get('/health',headers={'host':'malicious.example'}).status_code==400

def test_production_refuses_default_credentials_and_no_tls(tmp_path):
    script=tmp_path/'app.py';script.write_text('')
    with pytest.raises(ValueError,match='Production checks failed'):
        create_app(script,data_dir=tmp_path/'data',mode='production')
