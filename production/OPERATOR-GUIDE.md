# AI App Server — operator essentials (v1.0.2)

Use the private development installer for Windows. To deploy on a business Linux
host, use production/README.md and ACCEPTANCE.md. Manage passwords and backup
keys in a secret manager. Each installed application has separate data/config,
ports and administration. MCP is OFF by default. Approve the SHA-256 of trusted
MCP tool source explicitly before enabling it in production.

**Upgrades:** first validate against disposable cloned data; deploy a versioned
image, test HTTPS and app login; only then switch production. Keep the prior
image and a verified off-host SQLite/key/config/application snapshot together.
**Limitations:** no isolated execution of untrusted agent scripts; no individual
application-user accounts or SSO; no independent pentest certification.
