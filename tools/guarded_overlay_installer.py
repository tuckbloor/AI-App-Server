"""Fail-closed AI App Server engine overlay with preflight HTTP canary.

This updater is stored OUTSIDE the application. No changes to the live installation
are made unless a byte-verified candidate has answered real HTTP requests against
a *copy* of the user's data, with its own port and process. After cutover the
original port is checked and verified; failures restore the prior code/database.
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
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from urllib.error import HTTPError

VERSION = '1.0.2'
ALLOWED = {'0.9.2', '1.0.0', '1.0.1'}
EXTRA = (
    'MCP-MODULE.md',
    'PRODUCTION-SECURITY.md',
    'PRODUCTION-CHECKLIST.md',
    'production/compose.yaml',
    'production/Caddyfile',
    'production/Dockerfile',
    'production/README.md',
    'production/.env.example',
    'production/backup_worker.py',
    'production/verify-deployment.py',
    'production/OPERATOR-GUIDE.md',
    'production/ACCEPTANCE.md',
    'production/production_acceptance.py',
    'tools/guarded_overlay_installer.py',
    'RELEASE-NOTES.md',
    'tests/test_app.py',
    'tests/test_v04.py',
    'tests/test_v05.py',
    'tests/test_v051.py',
    'tests/test_v052.py',
    'tests/test_v060.py',
    'tests/test_v070_security.py',
    'tests/test_v080_production.py',
    'tests/test_v090_recovery.py',
    'tests/test_v091_mcp.py',
    'tests/test_v092_production.py',
    'tests/test_v092_version_display.py',
    'tests/test_v100_release.py',
    'tests/test_v101_backup_worker.py',
    'tests/test_v101_reliability.py',
    'tests/test_v102_guarded.py',
)


def version(engine: Path) -> str:
    path = engine / 'ai_app_server/version.py'
    if not path.is_file():
        raise RuntimeError(f'Missing engine version file: {path}')
    found = re.search(r'__version__\s*=\s*["\']([\d.]+)', path.read_text(encoding='utf8'))
    if not found:
        raise RuntimeError('Invalid engine version')
    return found.group(1)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_payload(release: Path) -> None:
    payload = release / 'payload'
    manifest = json.loads((release / 'FILES.sha256.json').read_text(encoding='utf8'))
    actual = {p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file()}
    if not isinstance(manifest, dict) or actual != set(manifest):
        raise RuntimeError('Release manifest does not match the contents')
    for name, checksum in manifest.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Unsafe path in release manifest')
        file = payload / relative
        if file.is_symlink() or digest(file) != checksum:
            raise RuntimeError(f'Release file failed SHA256 check: {name}')
    if version(payload / 'engine') != VERSION:
        raise RuntimeError('Release engine version mismatch')
    if not {'engine/pyproject.toml', 'engine/ai_app_server/server.py',
            'engine/ai_app_server/cli.py', 'engine/ai_app_server/desktop_launcher.py'} <= actual:
        raise RuntimeError('Release is missing required framework files')


def data_mode(root: Path) -> str:
    for path in (root/'config/hosting.json', root/'data/hosting.json'):
        if path.is_file():
            return json.loads(path.read_text(encoding='utf8')).get('mode', 'development')
    return 'development'


def config_port(root: Path) -> int:
    for path in (root/'config/hosting.json', root/'data/hosting.json'):
        if path.is_file():
            return int(json.loads(path.read_text(encoding='utf8'))['port'])
    return 8501


def engine_import(root: Path, engine: Path, code: str, *args: str, timeout: int = 35):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(engine) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run([sys.executable, '-c', code, *args], cwd=root,
                          env=env, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError('Engine validation failed: ' + (proc.stdout+'\n'+proc.stderr)[-2000:])


def command(root: Path, *args: str, check=True, timeout=80):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root/'engine') + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run([sys.executable, *args], cwd=root, env=env, capture_output=True,
                          text=True, timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(args) + '\n' + (proc.stdout+'\n'+proc.stderr)[-2000:])
    return proc


def recovery_module(stage: Path):
    mod_path = stage / 'ai_app_server/recovery.py'
    spec = importlib.util.spec_from_file_location('overlay_recovery', mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])


def available(port: int) -> bool:
    with socket.socket() as s:
        # Unix sockets can remain in TIME_WAIT briefly after shutdown. The
        # server sets SO_REUSEADDR, so the probe must match it.
        if os.name != 'nt':
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def wait_free(port: int, timeout: float=20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if available(port):
            return
        time.sleep(.25)
    raise RuntimeError(f'Configured port {port} is still occupied. Refusing to change it.')


def health(port: int, *, require_app_id: bool=True) -> bool:
    try:
        with urlopen(f'http://127.0.0.1:{port}/health', timeout=1.2) as r:
            result = json.loads(r.read())
            return result.get('status') == 'ok' and (not require_app_id or bool(result.get('app_id')))
    except (OSError, ValueError):
        return False


def smoke(root: Path, engine: Path, snapshot: Path, log: Path) -> None:
    """Exercise a shadow server using disposable restored data, never live data."""
    shadow = snapshot.parent / 'canary'
    restore = recovery_module(engine)
    restore.rehearse_restore(snapshot, shadow)
    # Make an app script in the disposable canary rather than import a user's
    # custom script while checking the framework's HTTP routes.
    (shadow/'app').mkdir(parents=True, exist_ok=True)
    script = shadow/'app/app.py'
    script.write_text('import ai_app_server as ui\nui.title("Canary")\n', encoding='utf8')
    port = free_port()
    env = os.environ.copy()
    env['PYTHONPATH'] = str(engine) + os.pathsep + env.get('PYTHONPATH', '')
    with log.open('w', encoding='utf8') as output:
        proc = subprocess.Popen([sys.executable, '-m', 'ai_app_server.cli', 'run', str(script),
                                 '--data-dir', str(shadow/'data'), '--port', str(port),
                                 '--mode', 'development'], cwd=root, env=env,
                                stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic()+25
            while time.monotonic()<deadline:
                if proc.poll() is not None:
                    break
                if health(port):
                    break
                time.sleep(.2)
            else:
                raise RuntimeError('Canary web server timed out')
            if not health(port):
                raise RuntimeError('Canary web server did not pass its health check')
            for endpoint in ('/', '/admin', '/static/admin.js'):
                try:
                    with urlopen(f'http://127.0.0.1:{port}{endpoint}', timeout=3) as r:
                        if r.status != 200:
                            raise RuntimeError(f'Canary endpoint failed: {endpoint}')
                except HTTPError as exc:
                    # An existing installation may be intentionally in maintenance
                    # mode. A 503 maintenance page is an expected working response.
                    if not (endpoint == '/' and exc.code == 503 and
                            b'maintenance' in exc.read(8192).lower()):
                        raise
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
    if proc.returncode not in (0, -15, 1, 15, 143):
        # The HTTP smoke test is authoritative; Windows can return differing
        # termination statuses after a deliberately terminated process.
        pass


def install(root: Path, release: Path, *, dry_run=False) -> dict:
    root, release = root.resolve(), release.resolve()
    if root == release or root in release.parents or release in root.parents:
        raise RuntimeError('Extract the update beside the installation, not inside it')
    verify_payload(release)
    engine = root/'engine'
    current = version(engine)
    if current not in ALLOWED:
        raise RuntimeError(f'Expected an existing v0.9.2 / v1.0.x installation; found {current}. Nothing changed.')
    if data_mode(root) == 'production':
        raise RuntimeError('Desktop updates are for local installs only. Deploy production with versioned container images and tested volumes.')
    if (engine/'pyproject.toml').read_bytes() != (release/'payload/engine/pyproject.toml').read_bytes():
        raise RuntimeError('Dependency changes require a tested package installer; no live update attempted')
    app_script = root/'examples/app.py' if (root/'examples/app.py').is_file() else root/'app/app.py'
    if not app_script.is_file():
        raise RuntimeError('Existing application app.py is missing; no changes made')
    port = config_port(root)
    if dry_run:
        return {'before':current, 'after':VERSION, 'dry_run':True}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = root/'backups'/f'guarded-v102-{stamp}'
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.mkdir()
    stage = backup/'incoming-engine'
    old = backup/'previous-engine'
    support_backup = backup/'previous-support'
    changed_support = []
    swapped = False
    stopped = False
    original_runtime = (root/'data/runtime.json').is_file()
    # Never stop an unknown process: the Windows launcher verifies its PID
    # against the application's executable and exact script path.
    if not original_runtime and not available(port):
        raise RuntimeError(f'Port {port} is busy but the server is not identifiable; refusing update')
    try:
        shutil.copytree(release/'payload/engine', stage)
        candidate = recovery_module(stage)
        candidate.create_snapshot(root, backup/'snapshot')
        candidate.verify_snapshot(backup/'snapshot')
        print('1/4 Testing the candidate server on a separate local port...', flush=True)
        engine_import(root, stage, 'from ai_app_server.server import create_app; '
                      'from ai_app_server.version import __version__; assert __version__=="1.0.2"; '
                      'from pathlib import Path; import sys; '
                      'app=create_app(Path(sys.argv[1]),data_dir=Path(sys.argv[2])); '
                      'assert any(r.path == "/health" for r in app.routes)',
                      str(app_script), str(backup/'snapshot'/'data'))
        smoke(root, stage, backup/'snapshot', backup/'canary.log')
        print('2/4 Candidate passed. Stopping only this application...', flush=True)
        if original_runtime:
            command(root, '-m', 'ai_app_server.desktop_launcher', 'stop', '--project', str(root))
            stopped = True
            if (root/'data/runtime.json').exists():
                raise RuntimeError('Server process has not stopped safely')
        wait_free(port)
        # Take a second consistent snapshot AFTER stopping so changes made
        # during the preflight check are captured in the rollback state.
        candidate.create_snapshot(root, backup/'rollback-state')
        candidate.verify_snapshot(backup/'rollback-state')
        engine.rename(old)
        swapped = True
        stage.rename(engine)
        print('3/4 Starting upgraded server and checking its real address...', flush=True)
        engine_import(root, engine, 'from ai_app_server.version import __version__; assert __version__=="1.0.2"')
        command(root, '-m', 'ai_app_server.desktop_launcher', 'start', '--project', str(root), '--no-browser', timeout=80)
        if config_port(root) != port or not health(port):
            raise RuntimeError('Upgraded server did not respond on the original port')
        # Copy non-runtime support documentation only after the running site is healthy.
        for relative in EXTRA:
            src = release/'payload'/relative
            if not src.is_file():
                raise RuntimeError(f'Missing release support file: {relative}')
            dest = root/relative
            if dest.is_file():
                original = support_backup/relative
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, original)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            changed_support.append(relative)
        candidate.verify_snapshot(backup/'rollback-state')
        print('4/4 Health verified; backup retained.', flush=True)
        return {'before':current,'after':VERSION,'port':port,'backup':str(backup)}
    except Exception as exc:
        # Partial update is never reported as success; try restoration and
        # re-start immediately. Keep logs/backups for diagnosis.
        for relative in reversed(changed_support):
            dest = root/relative
            saved = support_backup/relative
            if saved.is_file():
                shutil.copy2(saved,dest)
            else:
                dest.unlink(missing_ok=True)
        if swapped:
            try:
                command(root,'-m','ai_app_server.desktop_launcher','stop','--project',str(root),check=False)
            except Exception:
                pass
            wait_free(port)
            if engine.is_dir():
                engine.rename(backup/'rejected-engine')
            old.rename(engine)
            candidate.restore_snapshot(root, backup/'rollback-state')
        # Even when preflight failed, a formerly running server should remain online.
        if (swapped or stopped) and available(port):
            restart = command(root,'-m','ai_app_server.desktop_launcher','start',
                              '--project',str(root),'--no-browser',check=False,timeout=80)
            if restart.returncode != 0 or not health(port):
                raise RuntimeError(f'Update failed: {exc}. Rollback was attempted but server restart failed. Backup: {backup}') from exc
        raise RuntimeError(f'Update cancelled: {exc}. Original engine preserved or restored. Backup: {backup}') from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='AI App Server guarded overlay update')
    parser.add_argument('--target',type=Path)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    release = Path(__file__).resolve().parent
    root = args.target or release.parent/'ai-app-server'
    try:
        print(f'Checking installed application: {root}', flush=True)
        result=install(root,release,dry_run=args.check)
        if args.check:
            print('PRECHECK PASSED:', result)
        else:
            print('SUCCESS: Updated engine, port:',result['port'])
            print('Database and rollback state saved to:',result['backup'])
        return 0
    except Exception as exc:
        print('UPDATE FAILED:', exc, file=sys.stderr, flush=True)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
