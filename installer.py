"""AI App Server v0.9.1 overlay installer. No dependencies beyond stdlib.

Keep this script OUTSIDE the installation so engine changes and rollback cannot
replace the updater currently running. Only modifies engine/ and listed framework
support files. Never writes to app/, data/, config/ except SQLite migrations run
by the verified engine while the application is stopped.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

RELEASE = '0.9.1'
SUPPORT = (
    'PRODUCTION-SECURITY.md',
    'production/README.md',
    'production/Dockerfile',
    'production/compose.yaml',
    'production/Caddyfile',
    'production/.env.example',
    'SECURITY CHECK.bat',
    'tests/test_v060.py',
    'tests/test_v070_security.py',
    'tests/test_v090_recovery.py',
    'tests/test_v091_mcp.py',
    'MCP-MODULE.md',
)
MUST_HAVE = ('pyproject.toml', 'ai_app_server/__init__.py', 'ai_app_server/version.py', 'ai_app_server/recovery.py')


def engine_version(path: Path) -> tuple[int, int, int]:
    p = path / 'ai_app_server/version.py'
    if not p.is_file():
        raise RuntimeError('Cannot find a valid engine installation')
    match = re.search(r'__version__\s*=\s*[\'\"](\d+\.\d+\.\d+)', p.read_text(encoding='utf-8'))
    if not match:
        raise RuntimeError('Missing engine version')
    return tuple(int(v) for v in match.group(1).split('.'))


def payload_integrity(overlay: Path):
    manifest = json.loads((overlay / 'FILES.sha256.json').read_text(encoding='utf-8'))
    payload = overlay / 'payload'
    required_files = {f'engine/{x}' for x in MUST_HAVE}
    if not required_files.issubset(set(manifest)):
        raise RuntimeError('Overlay is incomplete')
    if set(manifest) != {p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file()}:
        raise RuntimeError('Overlay file list differs from manifest')
    for relative, sha in manifest.items():
        p = payload / relative
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            raise RuntimeError(f'Overlay integrity check failed: {relative}')
    if engine_version(payload / 'engine') != (0, 9, 1):
        raise RuntimeError('This overlay does not contain v0.9.1')


def _call(root: Path, *args: str, timeout: int=240, check: bool=True):
    cmd = [sys.executable, *args]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        detail = (result.stdout + '\n' + result.stderr).strip()[-2200:]
        raise RuntimeError(f'Command failed ({result.returncode}): {" ".join(args)}\n{detail}')
    return result


def recovery_module(overlay: Path):
    p = overlay / 'payload/engine/ai_app_server/recovery.py'
    spec = importlib.util.spec_from_file_location('overlay_recovery', p)
    mod = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = previous
    return mod


def _hosting_mode(root: Path) -> str:
    for path in (root/'config/hosting.json', root/'data/hosting.json'):
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8')).get('mode', 'development')
    return 'development'


def _validate_root(root: Path):
    if not (root / 'engine/ai_app_server/version.py').is_file() or not (root / 'tools/update_engine.py').is_file():
        raise RuntimeError('Existing AI App Server v0.9.0 installation not found. Select the correct folder.')
    version = engine_version(root / 'engine')
    if version != (0, 9, 0):
        raise RuntimeError(f'This overlay is for v0.9.0 only; found {".".join(map(str, version))}. No changes made.')
    if _hosting_mode(root) == 'production':
        raise RuntimeError('Production installations must be upgraded through the deployment pipeline with a tested snapshot. This desktop overlay only upgrades local installations.')
    return version


def install(root: Path, overlay: Path, *, dry_run=False) -> dict:
    root, overlay = Path(root).resolve(), Path(overlay).resolve()
    if root == overlay or root in overlay.parents:
        raise RuntimeError('Extract the overlay OUTSIDE E:\\ai-app-server, such as E:\\AI-App-Server-v0.9.1-MCP-OVERLAY')
    _validate_root(root)
    payload_integrity(overlay)
    if (root / 'engine/pyproject.toml').read_bytes() != (overlay / 'payload/engine/pyproject.toml').read_bytes():
        raise RuntimeError('Dependencies changed; refusing unsafe offline overlay update')
    result = {'previous': '0.9.0', 'new': RELEASE}
    if dry_run:
        return {**result, 'dry_run': True}
    data = root / 'data'
    runtime = data / 'runtime.json'
    had_runtime = runtime.is_file()
    # Stop first, so no writer can change SQLite after the consistent snapshot.
    if had_runtime:
        _call(root, '-m', 'ai_app_server.desktop_launcher', 'stop', '--project', str(root))
        if runtime.exists():
            raise RuntimeError('Application still appears to be running; refusing to upgrade')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = root / 'backups' / f'overlay-v091-{stamp}'
    idx = 1
    while backup.exists():
        backup = root / 'backups' / f'overlay-v091-{stamp}-{idx}'
        idx += 1
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.mkdir()
    recovery = recovery_module(overlay)
    engine = root / 'engine'
    old_engine = backup / 'previous-engine'
    stage = backup / 'staged-engine'
    support_backups = backup / 'support-files'
    replaced_support = []
    swapped = False
    try:
        recovery.create_snapshot(root, backup / 'state-snapshot')
        recovery.verify_snapshot(backup / 'state-snapshot')
        # Stage and validate before any live program file changes.
        shutil.copytree(overlay / 'payload/engine', stage, symlinks=False)
        if engine_version(stage) != (0, 9, 1):
            raise RuntimeError('Staged engine is invalid')
        engine.rename(old_engine)
        swapped = True
        stage.rename(engine)
        # This is a SOURCE-only update: dependencies and installed editable path
        # remain unchanged. Avoid network downloads, wheel builds and pip setup.
        # Prove the existing interpreter imports THIS installation's updated engine.
        _call(root, '-c', 'import ai_app_server, pathlib, sys; '
              'assert pathlib.Path(ai_app_server.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())', str(engine))
        # Exercise real SQLite schema migration on this stopped installation.
        _call(root, '-c', 'from ai_app_server.storage import Store; import sys; Store(sys.argv[1]); '
              'from ai_app_server.version import __version__; assert __version__ == "0.9.1"', str(data))
        # Replace support FILES only after upgraded engine and schema are healthy.
        for relative in SUPPORT:
            source = overlay / 'payload' / relative
            if not source.is_file():
                raise RuntimeError(f'Missing overlay support file: {relative}')
            dest = root / relative
            if dest.exists():
                original = support_backups / relative
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, original)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            replaced_support.append(relative)
        if had_runtime:
            _call(root, '-m', 'ai_app_server.desktop_launcher', 'start', '--project', str(root), '--no-browser', timeout=75)
        # Verify backup remained readable even after migrations.
        recovery.verify_snapshot(backup / 'state-snapshot')
        return {**result, 'backup': str(backup), 'restarted': had_runtime}
    except Exception as error:
        # Stop any newly-started process BEFORE reverting SQLite schema.
        if swapped and runtime.is_file():
            _call(root, '-m', 'ai_app_server.desktop_launcher', 'stop', '--project', str(root), check=False)
        for relative in reversed(replaced_support):
            dest = root / relative
            original = support_backups / relative
            if original.is_file():
                shutil.copy2(original, dest)
            else:
                dest.unlink(missing_ok=True)
        if swapped:
            if engine.exists():
                failed = backup / 'failed-engine'
                engine.rename(failed)
            old_engine.rename(engine)
            recovery.restore_snapshot(root, backup / 'state-snapshot')
            recovery.verify_snapshot(backup / 'state-snapshot')
            recovery_result = _call(root, '-c', 'import ai_app_server, pathlib, sys; assert pathlib.Path(ai_app_server.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())', str(engine), check=False)
            if had_runtime:
                restart_result = _call(root, '-m', 'ai_app_server.desktop_launcher', 'start', '--project', str(root), '--no-browser', timeout=75, check=False)
            else:
                restart_result = None
            if recovery_result.returncode or (restart_result and restart_result.returncode):
                raise RuntimeError(f'Update failed: {error}. Previous code/database restored, but automatic restart failed. Backup: {backup}') from error
        elif had_runtime:
            _call(root, '-m', 'ai_app_server.desktop_launcher', 'start', '--project', str(root), '--no-browser', check=False, timeout=75)
        raise RuntimeError(f'Update failed; previous installation restored. Detail: {error}. Backup: {backup}') from error


def main(argv=None):
    parser = argparse.ArgumentParser(description='v0.9.1 MCP SAFE OVERLAY — no folder deletions')
    parser.add_argument('--target', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    overlay = Path(__file__).resolve().parent
    target = (args.target or overlay.parent / 'ai-app-server').resolve()
    try:
        print(f'Installed application: {target}', flush=True)
        print(f'Overlay: {overlay}', flush=True)
        info = install(target, overlay, dry_run=args.dry_run)
        print('\nOVERLAY CHECK PASSED' if args.dry_run else '\nUPDATE SUCCESSFUL')
        if not args.dry_run:
            print('Your app/, data/, config/ and existing SQLite records were preserved.')
            print('Verified backup (includes encryption key):', info['backup'])
            if info['restarted']:
                print('The existing background server was restarted and health-checked.')
            else:
                print('Server was not running; start it normally with START HERE.bat.')
        return 0
    except Exception as exc:
        print('\nUPDATE NOT COMPLETED:', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
