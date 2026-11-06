# Release notes

## v1.0.5 — Portable installation and user guidance

- Distributable project now has only **two** Windows batch files: `INSTALL.bat` and `START.bat`.
- Windows fresh installer has an editable destination path / directory picker, no hard-coded drive letter, and an isolated virtual environment.
- Launcher provides local background start, stop and status; normal installation enables background startup **after Windows sign-in**.
- Windows Service setup is available separately through optional `pywin32`, with administrator access and dedicated service-account permission checks required. It is not installed by default and has not had end-to-end Windows service acceptance testing.
- Updated README with full source install, desktop shortcut, auto-start, Windows Service, recovery, troubleshooting and upgrade-safety instructions.
- Updated displayed engine version and release metadata to `1.0.5`.
- **No database schema migration** is part of the `1.0.5` version bump. This release's `INSTALL.bat` is for fresh installations only and refuses to overwrite non-empty destinations. Existing installations must use a separately verified upgrade process.
- Automated tests cover core features and portable installation; a real Windows deployment should still be acceptance-tested before production use.

## v1.0.4 — Individual application accounts

- Replaced shared production application password with individual application accounts, password hashes and separate sessions.
- Added Admin → App Users to create, disable and reset application users.
- Preserved separate administrator and application identities.
- Added versioned SQLite schema migration, backing up an existing database before upgrade.
- Production preflight now requires at least one active application user.
- Added `setup-app-user` for production bootstrap.

**Security limitation:** Developer-provided Python and MCP tools are trusted code and are not sandboxed; production deployments require independent review. See `SECURITY-STATUS.md`.
