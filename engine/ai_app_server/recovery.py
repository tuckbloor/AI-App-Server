"""Verified, per-installation backups of AI App Server persistent state.

Only administrator-controlled local tooling should call restore_snapshot; never expose
restore or filesystem paths through a web route. SQLite online backup captures WAL.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

SNAPSHOT_VERSION = 1
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


def create_snapshot(root: Path, snapshot: Path) -> dict:
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
    if not set(manifest['files']).issubset(allowed):
        raise ValueError('Snapshot contains unexpected file paths')
    for relative, sha in manifest['files'].items():
        path = snapshot / relative
        if path.is_symlink() or not path.is_file() or not isinstance(sha, str) or _digest(path) != sha:
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
