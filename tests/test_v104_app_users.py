"""v1.0.4: separate individual application identities and safe v1.0.3 migration."""
import hashlib
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from ai_app_server.server import create_app
from ai_app_server.storage import Store, SCHEMA_VERSION

ORIGIN = 'https://ai.example.test'


def configured(monkeypatch, data):
    store = Store(data)
    store.update_password(1, 'a-unique-changed-admin-password-2026')
    monkeypatch.setenv('AI_APP_SERVER_BEHIND_TLS_PROXY','1')
    monkeypatch.setenv('AI_APP_SERVER_PUBLIC_ORIGIN',ORIGIN)
    return store


def test_prod_rejects_shared_environment_secret_without_app_accounts(monkeypatch, tmp_path):
    monkeypatch.setenv('AI_APP_SERVER_APP_PASSWORD','a-unique-old-shared-password-2026')
    store = configured(monkeypatch, tmp_path/'data')
    script = tmp_path/'app.py'; script.write_text('import ai_app_server as ui\nui.title("Hi")')
    with pytest.raises(ValueError, match='Create at least one active application user'):
        create_app(script, data_dir=store.directory, mode='production')


def test_individual_users_sessions_disable_reset_and_admin_separation(monkeypatch, tmp_path):
    store=configured(monkeypatch,tmp_path/'data')
    store.create_app_user('alice','Alice','a-long-and-different-password-1')
    store.create_app_user('bob','Bob','a-long-and-different-password-2')
    script=tmp_path/'app.py';script.write_text('import ai_app_server as ui\nui.title("Hi")')
    with TestClient(create_app(script,data_dir=store.directory,mode='production'),base_url=ORIGIN) as c:
        assert c.get('/',follow_redirects=False).status_code==303
        assert c.post('/api/app/login',headers={'origin':ORIGIN},json={'password':'a-long-and-different-password-1'}).status_code==401
        assert c.post('/api/app/login',headers={'origin':ORIGIN},json={'username':'alice','password':'incorrect'}).status_code==401
        assert c.post('/api/app/login',headers={'origin':ORIGIN},json={'username':'alice','password':'a-long-and-different-password-2'}).status_code==401
        r=c.post('/api/app/login',headers={'origin':ORIGIN},json={'username':'alice','password':'a-long-and-different-password-1'})
        assert r.status_code==200
        token=c.cookies.get('aia_app_session')
        assert token and store.app_session_user(token)['username']=='alice'
        assert 'httponly' in r.headers['set-cookie'].lower()
        assert 'secure' in r.headers['set-cookie'].lower()
        assert c.get('/').status_code==200
        assert c.get('/api/admin/users').status_code==401
        alice=store.app_user_by_name('alice')
        assert store.set_app_user_active(alice['id'],False)
        assert not store.valid_app_session(token)
        assert c.get('/',follow_redirects=False).status_code==303
        assert c.post('/api/app/login',headers={'origin':ORIGIN},json={'username':'alice','password':'a-long-and-different-password-1'}).status_code==401
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect('/ws',headers={'origin':ORIGIN,'host':'ai.example.test'}):pass
        assert store.set_app_user_active(alice['id'],True)
        assert c.post('/api/app/login',headers={'origin':ORIGIN},json={'username':'bob','password':'a-long-and-different-password-2'}).status_code==200
        bobtoken=c.cookies.get('aia_app_session')
        bob=store.app_user_by_name('bob')
        assert store.reset_app_user_password(bob['id'],'new-secure-personal-password-2')
        assert not store.valid_app_session(bobtoken)
        assert c.post('/api/app/login',headers={'origin':ORIGIN},json={'username':'bob','password':'a-long-and-different-password-2'}).status_code==401
        assert c.post('/api/app/login',headers={'origin':ORIGIN},json={'username':'bob','password':'new-secure-personal-password-2'}).status_code==200


def test_only_admin_with_manage_users_and_csrf_can_edit_app_users(tmp_path):
    script=tmp_path/'app.py';script.write_text('import ai_app_server as ui\nui.title("Hi")')
    with TestClient(create_app(script,data_dir=tmp_path/'data')) as c:
        assert c.post('/api/admin/app-users',json={'username':'alice','display_name':'Alice','password':'a-long-and-different-password-1'}).status_code==401
        store=c.app.state.store
        store.update_password(1,'a-changed-admin-password-2026')
        csrf=c.post('/api/admin/login',json={'username':'admin','password':'a-changed-admin-password-2026'}).json()['csrf']
        data={'username':'alice','display_name':'Alice','email':'alice@example.test','password':'a-long-and-different-password-1'}
        assert c.post('/api/admin/app-users',json=data).status_code==403
        assert c.post('/api/admin/app-users',json=data,headers={'x-csrf-token':csrf}).status_code==201
        assert c.post('/api/admin/app-users',json=data,headers={'x-csrf-token':csrf}).status_code==409
        users=c.get('/api/admin/app-users').json()['users']
        assert len(users)==1 and 'password_hash' not in users[0]
        uid=users[0]['id']
        assert c.post(f'/api/admin/app-users/{uid}/reset-password',headers={'x-csrf-token':csrf},json={'new_password':'short'}).status_code==422
        assert c.patch(f'/api/admin/app-users/{uid}',headers={'x-csrf-token':csrf},json={'is_active':False}).status_code==200
        assert c.get('/api/admin/app-users').json()['users'][0]['is_active']==0


def test_old_shared_sessions_invalidated_and_schema_backed_up(tmp_path):
    data=tmp_path/'data'
    store=Store(data)
    store.update_password(1,'long-admin-password-after-setup')
    key=store.key_path.read_bytes()
    with store.db() as db:
        db.execute('DROP TABLE app_users')
        db.execute('DROP INDEX ix_app_sessions_user')
        db.execute('ALTER TABLE app_sessions RENAME TO app_sessions_with_user')
        db.execute('CREATE TABLE app_sessions(token_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL)')
        db.execute('INSERT INTO app_sessions VALUES (?,?)',(hashlib.sha256(b'old-shared-token').hexdigest(),'2099-01-01T00:00:00+00:00'))
        db.execute('DROP TABLE app_sessions_with_user')
        db.execute('PRAGMA user_version=5')
    migrated=Store(data)
    assert migrated.key_path.read_bytes()==key
    assert migrated.user_by_name('admin')['must_change_password']==0
    assert not migrated.valid_app_session('old-shared-token')
    with migrated.db() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
        assert 'user_id' in {x['name'] for x in db.execute('PRAGMA table_info(app_sessions)')}
        assert db.execute('SELECT count(*) FROM app_sessions').fetchone()[0]==0
    backups=list((data/'backups').glob('server-before-v6-*.sqlite3'))
    assert backups
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==5
