"""Portable v0.9.0 backup verification tests shipped with the engine."""
from __future__ import annotations
from pathlib import Path
import sqlite3
import pytest
from ai_app_server.storage import Store
from ai_app_server.recovery import create_snapshot, verify_snapshot, restore_snapshot


def test_verified_snapshot_has_database_and_key(tmp_path):
    root = tmp_path / 'app-instance'
    Store(root / 'data')
    snapshot = root / 'backups' / 'snapshot'
    files = create_snapshot(root, snapshot)['files']
    assert 'data/server.sqlite3' in files
    assert 'data/.secret-key' in files
    assert verify_snapshot(snapshot)['files'] == files


def test_backup_corruption_is_detected(tmp_path):
    root = tmp_path / 'app-instance'
    Store(root / 'data')
    snapshot = root / 'backups' / 'snapshot'
    create_snapshot(root, snapshot)
    with (snapshot / 'data/.secret-key').open('ab') as f:
        f.write(b'changed')
    with pytest.raises(RuntimeError, match='integrity'):
        verify_snapshot(snapshot)


def test_restores_verified_sqlite_and_host_settings(tmp_path):
    root = tmp_path / 'app-instance'
    Store(root / 'data')
    (root/'config').mkdir()
    (root/'config/hosting.json').write_text('{"port": 8502}')
    snapshot = root / 'backups' / 'snapshot'
    create_snapshot(root, snapshot)
    (root/'config/hosting.json').write_text('{"port": 9999}')
    with sqlite3.connect(root/'data/server.sqlite3') as db:
        db.execute('CREATE TABLE bad(x TEXT)')
    restore_snapshot(root, snapshot)
    assert (root/'config/hosting.json').read_text() == '{"port": 8502}'
    with sqlite3.connect(root/'data/server.sqlite3') as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='bad'").fetchone()
