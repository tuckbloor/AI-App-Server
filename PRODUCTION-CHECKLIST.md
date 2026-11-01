# AI App Server 0.9.2 — Production acceptance checklist

Status: release candidate; NOT a third-party security certification.

1. Review the actual application source and every `mcp_tools.py` function.
   `read_only=True` is descriptive, not a sandbox. Never run untrusted plugins.
2. Configure real HTTPS with Caddy, firewall 80/443, and prevent direct access
   to the Python port. Confirm TLS renewals and reverse proxy forwarding.
3. Use terminal-only admin setup, unique app password, verified recovery email,
   strong SMTP credentials and restricted persistent storage permissions.
4. Enable MCP only when needed; keep token in an external secret store,
   restrict client access, test token revocation, and approve tool source.
5. Test 401/403 responses for anonymous and cross-origin browser requests,
   WebSocket auth, MCP version/header and large-body rejection.
6. Run dependency and image vulnerability scanners and address all high/critical
   findings before external access. Pin reviewed dependencies for deployment.
7. Test database, encryption key, config and application restore from OFF-HOST
   backups. Verify rollback at the running system level.
8. Validate production traffic, restart, memory/CPU quotas, logs and alerts
   on an actual Linux/Windows target. Perform an independent security review.
9. Do not expose the framework to public users until controls above are
   independently demonstrated. Multi-user per-user identity and untrusted tool
   sandboxing are OUT OF SCOPE for this version.
