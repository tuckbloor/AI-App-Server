"""Regression checks: never hard-code admin version labels."""
from pathlib import Path
from fastapi.testclient import TestClient
from ai_app_server.server import create_app
from ai_app_server.version import __version__


def test_admin_reports_actual_engine_version(tmp_path):
    script=tmp_path / "app.py"
    script.write_text("import ai_app_server as ui\nui.title('Version check')\n")
    with TestClient(create_app(script,data_dir=tmp_path / "data")) as c:
        r=c.post('/api/admin/login',json={'username':'admin','password':'password'})
        assert r.status_code==200
        me=c.get('/api/admin/me')
        assert me.status_code==200
        assert me.json()['version']==__version__
        token=me.json()['csrf']
        c.post('/api/admin/password', json={'current_password':'password',
            'new_password':'new-password-that-is-long-enough', 'email':'admin@example.com'},
            headers={'X-CSRF-Token':token})
        login=c.post('/api/admin/login',json={'username':'admin','password':'new-password-that-is-long-enough'})
        assert login.status_code==200
        r=c.get('/api/admin/dashboard')
        assert r.status_code==200
        assert r.json()['server']['version']==__version__


def test_sidebar_label_uses_authenticated_server_version():
    from ai_app_server import admin
    s=(Path(admin.__file__).parent / 'static/admin.js').read_text()
    assert 'v0.9.1 • Independently hosted' not in s
    assert 'state.version=me.version' in s
    assert "state.version?'v'+state.version" in s
