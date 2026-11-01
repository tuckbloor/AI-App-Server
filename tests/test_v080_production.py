"""Deployment-preflight and environment regression tests for the v0.8 engine."""
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from ai_app_server.app_security import production_checks, request_ip
from ai_app_server.cli import main
from ai_app_server.hosting import read_hosting, save_hosting
from ai_app_server.server import create_app
from ai_app_server.storage import Store

SCRIPT = Path(__file__).resolve().parents[1] / 'starter' / 'app.py'
ORIGIN = 'https://ai.example.test'


def secure_env(monkeypatch, store):
    store.update_password(1, 'a genuinely long administrator passphrase', email='admin@example.test')
    monkeypatch.setenv('AI_APP_SERVER_BEHIND_TLS_PROXY', '1')
    monkeypatch.setenv('AI_APP_SERVER_PUBLIC_ORIGIN', ORIGIN)
    monkeypatch.setenv('AI_APP_SERVER_APP_PASSWORD', 'a long and unique production gate password')


def test_hosting_mode_persists_without_touching_sqlite(tmp_path):
    store = Store(tmp_path / 'data')
    original = store.key_path.read_bytes()
    user = store.user_by_name('admin')
    assert read_hosting(store.directory)['mode'] == 'development'
    save_hosting(store.directory, 8777, mode='production')
    assert read_hosting(store.directory)['mode'] == 'production'
    save_hosting(store.directory, 8778)
    assert read_hosting(store.directory)['mode'] == 'production'
    assert store.key_path.read_bytes() == original
    assert store.user_by_name('admin')['password_hash'] == user['password_hash']
    with pytest.raises(ValueError, match='Environment'):
        save_hosting(store.directory, 8501, mode='unsafe')


def test_production_check_admin_endpoint_and_refuse_unsafe_promotion(tmp_path):
    with TestClient(create_app(SCRIPT, data_dir=tmp_path / 'data')) as c:
        login = c.post('/api/admin/login', json={'username':'admin','password':'password'})
        csrf = login.json()['csrf']
        assert c.get('/api/admin/production-check').status_code == 403  # first-run password change required
        promote = c.put('/api/admin/hosting', json={'port': 8501,'mode':'production'},
                        headers={'X-CSRF-Token':csrf})
        assert promote.status_code == 403  # change initial password first
        assert read_hosting(c.app.state.store.directory)['mode'] == 'development'


def test_admin_promotes_only_after_preflight(monkeypatch, tmp_path):
    store = Store(tmp_path / 'data')
    secure_env(monkeypatch, store)
    with TestClient(create_app(SCRIPT, data_dir=tmp_path / 'data')) as c:
        login = c.post('/api/admin/login', json={'username':'admin','password':'a genuinely long administrator passphrase'})
        csrf = login.json()['csrf']
        response = c.put('/api/admin/hosting', json={'port':8501,'mode':'production'},
                         headers={'X-CSRF-Token':csrf})
        assert response.status_code == 200, response.text
        assert read_hosting(store.directory)['mode'] == 'production'
        assert response.json()['restart_required'] is True


def test_doctor_reports_default_as_not_ready(tmp_path, capsys):
    assert main(['doctor',str(SCRIPT),'--data-dir',str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert 'ACTION NEEDED' in out and 'TLS' in out


def test_development_rejects_nonlocal_host_and_websocket(tmp_path):
    app = create_app(SCRIPT, data_dir=tmp_path / 'data')
    with TestClient(app, base_url='http://hijacked-domain.test') as c:
        assert c.get('/').status_code == 400
        with pytest.raises(WebSocketDisconnect) as exc:
            with c.websocket_connect('/ws', headers={'origin':'http://hijacked-domain.test'}):
                pass
        assert exc.value.code == 1008


def test_production_requires_https_request_or_forwarded_scheme(monkeypatch, tmp_path):
    store = Store(tmp_path / 'data')
    secure_env(monkeypatch, store)
    app = create_app(SCRIPT, data_dir=store.directory, mode='production')
    with TestClient(app, base_url='http://ai.example.test') as c:
        assert c.get('/app-login').status_code == 400
        assert c.get('/app-login', headers={'X-Forwarded-Proto':'https'}).status_code == 200
        assert c.get('/app-login', headers={'X-Forwarded-Proto':'http'}).status_code == 400


def test_production_no_internal_errors_in_websocket(monkeypatch, tmp_path):
    store = Store(tmp_path / 'data')
    secure_env(monkeypatch, store)
    bad = tmp_path / 'bad.py'
    bad.write_text('raise RuntimeError("SECRET_INTERNAL_PATH")\n', encoding='utf-8')
    app = create_app(bad, data_dir=store.directory, mode='production')
    with TestClient(app, base_url=ORIGIN) as c:
        login = c.post('/api/app/login', json={'password':'a long and unique production gate password'},
                       headers={'origin':ORIGIN})
        assert login.status_code == 200
        with c.websocket_connect('/ws', headers={'origin':ORIGIN, 'host':'ai.example.test',
                                                  'cookie': f'aia_app_session={c.cookies.get("aia_app_session")}'}) as ws:
            msg = ws.receive_json()
            assert 'Application execution failed' in msg['error']
            assert 'SECRET_INTERNAL_PATH' not in msg['error']


def test_setup_admin_cli_first_run(tmp_path, monkeypatch):
    password = 'secure admin password changed from terminal'
    monkeypatch.setattr('builtins.input', lambda prompt: 'ops@example.test')
    monkeypatch.setattr('ai_app_server.cli.getpass', lambda prompt: password)
    assert main(['setup-admin',str(SCRIPT),'--data-dir',str(tmp_path)]) == 0
    store = Store(tmp_path)
    assert not store.user_by_name('admin')['must_change_password']
    assert store.user_by_name('admin')['email'] == 'ops@example.test'
    assert main(['setup-admin',str(SCRIPT),'--data-dir',str(tmp_path)]) == 0


def test_local_launcher_refuses_production_mode(tmp_path):
    from ai_app_server.desktop_launcher import launch
    app = tmp_path / 'instance' / 'app'
    app.mkdir(parents=True)
    (app/'app.py').write_text('print("hello")', encoding='utf-8')
    save_hosting(tmp_path/'instance'/'data',8501,mode='production')
    with pytest.raises(RuntimeError, match='Production is enabled'):
        launch(tmp_path/'instance',open_browser=False)
