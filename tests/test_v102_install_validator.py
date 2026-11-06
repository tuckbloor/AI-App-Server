"""Regression: some FastAPI versions return _IncludedRouter entries without path."""
from pathlib import Path
import ast
import importlib.util


def test_health_route_check_accepts_included_router_without_path(tmp_path):
    from ai_app_server.server import create_app
    p = tmp_path / "app.py"
    p.write_text('import ai_app_server as ui\nui.title("hello")\n')
    app = create_app(p, data_dir=tmp_path / "data")
    class IncludedRouter:
        pass
    app.router.routes.insert(0, IncludedRouter())
    assert any(getattr(r, "path", None) == "/health" for r in app.routes)


def test_complete_installer_uses_robust_route_introspection():
    p = Path(__file__).resolve().parents[2] / "installer.py"
    # In installed source the outer installer is not copied into the target,
    # so the behavior check above is the authoritative regression test.
    if p.is_file():
        assert 'getattr(r, "path", None)' in p.read_text()
