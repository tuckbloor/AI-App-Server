# MCP module — AI App Server v0.9.1

This module is **optional** and **disabled by default**. MCP configuration is saved in the application's existing `data/mcp.json` folder (outside `engine/`) and is preserved by later updates. The access token is shown **once** in the administration screen and stored as a SHA-256 digest, not in plaintext.

## Use it

1. Run your AI App Server normally, then sign in to `/admin`.
2. Open **MCP**. It shows your app's endpoint, its registered tools, and a button to enable MCP.
3. Create your custom tool file at `<installation-folder>\app\mcp_tools.py` (or `mcp_tools.py` next to your own Python app script). Tools are loaded when the app server starts. Restart once after adding or changing tools.
4. Select **Enable MCP and create token**, then copy the token immediately. No app data or administrator passwords are affected.
5. Configure your compatible MCP client to use `http://127.0.0.1:<your-port>/mcp` with `Authorization: Bearer YOUR_TOKEN`. For remote access you **must use HTTPS** and properly configured production security.

## Example custom tool file

```python
# app/mcp_tools.py  -- all tools are intentionally opt-in

def register_tools(registry):
    @registry.tool(
        name="welcome_message",
        description="Generate a simple welcome message",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string", "maxLength": 80}},
            "required": ["name"],
            "additionalProperties": False,
        },
    )
    def welcome_message(name: str) -> str:
        return f"Hello, {name}!"
```

### How it works

* MCP 2026-07-28 **Streamable HTTP, JSON-response subset**: `server/discover`, `tools/list`, `tools/call`, `ping` over POST `/mcp`.
* The module uses the existing application server port. No second process, extra installation, new Python dependency, or global agent registry.
* No tools are registered by default. The admin view shows registered tools but doesn't let random users create arbitrary Python source.
* The server accepts authenticated native clients without an Origin header, and rejects browser origins outside its own origin.
* Only tools declared `read_only=True` (default) are advertised and callable. All mutating tools are blocked in this release. This is not a security sandbox: functions run as your server's Python account. **Do not register untrusted code.**
* It is **not** the entire MCP protocol: OAuth discovery, prompts, resources, progress/SSE streams, tool-level identity, and older protocol versions aren't implemented yet. Not tested with external vendor clients in this environment. Use SDK-backed implementation for complete interoperability before public deployment.
* Use the Admin **Disable MCP** action to revoke the credential. **Rotate token** also invalidates the old credential immediately.

## Client test example (PowerShell)

```powershell
$token = 'YOUR_TOKEN_HERE'
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json, text/event-stream'; 'MCP-Protocol-Version' = '2026-07-28' }
$body = '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'
Invoke-RestMethod -Uri 'http://127.0.0.1:8501/mcp' -Method POST -ContentType 'application/json' -Headers $headers -Body $body
```

Check `tools/list` and `tools/call` after you add tools. Avoid putting access tokens in GitHub, command history, logs or application source.

## Upgrade notes

v0.9.1 overlay updates only `engine/`, specific documentation and tests. It does not overwrite `app/`, `config/` or `data/`. The installer backs up SQLite, encryption key, hosting settings and existing MCP configuration before changing anything. It will refuse to update a production-configured installation using the local overlay.


## v0.9.2 production policy

- Disabled MCP does not import `mcp_tools.py`.
- The local module is not a sandbox and must contain only reviewed, trusted code.
- On production deployments, set `AI_APP_SERVER_MCP_TOOLS_APPROVED=1` only
  after reviewing the exact file and configuring container restrictions.
- Native production MCP clients must send both protocol version header and
  matching `_meta` field, and advertise JSON and SSE Accept types.
- Rate limits and max body sizes apply. Keep an edge proxy rate limiter too.


SECURITY: A readOnlyHint is only metadata; it does not sandbox Python.
Run only trusted, reviewed application tools. MCP token access is powerful.
