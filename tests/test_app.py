from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_app_server.runner import render
from ai_app_server.server import create_app
from ai_app_server.storage import Store, verify_password

SCRIPT = Path(__file__).resolve().parents[1] / "starter" / "app.py"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(SCRIPT, data_dir=tmp_path)) as c:
        yield c


def login(client, username="admin", password="password"):
    resp = client.post("/api/admin/login", json={"username":username,"password":password})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf"]


def ready(client):
    csrf = login(client)
    resp = client.post("/api/admin/password", headers={"x-csrf-token":csrf},
        json={"current_password":"password","new_password":"a new very long password 5!", "email":"admin@example.com"})
    assert resp.status_code == 200, resp.text
    return login(client, password="a new very long password 5!")


def write(client, url, csrf, json=None, method="post"):
    return client.request(method.upper(), url, headers={"x-csrf-token":csrf}, json=json)


def test_renders_components():
    components=render(SCRIPT)
    assert any(x["type"]=="title" for x in components)
    assert any(x["type"]=="button" for x in components)
    assert not any("Ready to migrate" in str(x) for x in components)


def test_widget_state():
    components=render(SCRIPT)
    prompt_field=next(x for x in components if x["type"]=="textarea")
    updated=render(SCRIPT,{prompt_field["id"]:"Explain Python lists"})
    assert any("Explain Python lists" in str(x.get("value", "")) for x in updated)
    btn=next(x for x in components if x["type"]=="button")
    clicked=render(SCRIPT,{btn["id"]:True})
    assert any(x["type"]=="notice" and "Ollama" in x["value"] for x in clicked)
    assert any(x["type"]=="textarea" for x in components)
    assert any(x["type"]=="guide" for x in components)


def test_health_app_and_admin_ui(client):
    assert client.get("/health").json()["status"]=="ok"
    assert client.get("/").status_code==200
    assert "AI App Server" in client.get("/admin").text
    assert "developer sample" in SCRIPT.read_text()
    assert client.get("/static/admin.js").status_code==200
    assert client.get("/static/maintenance.svg").status_code==200


def test_websocket_event(client):
    with client.websocket_connect("/ws", headers={"origin":"http://testserver"}) as ws:
        first=ws.receive_json()
        field=next(c for c in first["components"] if c["type"]=="textarea")
        ws.send_json({"values":{field["id"]:"Explain algorithms"}})
        second=ws.receive_json()
        assert any("Explain algorithms" in str(c.get("value","")) for c in second["components"])


def test_admin_first_boot(client):
    assert client.get("/api/admin/dashboard").status_code==401
    csrf=login(client)
    assert client.get("/api/admin/me").json()["user"]["must_change_password"] is True
    assert client.get("/api/admin/dashboard").status_code==403
    assert write(client,"/api/admin/password","bad",{"current_password":"password","new_password":"something very long", "email":"admin@example.com"}).status_code==403
    assert write(client,"/api/admin/password",csrf,{"current_password":"password","new_password":"short", "email":"admin@example.com"}).status_code==400
    assert write(client,"/api/admin/password",csrf,{"current_password":"password","new_password":"much more secure password", "email":"admin@example.com"}).status_code==200
    assert client.get("/api/admin/dashboard").status_code==401
    newcsrf=login(client,password="much more secure password")
    dash=client.get("/api/admin/dashboard").json()
    assert dash["databases"]==1 and dash["users"]==1 and dash["roles"]==4
    assert newcsrf


def test_role_account_and_permissions(client):
    csrf=ready(client)
    roles=client.get("/api/admin/roles").json()["roles"]
    admin_role=next(r for r in roles if r["name"]=="Administrator")
    viewer_role=next(r for r in roles if r["name"]=="Viewer")
    body={"username":"viewer_1","display_name":"Viewer One","password":"temporary password 1", "role_id":viewer_role["id"]}
    resp=write(client,"/api/admin/users",csrf,body)
    assert resp.status_code==201,resp.text
    assert "password_hash" not in str(client.get("/api/admin/users").json())
    assert "temporary password 1" not in str(client.get("/api/admin/users").json())
    viewer_client=TestClient(client.app)
    token=login(viewer_client,"viewer_1","temporary password 1")
    assert viewer_client.get("/api/admin/roles").status_code==403
    assert write(viewer_client,"/api/admin/password",token,{"current_password":"temporary password 1","new_password":"viewer account password 123", "email":"viewer@example.com"}).status_code==200
    token=login(viewer_client,"viewer_1","viewer account password 123")
    assert viewer_client.get("/api/admin/dashboard").status_code==200
    assert viewer_client.get("/api/admin/users").status_code==403
    assert write(viewer_client,"/api/admin/users",token,body).status_code==403
    assert write(client,f"/api/admin/roles/{admin_role['id']}/permissions",csrf,{"permissions":["view_dashboard"]},method="put").status_code==200
    assert write(client,f"/api/admin/roles/{next(r for r in roles if r['name']=='Super Admin')['id']}/permissions",csrf,{"permissions":[]},method="put").status_code==400
    viewer_client.close()


def test_database_store_encrypts_url_and_rejects_system_removal(client):
    csrf=ready(client)
    res=client.get("/api/admin/databases").json()
    assert res["connections"][0]["default"] is True
    assert write(client,"/api/admin/databases",csrf,{"name":"Local example","engine":"sqlite","url":"sqlite:///:memory:"}).status_code==201
    conns=client.get("/api/admin/databases").json()["connections"]
    assert len(conns)==2
    assert "memory" not in str(conns)
    with client.app.state.store.db() as db:
        encrypted=db.execute("SELECT encrypted_url FROM database_connections").fetchone()[0]
    assert "sqlite" not in encrypted
    assert write(client,f"/api/admin/databases/{conns[1]['id']}/test",csrf).status_code==200
    assert write(client,"/api/admin/databases/0",csrf,method="delete").status_code==400
    assert write(client,f"/api/admin/databases/{conns[1]['id']}",csrf,method="delete").status_code==200


def test_maintenance_blocks_app_but_admin_remains(client):
    csrf=ready(client)
    resp=write(client,"/api/admin/settings",csrf,{"maintenance_enabled":True,"maintenance_message":"We will be right back"},method="put")
    assert resp.status_code==200,resp.text
    public=client.get("/")
    assert public.status_code==503
    assert "We will be right back" in public.text
    assert client.get("/admin").status_code==200
    assert client.get("/api/admin/dashboard").status_code==200
    assert client.get("/health").json()["maintenance"] is True
    assert write(client,"/api/admin/settings",csrf,{"maintenance_enabled":False},method="put").status_code==200
    assert client.get("/").status_code==200


def test_audit_logs_and_csrf(client):
    csrf=ready(client)
    assert write(client,"/api/admin/settings","wrong",{"app_title":"Changed"},method="put").status_code==403
    assert write(client,"/api/admin/settings",csrf,{"app_title":"New AI Server"},method="put").status_code==200
    assert client.get("/api/admin/audit").json()["events"][0]["action"]=="settings_updated"


def test_brute_force_lockout(client):
    for _ in range(5):
        resp=client.post("/api/admin/login",json={"username":"admin","password":"wrong"})
        assert resp.status_code==401
    assert client.post("/api/admin/login",json={"username":"admin","password":"password"}).status_code==429


def test_escaped_maintenance_message(client):
    csrf=ready(client)
    assert write(client,"/api/admin/settings",csrf,{"maintenance_enabled":True,"maintenance_message":"<script>alert(1)</script>"},method="put").status_code==200
    page=client.get("/").text
    assert "&lt;script&gt;" in page
    assert "<script>alert(1)</script>" not in page


def test_invalid_database_engine(client):
    csrf=ready(client)
    resp=write(client,"/api/admin/databases",csrf,{"name":"Invalid","engine":"postgresql","url":"https://x"})
    assert resp.status_code==400


def test_password_storage(tmp_path):
    store=Store(tmp_path)
    admin=store.user_by_name("admin")
    assert verify_password("password",admin["password_hash"])
    assert "password" not in admin["password_hash"]
    assert (tmp_path/"server.sqlite3").exists()
    assert (tmp_path/".secret-key").exists()


def test_recovery_email_required_on_password_change(client):
    csrf=login(client)
    assert write(client, '/api/admin/password', csrf, {
        'current_password':'password', 'new_password':'long enough admin password!'
    }).status_code == 422
    assert write(client, '/api/admin/password', csrf, {
        'current_password':'password', 'new_password':'long enough admin password!', 'email':'bad-address'
    }).status_code == 400
    assert write(client, '/api/admin/password', csrf, {
        'current_password':'password', 'new_password':'long enough admin password!', 'email':'admin@example.com'
    }).status_code == 200
    admin=client.app.state.store.user_by_name('admin')
    assert admin['email']=='admin@example.com'
    assert not admin['email_verified']
    assert client.get('/api/admin/dashboard').status_code == 401


def test_email_verify_and_forgot_password_flow(client, monkeypatch):
    sent=[]
    def fake_send_mail(to,subject,body):
        sent.append((to,subject,body))
        return True
    monkeypatch.setenv('AI_APP_SERVER_SMTP_HOST','smtp.local')
    monkeypatch.setenv('AI_APP_SERVER_SMTP_FROM','admin@local.test')
    monkeypatch.setattr('ai_app_server.admin.send_mail',fake_send_mail)
    csrf=login(client)
    res=write(client,'/api/admin/password',csrf,{
        'current_password':'password','new_password':'Initial changed password 123!','email':'admin@example.com'
    })
    assert res.status_code==200 and res.json()['verification_sent']
    assert len(sent)==1
    token=sent[0][2].split('verify-email=')[1].split()[0]
    assert 'token' not in str(res.json()).lower()
    verified=client.post('/api/admin/verify-email',json={'token':token})
    assert verified.status_code==200
    assert client.post('/api/admin/verify-email',json={'token':token}).status_code==400
    assert client.app.state.store.user_by_name('admin')['email_verified']
    assert client.post('/api/admin/forgot-password', json={'email':'nobody@example.com'}).status_code==200
    assert len(sent)==1
    assert client.post('/api/admin/forgot-password', json={'email':'admin@example.com'}).status_code==200
    reset_token=sent[-1][2].split('reset-password=')[1].split()[0]
    assert client.post('/api/admin/reset-password',json={'token':reset_token,'new_password':'too-short'}).status_code==400
    assert client.post('/api/admin/reset-password',json={'token':reset_token,'new_password':'brand new admin password 123'}).status_code==200
    assert client.post('/api/admin/reset-password',json={'token':reset_token,'new_password':'brand new admin password 123'}).status_code==400
    assert client.post('/api/admin/login',json={'username':'admin','password':'Initial changed password 123!'}).status_code==401
    assert client.post('/api/admin/login',json={'username':'admin','password':'brand new admin password 123'}).status_code==200


def test_password_recovery_no_smtp_never_exposes_reset_token(client):
    csrf=ready(client)
    assert client.post('/api/admin/forgot-password',json={'email':'admin@example.com'}).status_code==200
    with client.app.state.store.db() as db:
        assert not db.execute("SELECT 1 FROM email_tokens WHERE purpose='reset'").fetchone()


def test_existing_sqlite_upgrade_preserves_users(tmp_path):
    import sqlite3
    store=Store(tmp_path)
    with store.db() as db:
        db.execute('ALTER TABLE users DROP COLUMN email_verified')
    old_hash=store.user_by_name('admin')['password_hash']
    updated=Store(tmp_path)
    assert updated.user_by_name('admin')['password_hash']==old_hash
    assert updated.user_by_name('admin')['email_verified']==0


def test_ollama_models_are_local_and_optional(monkeypatch):
    from ai_app_server import ollama
    import io
    class Reply(io.BytesIO):
        def __enter__(self):return self
        def __exit__(self,*_):self.close()
    def open_local(url, *a, **kw):
        assert url=='http://127.0.0.1:11434/api/tags'
        return Reply(b'{"models":[{"name":"tinyllama:latest"},{"name":"llama3.2:latest"}]}')
    monkeypatch.setenv('AI_APP_SERVER_OLLAMA_URL','http://127.0.0.1:11434')
    monkeypatch.setattr(ollama,'urlopen',open_local)
    assert ollama.models(refresh=True)==['llama3.2:latest','tinyllama:latest']


def test_ollama_generation_checks_installed_model(monkeypatch):
    import io
    from ai_app_server import ollama
    class Reply(io.BytesIO):
        def __enter__(self):return self
        def __exit__(self,*_):self.close()
    monkeypatch.setattr(ollama,'models',lambda **_: ['tinyllama:latest'])
    def fake_open(req, **kw):
        import json
        assert req.full_url.endswith('/api/generate')
        data=json.loads(req.data)
        assert data == {'model':'tinyllama:latest','prompt':'Hello','stream':False}
        return Reply(b'{"response":"Hello to you!"}')
    monkeypatch.setattr(ollama,'urlopen',fake_open)
    assert ollama.generate('Hello','tinyllama:latest') == 'Hello to you!'
    with pytest.raises(ValueError):
        ollama.generate('Hello','unknown-model')


def test_starter_generate_button_shows_model_output_and_removes_project_options(tmp_path, monkeypatch):
    """A real browser WebSocket button click must execute local model generation."""
    from ai_app_server import ollama

    calls = []
    monkeypatch.setattr(ollama, 'models', lambda **_: ['tinyllama:latest'])

    def fake_generate(prompt, model):
        calls.append((prompt, model))
        return 'An answer from your own model.\nSecond line.'

    monkeypatch.setattr(ollama, 'generate', fake_generate)
    with TestClient(create_app(SCRIPT, data_dir=tmp_path)) as client:
        with client.websocket_connect('/ws') as ws:
            initial = ws.receive_json()['components']
            labels = [item.get('label', '') for item in initial]
            sections = [item.get('value', '') for item in initial]
            assert 'Project type' not in labels
            assert 'Developer / project name' not in labels
            assert 'Show developer instructions' not in labels
            assert 'Project options' not in sections
            assert any(item['type'] == 'select' and item['container'] == 'sidebar'
                       for item in initial)
            assert any(item['type'] == 'button' and item['id'] == 'generate'
                       for item in initial)

            ws.send_json({'values': {'model': 'tinyllama:latest', 'prompt': 'Tell me about Python', 'generate': True}})
            response = ws.receive_json()['components']
            assert calls == [('Tell me about Python', 'tinyllama:latest')]
            assert any(item['type'] == 'output' and
                       item['value'] == 'An answer from your own model.\nSecond line.'
                       for item in response)

            # Widgets cause script reruns, but the generated answer remains visible.
            ws.send_json({'values': {'model': 'tinyllama:latest', 'prompt': 'New prompt'}})
            refreshed = ws.receive_json()['components']
            assert any(item['type'] == 'output' for item in refreshed)
            assert len(calls) == 1

        # Other browser sessions must never inherit this answer.
        with client.websocket_connect('/ws') as ws:
            fresh = ws.receive_json()['components']
            assert not any(item['type'] == 'output' for item in fresh)


def test_starter_generate_requires_available_model(tmp_path, monkeypatch):
    from ai_app_server import ollama
    monkeypatch.setattr(ollama, 'models', lambda **_: [])
    with TestClient(create_app(SCRIPT, data_dir=tmp_path)) as client:
        with client.websocket_connect('/ws') as ws:
            ws.receive_json()
            ws.send_json({'values': {'prompt': 'Hello', 'generate': True}})
            components = ws.receive_json()['components']
            assert any(item['type'] == 'notice' and 'No Ollama model' in item['value']
                       for item in components)


def test_starter_generate_handles_connection_failure(tmp_path, monkeypatch):
    from ai_app_server import ollama
    from urllib.error import URLError
    monkeypatch.setattr(ollama, 'models', lambda **_: ['local:latest'])
    monkeypatch.setattr(ollama, 'generate', lambda *_: (_ for _ in ()).throw(URLError('refused')))
    with TestClient(create_app(SCRIPT, data_dir=tmp_path)) as client:
        with client.websocket_connect('/ws') as ws:
            ws.receive_json()
            ws.send_json({'values': {'model': 'local:latest', 'prompt': 'Hello', 'generate': True}})
            result = ws.receive_json()['components']
            assert any(item['type'] == 'notice' and item['tone'] == 'error' and
                       'Cannot connect to Ollama' in item['value'] for item in result)
