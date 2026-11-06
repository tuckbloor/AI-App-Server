"""Windows service support via pywin32 (installed by the one-click setup).

No third-party executable download or per-user password required. Each application
is a distinct Windows Service running as Windows' low-privilege LocalService.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .hosting import initialize_port, read_hosting, is_port_free
from .service import service_name, project_data_dir


def windows_modules():
    if sys.platform != "win32":
        raise RuntimeError("Windows Service installation is only available on Windows")
    try:
        import win32service
        import win32serviceutil
        import win32event
        import servicemanager
        import winreg
    except ImportError as exc:
        raise RuntimeError("Windows service support is missing. Install the optional engine[windows-service] dependencies and use the documented service CLI.") from exc
    return win32service, win32serviceutil, win32event, servicemanager, winreg


# Importing this module on Linux remains possible (for unit tests).
if sys.platform == "win32":
    try:
        import win32serviceutil as _svcutil
        import win32service as _win32service
        import win32event as _win32event
        class AIAppWindowsService(_svcutil.ServiceFramework):
            _svc_name_ = "AIAppServer"
            _svc_display_name_ = "AI App Server"

            def __init__(self, args):
                super().__init__(args)
                self.name = args[0]
                self.stop_event = _win32event.CreateEvent(None, 0, 0, None)
                self.server = None

            def SvcStop(self):
                self.ReportServiceStatus(_win32service.SERVICE_STOP_PENDING)
                if self.server is not None:
                    self.server.should_exit = True
                _win32event.SetEvent(self.stop_event)

            def SvcDoRun(self):
                import winreg
                import uvicorn
                from .server import create_app
                from .hosting import read_hosting
                regkey = rf"SOFTWARE\AIAppServer\Services\{self.name}"
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, regkey) as key:
                    script = Path(winreg.QueryValueEx(key, "Script")[0])
                    data_dir = Path(winreg.QueryValueEx(key, "DataDir")[0])
                config = read_hosting(data_dir)
                self.server = uvicorn.Server(uvicorn.Config(
                    create_app(script, data_dir=data_dir, mode="development", local_only=True),
                    host="127.0.0.1", port=config["port"], log_level="info", proxy_headers=False,
                    ws_max_size=65536))
                self.server.run()
    except ImportError:
        AIAppWindowsService = None
else:
    AIAppWindowsService = None


def install_service(script: Path, data_dir: Path):
    svc, util, _, _, winreg = windows_modules()
    script, data_dir = Path(script).resolve(), Path(data_dir).resolve()
    if not script.is_file():
        raise FileNotFoundError(f"Python application missing: {script}")
    data_dir.mkdir(parents=True, exist_ok=True)
    hosting = initialize_port(data_dir)
    if not is_port_free(hosting["port"]):
        raise RuntimeError(f"Port {hosting['port']} is in use. Stop the terminal running this application, or choose another port in Admin > Service, then try again.")
    name = service_name(script)
    # Grant only this service identity access to the system's own data folder.
    import subprocess
    acl = subprocess.run(["icacls.exe", str(data_dir), "/grant", "*S-1-5-19:(OI)(CI)M", "/T"],
                         capture_output=True, text=True, timeout=40)
    if acl.returncode:
        raise PermissionError("Cannot grant LocalService access to application data. " + acl.stderr[:250])
    registry_path = rf"SOFTWARE\AIAppServer\Services\{name}"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, registry_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Script", 0, winreg.REG_SZ, str(script))
        winreg.SetValueEx(key, "DataDir", 0, winreg.REG_SZ, str(data_dir))
    try:
        util.InstallService(
            "ai_app_server.windows_service.AIAppWindowsService", name,
            f"AI App Server - {script.parent.name} ({name[-6:]})",
            startType=svc.SERVICE_AUTO_START, userName=r"NT AUTHORITY\LocalService", password="",
            description=f"Independent AI App Server installation for {script}")
    except Exception:
        # Do not erase registry settings if a previously-installed service exists.
        raise
    print(f"Installed {name}; configured for automatic startup under LocalService.")
    return name


def control(action: str, script: Path, data_dir: Path):
    _, util, _, _, winreg = windows_modules()
    name = service_name(script)
    if action == "install":
        name = install_service(script, data_dir)
        action = "start"
    if action == "start":
        util.StartService(name)
    elif action == "stop":
        util.StopService(name)
    elif action == "restart":
        util.RestartService(name)
    elif action == "uninstall":
        try:
            util.StopService(name)
        except Exception:
            pass
        util.RemoveService(name)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\AIAppServer\Services", 0,
                            winreg.KEY_WRITE) as key:
            winreg.DeleteKey(key, name)
        print("Service removed. Your database and files are preserved.")
    elif action != "status":
        raise ValueError(f"Unsupported service action: {action}")
    from .service import service_status
    print(f"{name}: {service_status(script, data_dir)['status']}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Install and manage one AI App Server as a Windows Service")
    p.add_argument("action", choices=["install", "start", "stop", "restart", "uninstall", "status"])
    p.add_argument("script", type=Path)
    p.add_argument("--data-dir", type=Path)
    args = p.parse_args(argv)
    try:
        return control(args.action, args.script, project_data_dir(args.script, args.data_dir)) or 0
    except Exception as exc:
        p.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    sys.exit(main())
