"""Persistent, local SQLite control-plane database and credential handling."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import shutil

from cryptography.fernet import Fernet

SCHEMA_VERSION = 6

PERMISSIONS = {
    "view_service": "View this application service status",
    "view_dashboard": "View server dashboard",
    "manage_users": "Manage administrators",
    "manage_roles": "Manage roles and permissions",
    "manage_databases": "Manage database connections",
    "manage_maintenance": "Control maintenance mode",
    "manage_settings": "Change server settings",
    "view_audit": "View audit log",
}
ROLE_DEFAULTS = {
    "Super Admin": tuple(PERMISSIONS),
    "Administrator": tuple(PERMISSIONS),
    "Operator": ("view_dashboard", "view_service", "manage_databases", "view_audit"),
    "Viewer": ("view_dashboard", "view_audit"),
}


def utcnow():
    return datetime.now(timezone.utc)


def stamp():
    return utcnow().isoformat(timespec="seconds")


def default_data_dir():
    explicit = os.getenv("AI_APP_SERVER_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home())
    else:
        base = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "ai-app-server"


def password_hash(password: str):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return "pbkdf2_sha256$600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str):
    try:
        algo, rounds, salt, expected = stored.split("$")
        if algo != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def normalized_email(value: str):
    """Validate an ordinary mailbox address; domain ownership is verified by email link."""
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
        raise ValueError('Enter a valid email address, such as name@example.com')
    if '..' in value or any(part.startswith('-') or part.endswith('-') for part in value.split('@')[1].split('.')):
        raise ValueError('Enter a valid email address')
    return value


def is_strong_password(value: str):
    return 12 <= len(value) <= 256


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or default_data_dir()).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.directory, 0o700)
        self.path = self.directory / "server.sqlite3"
        self.key_path = self.directory / ".secret-key"
        # An existing DB without its Fernet key cannot safely be "upgraded":
        # generating another key would permanently break encrypted profiles.
        if self.path.exists() and not self.key_path.is_file():
            raise RuntimeError(f"Existing server database at {self.path} has no .secret-key. Restore the original key from backup before starting.")
        if not self.key_path.exists():
            # Exclusive creation prevents accidentally replacing an encryption key.
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(Fernet.generate_key())
            except FileExistsError:
                pass
        self.cipher = Fernet(self.key_path.read_bytes())
        self.backup_before_upgrade()
        self.init()

    def backup_before_upgrade(self):
        """Use SQLite's online backup API before modifying an existing schema.

        Never delete or replace the original DB. The backup preserves WAL data,
        and is kept beside the installation-specific data folder.
        """
        if not self.path.exists():
            return None
        with sqlite3.connect(str(self.path)) as original:
            version = original.execute("PRAGMA user_version").fetchone()[0]
            exists = original.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            if version >= SCHEMA_VERSION or not exists:
                return None
            if version > SCHEMA_VERSION:
                raise RuntimeError("Database schema is newer than this server release")
            backups = self.directory / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                os.chmod(backups, 0o700)
            name = utcnow().strftime(f"server-before-v{SCHEMA_VERSION}-%Y%m%dT%H%M%S")
            target = backups / f"{name}-{secrets.token_hex(4)}.sqlite3"
            with sqlite3.connect(str(target)) as dest:
                original.backup(dest)
            if os.name != "nt":
                os.chmod(target, 0o600)
            # .secret-key remains unchanged in the same data directory.
            return target

    def backup(self, destination: Path):
        """Consistent online backup of SQLite plus its encryption key.

        Destination must be an empty directory to avoid accidental overwrites.
        """
        dest = Path(destination).expanduser().resolve()
        if dest.exists() and any(dest.iterdir()):
            raise ValueError("Backup destination must be empty")
        if dest == self.directory or self.directory in dest.parents:
            raise ValueError("Choose a backup directory outside the live data folder")
        dest.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(dest, 0o700)
        with sqlite3.connect(str(self.path)) as src, sqlite3.connect(str(dest / "server.sqlite3")) as out:
            src.backup(out)
        shutil.copy2(self.key_path, dest / ".secret-key")
        if os.name != "nt":
            os.chmod(dest / "server.sqlite3", 0o600)
            os.chmod(dest / ".secret-key", 0o600)
        return dest

    @contextmanager
    def db(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self):
        with self.db() as db:
            existing_version = db.execute("PRAGMA user_version").fetchone()[0]
            if existing_version > SCHEMA_VERSION:
                raise RuntimeError("Cannot downgrade: database belongs to a newer AI App Server")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '', is_system INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS role_permissions (
                    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
                    permission TEXT NOT NULL, PRIMARY KEY(role_id, permission));
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL, role_id INTEGER NOT NULL REFERENCES roles(id),
                    is_active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, last_login TEXT);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf TEXT NOT NULL, expires_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS database_connections (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, engine TEXT NOT NULL,
                    encrypted_url TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS app_users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login TEXT);
                CREATE TABLE IF NOT EXISTS app_sessions (
                    token_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures (
                    identity TEXT PRIMARY KEY, attempts INTEGER NOT NULL, since TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS email_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    purpose TEXT NOT NULL CHECK(purpose IN ('verify', 'reset')),
                    expires_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ix_email_tokens_user ON email_tokens(user_id, purpose);
            """)
            # Bind each application session to an individual account.
            # Existing shared-password sessions are deliberately invalidated on upgrade.
            app_session_cols = {r['name'] for r in db.execute('PRAGMA table_info(app_sessions)')}
            if 'user_id' not in app_session_cols:
                db.execute('ALTER TABLE app_sessions ADD COLUMN user_id INTEGER')
                db.execute('DELETE FROM app_sessions')
            db.execute('CREATE INDEX IF NOT EXISTS ix_app_sessions_user ON app_sessions(user_id)')
            # Upgrade existing v0.2.0 installations in place, preserving admin data.
            cols = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
            if 'email_verified' not in cols:
                db.execute('ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0')
            db.execute("PRAGMA journal_mode=WAL")
            for role, permissions in ROLE_DEFAULTS.items():
                result = db.execute("INSERT OR IGNORE INTO roles (name, description, is_system) VALUES (?,?,1)",
                                    (role, "Built-in server role"))
                role_id = db.execute("SELECT id FROM roles WHERE name=?", (role,)).fetchone()["id"]
                if result.rowcount == 1:
                    db.executemany("INSERT INTO role_permissions VALUES (?,?)", [(role_id, p) for p in permissions])
            if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                role_id = db.execute("SELECT id FROM roles WHERE name='Super Admin'").fetchone()["id"]
                db.execute("INSERT INTO users (username,display_name,email,password_hash,role_id,must_change_password,created_at) VALUES (?,?,?,?,?,1,?)",
                           ("admin", "System Administrator", "", password_hash("password"), role_id, stamp()))
                db.execute("INSERT INTO audit (created_at,actor,action,target,details) VALUES (?,?,?,?,?)",
                           (stamp(), "system", "initial_setup", "admin", "Initial admin account created; password change required"))
            # Extend only the newly introduced built-in permission; keep custom
            # roles and all existing permission decisions untouched.
            if existing_version < SCHEMA_VERSION:
                for role in ("Administrator", "Operator"):
                    db.execute("INSERT OR IGNORE INTO role_permissions (role_id,permission) "
                               "SELECT id,? FROM roles WHERE name=?", ("view_service", role))
                db.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES (?,?)",
                           (SCHEMA_VERSION, stamp()))
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            for key, value in {
                "app_title": "AI App Server", "maintenance_enabled": False,
                "maintenance_message": "We're making improvements and will be back shortly.",
                "maintenance_start": "", "maintenance_end": "",
            }.items():
                db.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (key, json.dumps(value)))
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def settings(self):
        with self.db() as db:
            return {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM settings")}

    def update_settings(self, changes: dict):
        with self.db() as db:
            db.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           [(key, json.dumps(val)) for key, val in changes.items()])

    def audit(self, actor: str, action: str, target: str = "", details: str = ""):
        with self.db() as db:
            db.execute("INSERT INTO audit (created_at,actor,action,target,details) VALUES (?,?,?,?,?)",
                       (stamp(), actor, action, target, details[:500]))

    def user_by_name(self, username: str):
        with self.db() as db:
            return db.execute("SELECT u.*,r.name role FROM users u JOIN roles r ON r.id=u.role_id WHERE u.username=?", (username,)).fetchone()

    def user_by_id(self, uid: int):
        with self.db() as db:
            return db.execute("SELECT u.*,r.name role FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?", (uid,)).fetchone()

    def permissions(self, user):
        if user["role"] == "Super Admin":
            return list(PERMISSIONS)
        with self.db() as db:
            return [r["permission"] for r in db.execute("SELECT permission FROM role_permissions WHERE role_id=?", (user["role_id"],))]

    def list_app_users(self):
        with self.db() as db:
            return [dict(row) for row in db.execute(
                'SELECT id,username,display_name,email,is_active,created_at,last_login FROM app_users ORDER BY id')]

    def app_user_by_name(self, username: str):
        with self.db() as db:
            return db.execute('SELECT * FROM app_users WHERE username=?', (username,)).fetchone()

    def create_app_user(self, username: str, display_name: str, password: str, email: str='') -> int:
        if not is_strong_password(password):
            raise ValueError('Application password must contain 12–256 characters')
        if email:
            email = normalized_email(email)
        with self.db() as db:
            result = db.execute(
                'INSERT INTO app_users(username,display_name,email,password_hash,created_at) VALUES(?,?,?,?,?)',
                (username, display_name, email, password_hash(password), stamp()))
            return result.lastrowid

    def set_app_user_active(self, uid: int, active: bool) -> bool:
        with self.db() as db:
            row = db.execute('SELECT id FROM app_users WHERE id=?', (uid,)).fetchone()
            if row is None:
                return False
            db.execute('UPDATE app_users SET is_active=? WHERE id=?', (int(active), uid))
            db.execute('DELETE FROM app_sessions WHERE user_id=?', (uid,))
            return True

    def reset_app_user_password(self, uid: int, password: str) -> bool:
        if not is_strong_password(password):
            raise ValueError('Application password must contain 12–256 characters')
        with self.db() as db:
            row = db.execute('SELECT id FROM app_users WHERE id=?', (uid,)).fetchone()
            if row is None:
                return False
            db.execute('UPDATE app_users SET password_hash=? WHERE id=?', (password_hash(password), uid))
            db.execute('DELETE FROM app_sessions WHERE user_id=?', (uid,))
            return True

    def create_app_session(self, user_id: int) -> str:
        """Issue an application-only session, bound to an active application account."""
        token = secrets.token_urlsafe(48)
        expires = (utcnow() + timedelta(hours=8)).isoformat()
        with self.db() as db:
            if not db.execute('SELECT 1 FROM app_users WHERE id=? AND is_active=1', (user_id,)).fetchone():
                raise ValueError('Cannot issue a session for an inactive application user')
            db.execute('DELETE FROM app_sessions WHERE expires_at <= ?', (stamp(),))
            db.execute('INSERT INTO app_sessions(token_hash,user_id,expires_at) VALUES (?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), user_id, expires))
            db.execute('UPDATE app_users SET last_login=? WHERE id=?', (stamp(), user_id))
        return token

    def app_session_user(self, token: str):
        if not token or len(token) > 256:
            return None
        with self.db() as db:
            return db.execute('''SELECT u.id,u.username,u.display_name,u.email
                FROM app_sessions s JOIN app_users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1''',
                (hashlib.sha256(token.encode()).hexdigest(), stamp())).fetchone()

    def valid_app_session(self, token: str) -> bool:
        return self.app_session_user(token) is not None

    def revoke_app_session(self, token: str) -> None:
        if not token:
            return
        with self.db() as db:
            db.execute('DELETE FROM app_sessions WHERE token_hash=?',
                       (hashlib.sha256(token.encode()).hexdigest(),))

    def create_session(self, user_id: int):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expires = (utcnow() + timedelta(hours=12)).isoformat()
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (stamp(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, expires))
            db.execute("UPDATE users SET last_login=? WHERE id=?", (stamp(), user_id))
        return token, csrf

    def session(self, token: str):
        if not token:
            return None
        with self.db() as db:
            return db.execute("SELECT s.csrf,u.*,r.name role FROM sessions s JOIN users u ON u.id=s.user_id JOIN roles r ON r.id=u.role_id WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1",
                              (hashlib.sha256(token.encode()).hexdigest(), stamp())).fetchone()

    def revoke_session(self, token: str):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def revoke_user_sessions(self, uid: int):
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))

    def update_password(self, uid: int, password: str, email: str | None = None):
        with self.db() as db:
            if email is not None:
                previous = db.execute('SELECT email FROM users WHERE id=?', (uid,)).fetchone()
                verified = int(previous['email'].casefold() == email.casefold()) if previous else 0
                db.execute('UPDATE users SET email=?,email_verified=CASE WHEN ?=1 THEN email_verified ELSE 0 END WHERE id=?',
                           (email, verified, uid))
            db.execute("UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?", (password_hash(password), uid))
            db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            db.execute("DELETE FROM email_tokens WHERE user_id=?", (uid,))

    def make_email_token(self, uid: int, purpose: str, minutes: int = 30):
        if purpose not in ('verify', 'reset'):
            raise ValueError('Unsupported token purpose')
        token = secrets.token_urlsafe(36)
        with self.db() as db:
            db.execute('DELETE FROM email_tokens WHERE user_id=? AND purpose=?', (uid, purpose))
            db.execute('DELETE FROM email_tokens WHERE expires_at < ?', (stamp(),))
            db.execute('INSERT INTO email_tokens VALUES (?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), uid, purpose,
                        (utcnow() + timedelta(minutes=minutes)).isoformat()))
        return token

    def consume_email_token(self, token: str, purpose: str):
        if not token or len(token) > 128:
            return None
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as db:
            result = db.execute('DELETE FROM email_tokens WHERE token_hash=? AND purpose=? AND expires_at>? RETURNING user_id',
                                (hashed, purpose, stamp())).fetchone()
            return result['user_id'] if result else None

    def verify_email(self, token: str):
        uid = self.consume_email_token(token, 'verify')
        if uid is None:
            return False
        with self.db() as db:
            db.execute('UPDATE users SET email_verified=1 WHERE id=?', (uid,))
        return True

    def reset_password(self, token: str, new_password: str):
        uid = self.consume_email_token(token, 'reset')
        if uid is None:
            return False
        self.update_password(uid, new_password)
        return True

    def login_blocked(self, identity: str):
        with self.db() as db:
            row = db.execute("SELECT attempts,since FROM login_failures WHERE identity=?", (identity,)).fetchone()
            if not row:
                return False
            try:
                within = utcnow() - datetime.fromisoformat(row["since"]) < timedelta(minutes=15)
            except ValueError:
                within = False
            return within and row["attempts"] >= 5

    def login_failed(self, identity: str):
        with self.db() as db:
            row = db.execute("SELECT attempts,since FROM login_failures WHERE identity=?", (identity,)).fetchone()
            within = False
            if row:
                try:
                    within = utcnow() - datetime.fromisoformat(row["since"]) < timedelta(minutes=15)
                except ValueError:
                    pass
            if within:
                db.execute("UPDATE login_failures SET attempts=attempts+1 WHERE identity=?", (identity,))
            else:
                db.execute("INSERT INTO login_failures(identity,attempts,since) VALUES(?,1,?) ON CONFLICT(identity) DO UPDATE SET attempts=1,since=excluded.since", (identity, stamp()))

    def clear_login_failures(self, identity: str):
        with self.db() as db:
            db.execute("DELETE FROM login_failures WHERE identity=?", (identity,))

    def public_user(self, user):
        return {"id":user["id"], "username":user["username"], "display_name":user["display_name"],
                "email":user["email"], "email_verified":bool(user["email_verified"]), "role":user["role"], "role_id":user["role_id"],
                "is_active":bool(user["is_active"]), "must_change_password":bool(user["must_change_password"]),
                "created_at":user["created_at"], "last_login":user["last_login"]}

    def encrypt(self, text: str):
        return self.cipher.encrypt(text.encode()).decode()

    def decrypt(self, text: str):
        return self.cipher.decrypt(text.encode()).decode()

    def maintenance_on(self):
        opts = self.settings()
        if opts.get("maintenance_enabled"):
            return True
        start, end = opts.get("maintenance_start"), opts.get("maintenance_end")
        if start and end:
            try:
                current = utcnow()
                return datetime.fromisoformat(start) <= current < datetime.fromisoformat(end)
            except (ValueError, TypeError):
                return False
        return False
