# Updating AI App Server without losing your work

## First time installing v0.6.0

Download the complete v0.6.0 ZIP, extract to `E:\` (over your existing files if you already have v0.5.x) **without deleting the `data` folder**, then double-click **START HERE.bat**. Existing custom apps in `examples/app.py`, your admin database, keys and saved port will be kept. The old v0.5 framework is moved to `backups/`.

## Future versions — one-click framework upgrade

1. Download the next **trusted** AI App Server release ZIP. **Do not extract it over your installation.**
2. In your existing installation, double-click **UPDATE ENGINE.bat**.
3. Choose the release ZIP. You do not need to unpack it or work with PowerShell.
4. The updater checks the version, stops the current instance, backs up the old `engine/` and consistent SQLite state, swaps `engine/`, installs any new Python dependencies and verifies the server can start.
5. If the install fails, the updater restores the previous engine and reports the error. It **does not silently overwrite your live database**.

The `engine/` directory is the only source folder replaced. The programmer's `app/app.py` (or existing `examples/app.py`), `config/hosting.json`, `data/server.sqlite3`, `data/.secret-key`, passwords, logs and other projects are not overwritten.

An engine backup and SQLite snapshot are saved in `backups/engine-update-...`. Keep this folder private: database snapshots and encryption keys are sensitive.

A **database migration** may make an older version of the framework incompatible with a newer schema. If a migration itself fails, the updater saves the snapshot and reports that manual database restore may be needed; it does not automatically erase or replace application data.

## One independent instance per Python system

`E:\ai-app-server` and `E:\AnotherSystem\ai-app-server` have separate ports, SQLite databases and administrator accounts. Upgrading one instance does not upgrade the other. Each app only shows its **own** admin dashboard.

## For package developers

The installable Python package lives in `engine/` (`engine/pyproject.toml`). Editable installs use `pip install -e engine`; a Python wheel is bundled in `dist/`. Unit and integration tests live in `tests/`. Standard UI controls remain importable through `import ai_app_server as ui`.
