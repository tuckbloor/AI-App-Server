"""Automated snapshots must preserve encryption keys and only rotate verified history."""
from __future__ import annotations
import importlib.util
from pathlib import Path

import pytest

from ai_app_server.storage import Store
from ai_app_server.recovery import verify_snapshot, rehearse_restore

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('aia_backup_worker', ROOT/'production/backup_worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_automatic_snapshot_and_restore(tmp_path):
    root=tmp_path/'project'
    (root/'app').mkdir(parents=True)
    (root/'app/app.py').write_text('print("hello")')
    store=Store(root/'data')
    store.update_password(1, 'long-password-used-for-rehearsal', email='admin@example.test')
    saved_key=store.key_path.read_bytes()
    first=worker.snapshot_once(root,retain=2)
    second=worker.snapshot_once(root,retain=2)
    third=worker.snapshot_once(root,retain=2)
    assert not first.exists()
    assert second.exists() and third.exists()
    assert len(verify_snapshot(third)['files'])>=3
    restored=tmp_path/'restored'
    rehearse_restore(third,restored)
    assert (restored/'data/.secret-key').read_bytes()==saved_key
    assert (restored/'app/app.py').read_text()=='print("hello")'


def test_backup_refuses_missing_keys(tmp_path):
    root=tmp_path/'empty'
    root.mkdir()
    with pytest.raises(RuntimeError,match='missing'):
        worker.snapshot_once(root)
    assert not (root/'backups').exists()
