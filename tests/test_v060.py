"""Modular engine, upgrade, and v0.5 database backwards-compatibility tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile

import pytest
from ai_app_server.hosting import initialize_port, read_hosting, save_hosting
from ai_app_server.desktop_launcher import paths
from ai_app_server.version import __version__

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / 'tools'


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

bootstrap = load('bootstrap')
updater = load('update_engine')


def make_project(tmp_path):
    root = tmp_path / 'instance'
    root.mkdir()
    shutil.copytree(PROJECT / 'engine', root / 'engine', ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    # Exercise compatibility with a v1.0.1 installation, not the current source version.
    (root / 'engine/ai_app_server/version.py').write_text('__version__ = "1.0.1"\n')
    (root / 'starter').mkdir()
    shutil.copy2(PROJECT / 'starter' / 'app.py', root / 'starter' / 'app.py')
    return root


def seed_db(root):
    data = root / 'data'
    data.mkdir(exist_ok=True)
    with sqlite3.connect(str(data / 'server.sqlite3')) as db:
        db.execute('CREATE TABLE preserved (value TEXT NOT NULL)')
        db.execute('INSERT INTO preserved VALUES (?)', ('DO NOT DELETE',))
        db.commit()
    (data / '.secret-key').write_text('KEEP-MY-KEY', encoding='utf8')
    return data


def prepare_update(root, tmp_path, *, ver='1.0.2'):
    updated = tmp_path / 'update'
    shutil.copytree(root / 'engine', updated)
    (updated / 'ai_app_server' / 'version.py').write_text(f'__version__ = "{ver}"\n', encoding='utf8')
    return updated


def assert_db_unchanged(data):
    with sqlite3.connect(str(data / 'server.sqlite3')) as db:
        assert db.execute('SELECT value FROM preserved').fetchone()[0] == 'DO NOT DELETE'
    assert (data / '.secret-key').read_text() == 'KEEP-MY-KEY'


def test_version_and_modular_source_layout():
    assert __version__ == '1.0.2'
    assert (PROJECT / 'engine' / 'ai_app_server' / 'server.py').is_file()
    assert not (PROJECT / 'ai_app_server').exists()
    assert (PROJECT / 'starter' / 'app.py').is_file()
    assert (PROJECT / 'UPDATE ENGINE.bat').is_file()


def test_first_install_creates_app_but_does_not_overwrite_it(tmp_path):
    root = make_project(tmp_path)
    result = bootstrap.prepare(root)
    assert result['script'] == root / 'app' / 'app.py'
    (root / 'app' / 'app.py').write_text('print("MY CUSTOM APP")', encoding='utf8')
    bootstrap.prepare(root)
    assert (root / 'app' / 'app.py').read_text() == 'print("MY CUSTOM APP")'
    assert paths(root)[1] == root / 'app' / 'app.py'


def test_v05_migration_preserves_legacy_script_and_admin_database(tmp_path):
    root = make_project(tmp_path)
    (root / 'ai_app_server').mkdir()
    (root / 'ai_app_server' / '__init__.py').write_text('# old framework')
    (root / 'examples').mkdir()
    (root / 'examples' / 'app.py').write_text('print("MY ORIGINAL APP")')
    (root / 'pyproject.toml').write_text('[project]\nname="old"\n')
    data = seed_db(root)
    result = bootstrap.prepare(root)
    assert result['script'] == root / 'examples' / 'app.py'
    assert (root / 'examples' / 'app.py').read_text() == 'print("MY ORIGINAL APP")'
    assert not (root / 'ai_app_server').exists()
    assert not (root / 'pyproject.toml').exists()
    assert list((root / 'backups').glob('legacy-engine-*/legacy-pyproject.toml'))
    assert_db_unchanged(data)
    assert paths(root)[1] == root / 'examples' / 'app.py'


def test_existing_port_moves_to_separate_config_preserving_settings(tmp_path):
    root = make_project(tmp_path)
    data = seed_db(root)
    (data / 'hosting.json').write_text(json.dumps({'port': 8598, 'start_with_windows': True}))
    settings = initialize_port(data)
    assert settings['port'] == 8598
    assert settings['start_with_windows'] is True
    assert (root / 'config' / 'hosting.json').is_file()
    save_hosting(data, 8599)
    assert read_hosting(data)['port'] == 8599
    assert_db_unchanged(data)
    assert json.loads((data / 'hosting.json').read_text())['port'] == 8598


def test_zip_staging_extracts_only_engine(tmp_path):
    root = make_project(tmp_path)
    archive = tmp_path / 'release.zip'
    with zipfile.ZipFile(archive, 'w') as zip_file:
        for p in (root / 'engine').rglob('*'):
            if p.is_file():
                zip_file.write(p, 'ai-app-server/engine/' + p.relative_to(root / 'engine').as_posix())
        zip_file.writestr('ai-app-server/data/server.sqlite3', 'MALICIOUS DATABASE CONTENT')
    stage = tmp_path / 'stage'
    stage.mkdir()
    candidate = updater.stage_source(archive, stage)
    assert updater.check_engine(candidate) == (1, 0, 1)
    assert not (stage / 'data').exists()


def test_reject_zip_traversal_in_engine_path(tmp_path):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as zip_file:
        zip_file.writestr('engine/../data/server.sqlite3', 'overwrite me')
    with pytest.raises(ValueError, match='Unsafe'):
        updater.stage_source(archive, tmp_path / 'stage')
    assert not (tmp_path / 'data').exists()


def test_update_dry_run_preserves_everything(tmp_path):
    root = make_project(tmp_path)
    data = seed_db(root)
    new = prepare_update(root, tmp_path)
    result = updater.update(root, new, dry_run=True)
    assert result['current'] == (1, 0, 1)
    assert result['new'] == (1, 0, 2)
    assert updater.version(root / 'engine') == (1, 0, 1)
    assert not (root / 'backups').exists()
    assert_db_unchanged(data)


def test_successful_code_update_never_replaces_app_or_data(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    data = seed_db(root)
    bootstrap.prepare(root)
    (root / 'app' / 'app.py').write_text('print("MY CUSTOM APP")')
    save_hosting(data, 8566)
    update = prepare_update(root, tmp_path)
    calls = []
    monkeypatch.setattr(updater, '_command', lambda *args, **kw: calls.append(args))
    result = updater.update(root, update)
    assert updater.version(root / 'engine') == (1, 0, 2)
    assert (root / 'app' / 'app.py').read_text() == 'print("MY CUSTOM APP")'
    assert_db_unchanged(data)
    assert read_hosting(data)['port'] == 8566
    assert (result['backup'] / 'data-snapshot' / 'server.sqlite3').exists()
    assert (result['backup'] / 'data-snapshot' / '.secret-key').exists()
    assert (result['backup'] / 'config-snapshot' / 'hosting.json').exists()
    assert any('pip' in args for args in calls)
    assert any('desktop_launcher' in ' '.join(args) for args in calls)


def test_failed_install_restores_previous_engine_and_keeps_data(tmp_path, monkeypatch):
    root = make_project(tmp_path)
    data = seed_db(root)
    new = prepare_update(root, tmp_path)
    def fail_install(*parts, **kwargs):
        if 'pip' in parts and updater.version(root / 'engine') == (1, 0, 2):
            raise RuntimeError('simulation: offline install failed')
    monkeypatch.setattr(updater, '_command', fail_install)
    with pytest.raises(RuntimeError, match='Previous engine restored'):
        updater.update(root, new)
    assert updater.version(root / 'engine') == (1, 0, 1)
    assert_db_unchanged(data)
    assert list((root / 'backups').glob('engine-update-*/failed-engine'))


def test_downgrade_refused_before_backup_or_writes(tmp_path):
    root = make_project(tmp_path)
    data = seed_db(root)
    new = prepare_update(root, tmp_path, ver='0.5.9')
    with pytest.raises(ValueError, match='newer'):
        updater.update(root, new)
    assert updater.version(root / 'engine') == (1, 0, 1)
    assert_db_unchanged(data)
