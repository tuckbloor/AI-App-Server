"""Production security checks and optional application-scoped agents."""
from pathlib import Path
import importlib.util
import sqlite3

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ai_app_server.server import create_app
from ai_app_server.storage import Store, SCHEMA_VERSION
from ai_app_server.agents import Agent, AgentPipeline

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'starter' / 'app.py'
ORIGIN = 'https://ai.example.test'


def prepare_production(monkeypatch, tmp_path):
    store = Store(tmp_path / 'data')
    store.update_password(1, 'Unique-admin-passphrase-2026-very-long', email='boss@example.test')
    monkeypatch.setenv('AI_APP_SERVER_BEHIND_TLS_PROXY', '1')
    monkeypatch.setenv('AI_APP_SERVER_PUBLIC_ORIGIN', ORIGIN)
    monkeypatch.setenv('AI_APP_SERVER_APP_PASSWORD', 'very-unique-private-app-passphrase-123')
    return store


def test_development_keeps_simple_starter_unlocked(tmp_path, monkeypatch):
    monkeypatch.delenv('AI_APP_SERVER_APP_PASSWORD', raising=False)
    with TestClient(create_app(SCRIPT, data_dir=tmp_path)) as client:
        assert client.get('/').status_code == 200
        with client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as ws:
            assert ws.receive_json()['components']


def test_production_rejects_first_run_default_admin_even_when_proxy_configured(monkeypatch, tmp_path):
    monkeypatch.setenv('AI_APP_SERVER_BEHIND_TLS_PROXY', '1')
    monkeypatch.setenv('AI_APP_SERVER_PUBLIC_ORIGIN', ORIGIN)
    monkeypatch.setenv('AI_APP_SERVER_APP_PASSWORD', 'unique-private-passphrase-12345')
    with pytest.raises(ValueError, match='initial administrator password'):
        create_app(SCRIPT, data_dir=tmp_path / 'data', mode='production')


def test_production_requires_tls_and_password_and_local_binding(monkeypatch, tmp_path):
    prepare_production(monkeypatch, tmp_path)
    monkeypatch.delenv('AI_APP_SERVER_BEHIND_TLS_PROXY')
    with pytest.raises(ValueError, match='TLS reverse proxy'):
        create_app(SCRIPT, data_dir=tmp_path / 'data', mode='production')
    monkeypatch.setenv('AI_APP_SERVER_BEHIND_TLS_PROXY', '1')
    monkeypatch.setenv('AI_APP_SERVER_APP_PASSWORD', 'password')
    with pytest.raises(ValueError, match='16–256 characters'):
        create_app(SCRIPT, data_dir=tmp_path / 'data', mode='production')
    monkeypatch.setenv('AI_APP_SERVER_APP_PASSWORD', 'unique-private-passphrase-12345')
    with pytest.raises(ValueError, match='127.0.0.1'):
        create_app(SCRIPT, data_dir=tmp_path / 'data', mode='production', local_only=False)


def test_production_independent_app_login_and_websocket_authorisation(monkeypatch, tmp_path):
    prepare_production(monkeypatch, tmp_path)
    app = create_app(SCRIPT, data_dir=tmp_path / 'data', mode='production', secure_cookies=True)
    with TestClient(app, base_url=ORIGIN) as anonymous:
        assert anonymous.get('/').status_code == 200  # redirect follows to sign-in
        response = anonymous.get('/', follow_redirects=False)
        assert response.status_code == 303 and response.headers['location'] == '/app-login'
        assert anonymous.get('/app-login').status_code == 200
        assert anonymous.get('/api/admin/me').status_code == 401
        assert anonymous.post('/api/app/login', json={'password': 'bad'}, headers={'origin': ORIGIN}).status_code == 401
        with pytest.raises(WebSocketDisconnect) as exc:
            with anonymous.websocket_connect('/ws', headers={'origin': ORIGIN}):
                pass
        assert exc.value.code == 1008
        login = anonymous.post('/api/app/login', json={'password': 'very-unique-private-app-passphrase-123'}, headers={'origin': ORIGIN})
        assert login.status_code == 200
        cookie = login.headers['set-cookie']
        assert 'Secure' in cookie and 'httponly' in cookie.lower()
        assert anonymous.get('/').status_code == 200
        assert anonymous.get('/api/admin/me').status_code == 401
        assert anonymous.get('/health').json() == {'status':'ok'}
        assert anonymous.get('/').headers['strict-transport-security'].startswith('max-age=')
        with pytest.raises(WebSocketDisconnect):
            with anonymous.websocket_connect('/ws', headers={'origin': 'https://evil.test'}):
                pass
        with anonymous.websocket_connect('/ws', headers={'origin': ORIGIN, 'host': 'ai.example.test', 'cookie': f'aia_app_session={anonymous.cookies.get("aia_app_session")}'}) as ws:
            assert ws.receive_json()['components']
        assert anonymous.post('/api/app/logout', headers={'origin': ORIGIN}).status_code == 200
        assert anonymous.get('/', follow_redirects=False).status_code == 303


def test_production_rejects_unknown_host(monkeypatch, tmp_path):
    prepare_production(monkeypatch, tmp_path)
    app = create_app(SCRIPT, data_dir=tmp_path / 'data', mode='production')
    with TestClient(app, base_url='https://malicious.example') as c:
        assert c.get('/app-login').status_code == 400


def test_existing_data_survives_v5_migration(tmp_path):
    store = Store(tmp_path / 'data')
    store.update_password(1, 'something-unique-and-strong-2026')
    with store.db() as conn:
        conn.execute('PRAGMA user_version=4')
    existing_key = store.key_path.read_bytes()
    upgraded = Store(tmp_path / 'data')
    assert upgraded.key_path.read_bytes() == existing_key
    with upgraded.db() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='app_sessions'").fetchone()
    assert upgraded.user_by_name('admin')['must_change_password'] == 0
    assert list((tmp_path / 'data' / 'backups').glob('server-before-v5-*'))


def test_agents_are_optional_and_application_owned(monkeypatch):
    calls = []
    def fake_generate(prompt, model):
        calls.append((prompt, model))
        return 'answer-' + str(len(calls))
    monkeypatch.setattr('ai_app_server.agents.ollama.generate', fake_generate)
    pipeline = AgentPipeline(Agent('Research', 'modelA', 'Gather evidence'), Agent('Summary', 'modelB', 'Summarise'))
    assert pipeline.run('A request') == [
        {'agent': 'Research', 'output': 'answer-1'},
        {'agent': 'Summary', 'output': 'answer-2'},
    ]
    assert calls[0][1] == 'modelA'
    assert 'answer-1' in calls[1][0]
    with pytest.raises(ValueError):
        AgentPipeline()


def test_production_app_login_origin_required(monkeypatch, tmp_path):
    prepare_production(monkeypatch, tmp_path)
    app = create_app(SCRIPT, data_dir=tmp_path / 'data', mode='production')
    with TestClient(app, base_url=ORIGIN) as c:
        assert c.post('/api/app/login', json={'password': 'very-unique-private-app-passphrase-123'}).status_code == 403
        assert c.post('/api/app/login', json={'password': 'very-unique-private-app-passphrase-123'}, headers={'origin':'https://elsewhere.test'}).status_code == 403
        assert c.post('/api/app/login', json={'password': 'very-unique-private-app-passphrase-123'}, headers={'origin':ORIGIN}).status_code == 200


def test_updater_restores_pre_migration_database_on_failed_restart(tmp_path, monkeypatch):
    import importlib.util
    import shutil
    root = tmp_path / 'installation'
    root.mkdir()
    shutil.copytree(ROOT / 'engine', root / 'engine', ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    datadir = root / 'data'
    store = Store(datadir)
    store.update_password(1, 'old-admin-password-long-enough')
    # A v0.7 schema on disk; pretend the next engine applied an incompatible v0.8 migration.
    spec = importlib.util.spec_from_file_location('updater070', ROOT / 'tools' / 'update_engine.py')
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    incoming = tmp_path / 'new-engine'
    shutil.copytree(root / 'engine', incoming)
    (incoming / 'ai_app_server' / 'version.py').write_text('__version__ = "0.8.1"\n')
    def fake_command(*args, **kwargs):
        if any('desktop_launcher' in str(a) for a in args) and 'start' in args and updater.version(root / 'engine') == (0, 8, 1):
            with sqlite3.connect(datadir / 'server.sqlite3') as conn:
                conn.execute('PRAGMA user_version=99')
                conn.execute('CREATE TABLE bad_migration(test TEXT)')
            raise RuntimeError('simulated new engine failed health check')
    monkeypatch.setattr(updater, '_command', fake_command)
    with pytest.raises(RuntimeError, match='pre-upgrade SQLite snapshot reinstated'):
        updater.update(root, incoming)
    assert updater.version(root / 'engine') == (0, 8, 0)
    restored = Store(datadir)
    with restored.db() as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='bad_migration'").fetchone()
    assert restored.user_by_name('admin')['must_change_password'] == 0
