from pathlib import Path
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('portable_install', ROOT/'tools/portable_install.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_copy_full_required_engine_and_launchers(tmp_path):
    dest = tmp_path/'An App Folder'/'AI App Server'
    module.copy_fresh(ROOT, dest)
    assert (dest/'engine/ai_app_server/server.py').is_file()
    assert (dest/'starter/app.py').is_file()
    assert (dest/'tools/bootstrap.py').is_file()
    assert sorted(p.name for p in dest.rglob('*.bat')) == ['INSTALL.bat','START.bat']
    assert not (dest/'data').exists()
    assert not (dest/'config').exists()
    assert not (dest/'app').exists()


def test_nonempty_destination_never_overwritten(tmp_path):
    dest = tmp_path/'AI App Server'
    dest.mkdir()
    marker = dest/'server.sqlite3'
    marker.write_bytes(b'EXISTING USER DATABASE')
    with pytest.raises(module.InstallError, match='not empty'):
        module.copy_fresh(ROOT, dest)
    assert marker.read_bytes() == b'EXISTING USER DATABASE'


def test_nested_target_rejected_without_changes(tmp_path):
    with pytest.raises(module.InstallError, match='inside or above'):
        module.validate_destination(ROOT,ROOT/'nested')


def test_in_place_install_keeps_existing_data(tmp_path):
    dest = tmp_path/'App'
    dest.mkdir()
    (dest/'engine/ai_app_server').mkdir(parents=True)
    (dest/'data').mkdir()
    marker = dest/'data/server.sqlite3'
    marker.write_bytes(b'DO NOT TOUCH')
    # in-place mode performs no copying, and never deletes existing private files
    assert module.validate_destination(dest,dest) == 'in-place'
    assert marker.read_bytes() == b'DO NOT TOUCH'


def test_installer_has_no_fixed_windows_drive():
    source = (ROOT/'tools/portable_install.py').read_text()
    assert 'E:\\ai-app-server' not in source
    assert 'E:/ai-app-server' not in source


def test_release_layout_and_displayed_version_match_engine():
    from ai_app_server.version import __version__
    assert {p.name for p in ROOT.rglob('*.bat')} == {'INSTALL.bat', 'START.bat'}
    assert f'# AI App Server v{__version__}' in (ROOT/'README.md').read_text(encoding='utf-8')
    assert f'AI App Server v{__version__}' in (ROOT/'tools/portable_install.py').read_text(encoding='utf-8')
    assert f'## v{__version__}' in (ROOT/'RELEASE-NOTES.md').read_text(encoding='utf-8')
