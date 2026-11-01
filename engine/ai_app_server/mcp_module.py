"""Opt-in, per-application MCP Streamable HTTP tool endpoint.

Supports MCP 2026-07-28 discovery, tools/list and tools/call using
single-request JSON-RPC responses. It is NOT a general agent runtime,
OAuth authorization server, MCP client, or universal MCP feature implementation.

No tools are registered unless the application author explicitly creates
app/mcp_tools.py and registers trusted functions. MCP is disabled by default.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from .version import __version__

PROTOCOL = "2026-07-28"
MAX_REQUEST = 64 * 1024
MAX_RESULT = 16 * 1024
TOOL_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")


def config_file(data_dir: Path) -> Path:
    return Path(data_dir).resolve() / "mcp.json"


def read_config(data_dir: Path) -> dict:
    path = config_file(data_dir)
    if not path.is_file():
        return {"enabled": False, "token_hash": ""}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            return {"enabled": False, "token_hash": ""}
        digest = content.get("token_hash", "")
        return {"enabled": content.get("enabled") is True and isinstance(digest, str) and len(digest) == 64,
                "token_hash": digest if isinstance(digest, str) else ""}
    except (OSError, ValueError):
        # Fail closed on damaged config; never enable MCP accidentally.
        return {"enabled": False, "token_hash": ""}


def _save(data_dir: Path, setting: dict) -> None:
    directory = Path(data_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = config_file(data_dir)
    fd, temp = tempfile.mkstemp(prefix=".mcp-", suffix=".tmp", dir=directory)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(setting, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def enable(data_dir: Path) -> str:
    """Mint a new bearer credential (display it once to the admin)."""
    token = secrets.token_urlsafe(40)
    _save(data_dir, {"enabled": True, "token_hash": hashlib.sha256(token.encode()).hexdigest()})
    return token


def disable(data_dir: Path) -> None:
    """Revokes existing bearer credential, requiring explicit re-enable."""
    _save(data_dir, {"enabled": False, "token_hash": ""})


def authentic(data_dir: Path, authorization: str) -> bool:
    data = read_config(data_dir)
    if not data["enabled"] or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:]
    if len(token) < 40 or len(token) > 256:
        return False
    return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), data["token_hash"])


class Registry:
    """Explicit list of callable tools belonging ONLY to this application."""
    def __init__(self):
        self.tools = {}

    def tool(self, *, name: str, description: str, input_schema: dict, read_only: bool = True):
        if not TOOL_NAME.fullmatch(name):
            raise ValueError("Invalid MCP tool name")
        if not isinstance(description, str) or not description or len(description) > 500:
            raise ValueError("Provide a short MCP tool description")
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            raise ValueError("Tool input_schema must be a JSON Schema object")
        if not isinstance(input_schema.get("properties", {}), dict):
            raise ValueError("Tool properties must be an object")
        if name in self.tools:
            raise ValueError("Duplicate MCP tool name")
        def decorator(func):
            if not callable(func):
                raise TypeError("MCP tool must be callable")
            self.tools[name] = (func, {"name": name, "description": description,
                "inputSchema": input_schema,
                "annotations": {"readOnlyHint": bool(read_only), "destructiveHint": not bool(read_only)}})
            return func
        return decorator

    def descriptions(self) -> list[dict]:
        return [details for _, details in self.tools.values() if details["annotations"]["readOnlyHint"]]

    async def call(self, name: str, args: dict):
        # This initial module deliberately blocks write-capable tools.
        if name not in self.tools or not self.tools[name][1]["annotations"]["readOnlyHint"]:
            raise LookupError("Unknown or disabled tool")
        func, details = self.tools[name]
        schema = details["inputSchema"]
        if not isinstance(args, dict) or len(args) > 30:
            raise ValueError("Invalid tool arguments")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(required, list) or not set(required).issubset(args):
            raise ValueError("Missing required tool arguments")
        if any(key not in properties for key in args):
            raise ValueError("Unknown tool argument")
        for key, value in args.items():
            definition = properties.get(key)
            if not isinstance(definition, dict):
                raise ValueError("Invalid argument schema")
            kind = definition.get("type")
            matches = {"string":lambda v:isinstance(v, str),
                       "integer":lambda v:isinstance(v, int) and not isinstance(v, bool),
                       "number":lambda v:isinstance(v, (int, float)) and not isinstance(v, bool),
                       "boolean":lambda v:isinstance(v, bool)}
            if kind not in matches or not matches[kind](value):
                raise ValueError("Invalid argument type")
            if kind == "string" and len(value) > min(int(definition.get("maxLength", 4096)), 4096):
                raise ValueError("Tool argument too long")
            if "enum" in definition and value not in definition["enum"]:
                raise ValueError("Invalid option")
        # The author controls these trusted functions. No arbitrary source from MCP clients.
        if inspect.iscoroutinefunction(func):
            result = await asyncio.wait_for(func(**args), timeout=20)
        else:
            from starlette.concurrency import run_in_threadpool
            result = await asyncio.wait_for(run_in_threadpool(func, **args), timeout=20)
        return str(result)[:MAX_RESULT]


def load_tools(script: Path) -> Registry:
    registry = Registry()
    script = Path(script).resolve()
    # Separate application root (not package engine); never load unknown paths from HTTP.
    candidates = [script.parent / "mcp_tools.py", script.parent.parent / "app" / "mcp_tools.py"]
    chosen = next((p for p in candidates if p.is_file()), None)
    if chosen:
        spec = importlib.util.spec_from_file_location("aia_project_mcp_tools", chosen)
        if not spec or not spec.loader:
            raise RuntimeError("Unable to load MCP tools")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not callable(getattr(module, "register_tools", None)):
            raise RuntimeError("mcp_tools.py must export register_tools(registry)")
        module.register_tools(registry)
    return registry


def rpc_result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": {"resultType": "complete", **result}}


def rpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def router_for(app) -> APIRouter:
    router = APIRouter()
    # A developer tool error must not take down the whole web server.
    try:
        app.state.mcp_registry = load_tools(app.state.script)
        app.state.mcp_load_error = False
    except Exception:
        app.state.mcp_registry = Registry()
        app.state.mcp_load_error = True
    app.state.mcp_semaphore = asyncio.Semaphore(4)

    @router.post("/mcp", include_in_schema=False)
    async def mcp_endpoint(request: Request):
        if not authentic(app.state.store.directory, request.headers.get("authorization", "")):
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        # Browsers cannot use MCP cross-origin. Origin-free native clients must use a token.
        origin = request.headers.get("origin")
        if origin:
            expected = (os.environ.get("AI_APP_SERVER_PUBLIC_ORIGIN") or
                        str(request.base_url).rstrip("/"))
            if origin.rstrip("/") != expected.rstrip("/"):
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isascii() or not length.isdecimal():
            return Response(status_code=400)
        if int(length) > MAX_REQUEST:
            return Response(status_code=413)
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return Response(status_code=415)
        content = await request.body()
        if len(content) > MAX_REQUEST:
            return Response(status_code=413)
        try:
            message = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(rpc_error(None, -32700, "Parse error"))
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return JSONResponse(rpc_error(None, -32600, "Invalid request"))
        method = message["method"]
        ident = message.get("id")
        if ident is not None and (isinstance(ident, bool) or not isinstance(ident, (str, int))):
            return JSONResponse(rpc_error(None, -32600, "Invalid request id"))
        if ident is None:
            # No client-to-server notifications in the current HTTP core.
            return Response(status_code=202)
        params = message.get("params", {})
        if not isinstance(params, dict):
            return JSONResponse(rpc_error(ident, -32602, "Invalid params"))
        meta = params.get("_meta", {})
        version = request.headers.get("mcp-protocol-version") or (meta.get("io.modelcontextprotocol/protocolVersion") if isinstance(meta, dict) else None)
        if version and version != PROTOCOL:
            return JSONResponse(rpc_error(ident, -32602, "Unsupported MCP protocol version. Supported: " + PROTOCOL), status_code=400)
        if method == "server/discover":
            return JSONResponse(rpc_result(ident, {"supportedVersions": [PROTOCOL], "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "AI App Server MCP", "version": __version__}}}))
        if method == "ping":
            return JSONResponse(rpc_result(ident, {}))
        if method == "tools/list":
            return JSONResponse(rpc_result(ident, {"tools": app.state.mcp_registry.descriptions()}))
        if method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return JSONResponse(rpc_error(ident, -32602, "Invalid tool request"))
            if name not in {item["name"] for item in app.state.mcp_registry.descriptions()}:
                return JSONResponse(rpc_error(ident, -32602, "Unknown or disabled tool"))
            try:
                async with app.state.mcp_semaphore:
                    text = await app.state.mcp_registry.call(name, arguments)
                response = rpc_result(ident, {"content": [{"type": "text", "text": text}], "isError": False})
            except ValueError:
                response = rpc_result(ident, {"content": [{"type": "text", "text": "Invalid tool arguments"}], "isError": True})
            except Exception:
                # Never leak application secrets or Python stack traces to clients.
                response = rpc_result(ident, {"content": [{"type": "text", "text": "Tool failed. Check application logs."}], "isError": True})
            return JSONResponse(response)
        return JSONResponse(rpc_error(ident, -32601, "Method not found"))

    @router.get("/mcp", include_in_schema=False)
    async def mcp_get():
        # Current Streamable HTTP protocol uses POST. No legacy SSE service.
        return Response(status_code=405, headers={"Allow": "POST"})
    return router
