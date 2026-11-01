# Production security notes for v0.8.0

This release strengthens the production gate; it is **not yet independently audited or certified for public-facing use**.

The admin Service page stores a per-installation environment setting. **Development** allows plain HTTP but binds only to `127.0.0.1`; **Production** refuses to start without a HTTPS origin, TLS proxy declaration, changed administrator password, private application access password and loopback binding. Production browser requests require an HTTPS scheme (direct or trusted proxy-forwarded). Host and WebSocket origins are checked and application errors are redacted.

The production app password is a shared gate, not individual application accounts. Individual identity, SSO/MFA, agent/tool permission boundaries, untrusted Python sandboxing and full deployment pen-testing are **not included**.

See `production/README.md` for a TLS deployment example. Protect the SQLite file, `.secret-key`, backups and SMTP settings; configure your firewall and change the bundled admin password. Do not expose your Ollama endpoint.

Before go-live: perform an independent security review, verify certificate renewals and WSS, check CSP, rate limits and CSRF, run dependency audits, test backup restoration on another host, configure monitoring, and isolate trusted app code with a restricted account.
