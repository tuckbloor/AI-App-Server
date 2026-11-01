"""v0.5 plug-and-play port settings and independent application hosting."""
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient

from ai_app_server.hosting import initialize_port, read_hosting, save_hosting, validate_port, is_port_free
from ai_app_server.server import create_app
from ai_app_server.cli import main


def make_script(directory: Path) -> Path:
    directory.mkdir(parents=True)
    result = directory / 'app.py'
    result.write_text('import ai_app_server as ui\nui.title("Testing")\n', encoding='utf-8')
    return result


def test_hosting_is_per_project_and_sqlite_unchanged(tmp_path):
    first = tmp_path / 'first' / 'data'
    second = tmp_path / 'second' / 'data'
    a = initialize_port(first, preferred=8610)
    b = initialize_port(second, preferred=8611)
    assert a['port'] == 8610 and b['port'] == 8611
    old_key = (first / 'server.sqlite3')
    old_key.write_bytes(b'pretend-existing-db')
    save_hosting(first, 8777)
    assert (first / 'server.sqlite3').read_bytes() == b'pretend-existing-db'
    assert read_hosting(second)['port'] == 8611
    assert read_hosting(first)['port'] == 8777


def test_port_settings_validate_and_choose_free(tmp_path, monkeypatch):
    from ai_app_server import hosting
    with pytest.raises(ValueError): validate_port(80)
    with pytest.raises(ValueError): validate_port(True)
    with pytest.raises(ValueError): validate_port(90000)
    monkeypatch.setattr(hosting, 'is_port_free', lambda port: port != 8501)
    assert initialize_port(tmp_path)['port'] == 8502
    assert initialize_port(tmp_path)['port'] == 8502
    path = tmp_path / 'hosting.json'
    contents = path.read_text()
    with pytest.raises(ValueError): save_hosting(tmp_path, -1)
    assert path.read_text() == contents


def test_admin_can_save_port_not_touch_sqlite_and_csrf_required(tmp_path):
    script = make_script(tmp_path / 'demo')
    with TestClient(create_app(script)) as c:
        store = c.app.state.store
        db_before = store.path.stat().st_size
        assert c.put('/api/admin/hosting', json={'port': 8765}).status_code == 401
        login = c.post('/api/admin/login', json={'username': 'admin', 'password': 'password'})
        csrf = login.json()['csrf']
        assert c.put('/api/admin/hosting', json={'port': 8765}).status_code == 403
        change = c.post('/api/admin/password', json={
            'current_password':'password', 'new_password':'a stronger admin password 2026!@#',
            'email':'admin@example.com'}, headers={'X-CSRF-Token':csrf})
        assert change.status_code == 200, change.text
        login2 = c.post('/api/admin/login', json={'username':'admin','password':'a stronger admin password 2026!@#'})
        csrf = login2.json()['csrf']
        result = c.put('/api/admin/hosting', json={'port': 8765}, headers={'X-CSRF-Token':csrf})
        assert result.status_code == 200, result.text
        assert result.json()['restart_required'] is True
        assert read_hosting(store.directory)['port'] == 8765
        assert store.user_by_name('admin')['email'] == 'admin@example.com'
        assert c.get('/api/admin/service').json()['hosting']['port'] == 8765
        # Only the deployment's hosting JSON changed; DB still accessible.
        assert store.path.exists() and store.path.stat().st_size >= db_before
        invalid = c.put('/api/admin/hosting', json={'port': 81}, headers={'X-CSRF-Token':csrf})
        assert invalid.status_code == 422
        assert read_hosting(store.directory)['port'] == 8765


def test_platform_specific_service_code_imports_without_win32(tmp_path):
    import ai_app_server.windows_service as ws
    assert hasattr(ws, 'main') and hasattr(ws, 'install_service')
    if ws.sys.platform != 'win32':
        with pytest.raises(RuntimeError, match='only available on Windows'):
            ws.windows_modules()
