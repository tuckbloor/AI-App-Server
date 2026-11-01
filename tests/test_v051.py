"""Recovery release: zero-elevation launcher, port handling, and data safety."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_app_server.desktop_launcher import (
    instance_responding, launch, pick_port, enable_startup, disable_startup,
)
from ai_app_server.hosting import save_hosting, read_hosting
from ai_app_server.server import create_app
from ai_app_server.service import service_name


def project(tmp_path):
    home=tmp_path / 'project'
    (home / 'examples').mkdir(parents=True)
    script=home / 'examples' / 'app.py'
    script.write_text('import ai_app_server as ui\nui.title("Hello")\n', encoding='utf-8')
    return home, script, home / 'data'


def test_health_can_distinguish_other_python_apps(tmp_path):
    root, script, data = project(tmp_path)
    with TestClient(create_app(script, data_dir=data)) as client:
        response=client.get('/health')
        assert response.status_code == 200
        assert response.json()['app_id'] == service_name(script)


def test_existing_app_opened_without_starting_duplicate(tmp_path, monkeypatch):
    root, script, data = project(tmp_path)
    db=data / 'server.sqlite3'
    db.parent.mkdir(exist_ok=True)
    db.write_bytes(b'EXISTING ADMIN DATABASE')
    save_hosting(data, 8688)
    monkeypatch.setattr('ai_app_server.desktop_launcher.instance_responding', lambda script,port:port == 8688)
    result=launch(root, open_browser=False)
    assert result['already_running'] is True
    assert result['port'] == 8688
    assert db.read_bytes() == b'EXISTING ADMIN DATABASE'


def test_existing_port_conflict_fails_closed_without_touching_db(tmp_path, monkeypatch):
    root, script, data=project(tmp_path)
    save_hosting(data, 8501)
    db=data/'server.sqlite3'
    db.write_bytes(b'EXISTING DATABASE')
    monkeypatch.setattr('ai_app_server.desktop_launcher.instance_responding', lambda script,port:False)
    monkeypatch.setattr('ai_app_server.desktop_launcher.is_port_free',lambda port:port == 8502)
    with pytest.raises(RuntimeError, match="Configured port 8501 is busy"):
        pick_port(script,data)
    assert read_hosting(data)['port'] == 8501
    assert db.read_bytes() == b'EXISTING DATABASE'


def test_startup_shortcut_is_user_level_and_project_scoped(tmp_path,monkeypatch):
    root, script, data=project(tmp_path)
    monkeypatch.setattr('ai_app_server.desktop_launcher.sys.platform','win32')
    monkeypatch.setenv('APPDATA',str(tmp_path/'Roaming'))
    shortcut=enable_startup(root)
    assert shortcut.is_file()
    text=shortcut.read_text(encoding='utf-8')
    assert str(root/'Launch in Background.bat') in text
    assert str(shortcut).startswith(str(tmp_path/'Roaming'))
    disable_startup(root)
    assert not shortcut.exists()


def test_launcher_reports_missing_application(tmp_path):
    with pytest.raises(FileNotFoundError,match='extract the entire ZIP'):
        launch(tmp_path/'missing',open_browser=False)
