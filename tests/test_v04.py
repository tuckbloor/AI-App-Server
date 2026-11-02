"""v0.4 regression tests: preserve installations and isolate independent apps."""
import os
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET
import pytest
from fastapi.testclient import TestClient

from ai_app_server.storage import SCHEMA_VERSION, Store, verify_password
from ai_app_server.server import create_app
from ai_app_server.service import project_data_dir, service_name, service_paths, service_xml, service_status
from ai_app_server.cli import main


def script_in(path, text='import ai_app_server as ui\nui.title("App")\n'):
    path.mkdir(parents=True)
    script = path / 'app.py'
    script.write_text(text, encoding='utf-8')
    return script


def test_separate_apps_cannot_see_others_admin_users_or_settings(tmp_path):
    first = script_in(tmp_path / 'alpha')
    second = script_in(tmp_path / 'beta')
    assert project_data_dir(first) != project_data_dir(second)
    with TestClient(create_app(first)) as a, TestClient(create_app(second)) as b:
        a_store, b_store = a.app.state.store, b.app.state.store
        assert a_store.path != b_store.path
        a_store.update_settings({'app_title': 'Private Alpha', 'maintenance_enabled': True})
        with a_store.db() as db:
            db.execute("INSERT INTO users(username,display_name,password_hash,role_id,created_at) "
                       "VALUES ('alpha_only','Only alpha','not-a-hash',1,'2026-01-01')")
        assert a_store.user_by_name('alpha_only')
        assert not b_store.user_by_name('alpha_only')
        assert a_store.settings()['app_title']=='Private Alpha'
        assert b_store.settings()['app_title']=='AI App Server'
        assert a.get('/').status_code == 503
        assert b.get('/').status_code == 200
        assert a_store.key_path != b_store.key_path


def test_upgrade_existing_sqlite_backs_up_and_preserves_admin_connections_roles(tmp_path):
    data = tmp_path / 'original-data'
    original = Store(data)
    old_password = 'previously set admin password abc!'
    original.update_password(1, old_password, email='root@example.com')
    with original.db() as db:
        db.execute('INSERT INTO database_connections(name,engine,encrypted_url,created_at) VALUES(?,?,?,?)',
                   ('Finance SQL', 'mssql', original.encrypt('mssql+pyodbc://internal/private'), '2026-01-01'))
        db.execute("INSERT INTO roles(name,description,is_system) VALUES ('Financial Reviewer','Reports',0)")
        db.execute('PRAGMA user_version=3')
    key_before = original.key_path.read_bytes()
    restored = Store(data)
    assert restored.key_path.read_bytes() == key_before
    assert verify_password(old_password, restored.user_by_name('admin')['password_hash'])
    assert restored.user_by_name('admin')['email'] == 'root@example.com'
    with restored.db() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert db.execute("SELECT 1 FROM roles WHERE name='Financial Reviewer'").fetchone()
        conn = db.execute("SELECT encrypted_url FROM database_connections WHERE name='Finance SQL'").fetchone()
        assert restored.decrypt(conn[0]) == 'mssql+pyodbc://internal/private'
    backup_files = list((data / 'backups').glob(f'server-before-v{SCHEMA_VERSION}-*.sqlite3'))
    assert len(backup_files) == 1
    with sqlite3.connect(backup_files[0]) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 3
        assert backup.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1
    Store(data)
    assert len(list((data / 'backups').glob(f'server-before-v{SCHEMA_VERSION}-*.sqlite3'))) == 1


def test_missing_key_must_not_be_silently_regenerated(tmp_path):
    data = tmp_path / 'private'
    store = Store(data)
    store.key_path.unlink()
    with pytest.raises(RuntimeError, match='original key'):
        Store(data)
    assert not store.key_path.exists()


def test_manual_backup_contains_sqlite_and_unchanged_encryption_key(tmp_path):
    data = tmp_path / 'instance'
    store = Store(data)
    dest = tmp_path / 'offsite-copy'
    store.backup(dest)
    assert (dest / 'server.sqlite3').exists()
    assert (dest / '.secret-key').read_bytes() == store.key_path.read_bytes()
    with pytest.raises(ValueError, match='empty'):
        store.backup(dest)
    with pytest.raises(ValueError, match='outside'):
        store.backup(data / 'backups' / 'wrong-place')


def test_read_only_service_endpoint_is_scoped_and_permission_protected(tmp_path):
    script = script_in(tmp_path / 'only')
    with TestClient(create_app(script)) as c:
        assert c.get('/api/admin/service').status_code == 401
        result = c.post('/api/admin/login',json={'username':'admin','password':'password'})
        assert result.status_code == 200
        csrf=result.json()['csrf']
        response=c.post('/api/admin/password', headers={'X-CSRF-Token':csrf},json={
            'current_password':'password', 'new_password':'much more secure admin password 2026!',
            'email':'admin@example.com'})
        assert response.status_code==200
        c.post('/api/admin/login',json={'username':'admin','password':'much more secure admin password 2026!'})
        service=c.get('/api/admin/service')
        assert service.status_code == 200
        info=service.json()
        assert info['application'] == 'app.py'
        assert info['name'] == service_name(script)
        assert 'applications' not in info
        assert c.post('/api/admin/service').status_code == 405


def test_winsw_service_config_is_independent_and_quotes_paths(tmp_path):
    script=script_in(tmp_path / 'my project')
    other=script_in(tmp_path / 'another project')
    assert service_name(script)!=service_name(other)
    data=project_data_dir(script)
    exe, xmlpath=service_paths(script)
    assert exe.parent==data/'service'
    assert xmlpath.suffix=='.xml'
    xml=service_xml(script,data,port=8600,interpreter=Path(sys.executable))
    root=ET.fromstring(xml)
    assert root.findtext('id')==service_name(script)
    assert root.findtext('startmode')=='Automatic'
    assert root.findtext('executable')==str(Path(sys.executable).resolve())
    assert '8600' in root.findtext('arguments')
    assert str(script) in root.findtext('arguments')
    assert root.find('onfailure').attrib['action']=='restart'
    assert root.find('log').attrib['mode']=='roll'
    assert root.findtext('serviceaccount/prompt') == 'dialog'
    assert '<password>' not in xml
    with pytest.raises(ValueError,match='production'):
        service_xml(script,data,host='0.0.0.0')


def test_cli_backup_uses_explicit_legacy_data_path(tmp_path):
    script=script_in(tmp_path / 'old-app')
    legacy=tmp_path / 'legacy'
    original=Store(legacy)
    original.update_settings({'app_title': 'Existing installation'})
    copy=tmp_path / 'external-copy'
    assert main(['backup',str(script),'--data-dir',str(legacy),'--to',str(copy)]) == 0
    assert (copy/'.secret-key').exists()
    with sqlite3.connect(copy/'server.sqlite3') as db:
        assert db.execute("SELECT value FROM settings WHERE key='app_title'").fetchone()[0]=='"Existing installation"'
    assert not project_data_dir(script).exists()
