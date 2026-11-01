"""Windows Service integration for one independently deployed AI App Server application.

WinSW is an external, established service wrapper. We do not bundle or silently
fetch an executable, and never run service-management commands from an HTTP request.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


def project_data_dir(script: Path, explicit: Path | None = None) -> Path:
    """One data folder per app. Explicit paths preserve legacy deployments."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    return Path(script).expanduser().resolve().parent / ".ai-app-server" / "data"


def service_name(script: Path) -> str:
    path = Path(script).expanduser().resolve()
    digest = hashlib.sha256(str(path).casefold().encode("utf-8")).hexdigest()[:10]
    return f"AIAppServer-{digest}"


def service_paths(script: Path, data_dir: Path | None = None):
    directory = project_data_dir(script, data_dir) / "service"
    base = directory / service_name(script)
    return base.with_suffix(".exe"), base.with_suffix(".xml")


def service_xml(script: Path, data_dir: Path, *, port: int = 8501, host: str = "127.0.0.1",
                mode: str = "development", interpreter: Path | None = None) -> str:
    """Construct WinSW v3 XML (no executable shell commands or credentials)."""
    if not (1 <= port <= 65535):
        raise ValueError("Port must be between 1 and 65535")
    if host not in ("127.0.0.1", "::1", "localhost") and mode != "production":
        raise ValueError("Network binding requires production mode")
    if mode not in ("development", "production"):
        raise ValueError("Invalid mode")
    script = Path(script).resolve()
    data_dir = Path(data_dir).resolve()
    name = service_name(script)
    executable = Path(interpreter or sys.executable).resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Python executable not found: {executable}")
    # Windows command-line quoting is performed by the standard library.
    arguments = subprocess.list2cmdline([
        "-m", "ai_app_server.cli", "run", str(script), "--data-dir", str(data_dir),
        "--host", host, "--port", str(port), "--mode", mode,
    ])
    root = ET.Element("service")
    values = {
        "id": name,
        "name": f"AI App Server – {script.parent.name} ({name[-6:]})",
        "description": f"Independent AI App Server for {script.name}; application files remain separate.",
        "executable": str(executable), "arguments": arguments,
        "workingdirectory": str(script.parent), "startmode": "Automatic",
        "delayedAutoStart": "true", "logpath": str(data_dir / "service"),
    }
    for key, value in values.items():
        ET.SubElement(root, key).text = value
    # WinSW prompts for a restricted Windows account. Do not save passwords
    # in XML, history, environment variables, or the command line.
    ET.SubElement(ET.SubElement(root, "serviceaccount"), "prompt").text = "dialog"
    ET.SubElement(root, "log", {"mode": "roll"})
    ET.SubElement(root, "onfailure", {"action": "restart", "delay": "10 sec"})
    return ET.tostring(root, encoding="unicode")


def service_status(script: Path, data_dir: Path | None = None) -> dict:
    """Read-only status for THIS app; never execute control commands from the API."""
    exe, config = service_paths(script, data_dir)
    info = {"name": service_name(script), "installed": False,
            "running": False, "status": "Not installed", "platform": sys.platform}
    # Preferred no-elevation background launcher: this check is scoped to one app.
    try:
        from .hosting import read_hosting
        from .desktop_launcher import instance_responding
        port = read_hosting(project_data_dir(script, data_dir))["port"]
        if instance_responding(Path(script).resolve(), port):
            info.update(installed=True, running=True, status="Running in background")
            return info
    except (OSError, ValueError, KeyError):
        pass
    if sys.platform != "win32":
        info["status"] = "Not running in background"
        return info
    # Check the Windows Service Control Manager directly. New versions use
    # pywin32, while pre-existing WinSW deployments remain detectable.
    # Ask the OS service manager, not the internet or a user-controlled shell.
    try:
        process = subprocess.run(["sc.exe", "query", info["name"]], capture_output=True,
                                 text=True, timeout=6, check=False)
        output = process.stdout.upper()
        if process.returncode == 0:
            info["installed"] = True
            info["running"] = "RUNNING" in output
            info["status"] = "Running" if info["running"] else ("Stopped" if "STOPPED" in output else "Starting or stopping")
        else:
            info["status"] = "Not installed"
    except (OSError, subprocess.TimeoutExpired):
        info["status"] = "Status unavailable"
    return info


def service_command(action: str, script: Path, *, data_dir: Path | None = None,
                    wrapper: Path | None = None,
                    port: int = 8501, host: str = "127.0.0.1", mode: str = "development") -> int:
    if sys.platform != "win32":
        raise RuntimeError("Windows Service commands require Windows. Use systemd on Linux.")
    script = Path(script).resolve()
    if not script.is_file():
        raise FileNotFoundError(f"Application script not found: {script}")
    directory = project_data_dir(script, data_dir)
    exe, config = service_paths(script, directory)
    if action == "install":
        if wrapper is None or not Path(wrapper).is_file():
            raise ValueError("Provide the WinSW v3 executable using --wrapper PATH")
        if exe.exists() or config.exists():
            raise FileExistsError("Service files exist already. Use 'service status' or uninstall before reinstalling.")
        # Validate BEFORE writing any files. Current Python must be from the
        # environment where this server package has been installed.
        xml = service_xml(script, directory, port=port, host=host, mode=mode)
        exe.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wrapper, exe)
        config.write_text(xml, encoding="utf-8")
        command = [str(exe), "install"]
    else:
        if action not in ("start", "stop", "restart", "status", "uninstall"):
            raise ValueError("Unknown service command")
        if not exe.is_file() or not config.is_file():
            raise FileNotFoundError("Service has not been configured for this application")
        command = [str(exe), action]
    # An OS elevation prompt can appear. No HTTP endpoint can trigger this call.
    result = subprocess.run(command, check=False)
    if result.returncode == 0 and action == "uninstall":
        # Preserve all databases and logs; keep wrapper configuration as evidence.
        print("Service uninstalled. Application data and service config are preserved.")
    return result.returncode
