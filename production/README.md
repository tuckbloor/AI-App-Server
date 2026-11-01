# Production deployment — AI App Server 1.0.2

This is the **production deployment template for trusted, self-hosted Python
applications**, not an unrestricted code-execution hosting service. It requires
real DNS, TLS, administrator setup and operational acceptance tests. Do not use
the Windows one-click development launcher as a production service.

1. Set your own `production/.env` from `.env.example`, using real DNS and a long,
   distinct application password. Keep `.env` outside Git.
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
Production updates use staged, versioned container images. The Windows overlay
updater refuses to modify production-configured installations.
