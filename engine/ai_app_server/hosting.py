"""Per-application hosting settings. Never stored in, or shipped over, the source ZIP."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile

DEFAULT_PORT = 8501


def validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("Choose a port between 1024 and 65535")
    return port


def is_port_free(port: int) -> bool:
    validate_port(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def config_path(directory: Path) -> Path:
    """Store installation port in persistent config/, not in engine/.

    Compatibility: unrelated projects (and older flat data directories) may
    still use a hosting.json in their supplied data directory.
    """
    directory = Path(directory).resolve()
    if directory.name == "data" and (directory.parent / "engine" / "ai_app_server").is_dir():
        return directory.parent / "config" / "hosting.json"
    return directory / "hosting.json"


def _existing_config(directory: Path) -> Path:
    directory = Path(directory).resolve()
    preferred = config_path(directory)
    legacy = directory / "hosting.json"
    return preferred if preferred.is_file() else legacy



def read_hosting(directory: Path) -> dict:
    path = _existing_config(directory)
    if not path.is_file():
        return {"port": DEFAULT_PORT, "host": "127.0.0.1", "start_with_windows": False, "mode": "development"}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"port": validate_port(data["port"]), "host": "127.0.0.1",
            "start_with_windows": bool(data.get("start_with_windows", False)),
            "mode": validate_mode(data.get("mode", "development"))}


def validate_mode(mode: str) -> str:
    if mode not in ("development", "production"):
        raise ValueError("Environment must be development or production")
    return mode


def save_hosting(directory: Path, port: int, *, start_with_windows: bool | None = None, mode: str | None = None) -> dict:
    """Atomic write: no database migration, existing database unaffected."""
    validate_port(port)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = config_path(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = read_hosting(directory)
    data = {"port": port, "host": "127.0.0.1", "start_with_windows": (
        existing["start_with_windows"] if start_with_windows is None else start_with_windows),
            "mode": validate_mode(existing["mode"] if mode is None else mode)}
    fd, temp = tempfile.mkstemp(prefix="hosting-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return data


def initialize_port(directory: Path, preferred: int = DEFAULT_PORT) -> dict:
    """On first run pick a free local port; existing projects keep their saved choice."""
    if _existing_config(directory).exists():
        settings = read_hosting(directory)
        if not config_path(directory).is_file():
            return save_hosting(directory, settings["port"], start_with_windows=settings["start_with_windows"], mode=settings["mode"])
        return settings
    for port in [preferred, *range(8501, 8601)]:
        if is_port_free(port):
            return save_hosting(directory, port)
    raise RuntimeError("No available local ports from 8501 to 8600; select a custom port")
