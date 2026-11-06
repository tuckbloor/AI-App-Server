"""Run independent Python applications with the AI App Server UI framework."""
from __future__ import annotations
import argparse
from getpass import getpass
import os
from pathlib import Path
import sys
import uvicorn
from .server import create_app
from .service import project_data_dir, service_command, service_status
from .storage import Store
from .version import __version__
from .hosting import initialize_port, read_hosting, validate_port
from .app_security import validate_production, production_checks


def _secure_production(parser, data_dir: Path, *, localhost=True):
    try:
        validate_production(Store(data_dir), local_only=localhost)
    except ValueError as exc:
        parser.error(str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ai-app-server", description="Self-hosted Python web app framework")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run your independent app.py")
    run.add_argument("script", type=Path)
    run.add_argument("--port", type=int, default=None)
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--mode", choices=["development", "production"], default=None)
    run.add_argument("--data-dir", type=Path, default=None)

    service = sub.add_parser("service", help="Install/manage this app as its own Windows Service (WinSW v3)")
    service.add_argument("action", choices=["install", "start", "stop", "restart", "status", "uninstall"])
    service.add_argument("script", type=Path)
    service.add_argument("--data-dir", type=Path, default=None)
    service.add_argument("--wrapper", type=Path, default=None, help="WinSW v3 executable (install only)")
    service.add_argument("--port", type=int, default=None)
    service.add_argument("--host", default="127.0.0.1")
    service.add_argument("--mode", choices=["development", "production"], default="development")

    setup = sub.add_parser("setup-admin", help="Set up the first administrator from a trusted local terminal")
    setup.add_argument("script", type=Path)
    setup.add_argument("--data-dir", type=Path, default=None)

    create_app_user_cmd = sub.add_parser('setup-app-user', help='Create an individual application login on a trusted server terminal')
    create_app_user_cmd.add_argument('script', type=Path)
    create_app_user_cmd.add_argument('--data-dir', type=Path, default=None)

    doctor = sub.add_parser("doctor", help="Check whether this installation can be deployed in production")
    doctor.add_argument("script", type=Path)
    doctor.add_argument("--data-dir", type=Path, default=None)

    backup = sub.add_parser("backup", help="Back up this app's SQLite database AND encryption key")
    backup.add_argument("script", type=Path)
    backup.add_argument("--to", type=Path, required=True)
    backup.add_argument("--data-dir", type=Path, default=None)

    snapshot = sub.add_parser("snapshot", help="Create a verified backup of SQLite, key, config and project code to another location")
    snapshot.add_argument("script", type=Path)
    snapshot.add_argument("--to", type=Path, required=True)
    snapshot.add_argument("--data-dir", type=Path, default=None)

    restore_test = sub.add_parser("restore-test", help="Prove a snapshot can restore to a fresh isolated folder")
    restore_test.add_argument("script", type=Path)
    restore_test.add_argument("--snapshot", type=Path, required=True)
    restore_test.add_argument("--to", type=Path, required=True)
    restore_test.add_argument("--data-dir", type=Path, default=None)

    verify = sub.add_parser("verify-backup", help="Verify an automatic upgrade snapshot without changing the server")
    verify.add_argument("script", type=Path)
    verify.add_argument("--snapshot", type=Path, required=True)
    verify.add_argument("--data-dir", type=Path, default=None)

    args = parser.parse_args(argv)
    if not args.script.is_file():
        parser.error(f"Application not found: {args.script}")
    data_dir = project_data_dir(args.script, args.data_dir)
    if args.command in ("snapshot", "restore-test"):
        from .recovery import create_snapshot, rehearse_restore
        # Installed layout: app/app.py, data/, config/ are siblings.
        root = data_dir.parent
        if not (root / "app").is_dir() or not args.script.resolve().is_relative_to(root / "app"):
            parser.error("Snapshot requires a modular installation with app/ and data/ siblings")
        if args.command == "snapshot":
            result = create_snapshot(root, args.to, include_app=True)
            print(f"Verified snapshot saved: {args.to} ({len(result['files'])} files)")
        else:
            result = rehearse_restore(args.snapshot, args.to)
            print(f"Restore rehearsal succeeded: {args.to} ({len(result['files'])} files)")
        return 0
    if args.command == "verify-backup":
        from .recovery import verify_snapshot
        result = verify_snapshot(args.snapshot)
        print(f"Verified backup: {args.snapshot} ({len(result['files'])} protected files)")
        return 0
    if args.command == "setup-admin":
        from .storage import normalized_email, is_strong_password, verify_password
        store = Store(data_dir)
        user = store.user_by_name('admin')
        if not user:
            parser.error('Initial admin account is missing. Use your administrator tools to recover access.')
        if not user['must_change_password']:
            print('The initial administrator is already configured. Use Admin > Security to change credentials.')
            return 0
        if not verify_password('password', user['password_hash']):
            parser.error('Initial account state does not match the bundled default; use Admin > Security.')
        try:
            email = normalized_email(input('Administrator recovery email: '))
            password = getpass('New administrator password (at least 12 characters): ')
            confirm = getpass('Confirm new administrator password: ')
        except (EOFError, KeyboardInterrupt):
            print('\nSetup cancelled. No changes made.')
            return 1
        if not is_strong_password(password) or password == 'password' or password != confirm:
            parser.error('Passwords must match, be at least 12 characters and not be the bundled default.')
        store.update_password(user['id'], password, email=email)
        store.audit('system', 'first_run_admin_configured', 'admin')
        print('Administrator configured. Verify the email after SMTP has been configured.')
        return 0
    if args.command == 'setup-app-user':
        from .storage import normalized_email, is_strong_password
        from sqlite3 import IntegrityError
        try:
            username = input('Application username (3-60 characters): ').strip()
            display_name = input('Full name: ').strip()
            email = input('Email (optional): ').strip()
            password = getpass('Individual application password (at least 12 characters): ')
            confirm = getpass('Confirm password: ')
        except (EOFError, KeyboardInterrupt):
            print('\nCancelled. No changes made.')
            return 1
        import re
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,60}', username) or not 1 <= len(display_name) <= 100:
            parser.error('Username or full name is invalid')
        if not is_strong_password(password) or password != confirm:
            parser.error('Passwords must match and contain 12–256 characters')
        try:
            Store(data_dir).create_app_user(username, display_name, password, email)
        except (ValueError, IntegrityError) as exc:
            parser.error('Cannot create application user: ' + str(exc))
        print('Application user created; use this account to sign in to the public app.')
        return 0
    if args.command == "doctor":
        for result in production_checks(Store(data_dir), local_only=True):
            print(("PASS" if result['ok'] else "ACTION NEEDED") + ": " + result['message'])
        return 0 if all(result['ok'] for result in production_checks(Store(data_dir), local_only=True)) else 2
    if args.command == "backup":
        print(f"Backup saved: {Store(data_dir).backup(args.to)}")
        return 0
    if args.command == "service":
        if args.action == "status":
            info = service_status(args.script, data_dir)
            print(f"{info['name']}: {info['status']}")
            return 0
        try:
            if args.wrapper:
                return service_command(args.action, args.script, data_dir=data_dir, wrapper=args.wrapper,
                                       port=args.port or read_hosting(data_dir)["port"], host=args.host, mode=args.mode)
            from .windows_service import control
            return control(args.action, args.script, data_dir) or 0
        except (OSError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
    if args.command == "run":
        settings = initialize_port(data_dir)
        configured_mode = settings['mode']
        if args.mode is None:
            args.mode = configured_mode
        elif configured_mode == 'production' and args.mode != 'production':
            parser.error('This installation is configured for production; refusing a development-mode override')
        if args.port is None:
            args.port = settings["port"]
        if not 1 <= args.port <= 65535:
            parser.error("Port must be 1–65535")
        localhost = args.host in ("127.0.0.1", "localhost", "::1")
        if not localhost and args.mode != "production":
            parser.error("Development mode can only bind to localhost")
        if args.mode == "production":
            _secure_production(parser, data_dir, localhost=localhost)
        print(f"\nAI App Server v{__version__} — {args.script.name}")
        if args.mode == "production":
            from .app_security import configured_origin
            print(f"Public application: {configured_origin()}/ (through your HTTPS reverse proxy)")
        else:
            print(f"Application: http://127.0.0.1:{args.port}/")
        print(f"Admin panel: {configured_origin() if args.mode == 'production' else f'http://127.0.0.1:{args.port}'}/admin")
        print(f"Private system data: {data_dir}")
        print("\nPress Ctrl+C to stop. Use START.bat for background startup on Windows.\n")
        uvicorn.run(create_app(args.script, data_dir=data_dir, mode=args.mode,
                               secure_cookies=args.mode == "production", local_only=localhost),
                    host=args.host, port=args.port, proxy_headers=False, ws_max_size=65536)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
