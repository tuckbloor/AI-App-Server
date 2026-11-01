"""Windows one-click launcher path regression tests."""
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    "START HERE.bat",
    "Open AI App Server.bat",
    "Launch in Background.bat",
    "Stop AI App Server.bat",
    "Disable Automatic Startup.bat",
]

def test_all_launchers_change_into_project_dir():
    for name in SCRIPTS:
        body = (PROJECT / name).read_text(encoding="utf-8")
        assert 'cd /d "%~dp0"' in body, name

def test_no_launchers_pass_trailing_backslash_folder_as_quoted_argument():
    for name in SCRIPTS:
        body = (PROJECT / name).read_text(encoding="utf-8")
        assert '--project "%~dp0"' not in body, name

def test_start_command_uses_cwd_default_project():
    for name in SCRIPTS:
        body = (PROJECT / name).read_text(encoding="utf-8")
        assert '-m ai_app_server.desktop_launcher' in body
    assert 'install' in (PROJECT / 'START HERE.bat').read_text(encoding='utf-8')

def test_example_application_is_in_archive_source():
    assert (PROJECT / 'starter' / 'app.py').is_file()

def test_batch_file_line_endings_are_windows_compatible():
    for name in SCRIPTS:
        data=(PROJECT / name).read_bytes()
        assert b'\r\n' in data and b'\n' not in data.replace(b'\r\n',b''), name
