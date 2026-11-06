"""Small, dependency-free, idempotent installer for new and v0.5 installations.

Runs *before* the editable engine install. Persistent data is never removed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import subprocess
import sys


def prepare(root: Path) -> dict:
    root = Path(root).resolve()
    old_engine = root / "ai_app_server"
    engine = root / "engine" / "ai_app_server"
    if not (engine / "__init__.py").is_file():
        raise RuntimeError("Missing engine files. Re-extract the complete ZIP without deleting data.")
    legacy = root / "examples" / "app.py"
    app = root / "app" / "app.py"
    template = root / "starter" / "app.py"
    if not legacy.is_file() and not app.is_file():
        if not template.is_file():
            raise RuntimeError("Missing starter/app.py; please extract the complete release.")
        app.parent.mkdir(exist_ok=True, parents=True)
        shutil.copy2(template, app)
    # A running v0.5 process must be stopped before its legacy source is moved.
    # Refuse migration rather than accidentally killing an unrelated process.
    if old_engine.is_dir():
        runtime = root / "data" / "runtime.json"
        if runtime.is_file():
            result = subprocess.run([sys.executable, "-m", "ai_app_server.desktop_launcher", "stop"],
                                    cwd=str(root), capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError("Stop the old server before upgrading (START.bat --stop). "
                                   + (result.stderr or result.stdout).strip())
        backups = root / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        dest = backups / ("legacy-engine-v0.5-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
        index = 1
        while dest.exists():
            dest = backups / f"legacy-engine-v0.5-{index}"
            index += 1
        old_engine.rename(dest)
        # The old root metadata is not authoritative after the move. Keeping it
        # at root would make an accidental `pip install -e .` resurrect v0.5.
        old_project = root / "pyproject.toml"
        if old_project.is_file():
            old_project.rename(dest / "legacy-pyproject.toml")
        print(f"Previous framework code preserved: {dest}")
    script = legacy if legacy.is_file() else app
    print(f"Application script: {script}")
    print(f"Persistent database: {root / 'data' / 'server.sqlite3'} (never replaced)")
    return {"script": script, "engine": engine, "data": root / "data"}


if __name__ == "__main__":
    try:
        prepare(Path(__file__).resolve().parent.parent)
    except Exception as e:
        print("INSTALL ERROR:", e, file=sys.stderr)
        sys.exit(1)
