#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export AI_APP_SERVER_DATA_DIR="$PWD/data"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python tools/bootstrap.py
.venv/bin/python -m pip install -e engine
if [ -f examples/app.py ]; then APP_SCRIPT=examples/app.py; else APP_SCRIPT=app/app.py; fi
exec .venv/bin/python -m ai_app_server.cli run "$APP_SCRIPT" --data-dir "$AI_APP_SERVER_DATA_DIR"
