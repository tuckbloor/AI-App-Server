# AI App Server v0.9.0 — production hardening candidate

This is a **security-testing candidate**, not a certified or independently audited
production framework. The engine will refuse to run with several unsafe production
settings. It still executes the developer's trusted `app.py` with the Python process's
privileges, so never expose untrusted executable code or unrestricted agent tools.

## Modes

- **Development:** HTTP on localhost only. No certificate required. Use `START HERE.bat`.
- **Production:** Restricted Python process and separate HTTPS reverse proxy,
  configured public origin, strong application gate password, and a non-default
  administrator password. `ai-app-server doctor` must pass before deployment.

## What this release improves

- Windows overlay update: validates source-file digests, snapshots SQLite through
  the SQLite backup API, copies the encryption key and hosting configuration,
  verifies integrity, and restores old engine/database if an update fails.
- Production access: separate admin and application sessions; strict cookie and
  origin handling, request and WebSocket size limits, and security headers.
- Deployment: an example rootless-application Docker/Caddy arrangement; no direct
  published Python service port; HTTPS at the reverse proxy; read-only image;
  limited resources and capabilities.
- Recovery: cryptographically hashed snapshot manifests and `verify-backup`
  command. Backups are **not encrypted** and must be restricted by filesystem
  permissions and copied off the machine for disaster recovery.

## Still required before unrestricted real-world production

- Real Windows and Linux deployment testing on the actual target machines;
  DNS and TLS issuance/renewal validation.
- Independent penetration test, software-composition audit and review of Python
  agent capabilities. Run only code from trusted developers.
- Per-user application identity/SSO/MFA for staff-facing systems; current
  production public app password is shared, not individual user authorization.
- A scheduled, tested **off-host** backup and restoration procedure; the overlay
  backup protects upgrades on the same disk, not disk failure or ransomware.
- Full load/restart/failure testing and tested emergency recovery runbook.

## Updating without deleting folders

1. Download `AI-App-Server-v0.9.0-OVERLAY.zip`.
2. Extract it beside the existing app so the folders are siblings:
   `E:\ai-app-server` and `E:\AI-App-Server-v0.9.0-OVERLAY`.
3. Double-click `INSTALL UPDATE.bat` in the overlay folder. No manual backups.
4. The updater stops only that installation, creates a verified local recovery
   snapshot and previous-engine copy, applies the new engine, and restarts it if
   it was already running. It will attempt rollback if a step fails.
5. Port, `app/`, admin accounts, encryption key, SQLite, `config/` and private
   `production/.env` remain in place. A backup is in `backups/overlay-v090-*`.

Never publish `data/`, `config/`, `.env`, encryption keys or backups on GitHub.

MCP: disabled by default. Never expose /mcp without TLS, bearer authentication, input validation and per-tool authorization. This release exposes only explicitly registered read-only tools, and is not yet a full OAuth-enabled MCP platform.
