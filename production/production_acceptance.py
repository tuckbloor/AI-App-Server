"""Local production-environment checks. Complements external TLS probe.

Run only in deployment/staging; never modifies the application database.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def validate(environment: dict, compose_file: Path) -> list[tuple[str, bool]]:
    origin = environment.get('AI_APP_SERVER_PUBLIC_ORIGIN','')
    parsed = urlsplit(origin)
    password = environment.get('AI_APP_SERVER_APP_PASSWORD', '')
    compose = compose_file.read_text(encoding='utf8')
    checks = [
      ('Exact HTTPS hostname', parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
       and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment),
      ('Reverse-proxy declaration', environment.get('AI_APP_SERVER_BEHIND_TLS_PROXY') == '1'),
      ('Unique application secret configured', len(password) >= 16 and password not in ('password', 'changeme')
       and 'replace' not in password.lower()),
      ('Container drop-all Linux capabilities', 'cap_drop: [ALL]' in compose),
      ('Container no-new-privileges', 'no-new-privileges:true' in compose),
      ('Persistent SQLite state volume', 'aiapp_data:/workspace/data' in compose),
      ('No publicly exposed Python HTTP port', '8501:8501' not in compose and '0.0.0.0:8501' not in compose),
      ('HTTPS reverse proxy included', 'caddy:' in compose and '443:443' in compose),
    ]
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--compose', type=Path, default=Path(__file__).with_name('compose.yaml'))
    args = parser.parse_args(argv)
    checks = validate(os.environ, args.compose)
    for name, passed in checks:
        print(('PASS: ' if passed else 'FAIL: ') + name)
    return 0 if all(ok for _,ok in checks) else 2

if __name__ == '__main__':
    raise SystemExit(main())
