# Security status — v1.0.5

## Implemented and tested

- Separate application users and administrator accounts
- Individual salted PBKDF2 password hashes, password reset and account disable
- Immediate application-session revocation when accounts are disabled or reset
- No shared production application password; preflight requires active app user
- Secure / HttpOnly / SameSite application cookies and protected WebSockets
- Origin restrictions and rate limiting on application sign-in
- Versioned SQLite schema migration with a backup before applying it
- Tested regression suite and guarded engine upgrade/rollback rehearsal
- Existing MCP authentication and approved-source checks retained

## NOT yet independently validated or fully protected

- Untrusted Python code / MCP tools are **NOT sandboxed** from server data.
  Deployment MUST only run trusted, reviewed code in separate, least-privileged
  app instances. Do not accept arbitrary Python source uploads.
- Live Docker/HTTPS certificate and reverse-proxy deployment not tested here.
- Independent penetration test and dependency CVE assessment outstanding.
- Off-machine backup restoration and disaster recovery need validation on
  the actual target hosting environment.
- Multi-factor identity provider / enterprise SSO not included.

**Release recommendation:** GitHub security preview for trusted-code
self-hosted development and staging. Do not label this independently
security-approved or suitable for arbitrary untrusted agent hosting.
