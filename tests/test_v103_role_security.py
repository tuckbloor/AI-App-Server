from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from ai_app_server.server import create_app
from ai_app_server.storage import password_hash

@pytest.fixture
def limited(tmp_path):
    script = tmp_path / 'app.py'
    script.write_text('from ai_app_server import ui\nui.title("Audit")\n')
    client = TestClient(create_app(script, data_dir=tmp_path / 'data'))
    store=client.app.state.store
    with store.db() as db:
        mgr=db.execute("INSERT INTO roles(name,description,is_system) VALUES ('LimitedUserManager','',0)").lastrowid
        db.execute('INSERT INTO role_permissions(role_id,permission) VALUES (?,?)',(mgr,'manage_users'))
        db.execute('INSERT INTO users(username,display_name,email,password_hash,role_id,is_active,must_change_password,created_at) VALUES (?,?,?,?,?,1,0,?)', ('limited','Limited Manager','',password_hash('a-test-password-very-long'),mgr,'2026-11-02T00:00:00+00:00'))
        elevated=db.execute("SELECT id FROM roles WHERE name='Administrator'").fetchone()['id']
        viewer=db.execute("SELECT id FROM roles WHERE name='Viewer'").fetchone()['id']
    login=client.post('/api/admin/login',json={'username':'limited','password':'a-test-password-very-long'})
    assert login.status_code==200
    yield client, store, {'x-csrf-token':login.json()['csrf']}, elevated, viewer
    client.close()

def test_cannot_create_elevated_user(limited):
    client,store,csrf,elevated,_=limited
    x=client.post('/api/admin/users',headers=csrf,json={'username':'newadmin','display_name':'New Admin','email':'','password':'some-new-password-very-long','role_id':elevated})
    assert x.status_code==403, x.text

def test_cannot_reset_elevated_password(limited):
    client,store,csrf,elevated,_=limited
    with store.db() as db:
        uid=db.execute("INSERT INTO users(username,display_name,email,password_hash,role_id,is_active,must_change_password,created_at) VALUES (?,?,?,?,?,1,0,?)",('existingadmin','Existing Administrator','',password_hash('some-password-very-long'),elevated,'2026-11-02T00:00:00+00:00')).lastrowid
    r=client.post(f'/api/admin/users/{uid}/reset-password',headers=csrf,json={'new_password':'new-password-very-long'})
    assert r.status_code==403, r.text

def test_cannot_promote_existing_limited_account(limited):
    client,store,csrf,elevated,_=limited
    with store.db() as db:
        uid=db.execute("INSERT INTO users(username,display_name,email,password_hash,role_id,is_active,must_change_password,created_at) VALUES (?,?,?,?,?,1,0,?)",('existinglimited','Existing Limited','',password_hash('some-password-very-long'),db.execute("SELECT id FROM roles WHERE name='LimitedUserManager'").fetchone()['id'],'2026-11-02T00:00:00+00:00')).lastrowid
    r=client.patch(f'/api/admin/users/{uid}',headers=csrf,json={'role_id':elevated})
    assert r.status_code==403, r.text


def test_delegated_role_manager_cannot_grant_new_permissions(tmp_path):
    from ai_app_server.server import create_app
    from ai_app_server.storage import password_hash
    from fastapi.testclient import TestClient
    script=tmp_path/'app.py'; script.write_text('import ai_app_server as ui\nui.title("T")\n')
    with TestClient(create_app(script,data_dir=tmp_path/'data')) as client:
        store=client.app.state.store
        with store.db() as db:
            rid=db.execute("INSERT INTO roles(name,description,is_system) VALUES ('DelegatedRoleManager','',0)").lastrowid
            db.execute("INSERT INTO role_permissions(role_id,permission) VALUES (?,?)",(rid,'manage_roles'))
            db.execute("INSERT INTO users(username,display_name,email,password_hash,role_id,is_active,must_change_password,created_at) VALUES (?,?,?,?,?,1,0,?)",('rolemanager','Role Manager','',password_hash('very-long-test-password'),rid,'2026-11-02T00:00:00Z'))
        login=client.post('/api/admin/login',json={'username':'rolemanager','password':'very-long-test-password'})
        csrf={'x-csrf-token':login.json()['csrf']}
        res=client.post('/api/admin/roles',headers=csrf,json={'name':'EscalatedRole','description':'','permissions':['manage_roles','manage_settings']})
        assert res.status_code==403
