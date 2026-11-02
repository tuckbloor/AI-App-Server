"""Server administration API. Only admin users can access control-plane state."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
import os
import platform
import sqlite3
import sys

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .storage import Store, PERMISSIONS, is_strong_password, verify_password, password_hash, normalized_email, stamp, utcnow
from .mail import configured as smtp_configured, send_mail
from .service import service_status
from .hosting import read_hosting, save_hosting, is_port_free, validate_port, validate_mode
from .storage import SCHEMA_VERSION
from .version import __version__
from .app_security import production_checks, validate_production, request_ip


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str
    email: str = Field(min_length=3, max_length=254)


class ForgotPassword(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class PasswordReset(TokenRequest):
    new_password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    email: str = Field(default="", max_length=254)
    password: str
    role_id: int


class AppUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    email: str = Field(default="", max_length=254)
    password: str = Field(min_length=12, max_length=256)


class AppUserActive(BaseModel):
    is_active: bool


class AppUserPassword(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role_id: int | None = None
    is_active: bool | None = None


class ResetPassword(BaseModel):
    new_password: str


class RoleCreate(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    description: str = Field(default="", max_length=240)
    permissions: list[str] = Field(default_factory=list)


class RolePermissions(BaseModel):
    permissions: list[str]


class DatabaseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=70)
    engine: str
    url: str = Field(min_length=4, max_length=2048)


class HostingUpdate(BaseModel):
    port: int = Field(ge=1024, le=65535)
    mode: str | None = None


class SettingsUpdate(BaseModel):
    app_title: str | None = Field(default=None, min_length=1, max_length=80)
    maintenance_enabled: bool | None = None
    maintenance_message: str | None = Field(default=None, min_length=1, max_length=400)
    maintenance_start: str | None = None
    maintenance_end: str | None = None


def error(message: str, code=400):
    raise HTTPException(status_code=code, detail=message)


def require(request: Request, permission: str | None = None, *, write=False, allow_initial=False):
    store: Store = request.app.state.store
    token = request.cookies.get("aia_admin_session", "")
    user = store.session(token)
    if not user:
        error("Administrator login required", 401)
    if write and request.headers.get("x-csrf-token") != user["csrf"]:
        error("Invalid CSRF token", 403)
    if user["must_change_password"] and not allow_initial:
        error("Change the initial password before continuing", 403)
    if permission and permission not in store.permissions(user):
        error("You do not have permission for this action", 403)
    return user


def get_roles(store: Store):
    with store.db() as db:
        roles = db.execute("SELECT * FROM roles ORDER BY id").fetchall()
        perms = db.execute("SELECT * FROM role_permissions").fetchall()
    return [{**dict(r), "permissions": [p["permission"] for p in perms if p["role_id"] == r["id"]]} for r in roles]



def ensure_role_delegation(store: Store, actor, role_id: int):
    """A delegated manager cannot assign permissions that they do not possess."""
    with store.db() as db:
        role = db.execute("SELECT name FROM roles WHERE id=?", (role_id,)).fetchone()
        if role is None:
            error("Role not found", 404)
        assigned = {r["permission"] for r in db.execute(
            "SELECT permission FROM role_permissions WHERE role_id=?", (role_id,))}
    if actor["role"] != "Super Admin" and (
        role["name"] == "Super Admin" or not assigned.issubset(set(store.permissions(actor)))
    ):
        error("Cannot manage a role with permissions beyond your own", 403)
    return assigned


def safe_user_rows(store: Store):
    with store.db() as db:
        users = db.execute("SELECT u.*,r.name role FROM users u JOIN roles r ON r.id=u.role_id ORDER BY u.id").fetchall()
    return [store.public_user(user) for user in users]


def admin_router():
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.post("/login")
    def login(request: Request, body: Login, response: Response):
        store: Store = request.app.state.store
        identity = f"{request_ip(request)}:{body.username.casefold()}"
        if store.login_blocked(identity):
            error("Too many unsuccessful attempts. Try again in 15 minutes.", 429)
        user = store.user_by_name(body.username)
        if not user or not user["is_active"] or not verify_password(body.password, user["password_hash"]):
            store.login_failed(identity)
            store.audit(body.username[:60], "login_failed")
            error("Invalid username or password", 401)
        store.clear_login_failures(identity)
        token, csrf = store.create_session(user["id"])
        response.set_cookie(
            key="aia_admin_session", value=token, httponly=True, samesite="strict", path="/",
            secure=bool(request.app.state.secure_cookies), max_age=12 * 3600,
        )
        store.audit(user["username"], "login")
        return {"user":store.public_user(user), "csrf":csrf}

    @router.post("/logout")
    def logout(request: Request, response: Response):
        user = require(request, write=True, allow_initial=True)
        store: Store = request.app.state.store
        store.revoke_session(request.cookies.get("aia_admin_session", ""))
        response.delete_cookie("aia_admin_session", path="/")
        store.audit(user["username"], "logout")
        return {"ok":True}

    @router.get("/me")
    def me(request: Request):
        user = require(request, allow_initial=True)
        store = request.app.state.store
        return {"user":store.public_user(user), "csrf":user["csrf"],
                "permissions":store.permissions(user), "app_title":store.settings().get("app_title", "AI App Server"), "version": __version__}

    def link_base(request: Request):
        # For internet deployment the operator must supply an explicitly trusted origin.
        public = os.getenv('AI_APP_SERVER_PUBLIC_ORIGIN')
        if public:
            return public.rstrip('/')
        # Development links must not trust user-supplied Host headers.
        port = request.scope.get('server', ('127.0.0.1', 8501))[1]
        return f'http://127.0.0.1:{port}' 

    def deliver_link(request: Request, user, purpose: str):
        token = request.app.state.store.make_email_token(user['id'], purpose)
        path = 'verify-email' if purpose == 'verify' else 'reset-password'
        url = f"{link_base(request)}/admin?{path}={token}"
        subject = 'Verify your AI App Server email' if purpose == 'verify' else 'Reset your AI App Server password'
        body = (f"Open this link to {'verify your address' if purpose == 'verify' else 'reset your password'}:\n\n{url}\n\n"
                'This link expires in 30 minutes and can be used once. If you did not request it, ignore this email.')
        try:
            return send_mail(user['email'], subject, body)
        except Exception:
            # No credentials or reset links go into public responses or logs.
            return False

    @router.post('/forgot-password')
    def forgot_password(request: Request, body: ForgotPassword):
        store: Store = request.app.state.store
        # Same response for known/unknown/unverified emails prevents user enumeration.
        message = {'message':'If this is a verified administrator email and mail delivery is configured, a reset link will be sent.'}
        try:
            email = normalized_email(body.email)
        except ValueError:
            return message
        client = request_ip(request)
        identity = f"forgot:{client}:{hashlib.sha256(email.encode()).hexdigest()[:16]}"
        if store.login_blocked(identity):
            return message
        store.login_failed(identity)  # Limit reset requests even for valid accounts.
        with store.db() as db:
            users = db.execute('SELECT * FROM users WHERE email=? COLLATE NOCASE AND email_verified=1 AND is_active=1', (email,)).fetchall()
        if len(users) == 1 and smtp_configured():
            deliver_link(request, users[0], 'reset')
        return message

    @router.post('/verify-email')
    def verify_email(request: Request, body: TokenRequest):
        ok = request.app.state.store.verify_email(body.token)
        if not ok:
            error('Verification link is invalid or expired', 400)
        request.app.state.store.audit('system', 'email_verified')
        return {'ok': True}

    @router.post('/reset-password')
    def reset_password_link(request: Request, body: PasswordReset):
        if not is_strong_password(body.new_password):
            error('New password must be 12–256 characters')
        if not request.app.state.store.reset_password(body.token, body.new_password):
            error('Reset link is invalid or expired', 400)
        request.app.state.store.audit('system', 'password_recovered')
        return {'ok':True}

    @router.post('/resend-verification')
    def resend_verification(request: Request):
        user = require(request, write=True)
        if user['email_verified']:
            return {'ok':True, 'message':'Your email is already verified'}
        if not smtp_configured():
            error('Configure SMTP delivery to send verification email')
        identity = f'verification:{user["id"]}'
        store = request.app.state.store
        if store.login_blocked(identity):
            error('Too many verification emails requested. Try again in 15 minutes.', 429)
        store.login_failed(identity)
        if not deliver_link(request, user, 'verify'):
            error('Email delivery failed. Check the SMTP configuration.')
        request.app.state.store.audit(user['username'], 'email_verification_sent')
        return {'ok':True, 'message':'Verification email sent. Check your inbox.'}

    @router.post("/password")
    def password(request: Request, body: PasswordUpdate):
        user = require(request, write=True, allow_initial=True)
        store = request.app.state.store
        if not verify_password(body.current_password, user["password_hash"]):
            error("Current password is incorrect")
        if not is_strong_password(body.new_password):
            error("New password must be 12–256 characters")
        if body.new_password == body.current_password:
            error("Choose a different password")
        try:
            email = normalized_email(body.email)
        except ValueError as exc:
            error(str(exc))
        with store.db() as db:
            other = db.execute('SELECT id FROM users WHERE email=? COLLATE NOCASE AND id<>?', (email, user['id'])).fetchone()
            if other:
                error('This email is already used by another administrator')
        store.update_password(user['id'], body.new_password, email=email)
        refreshed = store.user_by_id(user['id'])
        sent = bool(not refreshed['email_verified'] and smtp_configured() and deliver_link(request, refreshed, 'verify'))
        store.audit(user["username"], "password_changed")
        return {"ok":True, "verification_sent":sent, "message":"Password changed. Please sign in again."}

    @router.get("/dashboard")
    def dashboard(request: Request):
        user = require(request, "view_dashboard")
        store: Store = request.app.state.store
        with store.db() as db:
            count_users = db.execute("SELECT count(*) FROM users WHERE is_active=1").fetchone()[0]
            count_roles = db.execute("SELECT count(*) FROM roles").fetchone()[0]
            count_databases = db.execute("SELECT count(*) FROM database_connections").fetchone()[0] + 1
            recent = [dict(r) for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 6")]
        return {"app_title":store.settings()["app_title"], "users":count_users,"roles":count_roles,
                "databases":count_databases,"maintenance":store.maintenance_on(),"recent":recent,
                "server":{"python":platform.python_version(),"os":platform.system(),"mode":request.app.state.mode,
                          "script":request.app.state.script.name,"storage":str(store.path),"schema_version":SCHEMA_VERSION,"version":__version__}}

    @router.get("/service")
    def service(request: Request):
        # This endpoint is deliberately read-only: restarting a process from
        # inside itself or granting OS-level privileges to HTTP is unsafe.
        require(request, "view_service")
        store: Store = request.app.state.store
        details = service_status(request.app.state.script, store.directory)
        return {**details, "hosting":read_hosting(store.directory),
                "application":request.app.state.script.name,
                "mode":request.app.state.mode,
                "database":"SQLite",
                "schema_version":SCHEMA_VERSION,
                "upgrade_protection":"Automatic online backup before schema upgrades",
                "note":"Local mode uses one-click background startup after Windows sign-in. Production requires an HTTPS reverse proxy and separate deployment configuration."}

    @router.put("/hosting")
    def update_hosting(body: HostingUpdate, request: Request):
        actor = require(request, "manage_settings", write=True)
        store: Store = request.app.state.store
        current = read_hosting(store.directory)
        validate_port(body.port)
        if body.port != current["port"] and not is_port_free(body.port):
            error("That port is already in use. Choose another port.", 409)
        mode = validate_mode(body.mode if body.mode is not None else current['mode'])
        if request.app.state.production and mode != 'production':
            error('Production cannot be downgraded remotely. Change deployment mode offline on the host.', 403)
        if mode == 'production':
            checks = production_checks(store, local_only=True)
            problems = [item['message'] for item in checks if not item['ok']]
            if problems:
                error('Production not enabled: ' + '; '.join(problems), 409)
        config = save_hosting(store.directory, body.port, mode=mode)
        store.audit(actor["username"], "hosting_updated", f"port={body.port}, mode={mode}")
        return {"ok":True, "hosting":config,
                "restart_required":body.port != current["port"] or mode != current['mode'],
                "message":"Saved. Restart this system to apply changes; your SQLite database was not replaced."}

    @router.get("/production-check")
    def production_check(request: Request):
        require(request, "view_dashboard")
        results = production_checks(request.app.state.store, local_only=request.app.state.local_only)
        return {"ready_to_configure":all(item['ok'] for item in results), "checks":results,
                "mode":request.app.state.mode,
                "note":"Preflight checks do not verify your TLS proxy, container isolation, or deployment security."}

    @router.get("/security")
    def security(request: Request):
        user = require(request, "view_dashboard")
        store = request.app.state.store
        return {"account":store.public_user(user),"smtp_configured":smtp_configured(),"initial_password_changed":not user["must_change_password"],
                "csrf_protected":True,"session_hours":12,"localhost_only":request.app.state.local_only,
                "secure_cookies":request.app.state.secure_cookies,"auth_lockout":"5 failures / 15 min",
                "storage":str(store.path)}

    @router.get("/users")
    def users(request: Request):
        require(request, "manage_users")
        return {"users":safe_user_rows(request.app.state.store)}

    @router.post("/users", status_code=201)
    def create_user(request: Request, body: UserCreate):
        actor = require(request, "manage_users", write=True)
        store = request.app.state.store
        if not is_strong_password(body.password):
            error("Temporary password must be at least 12 characters")
        if body.email:
            try:
                normalized_email(body.email)
            except ValueError as exc:
                error(str(exc))
        with store.db() as db:
            if body.email and db.execute('SELECT id FROM users WHERE email=? COLLATE NOCASE', (body.email.strip(),)).fetchone():
                error('That email address already belongs to another administrator', 409)
            role = db.execute("SELECT * FROM roles WHERE id=?", (body.role_id,)).fetchone()
            if not role:
                error("Role not found", 404)
            ensure_role_delegation(store, actor, body.role_id)
            try:
                db.execute("INSERT INTO users (username,display_name,email,password_hash,role_id,is_active,must_change_password,created_at) VALUES (?,?,?,?,?,1,1,?)",
                           (body.username, body.display_name, body.email, password_hash(body.password), body.role_id, stamp()))
            except sqlite3.IntegrityError:
                error("Username already exists", 409)
        store.audit(actor["username"], "user_created", body.username, role["name"])
        return {"ok":True}

    @router.patch("/users/{uid}")
    def update_user(uid: int, body: UserUpdate, request: Request):
        actor = require(request, "manage_users", write=True)
        store = request.app.state.store
        target = store.user_by_id(uid)
        if not target:
            error("User not found", 404)
        ensure_role_delegation(store, actor, target["role_id"])
        if body.role_id is not None:
            ensure_role_delegation(store, actor, body.role_id)
        if (target["role"] == "Super Admin" or body.role_id is not None and
            get_role_name(store, body.role_id) == "Super Admin") and actor["role"] != "Super Admin":
            error("Only a Super Admin can manage Super Admin accounts", 403)
        if uid == actor["id"] and (body.is_active is False or body.role_id is not None and body.role_id != actor["role_id"]):
            error("You cannot disable or change your own role")
        with store.db() as db:
            if body.role_id is not None and not db.execute("SELECT 1 FROM roles WHERE id=?", (body.role_id,)).fetchone():
                error("Role not found", 404)
            if body.is_active is False and target["role"] == "Super Admin":
                count = db.execute("SELECT count(*) FROM users u JOIN roles r ON r.id=u.role_id WHERE r.name='Super Admin' AND is_active=1").fetchone()[0]
                if count <= 1:
                    error("Cannot disable the last active Super Admin")
            if body.display_name is not None:
                db.execute("UPDATE users SET display_name=? WHERE id=?", (body.display_name, uid))
            if body.role_id is not None:
                db.execute("UPDATE users SET role_id=? WHERE id=?", (body.role_id, uid))
            if body.is_active is not None:
                db.execute("UPDATE users SET is_active=? WHERE id=?", (int(body.is_active), uid))
        if body.role_id is not None or body.is_active is False:
            store.revoke_user_sessions(uid)
        store.audit(actor["username"], "user_updated", target["username"])
        return {"ok":True}

    @router.post("/users/{uid}/reset-password")
    def reset_password(uid: int, body: ResetPassword, request: Request):
        actor = require(request, "manage_users", write=True)
        store = request.app.state.store
        target = store.user_by_id(uid)
        if not target:
            error("User not found", 404)
        ensure_role_delegation(store, actor, target["role_id"])
        if target["role"] == "Super Admin" and actor["role"] != "Super Admin":
            error("Only a Super Admin can reset a Super Admin password", 403)
        if not is_strong_password(body.new_password):
            error("Temporary password must be 12–256 characters")
        with store.db() as db:
            db.execute("UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?",
                       (password_hash(body.new_password), uid))
        store.revoke_user_sessions(uid)
        store.audit(actor["username"], "password_reset", target["username"])
        return {"ok":True}

    @router.get('/app-users')
    def list_application_users(request: Request):
        require(request, 'manage_users')
        return {'users': request.app.state.store.list_app_users()}

    @router.post('/app-users', status_code=201)
    def create_application_user(request: Request, body: AppUserCreate):
        actor = require(request, 'manage_users', write=True)
        store = request.app.state.store
        try:
            uid = store.create_app_user(body.username, body.display_name, body.password, body.email)
        except ValueError as exc:
            error(str(exc))
        except sqlite3.IntegrityError:
            error('Application username already exists', 409)
        store.audit(actor['username'], 'app_user_created', body.username)
        return {'id': uid, 'ok': True}

    @router.patch('/app-users/{uid}')
    def set_application_user_active(uid: int, body: AppUserActive, request: Request):
        actor = require(request, 'manage_users', write=True)
        store = request.app.state.store
        if not store.set_app_user_active(uid, body.is_active):
            error('Application user not found', 404)
        store.audit(actor['username'], 'app_user_status', str(uid), 'active' if body.is_active else 'disabled')
        return {'ok':True}

    @router.post('/app-users/{uid}/reset-password')
    def reset_application_user_password(uid: int, body: AppUserPassword, request: Request):
        actor = require(request, 'manage_users', write=True)
        store = request.app.state.store
        if not store.reset_app_user_password(uid, body.new_password):
            error('Application user not found', 404)
        store.audit(actor['username'], 'app_user_password_reset', str(uid))
        return {'ok':True}

    @router.get("/roles")
    def roles(request: Request):
        require(request, "view_dashboard")
        return {"roles":get_roles(request.app.state.store), "permission_catalog":PERMISSIONS}

    @router.post("/roles", status_code=201)
    def create_role(request: Request, body: RoleCreate):
        actor = require(request, "manage_roles", write=True)
        store = request.app.state.store
        if set(body.permissions) - set(PERMISSIONS):
            error("Unknown permission")
        if actor["role"] != "Super Admin" and not set(body.permissions).issubset(set(store.permissions(actor))):
            error("Cannot create a role with permissions beyond your own", 403)
        with store.db() as db:
            try:
                cur = db.execute("INSERT INTO roles(name,description,is_system) VALUES (?,?,0)",
                                 (body.name, body.description))
                db.executemany("INSERT INTO role_permissions VALUES (?,?)", [(cur.lastrowid, p) for p in set(body.permissions)])
            except sqlite3.IntegrityError:
                error("Role name already exists", 409)
        store.audit(actor["username"], "role_created", body.name)
        return {"ok":True}

    @router.put("/roles/{rid}/permissions")
    def update_role_permissions(rid: int, body: RolePermissions, request: Request):
        actor = require(request, "manage_roles", write=True)
        store = request.app.state.store
        if set(body.permissions) - set(PERMISSIONS):
            error("Unknown permission")
        ensure_role_delegation(store, actor, rid)
        if actor["role"] != "Super Admin" and not set(body.permissions).issubset(set(store.permissions(actor))):
            error("Cannot grant permissions beyond your own", 403)
        with store.db() as db:
            role = db.execute("SELECT * FROM roles WHERE id=?", (rid,)).fetchone()
            if not role:
                error("Role not found", 404)
            if role["name"] == "Super Admin":
                error("Super Admin permissions cannot be changed")
            db.execute("DELETE FROM role_permissions WHERE role_id=?", (rid,))
            db.executemany("INSERT INTO role_permissions VALUES (?,?)", [(rid, p) for p in set(body.permissions)])
            db.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE role_id=?)", (rid,))
        store.audit(actor["username"], "role_permissions_updated", role["name"])
        return {"ok":True}

    @router.get("/databases")
    def databases(request: Request):
        require(request, "manage_databases")
        store = request.app.state.store
        with store.db() as db:
            rows = [dict(r) for r in db.execute("SELECT id,name,engine,created_at FROM database_connections ORDER BY name")]
        return {"connections":[{"id":0,"name":"System SQLite","engine":"sqlite","default":True,"status":"Active","path":str(store.path)}] +
                [{**row,"default":False,"status":"Configured"} for row in rows],
                "engines":["sqlite","postgresql","mysql","mssql"]}

    @router.post("/databases", status_code=201)
    def create_database(request: Request, body: DatabaseCreate):
        actor = require(request, "manage_databases", write=True)
        store = request.app.state.store
        allowed = {"sqlite": "sqlite:///", "postgresql": "postgresql+psycopg://",
                   "mysql": "mysql+pymysql://", "mssql": "mssql+pyodbc://"}
        if body.engine not in allowed or not body.url.startswith(allowed[body.engine]):
            error("Invalid connection URL prefix for selected database engine")
        with store.db() as db:
            try:
                db.execute("INSERT INTO database_connections(name,engine,encrypted_url,created_at) VALUES(?,?,?,?)",
                           (body.name, body.engine, store.encrypt(body.url), stamp()))
            except sqlite3.IntegrityError:
                error("A database connection with this name already exists", 409)
        store.audit(actor["username"], "database_added", body.name, body.engine)
        return {"ok":True}

    @router.delete("/databases/{dbid}")
    def delete_database(dbid: int, request: Request):
        actor = require(request, "manage_databases", write=True)
        if dbid == 0:
            error("The system SQLite database cannot be deleted")
        store = request.app.state.store
        with store.db() as db:
            row = db.execute("SELECT name FROM database_connections WHERE id=?", (dbid,)).fetchone()
            if not row:
                error("Connection not found", 404)
            db.execute("DELETE FROM database_connections WHERE id=?", (dbid,))
        store.audit(actor["username"], "database_removed", row["name"])
        return {"ok":True}

    @router.post("/databases/{dbid}/test")
    def test_database(dbid: int, request: Request):
        actor = require(request, "manage_databases", write=True)
        store = request.app.state.store
        if dbid == 0:
            with store.db() as db:
                db.execute("SELECT 1").fetchone()
            return {"ok":True,"message":"System SQLite is responding."}
        with store.db() as db:
            row = db.execute("SELECT * FROM database_connections WHERE id=?", (dbid,)).fetchone()
        if not row:
            error("Connection not found", 404)
        try:
            from sqlalchemy import create_engine, text
            url = store.decrypt(row["encrypted_url"])
            engine = create_engine(url, pool_pre_ping=True, **({"connect_args":{"timeout":5}} if row["engine"]=="sqlite" else {"pool_timeout":5}))
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            finally:
                engine.dispose()
        except Exception:
            store.audit(actor["username"], "database_test_failed", row["name"])
            error("Connection failed. Check the driver, server reachability and credentials.")
        store.audit(actor["username"], "database_test_success", row["name"])
        return {"ok":True,"message":"Database connection successful."}

    @router.get("/settings")
    def settings(request: Request):
        require(request, "view_dashboard")
        return {"settings":request.app.state.store.settings()}

    @router.put("/settings")
    def update_settings(request: Request, body: SettingsUpdate):
        fields = body.model_dump(exclude_unset=True)
        perms = set(fields)
        actor = require(request, write=True)
        store = request.app.state.store
        if perms & {"maintenance_enabled","maintenance_message","maintenance_start","maintenance_end"}:
            if "manage_maintenance" not in store.permissions(actor):
                error("Maintenance permission required", 403)
        if "app_title" in perms and "manage_settings" not in store.permissions(actor):
            error("Settings permission required", 403)
        for key in ("maintenance_start", "maintenance_end"):
            if fields.get(key):
                try:
                    dt = datetime.fromisoformat(fields[key])
                    if dt.tzinfo is None:
                        error("Scheduled times must include a timezone offset")
                    fields[key] = dt.astimezone(timezone.utc).isoformat()
                except ValueError:
                    error(f"Invalid {key} timestamp")
        merged = {**store.settings(),**fields}
        if bool(merged["maintenance_start"]) != bool(merged["maintenance_end"]):
            error("Provide both scheduled start and end, or neither")
        if merged["maintenance_start"] and merged["maintenance_end"] and merged["maintenance_start"] >= merged["maintenance_end"]:
            error("Scheduled end must follow start")
        store.update_settings(fields)
        store.audit(actor["username"], "settings_updated", ", ".join(fields))
        return {"ok":True,"settings":store.settings()}

    @router.get("/mcp")
    def mcp_status(request: Request):
        require(request, "view_service")
        from .mcp_module import read_config
        setting = read_config(request.app.state.store.directory)
        return {"enabled": setting["enabled"], "token_configured": bool(setting["token_hash"]),
                "endpoint": "/mcp", "tools": request.app.state.mcp_registry.descriptions(),
                "protocol": "2026-07-28", "tool_load_error": request.app.state.mcp_load_error}

    @router.post("/mcp/enable")
    def mcp_enable(request: Request):
        admin = require(request, "manage_settings", write=True)
        from .mcp_module import enable
        token = enable(request.app.state.store.directory)
        request.app.state.store.audit(admin["username"], "mcp_enabled_or_rotated")
        return {"ok": True, "token": token, "warning": "Save this token now. It cannot be displayed again."}

    @router.post("/mcp/disable")
    def mcp_disable(request: Request):
        admin = require(request, "manage_settings", write=True)
        from .mcp_module import disable
        disable(request.app.state.store.directory)
        request.app.state.store.audit(admin["username"], "mcp_disabled")
        return {"ok": True}

    @router.get("/audit")
    def audit(request: Request):
        require(request, "view_audit")
        store = request.app.state.store
        with store.db() as db:
            rows = [dict(r) for r in db.execute("SELECT id,created_at,actor,action,target,details FROM audit ORDER BY id DESC LIMIT 200")]
        return {"events":rows}

    return router


def get_role_name(store: Store, role_id: int):
    with store.db() as db:
        row = db.execute("SELECT name FROM roles WHERE id=?", (role_id,)).fetchone()
    return row["name"] if row else None
