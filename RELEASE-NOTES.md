# AI App Server v1.0.2 — Guarded Upgrade

- Adds isolated live HTTP canary before stopping an installed v0.9.2 server.
- Stops only the identified application and refuses port conflicts without changing a saved port.
- Restarts on the original port, verifies HTTP health, and restores the previous engine and SQLite snapshot after a simulated failed update.
- Preserves `app/`, `data/`, `config/` and encryption key.
- Includes TLS/Docker reference configuration and production acceptance checklist.

**Security scope:** trusted first-party Python application and reviewed MCP tools, in a single-organisation deployment. Not a sandbox for untrusted agent scripts or customer-uploaded Python. Individual application users/SSO, external penetration testing, public certificate validation and off-host restore must be completed for deployments needing them.

See `production/ACCEPTANCE.md`.
