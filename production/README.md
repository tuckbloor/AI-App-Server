# Production deployment — AI App Server 1.0.5

This is the **production deployment template for trusted, self-hosted Python
applications**, not an unrestricted code-execution hosting service. It requires
real DNS, TLS, administrator setup and operational acceptance tests. Do not use
the Windows one-click development launcher as a production service.

1. Set your own `production/.env` from `.env.example`, using real DNS and
   HTTPS origin. Store application accounts in SQLite. Keep `.env` outside Git.
2. Start a Linux Docker Compose staging stack, set the first admin with
   `python -m ai_app_server.cli setup-admin /workspace/app/app.py --data-dir /workspace/data`
   through `docker compose run --rm --no-deps ai-app ...` and run `doctor`.
3. Deploy Caddy TLS proxy with `docker compose --env-file production/.env -f production/compose.yaml up -d`.
4. Run `python production/verify-deployment.py https://your-host` externally.
   Run `python production/production_acceptance.py` with the same production
   environment variables to check deployment configuration.
5. Test application login, administrator permissions, WebSockets, MCP token
   denial and approval, maintenance, restart recovery and off-host restore.

Read **ACCEPTANCE.md** for the required acceptance checklist and limitations.
Production updates use staged, versioned container images. Do not use the Windows fresh installer to upgrade a production deployment.


### Individual application users (v1.0.4)

Before production startup, create at least one application account. It is **not**
 an administrator. Run the one-time terminal setup in the container with the
persistent data volume mounted, for example:

```bash
docker compose --env-file .env run --rm --no-deps ai-app \
  python -m ai_app_server.cli setup-app-user /workspace/app/app.py --data-dir /workspace/data
```

The initial administrator is created with `setup-admin`, also before production
startup. Use **Admin → App Users** to add, disable or reset application accounts.
Application user sessions are separate from admin sessions. Existing v1.0.3
shared-password sessions are revoked automatically during the SQLite migration.

**Security scope:** Only run developer-reviewed Python application scripts and MCP
tools. Tools run inside the application process; there is currently **no sandbox
between arbitrary Python code and the application's SQLite/control-plane data**.
Do not host untrusted user-submitted Python code in this deployment.
