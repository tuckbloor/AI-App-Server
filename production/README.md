# AI App Server v0.8.0 — HTTPS production deployment candidate

**Status: production hardening candidate, NOT security-certified or approved for unrestricted public deployment.** This example is a starting point for a trusted, single-application host; it does not sandbox untrusted agents, offer individual application user accounts, or supply enterprise SSO/MFA. Review and test before putting sensitive customer data on it.

## Requirements

Linux with Docker Engine and Docker Compose v2, a real DNS hostname pointing to this host, publicly reachable ports **80 and 443** for certificate issuance, and credentials for each application. The local one-click Windows launcher is **development only**. No SSL is required for that local use.

## Set up once

1. From your installation root, create `app/` and copy `starter/app.py` to `app/app.py` if you do not already have an app. The application is the developer's own trusted Python code and isn't included in engine updates.
2. Copy `production/.env.example` to `production/.env`, set `APP_DOMAIN`, `PUBLIC_ORIGIN=https://that-same-domain`, and a unique `AI_APP_SERVER_APP_PASSWORD` of at least 16 characters. Restrict this file's permissions (`chmod 600 production/.env`). Never commit it. For a real deployment, prefer secrets injected by your infrastructure instead of plaintext environment files.
3. From the project root run `docker compose --env-file production/.env -f production/compose.yaml build`.
4. Create the initial administrator **before bringing the public service online**:

   `docker compose --env-file production/.env -f production/compose.yaml run --rm --no-deps ai-app python -m ai_app_server.cli setup-admin /workspace/app/app.py --data-dir /workspace/data`

   The installer asks for an administrator email, new password and confirmation. The bundled `admin/password` is never accepted as production credentials.
5. Check readiness (all checks must say PASS):

   `docker compose --env-file production/.env -f production/compose.yaml run --rm --no-deps ai-app python -m ai_app_server.cli doctor /workspace/app/app.py --data-dir /workspace/data`

6. Start services:

   `docker compose --env-file production/.env -f production/compose.yaml up -d`

7. Open your **actual** HTTPS domain (not localhost) to verify the application sign-in and admin panel. Configure SMTP if you want self-service forgotten-password emails.

## Security model

- Public port 80 redirects to HTTPS, Caddy obtains TLS certificates for the configured hostname; Python runs as UID 10001, read-only root filesystem, with its own persistent named data volume and no public access to its HTTP port.
- The TLS proxy and app share a network namespace so the Python server can remain bound to `127.0.0.1`.
- Production uses two separate logins: a shared application access secret and server administrator users/roles. For businesses with many staff, add a supported identity provider and per-user authorization before general roll-out.
- **Do not upload or run arbitrary/untrusted Python code.** The framework executes the application under the current account; agent tools may read files or access networks available to that account.
- Keep the OS, container images, Python dependencies and framework patched. Back up the application code, persistent Docker volumes and recovery secrets off-host; test restoration. Engine updates only replace engine code, not data.
- Do not expose Ollama directly to the internet. Carefully review agent tool permissions, model access, and any third-party API policies.
- No agent auto-run, deployment, or security scan is initiated without the developer's action.

## Maintenance / upgrades

Make a consistent backup of the SQLite database and `.secret-key` with `ai-app-server backup` or the administrator backup workflow before upgrade. Stop the production application before replacing its image. Verify the new image and schema against a restored copy of your data before applying it to real users. Do not mount the database into multiple live app containers using the same SQLite file.

**Important:** this Docker Compose production example has not been exercised end-to-end against a real internet DNS/TLS environment in the ChatGPT build environment. Security testing and operations sign-off are required before real-world production deployment.
