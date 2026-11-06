"""Portable, stdlib-only Windows installer for the bundled AI App Server source.

The installation directory is chosen by the user. NEVER overwrite an existing
installation with this fresh-install path: its database, app and secrets belong to it.
The original source archive is not downloaded, modified or executed from an
untrusted location, and all runtime dependencies go into a local virtualenv.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
REQUIRED = (
    "engine/pyproject.toml",
    "engine/ai_app_server/__init__.py",
    "engine/ai_app_server/desktop_launcher.py",
    "starter/app.py",
    "tools/bootstrap.py",
    "START.bat",
)
COPY_DIRS = ("engine", "starter", "tools")
COPY_FILES = ("START.bat", "INSTALL.bat", "README.md", "LICENSE", ".env.smtp.example")


class InstallError(RuntimeError):
    pass


def recommended_target() -> Path:
    # No E: or C: assumption; Windows provides a user-writable local app directory.
    home = os.environ.get("LOCALAPPDATA")
    return (Path(home) if home else Path.home()) / "Programs" / "AI-App-Server"


def choose_target(default: Path, *, console: bool = False) -> Path:
    """A single ordinary installer dialog, with a visible editable destination."""
    if not console:
        try:
            import tkinter as tk
            from tkinter import ttk, filedialog
            window = tk.Tk()
            window.title("Install AI App Server")
            window.resizable(False, False)
            window.geometry("590x208")
            path = tk.StringVar(value=str(default))
            selected: list[str] = []
            frame = ttk.Frame(window, padding=18)
            frame.pack(fill='both', expand=True)
            ttk.Label(frame, text="AI App Server v1.0.5", font=("Segoe UI", 15, "bold")).grid(
                row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
            ttk.Label(frame, text="Choose an empty installation folder (any drive):").grid(
                row=1, column=0, columnspan=2, sticky='w')
            entry = ttk.Entry(frame, textvariable=path, width=67)
            entry.grid(row=2, column=0, sticky='ew', pady=(5, 12))

            def browse():
                initial = Path(path.get().strip() or default).expanduser().parent
                if not initial.exists():
                    initial = Path.home()
                chosen = filedialog.askdirectory(
                    title="Choose AI App Server destination folder",
                    parent=window, initialdir=str(initial), mustexist=False)
                if chosen:
                    path.set(chosen)

            ttk.Button(frame, text="Browse...", command=browse).grid(
                row=2, column=1, sticky='e', padx=(10, 0), pady=(5, 12))
            ttk.Label(frame, text="Existing installations and their databases will not be overwritten.").grid(
                row=3, column=0, columnspan=2, sticky='w')

            def accept():
                if path.get().strip():
                    selected.append(path.get().strip().strip('"'))
                    window.destroy()

            def cancel():
                window.destroy()

            button_row = ttk.Frame(frame)
            button_row.grid(row=4, column=0, columnspan=2, sticky='e', pady=(14, 0))
            ttk.Button(button_row, text="Cancel", command=cancel).pack(side='right')
            ttk.Button(button_row, text="Install", command=accept).pack(side='right', padx=10)
            frame.columnconfigure(0, weight=1)
            window.protocol("WM_DELETE_WINDOW", cancel)
            entry.focus_set()
            window.mainloop()
            if not selected:
                raise InstallError("Installation cancelled. Nothing was changed.")
            return Path(selected[0]).expanduser().resolve()
        except ImportError:
            print("Graphical folder picker is not installed. Using a console prompt.")
        except Exception as exc:
            # Tk may fail on remote sessions without a graphical desktop.
            if exc.__class__.__name__ != 'TclError':
                raise
            print("Graphical folder picker unavailable. Using a console prompt.")
    if not sys.stdin.isatty():
        raise InstallError("No interactive folder selector is available. Use --target PATH.")
    selection = input(f"Install directory [{default}]: ").strip().strip('"')
    return Path(selection or default).expanduser().resolve()


def validate_source(source: Path) -> None:
    for relative in REQUIRED:
        if not (source / relative).is_file():
            raise InstallError(f"Incomplete project archive: missing {relative}")
    # Refuse copied git references or filesystem links pointing outside this package.
    for relative in (*COPY_FILES, *COPY_DIRS):
        p = source / relative
        if p.exists() and p.is_symlink():
            raise InstallError(f"Source contains a symbolic link: {relative}")


def validate_destination(source: Path, dest: Path) -> str:
    src, dst = source.resolve(), dest.resolve()
    if dst == src:
        return "in-place"
    if dst in src.parents or src in dst.parents:
        raise InstallError("Choose a different folder, not inside or above the downloaded source folder.")
    if dst.exists():
        if dst.is_symlink() or not dst.is_dir():
            raise InstallError("Destination must be an ordinary directory.")
        if any(dst.iterdir()):
            raise InstallError(
                "The chosen folder is not empty. Nothing was overwritten. "
                "For an existing installation, use START.bat or a separately validated upgrade. "
                "Select a new empty folder for a clean install."
            )
    return "new"


def copy_fresh(source: Path, dest: Path) -> None:
    """Stage and publish only static program files; avoid user-owned runtime data."""
    source, dest = source.resolve(), dest.resolve()
    validate_source(source)
    mode = validate_destination(source, dest)
    if mode == "in-place":
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".ai-app-server-stage-", dir=dest.parent))
    try:
        for relative in COPY_DIRS:
            src = source / relative
            if src.exists():
                # No symbolic links in the source tree or accidental runtime copies.
                for path in src.rglob('*'):
                    if path.is_symlink():
                        raise InstallError(f"Refusing symbolic link in source: {path}")
                shutil.copytree(src, staging / relative, symlinks=False,
                                ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo','.pytest_cache'))
        for relative in COPY_FILES:
            src = source / relative
            if src.exists():
                shutil.copy2(src, staging / relative)
        if dest.exists():
            # An empty folder chosen in the picker is never silently replaced
            # without confirming that it is still empty.
            if any(dest.iterdir()):
                raise InstallError("Destination changed during installation; refusing to overwrite it.")
            dest.rmdir()
        staging.rename(dest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def execute(cmd: list[str], target: Path, *, title: str) -> None:
    print(f"\n[{title}]", flush=True)
    result = subprocess.run(cmd, cwd=target, check=False)
    if result.returncode:
        raise InstallError(f"{title} failed (exit {result.returncode}). See the console output above.")


def install_runtime(target: Path, *, start: bool = True) -> None:
    exe = target / ".venv" / "Scripts" / "python.exe"
    if not exe.exists():
        execute([sys.executable,"-m","venv",str(target / ".venv")],target,title="Create Python environment")
    if not exe.exists():
        raise InstallError(f"Python environment creation failed: {exe}")
    execute([str(exe),str(target / "tools" / "bootstrap.py")],target,
            title="Create initial application (preserve existing data)")
    execute([str(exe),"-m","pip","install","--disable-pip-version-check","-e",str(target / "engine")],
            target,title="Install Python requirements")
    if start:
        execute([str(exe),"-m","ai_app_server.desktop_launcher","install","--project",str(target)],
                target,title="Start server and enable Windows sign-in startup")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AI App Server portable Windows installer")
    parser.add_argument('--target',type=Path,help='Install destination; bypass graphical folder selector')
    parser.add_argument('--console',action='store_true',help='Use a console folder prompt')
    parser.add_argument('--copy-only',action='store_true',help='Prepare a clean application folder without installing requirements')
    parser.add_argument('--no-start',action='store_true',help='Install requirements but do not start the server')
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32' and not args.copy_only:
            raise InstallError('This installer is for Windows; use run-linux.sh for Linux.')
        if sys.version_info < (3,11):
            raise InstallError('Python 3.11 or newer is required.')
        source = SOURCE.resolve()
        validate_source(source)
        target = (args.target.expanduser().resolve() if args.target else
                  choose_target(recommended_target(),console=args.console))
        mode = validate_destination(source,target)
        print(f"\nProject source : {source}\nInstall folder : {target}\nMode : {mode}",flush=True)
        copy_fresh(source,target)
        if not args.copy_only:
            install_runtime(target,start=not args.no_start)
        print(f"\nSUCCESS. AI App Server is installed at: {target}\n"
              f"Use {target / 'START.bat'} to open it next time.", flush=True)
        return 0
    except (InstallError, OSError, subprocess.SubprocessError) as exc:
        print(f"\nINSTALLATION STOPPED: {exc}\nYour previous installation was not deleted.",file=sys.stderr,flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
