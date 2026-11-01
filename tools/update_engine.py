"""Upgrade only engine/, leaving each project's app and private state intact.

Requires only the Python standard library. The updater is OUTSIDE engine/ so a
failed update can still restore the previous engine code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

VERSION_PATTERN = re.compile(r'^__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']', re.M)
REQUIRED = ('pyproject.toml', 'ai_app_server/__init__.py', 'ai_app_server/version.py')
MAX_ENGINE_BYTES = 80 * 1024 * 1024


def version(engine: Path) -> tuple[int, int, int]:
    source = (engine / 'ai_app_server' / 'version.py').read_text(encoding='utf-8')
    match = VERSION_PATTERN.search(source)
    if not match:
        raise ValueError('Invalid engine: missing __version__ in version.py')
    return tuple(map(int, match.group(1).split('.')))


def check_engine(engine: Path) -> tuple[int, int, int]:
    if not engine.is_dir() or engine.is_symlink():
        raise ValueError('The update needs a normal engine folder.')
    for filename in REQUIRED:
        if not (engine / filename).is_file():
            raise ValueError(f'Incomplete engine update: missing {filename}')
    return version(engine)


def _is_inside(name: str) -> tuple[str | None, str | None]:
    """Accept the documented archive layout only; ignore unrelated ZIP members."""
    member = name.replace('\\', '/')
    prefixes = ('ai-app-server/engine/', 'engine/')
    for prefix in prefixes:
        if member.startswith(prefix):
            path = member[len(prefix):]
            parts = PurePosixPath(path).parts
            if path.startswith('/') or any(p in ('..', '.') for p in parts) or not path:
                return None, 'Unsafe archive entry'
            return path, None
    return None, None


def stage_source(source: Path, destination: Path) -> Path:
    """Stage an engine directory or release ZIP, with traversal and size guards."""
    source = Path(source).resolve()
    dest = destination / 'engine'
    if source.is_dir():
        candidate = source / 'engine' if (source / 'engine').is_dir() else source
        check_engine(candidate)
        shutil.copytree(candidate, dest, symlinks=False)
    elif source.is_file() and source.suffix.lower() == '.zip':
        dest.mkdir(parents=True)
        total = 0
        found = set()
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                path, problem = _is_inside(member.filename)
                if problem:
                    raise ValueError(problem)
                if path is None:
                    continue
                parts = PurePosixPath(path).parts
                if any(p in ('..', '.') for p in parts) or ':' in path or path.startswith('/'):
                    raise ValueError('Unsafe archive entry')
                # Refuse symlinks and special files inside archives.
                mode = (member.external_attr >> 16) & 0o170000
                if mode not in (0, 0o100000, 0o040000):
                    raise ValueError('Engine update archive contains links or special files')
                if member.is_dir():
                    continue
                total += member.file_size
                if total > MAX_ENGINE_BYTES:
                    raise ValueError('Engine archive is unexpectedly large')
                target = dest.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, target.open('wb') as out:
                    shutil.copyfileobj(src, out)
                found.add(path)
        if not all(p in found for p in REQUIRED):
            raise ValueError('No complete engine folder was found in that ZIP.')
    else:
        raise ValueError('Select a new AI App Server release ZIP or engine folder.')
    check_engine(dest)
    return dest


def backup_state(root: Path, backup: Path) -> None:
    """Consistent copy of SQLite plus its key. Never overwrites live state."""
    data = root / 'data'
    dest = backup / 'data-snapshot'
    dest.mkdir(parents=True)
    db = data / 'server.sqlite3'
    key = data / '.secret-key'
    if db.is_file() and not key.is_file():
        raise RuntimeError('Cannot safely back up encrypted SQLite: data/.secret-key is missing.')
    if db.is_file():
        with sqlite3.connect(str(db)) as source, sqlite3.connect(str(dest / db.name)) as target:
            source.backup(target)
    for filename in ('.secret-key', 'hosting.json'):
        if (data / filename).is_file():
            shutil.copy2(data / filename, dest / filename)
    config = root / "config" / "hosting.json"
    if config.is_file():
        (backup / "config-snapshot").mkdir(parents=True)
        shutil.copy2(config, backup / "config-snapshot" / "hosting.json")
    # Keep old engine rollback and the data snapshot together.


def restore_database_from_snapshot(root: Path, backup: Path) -> bool:
    """Return database to pre-upgrade schema if a new engine fails to start.

    Only called while the application's process is stopped. Restores a SQLite
    consistent snapshot rather than guessing how to reverse migrations.
    """
    snapshot = backup / 'data-snapshot' / 'server.sqlite3'
    live = root / 'data' / 'server.sqlite3'
    if not snapshot.is_file():
        return False
    live.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(snapshot)) as source, sqlite3.connect(str(live)) as target:
        source.backup(target)
    return True


def _command(*parts: str, root: Path) -> None:
    cmd = [sys.executable, *parts]
    process = subprocess.run(cmd, cwd=str(root), timeout=180)
    if process.returncode:
        raise RuntimeError(f'Command failed (exit {process.returncode}): {" ".join(parts)}')


def update(root: Path, source: Path, *, dry_run=False, restart=True) -> dict:
    root = Path(root).resolve()
    engine = root / 'engine'
    current = check_engine(engine)
    with tempfile.TemporaryDirectory(prefix='.engine-update-', dir=root) as tmp:
        staged = stage_source(source, Path(tmp))
        incoming = check_engine(staged)
        if incoming <= current:
            raise ValueError(f'Update must be newer than current {".".join(map(str,current))}; '
                             f'selected {".".join(map(str,incoming))}.')
        if incoming[0] != current[0]:
            raise ValueError('Major-version updates need an explicit compatibility review.')
        if dry_run:
            return {'current': current, 'new': incoming, 'dry_run': True}
        # Stop the specific project; never stop an unrelated PID.
        if (root / 'data' / 'runtime.json').exists():
            _command('-m', 'ai_app_server.desktop_launcher', 'stop', '--project', str(root), root=root)
        backups = root / 'backups'
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = backups / f'engine-update-{stamp}'
        idx = 1
        while backup.exists():
            backup = backups / f'engine-update-{stamp}-{idx}'
            idx += 1
        backup.mkdir()
        backup_state(root, backup)
        old = backup / 'previous-engine'
        engine.rename(old)
        try:
            staged.rename(engine)
            _command('-m', 'pip', 'install', '--disable-pip-version-check', '-e', str(engine), root=root)
            if restart:
                _command('-m', 'ai_app_server.desktop_launcher', 'start', '--project', str(root), '--no-browser', root=root)
        except Exception as update_error:
            failed = backup / 'failed-engine'
            if engine.exists():
                engine.rename(failed)
            # Roll back the DB too: the failed new engine may have migrated it.
            # A pre-upgrade SQLite backup was captured before any new code ran.
            restored_db = restore_database_from_snapshot(root, backup)
            old.rename(engine)
            try:
                _command('-m', 'pip', 'install', '--disable-pip-version-check', '-e', str(engine), root=root)
                if restart:
                    _command('-m', 'ai_app_server.desktop_launcher', 'start', '--project', str(root), '--no-browser', root=root)
            except Exception as recovery_error:
                raise RuntimeError(f'Upgrade failed: {update_error}. Previous engine and database snapshot restored, but could not start it: '
                                   f'{recovery_error}. Backup: {backup}. Database NOT overwritten.') from recovery_error
            raise RuntimeError(f'Upgrade failed: {update_error}. Previous engine restored and pre-upgrade SQLite snapshot reinstated. '
                               f'Backup saved at {backup}.') from update_error
        return {'current': current, 'new': incoming, 'backup': backup, 'dry_run': False}


def select_source() -> Path | None:
    """Friendly file chooser: the user selects just one downloaded ZIP."""
    try:
        from tkinter import Tk, filedialog
        tk = Tk()
        tk.withdraw()
        tk.attributes('-topmost', True)
        chosen = filedialog.askopenfilename(title='Select the NEW AI App Server release ZIP',
                                            filetypes=[('AI App Server ZIP', '*.zip'), ('All files', '*.*')])
        tk.destroy()
        return Path(chosen) if chosen else None
    except (ImportError, RuntimeError):
        try:
            value = input('Path to the downloaded update ZIP (Enter cancels): ').strip().strip('"')
            return Path(value) if value else None
        except EOFError:
            return None


def main(argv=None):
    parser = argparse.ArgumentParser(description='Upgrade engine only (preserve project, database and settings)')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-restart', action='store_true')
    args = parser.parse_args(argv)
    source = args.source or select_source()
    if not source:
        print('No update ZIP selected. Nothing changed.')
        return 0
    try:
        result = update(args.project, source, dry_run=args.dry_run, restart=not args.no_restart)
        print('Engine update check completed.' if args.dry_run else 'ENGINE UPDATE SUCCESSFUL')
        print(f'Version: {".".join(map(str, result["current"]))} -> {".".join(map(str, result["new"]))}')
        if not args.dry_run:
            print(f'Previous engine and data backup: {result["backup"]}')
            print('Your app, configuration, SQLite database and encryption key were not replaced.')
        return 0
    except Exception as exc:
        print(f'UPDATE ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
