AI APP SERVER v0.9.1 - SAFE OVERLAY UPDATE
========================================

NO DELETING. NO MANUAL FILE REPLACEMENT. NO MANUAL BACKUP.

1. Extract this ZIP directly to E:\
2. You will have E:\AI-App-Server-v0.9.1-MCP-OVERLAY
   beside your existing E:\ai-app-server folder.
3. Double-click INSTALL UPDATE.bat inside the OVERLAY folder.
4. The updater handles stopping, backup, engine update, restart and rollback.

IT KEEPS:
- app/ and examples/app.py (your application)
- data/ (SQLite, passwords, settings, secrets)
- config/ (including port)
- logs/ and backups/
- production/.env private credentials

This overlay is specifically for v0.9.0 LOCAL installations.
Never use the desktop updater directly against a live Linux production deployment.

Version 0.9.1 is a production-hardening candidate; independent security and real
infrastructure tests are still needed before public business use.
