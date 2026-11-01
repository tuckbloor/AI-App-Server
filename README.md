# AI App Server v0.8.0 — Development and production hardening

**Self-hosted modular Python AI app server** for ordinary apps, one agent, or several developer-owned agents. Each application has its own admin, SQLite database, settings and process. No global agent management.

## Local Windows development: no SSL needed

Extract the release ZIP to `E:\` so it becomes `E:\ai-app-server`, then double-click **START HERE.bat**. It installs dependencies, starts the local app in the background, checks health, and opens the correct local URL. Admin users log in at `/admin`. The default admin credentials are only for initial local setup and must be changed before production.

## Production

Production has a separate, fail-closed configuration: localhost Python bind behind HTTPS proxy, an explicit trusted public HTTPS origin, a private application password, and a changed administrator password. HTTP is allowed locally in development. The admin **Service** page can show the environment selection and preflight requirements; a production selection is rejected until they pass. Use `ai-app-server doctor app/app.py --data-dir data` to run preflight checks.

See [production/README.md](production/README.md) and [PRODUCTION-SECURITY.md](PRODUCTION-SECURITY.md). **This is a production deployment candidate, not a public-internet security certification.** The included Compose/Caddy example still needs full end-to-end review on the target infrastructure.

## Safe engine upgrades

The replaceable code lives under `engine/`. Application code lives in `app/`, private SQLite data in `data/` and port/mode settings in `config/`. Future engine upgrades do not include those files. Use **UPDATE ENGINE.bat** instead of deleting the installation. The updater backs up the previous engine and SQLite state, checks the new server, and attempts rollback when startup fails. Keep separate off-device backups for drive failure and ransomware protection.

## AI capabilities

Developers can build normal Python UIs or optional `Agent` / `AgentPipeline` steps with Ollama. Our server does not auto-create agents or let remote visitors execute arbitrary uploaded Python code. All agent scripts are trusted developer code.

## Run tests

```bash
python -m pip install -e './engine[dev]'
python -m pytest -q
```

The Python package is not yet published on PyPI.
