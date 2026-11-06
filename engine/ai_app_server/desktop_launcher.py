"""No-elevation Windows desktop hosting (run after user sign-in, no open console).

Not a Windows Service: deliberately avoids SCM, pywin32, service accounts and UAC.
Runs exactly one trusted project, bound to 127.0.0.1, with separate data.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from .hosting import initialize_port, is_port_free, read_hosting, save_hosting
from .service import service_name


def paths(project: Path):
    project = Path(project).resolve()
    # Keep existing v0.5.x script path to preserve active app identity and user edits.
    legacy = project / "examples" / "app.py"
    script = legacy if legacy.is_file() else project / "app" / "app.py"
    return project, script, project / "data"


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def instance_responding(script: Path, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.2) as r:
            payload = json.load(r)
            return payload.get("app_id") == service_name(script)
    except (ValueError, OSError, urllib.error.URLError, TimeoutError):
        return False


def pick_port(script: Path, data: Path) -> tuple[int, bool]:
    # Existing installations must never silently change their saved port.
    # Only a brand-new installation may choose a free port automatically.
    from .hosting import _existing_config
    first_run = not _existing_config(data).is_file()
    settings = initialize_port(data)
    port = settings["port"]
    if instance_responding(script, port):
        return port, True
    if is_port_free(port):
        return port, False
    # An existing configured port is part of this application identity.
    # Fail instead of unexpectedly moving the server to a different address.
    if not first_run:
        raise RuntimeError(f"Configured port {port} is busy. Stop the other application or change this installation's port in Admin > Service.")
    # Only first-run installations can choose another available port.
    for candidate in range(8501, 8701):
        if is_port_free(candidate):
            save_hosting(data, candidate)
            print(f"Port {port} was already occupied; using {candidate} instead.", flush=True)
            return candidate, False
    raise RuntimeError("Ports 8501–8700 are all in use. Change the port in Admin > Service.")


def launch(project: Path, *, open_browser: bool = True, timeout: int = 35) -> dict:
    project, script, data = paths(project)
    if not script.is_file():
        raise FileNotFoundError(f"Missing application: {script}. Please extract the entire ZIP, then run INSTALL.bat.")
    data.mkdir(exist_ok=True, parents=True)
    if read_hosting(data)['mode'] == 'production':
        raise RuntimeError('Production is enabled. Use the documented HTTPS reverse-proxy deployment, not the local one-click launcher.')
    port, already_running = pick_port(script, data)
    address = url(port)
    if already_running:
        print(f"Already running: {address}", flush=True)
        if open_browser:
            webbrowser.open(address)
        return {"url": address, "already_running": True, "port": port}
    logs = data / "logs"
    logs.mkdir(exist_ok=True, parents=True)
    output = logs / "server.log"
    interpreter = Path(sys.executable)
    if sys.platform == "win32":
        alternative = interpreter.with_name("pythonw.exe")
        if alternative.is_file():
            interpreter = alternative
    cmd = [str(interpreter), "-m", "ai_app_server.cli", "run", str(script),
           "--data-dir", str(data), "--port", str(port)]
    flags = 0
    kwargs = {}
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    with output.open("a", encoding="utf-8") as log:
        log.write(f"\n--- Starting {script} at {address} ---\n")
        log.flush()
        p = subprocess.Popen(cmd, cwd=str(project), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, creationflags=flags, **kwargs)
    (data / "runtime.json").write_text(json.dumps({"pid": p.pid, "script": str(script), "port": port}), encoding="utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if instance_responding(script, port):
            print(f"AI App Server is running: {address}", flush=True)
            print(f"Administration: {address}admin", flush=True)
            if open_browser:
                webbrowser.open(address)
            return {"url": address, "already_running": False, "port": port}
        if p.poll() is not None:
            break
        time.sleep(.35)
    if p.poll() is None:
        # Avoid leaving a second, broken background server behind after a timeout.
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    (data / "runtime.json").unlink(missing_ok=True)
    tail = output.read_text(encoding="utf-8", errors="replace").splitlines()[-18:]
    raise RuntimeError("The server did not start. See data\\logs\\server.log.\n" + "\n".join(tail))


def startup_file(project: Path) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Windows sign-in startup is only available on Windows.")
    base = os.environ.get("APPDATA")
    if not base:
        raise RuntimeError("Windows APPDATA location is not available.")
    return (Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" /
            f"AI App Server {service_name(paths(project)[1])[-10:]}.vbs")


def enable_startup(project: Path):
    project = Path(project).resolve()
    destination = startup_file(project)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # One Windows entrypoint for interactive and silent startup.
    # Do not point at a separate helper .bat that is absent from the release.
    batch = str(project / "START.bat").replace('"', '""')
    destination.write_text('Set shell = CreateObject("WScript.Shell")\n'
                           f'shell.Run Chr(34) & "{batch}" & Chr(34) & " --background", 0, False\n',
                           encoding="utf-8")
    print("Background auto-start enabled for your Windows sign-in (no administrator access needed).", flush=True)
    return destination


def disable_startup(project: Path):
    destination = startup_file(project)
    destination.unlink(missing_ok=True)
    print("Automatic startup disabled. Your application and database have not been deleted.", flush=True)


def stop(project: Path):
    project, script, data = paths(project)
    runtime = data / "runtime.json"
    if not runtime.is_file():
        print("No background process recorded for this application.")
        return
    details = json.loads(runtime.read_text(encoding="utf-8"))
    pid = int(details["pid"])
    if details.get("script") != str(script):
        raise RuntimeError("Recorded process belongs to a different application. Refusing to stop it.")
    if sys.platform == "win32":
        check = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
            f'(Get-CimInstance Win32_Process -Filter "ProcessId = {pid}").CommandLine'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
        actual = check.stdout.casefold()
        if "ai_app_server.cli" not in actual or str(script).casefold() not in actual:
            if not instance_responding(script, details["port"]):
                print("Application is already stopped.")
                runtime.unlink(missing_ok=True)
                return
            raise RuntimeError("Could not verify the server process. Refusing to stop an unrelated program.")
        result = subprocess.run(["taskkill.exe", "/PID", str(pid), "/F"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Could not stop the application")
    else:
        import signal
        os.kill(pid, signal.SIGTERM)
    runtime.unlink(missing_ok=True)
    print("AI App Server stopped. Your application files and database are unchanged.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="AI App Server Launcher")
    parser.add_argument("action", choices=["install", "start", "stop", "remove-startup", "status"])
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        project, script, data = paths(args.project)
        if args.action == "install":
            info = launch(project, open_browser=not args.no_browser)
            if sys.platform == "win32":
                enable_startup(project)
        elif args.action == "start":
            launch(project, open_browser=not args.no_browser)
        elif args.action == "stop":
            stop(project)
        elif args.action == "remove-startup":
            disable_startup(project)
        else:
            port = read_hosting(data)["port"]
            print(f"Server: {'Running' if instance_responding(script, port) else 'Not responding'}; address {url(port)}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
