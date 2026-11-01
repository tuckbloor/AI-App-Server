# AI App Server v1.0.2 — production acceptance, not a certificate

**Supported deployment scope:** a single-organisation, self-hosted Python AI
application operated by trusted developers, with approved read-only MCP tools.
**Not supported as a safe boundary:** anonymous code hosting, untrusted customer
agents/tools, multi-tenant isolation, or public workloads requiring per-user
application permissions. The single application-access password is not an IdP.

## Pre-deployment checks

1. Install on a dedicated Linux host with Docker Engine and Docker Compose v2.
   Put application code in `app/`, keep `data/`, `config/` and `backups/` persistent.
2. Set real `APP_DOMAIN`, `PUBLIC_ORIGIN=https://<host>` and a new 16+ character
   app-access secret in `production/.env`; keep permissions restricted.
3. Run `docker compose --env-file production/.env -f production/compose.yaml config`
   and inspect the output: only ports 80 and 443 should be published.
4. Run `docker compose --env-file production/.env -f production/compose.yaml build`.
   Before starting public traffic, initialise the administrator using the
   documented console command `setup-admin` and run `doctor`.
5. Start with `docker compose --env-file production/.env -f production/compose.yaml up -d`.
   Check `docker compose ... ps` and actual Caddy certificate issuance.
6. Run `python production/verify-deployment.py https://your-real-host` **from a
   different network**. Test admin login and logout, app login/logout, one
   WebSocket event, maintenance mode and explicit MCP deny/allow manually.
7. Restore a complete off-host encrypted snapshot on a separate machine. Do not
   count local snapshots on the same disk as disaster recovery.
8. Independently scan Python dependencies and the image, review least-privilege
   tool code and test denial of unexpected origins, oversized requests and
   unauthorised MCP calls. Review OS and container security patches.

If any mandatory item is incomplete, do not approve internet-facing production.

## Updating production

The Windows overlay is exclusively for local/development installations.
For production, build a version-tagged image and run the new image in a
separate staging stack with a *copy* of persistent data. After acceptance,
back up the production volume off the host, deploy during a maintenance window,
run the post-deploy checks, and retain the prior image and database snapshot for
rollback. SQLite schema changes must be reverted with their matching backup.

**Security disclaimer:** Running trusted Python code inside one container does
not isolate it from other code in that container. Dedicated containers/VMs and
restricted outbound networking are required when a separate trust boundary is
needed. No independent penetration test has been completed by this release.
