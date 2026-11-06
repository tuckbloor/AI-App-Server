"""Portable Windows entrypoint regression checks."""
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = ['INSTALL.bat', 'START.bat']


def test_exactly_two_windows_launchers():
    assert sorted(x.name for x in PROJECT.rglob('*.bat')) == sorted(SCRIPTS)


def test_both_launcher_paths_are_relative_to_the_script():
    for name in SCRIPTS:
        data = (PROJECT / name).read_text(encoding='utf8')
        assert 'cd /d "%~dp0"' in data
        assert 'E:\\' not in data and 'E:/' not in data


def test_launcher_actions_and_background_startup():
    assert 'portable_install.py' in (PROJECT / 'INSTALL.bat').read_text(encoding='utf8')
    assert 'desktop_launcher' in (PROJECT / 'START.bat').read_text(encoding='utf8')
    assert '--background' in (PROJECT / 'START.bat').read_text(encoding='utf8')
    assert 'START.bat' in (PROJECT / 'engine/ai_app_server/desktop_launcher.py').read_text(encoding='utf8')


def test_starter_application_and_compatible_windows_line_endings():
    assert (PROJECT / 'starter/app.py').is_file()
    for name in SCRIPTS:
        contents=(PROJECT / name).read_bytes()
        assert b'\r\n' in contents
        assert b'\n' not in contents.replace(b'\r\n',b'')
