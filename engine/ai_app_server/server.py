"""Python app server. Production supports only trusted application source code."""
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .storage import Store, verify_password
from .app_security import validate_production, configured_origin, request_ip
from .admin import admin_router
import os
from fastapi.responses import HTMLResponse, JSONResponse
from .runner import render
from .service import service_name
import asyncio
import json
import secrets
import time
import hmac
import logging
from urllib.parse import urlsplit

logger = logging.getLogger("ai_app_server.security")

MAINTENANCE_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Scheduled maintenance</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:28px;font-family:Inter,Segoe UI,Arial,sans-serif;color:#20335a;background:radial-gradient(circle at 85% 10%,#dfeaff 0%,transparent 40%),linear-gradient(145deg,#f8fbff,#e9f1ff)}
.shell{width:min(100%,980px);overflow:hidden;border:1px solid #d5e3f9;background:#ffffffeb;border-radius:28px;box-shadow:0 30px 90px #476a9e25;display:grid;grid-template-columns:1fr 1fr;align-items:center;padding:46px;gap:12px}
.brand{display:flex;align-items:center;gap:12px;color:#265ed3;font-size:14px;font-weight:800;letter-spacing:.03em}.brand i{width:35px;height:35px;background:#2867e9;border-radius:11px;color:white;display:grid;place-items:center;font-size:20px;font-style:normal}
h1{font-size:clamp(32px,4vw,52px);letter-spacing:-.045em;line-height:1.08;margin:45px 0 22px}p{font-size:17px;line-height:1.75;color:#63738f;max-width:440px}.pill{display:inline-flex;align-items:center;gap:7px;background:#e9f1ff;color:#2561c9;padding:9px 13px;border-radius:999px;font-size:13px;font-weight:750}
.dot{width:7px;height:7px;border-radius:50%;background:#2d6df5}.art{width:100%;height:auto}.bottom{margin-top:45px;font-size:12px;color:#8490a5}
@media(max-width:720px){.shell{grid-template-columns:1fr;padding:26px}.art{max-height:220px}h1{margin-top:30px}}
</style></head><body><main class="shell"><div><div class="brand"><i>✦</i><span id="brand">AI APP SERVER</span></div><h1>Sorry, down for<br>maintenance.</h1><p id="message">We're making improvements and will be back shortly.</p><span class="pill"><span class="dot"></span>We'll be back soon</span><div class="bottom">Thank you for your patience.</div></div><img class="art" src="/static/maintenance.svg" alt="Illustration of servers being maintained"></main></body></html>"""


def create_app(script: Path, *, data_dir: Path | None = None,
               mode: str = "development", secure_cookies: bool = False,
               local_only: bool = True) -> FastAPI:
    script = Path(script).resolve()
    app = FastAPI(title="AI App Server", docs_url=None, redoc_url=None, openapi_url=None)
    static_dir = Path(__file__).parent / "static"
    app.state.store = Store(data_dir if data_dir is not None else script.parent / ".ai-app-server" / "data")
    app.state.script = script
    app.state.mode = mode
    app.state.secure_cookies = secure_cookies or mode == "production"
    app.state.local_only = local_only
    app.state.active_ws = 0
    app.state.production = mode == "production"
    if app.state.production:
        validate_production(app.state.store, local_only=local_only)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        # Prevent Host-header poisoning and browser DNS-rebinding, including on local installs.
        host = request.headers.get('host', '').lower().split(':')[0]
        if app.state.production:
            allowed_host = urlsplit(configured_origin()).netloc.lower()
            if request.headers.get("host", "").lower() != allowed_host:
                return JSONResponse({"detail":"Unrecognized host"}, status_code=400)
            # TLS terminates at the trusted loopback reverse proxy. It must set
            # X-Forwarded-Proto itself and overwrite any client-supplied value.
            if request.url.scheme != 'https' and request.headers.get('x-forwarded-proto', '').lower() != 'https':
                return JSONResponse({"detail":"HTTPS is required"}, status_code=400)
        elif host not in ('127.0.0.1', 'localhost', '[::1]', 'testserver'):
            return JSONResponse({"detail":"Development server is localhost only"}, status_code=400)
        # Admin API requests are same-origin; state-changing authenticated requests also require CSRF.
        if (request.url.path.startswith("/api/admin/") or request.url.path.startswith("/api/app/")) and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            allowed_origin = os.getenv("AI_APP_SERVER_PUBLIC_ORIGIN") or str(request.base_url).rstrip("/")
            if (origin and origin != allowed_origin) or (app.state.production and origin != allowed_origin):
                return JSONResponse({"detail":"Origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.state.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path == "/app-login":
            response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        elif request.url.path.startswith("/admin") or request.url.path.startswith("/static/admin"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return response

    from .mcp_module import router_for
    app.include_router(router_for(app))
    app.include_router(admin_router())
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def admin_page():
        return FileResponse(static_dir / "admin.html", media_type="text/html")

    @app.get("/app-login", include_in_schema=False)
    async def app_login_page():
        if not app.state.production:
            return Response(status_code=404)
        return FileResponse(static_dir / "app-login.html", media_type="text/html")

    @app.post("/api/app/login")
    async def application_login(request: Request):
        if not app.state.production:
            raise HTTPException(404, "App login is not enabled")
        client_ip = request_ip(request)
        if request.headers.get('content-length', '0').isdigit() and int(request.headers.get('content-length', '0')) > 4096:
            raise HTTPException(413, 'Request too large')
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(400, 'Invalid JSON payload')
        username = payload.get('username', '') if isinstance(payload, dict) else ''
        password = payload.get('password', '') if isinstance(payload, dict) else ''
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 60 or len(password) > 256:
            raise HTTPException(400, 'Invalid login details')
        identity = f'app:{client_ip}:{username.casefold()}'
        # Also rate-limit by source IP across usernames to resist account enumeration.
        source_identity = f'app-ip:{client_ip}'
        if app.state.store.login_blocked(identity) or app.state.store.login_blocked(source_identity):
            raise HTTPException(429, 'Too many login attempts; try again later')
        user = app.state.store.app_user_by_name(username)
        if not user or not user['is_active'] or not verify_password(password, user['password_hash']):
            app.state.store.login_failed(identity)
            app.state.store.login_failed(source_identity)
            raise HTTPException(401, 'Invalid username or password')
        app.state.store.clear_login_failures(identity)
        app.state.store.clear_login_failures(source_identity)
        token = app.state.store.create_app_session(user['id'])
        response = JSONResponse({"ok": True})
        response.set_cookie("aia_app_session", token, httponly=True, secure=True,
                            samesite="strict", max_age=8 * 3600, path="/")
        return response

    @app.post("/api/app/logout")
    async def application_logout(request: Request):
        app.state.store.revoke_app_session(request.cookies.get("aia_app_session", ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie("aia_app_session", path="/")
        return response

    @app.get("/", include_in_schema=False)
    async def homepage(request: Request):
        store = app.state.store
        if app.state.production and not store.valid_app_session(request.cookies.get("aia_app_session", "")):
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/app-login", status_code=303)
        if store.maintenance_on():
            opts = store.settings()
            from html import escape
            content = MAINTENANCE_PAGE.replace("AI APP SERVER", escape(opts.get("app_title", "AI App Server")))
            content = content.replace("We're making improvements and will be back shortly.",
                                      escape(opts.get("maintenance_message") or "We're making improvements and will be back shortly."))
            return HTMLResponse(content, status_code=503, headers={"Retry-After":"600"})
        return FileResponse(static_dir / "app.html", media_type="text/html")

    @app.get("/health")
    async def health():
        if app.state.production:
            return {"status": "ok"}
        return {"status":"ok", "script":script.name, "app_id":service_name(script), "maintenance":app.state.store.maintenance_on()}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        origin = ws.headers.get("origin", "")
        if app.state.production and ws.headers.get('host', '').lower() != urlsplit(configured_origin()).netloc.lower():
            await ws.close(code=1008)
            return
        if not app.state.production and ws.headers.get('host', '').split(':')[0].lower() not in ('127.0.0.1', 'localhost', '[::1]', 'testserver'):
            await ws.close(code=1008)
            return
        if app.state.production:
            if (not origin or origin != configured_origin() or
                    not app.state.store.valid_app_session(ws.cookies.get("aia_app_session", ""))):
                await ws.close(code=1008)
                return
        if app.state.active_ws >= 24:
            await ws.close(code=1013)
            return
        host = ws.headers.get("host", "")
        allowed_origin = os.getenv("AI_APP_SERVER_PUBLIC_ORIGIN")
        if origin and origin not in ((allowed_origin,) if allowed_origin else (f"http://{host}", f"https://{host}")):
            await ws.close(code=1008)
            return
        if app.state.store.maintenance_on():
            await ws.close(code=1013)
            return
        await ws.accept()
        app.state.active_ws += 1
        values = {}
        session = {}  # Isolated from other browser connections.
        burst_start = time.monotonic()
        messages_in_window = 0
        try:
            while True:
                if app.state.production and not app.state.store.valid_app_session(ws.cookies.get("aia_app_session", "")):
                    await ws.close(code=1008)
                    return
                if app.state.store.maintenance_on():
                    await ws.close(code=1013)
                    return
                try:
                    components = await asyncio.to_thread(render, script, values.copy(), session=session)
                    await ws.send_json({"components":components})
                except Exception as exc:
                    logger.exception('Application render failed')
                    await ws.send_json({"error": "Application execution failed. Contact the administrator." if app.state.production else f"{type(exc).__name__}: {exc}"})
                try:
                    message = await asyncio.wait_for(ws.receive_json(), timeout=1800)
                except asyncio.TimeoutError:
                    await ws.close(code=1001)
                    return
                except (ValueError, json.JSONDecodeError):
                    await ws.close(code=1003)
                    return
                now = time.monotonic()
                if now - burst_start >= 2.0:
                    burst_start, messages_in_window = now, 0
                messages_in_window += 1
                if messages_in_window > 12:
                    await ws.close(code=1008)
                    return
                if not isinstance(message, dict) or not isinstance(message.get("values"), dict):
                    await ws.send_json({"error":"Invalid widget message"})
                    continue
                if len(json.dumps(message)) > 65536 or len(message["values"]) > 100:
                    await ws.close(code=1009)
                    return
                values = message["values"]
        except WebSocketDisconnect:
            pass
        finally:
            app.state.active_ws -= 1
    return app
