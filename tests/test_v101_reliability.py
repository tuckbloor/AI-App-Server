"""Release-specific invariants: the updater must never report success without the website."""
import importlib.util
import json
from pathlib import Path
import socket

import pytest

from ai_app_server.desktop_launcher import paths
from ai_app_server.version import __version__


def test_release_version():
    assert __version__ == '1.0.3'


def test_python_project_layout_isolated(tmp_path):
    project = tmp_path / 'another-project'
    (project / 'app').mkdir(parents=True)
    (project / 'app' / 'app.py').write_text('print("demo")')
    root, script, data = paths(project)
    assert script == project / 'app' / 'app.py'
    assert data == project / 'data'
    assert not data.exists()


def test_installer_has_mandatory_live_health_check():
    # Regresion for v1.0.0's false-positive successful update.
    overlay_install = Path(__file__).resolve().parents[1] / 'tools' / 'guarded_overlay_installer.py'
    if overlay_install.is_file():
        source = overlay_install.read_text()
        assert "smoke(root, stage, backup/'snapshot'" in source
        assert "health(port)" in source
        assert "previous-engine" in source
    else:
        pytest.skip('The separately distributed overlay contains the installer')


def test_production_compose_has_no_published_python_port():
    compose = (Path(__file__).resolve().parents[1] / 'production' / 'compose.yaml').read_text()
    assert "8501:8501" not in compose
    assert 'no-new-privileges:true' in compose
    assert 'cap_drop: [ALL]' in compose
    assert 'AI_APP_SERVER_MCP_TOOLS_SHA256' in compose
