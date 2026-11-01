"""Verified, per-installation backups of AI App Server persistent state.

Only administrator-controlled local tooling should call restore_snapshot; never expose
restore or filesystem paths through a web route. SQLite online backup captures WAL.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile

SNAPSHOT_VERSION = 1
MAX_PROJECT_FILES = 1000
MAX_PROJECT_BYTES = 100 * 1024 * 1024
MAX_SINGLE_FILE = 20 * 1024 * 1024
IGNORE_DIRECTORIES = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules"}
FILES = (
    ('data/server.sqlite3', 'data/server.sqlite3'),
    ('data/.secret-key', 'data/.secret-key'),
    ('data/mcp.json', 'data/mcp.json'),
    ('data/hosting.json', 'data/hosting.json'),
    ('config/hosting.json', 'config/hosting.json'),
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as src:
        for block in iter(lambda: src.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _check_db(path: Path) -> None:
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as con:
        result = con.execute('PRAGMA quick_check').fetchone()
        if result is None or result[0] != 'ok':
            raise RuntimeError('SQLite integrity check failed')


def create_snapshot(root: Path, snapshot: Path, *, include_app: bool = False) -> dict:
    """Snapshot SQLite, key and server settings, without changing live installation."""
    root, snapshot = Path(root).resolve(), Path(snapshot).resolve()
    if snapshot == root / 'data' or (root / 'data') in snapshot.parents:
        raise ValueError('Invalid backup destination')
    if snapshot.exists():
        raise FileExistsError('Refusing to overwrite an existing backup')
    db = root / 'data/server.sqlite3'
    key = root / 'data/.secret-key'
    if db.exists() and not key.is_file():
        raise RuntimeError('Database encryption key missing: refusing upgrade')
    snapshot.mkdir(parents=True, exist_ok=False)
    if os.name != 'nt':
        snapshot.chmod(0o700)
    manifest = {'format': SNAPSHOT_VERSION, 'created_at': datetime.now(timezone.utc).isoformat(), 'files': {}}
    try:
        for relative, _ in FILES:
            live = root / relative
            if not live.is_file():
                continue
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if relative == 'data/server.sqlite3':
                with sqlite3.connect(str(live)) as src, sqlite3.connect(str(destination)) as dst:
                    src.backup(dst)
                _check_db(destination)
            else:
                shutil.copy2(live, destination)
            if os.name != 'nt':
                destination.chmod(0o600)
            manifest['files'][relative] = _digest(destination)
        if include_app:
            # Full application source for off-host disaster recovery. Never follow links.
            app_dir = root / 'app'
            count = 0
            total = 0
            if app_dir.is_symlink():
                raise RuntimeError('Application directory cannot be a symlink')
            if app_dir.is_dir():
                for parent, dirs, names in os.walk(app_dir, followlinks=False):
                    dirs[:] = [d for d in dirs if d not in IGNORE_DIRECTORIES]
                    for d in dirs:
                        if (Path(parent) / d).is_symlink():
                            raise RuntimeError('Cannot back up linked application folders')
                    for name in names:
                        src = Path(parent) / name
                        if src.is_symlink() or not src.is_file():
                            raise RuntimeError('Cannot back up linked or special application files')
                        count += 1
                        size = src.stat().st_size
                        total += size
                        if count > MAX_PROJECT_FILES or size > MAX_SINGLE_FILE or total > MAX_PROJECT_BYTES:
                            raise RuntimeError('Application backup exceeds safety limits; use a dedicated off-host project backup')
                        relative = src.relative_to(root).as_posix()
                        dst = snapshot / relative
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        if os.name != 'nt':
                            dst.chmod(0o600)
                        manifest['files'][relative] = _digest(dst)
        (snapshot / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        verify_snapshot(snapshot)
    except Exception:
        shutil.rmtree(snapshot)
        raise
    return manifest


def verify_snapshot(snapshot: Path) -> dict:
    snapshot = Path(snapshot).resolve()
    manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != SNAPSHOT_VERSION or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported snapshot format')
    allowed = {source for source, _ in FILES}
    if len(manifest['files']) > MAX_PROJECT_FILES + len(FILES):
        raise ValueError('Snapshot contains too many files')
    for relative, sha in manifest['files'].items():
        relpath = PurePosixPath(relative)
        if (not isinstance(relative, str) or relpath.is_absolute() or '..' in relpath.parts or
                str(relpath) != relative or
                not (relative in allowed or (relative.startswith('app/') and len(relpath.parts) > 1))):
            raise ValueError('Snapshot contains unexpected file paths')
        path = snapshot / relative
        if (not path.resolve().is_relative_to(snapshot) or path.is_symlink()
                or not path.is_file() or not isinstance(sha, str) or _digest(path) != sha):
            raise RuntimeError(f'Backup integrity failure: {relative}')
    if 'data/server.sqlite3' in manifest['files']:
        if 'data/.secret-key' not in manifest['files']:
            raise RuntimeError('Encrypted database backup has no encryption key')
        _check_db(snapshot / 'data/server.sqlite3')
    return manifest


def restore_snapshot(root: Path, snapshot: Path) -> None:
    """Restore snapshot files when the app is STOPPED. Offline-only operation.

    Rollback may discard writes made after the snapshot. Always snapshot only
    after taking the instance offline before an engine update.
    """
    root, snapshot = Path(root).resolve(), Path(snapshot).resolve()
    manifest = verify_snapshot(snapshot)
    for relative in manifest['files']:
        dest = root / relative
        if not dest.resolve().is_relative_to(root):
            raise RuntimeError('Restoration path escapes installation')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dest.parent, prefix='.restore-', delete=False) as out:
            tmp = Path(out.name)
        try:
            shutil.copy2(snapshot / relative, tmp)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        if os.name != 'nt':
            dest.chmod(0o600)
    if 'data/server.sqlite3' in manifest['files']:
        # Never leave journal files from the failed newer database on rollback.
        for suffix in ('-wal', '-shm'):
            (root / 'data' / ('server.sqlite3' + suffix)).unlink(missing_ok=True)
        _check_db(root / 'data/server.sqlite3')


def rehearse_restore(snapshot: Path, destination: Path) -> dict:
    """Actually restore into a NEW isolated directory, never touch the live server."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError('Restore rehearsal destination must not exist')
    if destination == Path(snapshot).resolve() or destination in Path(snapshot).resolve().parents:
        raise ValueError('Invalid restore destination')
    destination.mkdir(parents=True, exist_ok=False)
    try:
        restore_snapshot(destination, snapshot)
        return verify_snapshot(snapshot)
    except Exception:
        shutil.rmtree(destination)
        raise
