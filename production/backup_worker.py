"""Periodic verified snapshots for trusted single-tenant production deployments.

Snapshots live in a dedicated volume; operators must replicate this volume
outside the host for disaster recovery. Run as the same restricted UID as the
application, without network access or elevated host permissions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys
import time

from ai_app_server.recovery import create_snapshot, verify_snapshot


ROOT = Path('/workspace')
BACKUP_ROOT = ROOT / 'backups'


def snapshot_once(root: Path = ROOT, *, retain: int = 7) -> Path:
    """Create, verify, then rotate snapshots; never delete the only good one."""
    root = Path(root).resolve()
    database = root / 'data/server.sqlite3'
    key = root / 'data/.secret-key'
    if not database.is_file() or not key.is_file():
        raise RuntimeError('Cannot back up: server database or encryption key is missing')
    destination_root = root / 'backups'
    destination_root.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        destination_root.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = destination_root / f'snapshot-{stamp}'
    create_snapshot(root, target, include_app=True)
    verify_snapshot(target)
    candidates = sorted((p for p in destination_root.glob('snapshot-*')
                         if p.is_dir() and not p.is_symlink()), key=lambda p: p.name)
    good = []
    for candidate in candidates:
        try:
            verify_snapshot(candidate)
            good.append(candidate)
        except Exception:
            # Never silently remove a damaged backup; retain it for diagnosis.
            print(f'WARNING: Failed to verify previous snapshot: {candidate}', flush=True)
    for candidate in good[:-max(1, retain)]:
        if candidate != target:
            shutil.rmtree(candidate)
    return target


def main():
    interval = max(3600, int(os.getenv('AI_APP_SERVER_BACKUP_INTERVAL', '86400')))
    retain = max(2, min(30, int(os.getenv('AI_APP_SERVER_BACKUP_RETENTION', '7'))))
    while True:
        try:
            dest = snapshot_once(retain=retain)
            print(f'VERIFIED BACKUP: {dest}', flush=True)
        except Exception as error:
            print(f'BACKUP FAILURE: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == '__main__':
    main()
