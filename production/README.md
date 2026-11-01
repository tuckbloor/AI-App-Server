# Production deployment reference — AI App Server v0.9.0

This is a **production hardening candidate**, not a blanket approval to expose the
project to the internet. Start from a trusted, dedicated Linux host with Docker
Compose v2, a DNS hostname, reachable ports 80/443, and reviewed application code.

The Windows double-click installer is for LOCAL development; no SSL needed there.
The overlay installer deliberately refuses to modify a production-configured
instance. For Linux production, build and test the updated image, verify a cloned
persistent volume, schedule a maintenance window, and deploy via your normal
Docker release process with a rollback image and offline backup.

## Initial deployment

1. Keep your own Python `app/app.py` outside the framework engine.
2. Copy `production/.env.example` to `production/.env`. Set `APP_DOMAIN`,
   `PUBLIC_ORIGIN` (exact `https://...`), and unique 16+ character
   `AI_APP_SERVER_APP_PASSWORD`. Restrict `.env` permissions (`chmod 600`).
3. Run `docker compose --env-file production/.env -f production/compose.yaml build`.
4. Before exposing the service, create the first administrator through the CLI:

   `docker compose --env-file production/.env -f production/compose.yaml run --rm --no-deps ai-app python -m ai_app_server.cli setup-admin /workspace/app/app.py --data-dir /workspace/data`

5. Check all production requirements:

   `docker compose --env-file production/.env -f production/compose.yaml run --rm --no-deps ai-app python -m ai_app_server.cli doctor /workspace/app/app.py --data-dir /workspace/data`

6. Bring it online: `docker compose --env-file production/.env -f production/compose.yaml up -d`.
7. Test HTTPS, administrator login, application gate login, WebSockets, maintenance
   mode, restart recovery, and backup/restore in the target environment.

## Security boundaries

- Caddy terminates TLS. The Python HTTP port is local to the shared network namespace;
  it is not published directly to clients.
- Run applications with an unprivileged user and read-only code volume. Set resource
  limits and protect data and secrets. Containers limit some damage, but **do not**
  make untrusted Python code safe.
- Current application access uses a single shared password; it is not staff-level
  authentication or authorization. Admin login remains separate.
- Never expose local Ollama directly to the internet. Restrict agent file, network
  and external-tool access to only what the project needs.
- Make off-server encrypted backups of the database, config, keys and application
  data; test restoration. The overlay's local snapshot is not disaster recovery.

For background and limitations read `PRODUCTION-SECURITY.md`.
