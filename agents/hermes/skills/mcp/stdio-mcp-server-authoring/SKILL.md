---
name: stdio-mcp-server-authoring
description: "Use when building or registering local stdio MCP servers."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [mcp, stdio, json-rpc, nixos, tools, registration]
    related_skills: [fastmcp, hermes-agent, mcporter]
---

# Local Stdio MCP Server Authoring & Registration

Build zero-dependency Python stdlib MCP servers over JSON-RPC 2.0 stdio transport and register them non-interactively into Hermes.

## When to Use

- Adding new tool capabilities to Hermes via local stdio MCP servers on NixOS or PEP 668 systems where `pip` is unavailable in the system Python.
- Wrapping local CLI scripts, desktop utilities, or domain logic as first-class MCP tools without external venvs or third-party SDK dependencies.
- Registering and testing MCP servers from non-interactive shell commands.

## Included Files

- `templates/stdlib_mcp_server.py` — Zero-dependency Python 3 stdlib JSON-RPC 2.0 (`2024-11-05`) stdio MCP server starter template.

## Procedure

### 1. Implement the Stdio JSON-RPC Loop with Python Stdlib

Start from `templates/stdlib_mcp_server.py` and place the executable script in `/home/aesc/.local/lib/<server_name>.py`:

1. Read line-delimited JSON-RPC 2.0 messages from `sys.stdin` (`for raw_line in sys.stdin:`) and write single-line JSON responses to `sys.stdout` with `flush=True`.
2. Handle the required MCP methods:
   - `initialize`: Return `protocolVersion: "2024-11-05"`, `capabilities: {"tools": {}}`, and `serverInfo: {"name": ..., "version": ...}`.
   - `notifications/initialized` (or any method without `"id"`): Return `None` (emit no response line for notifications).
   - `ping`: Return `{}`.
   - `tools/list`: Return `{"tools": TOOLS}` where each entry has `name`, `description`, and a JSON Schema `inputSchema`.
   - `tools/call`: Extract `params["name"]` and `params.get("arguments", {})`, execute the tool handler, and return `{"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}`.
3. Never print debug logs to `stdout` inside a stdio MCP server or subprocess — `stdout` carries the JSON-RPC wire protocol. Route any diagnostic logging to `sys.stderr` and always pass `capture_output=True` to `subprocess.run`.

### 2. Validate Syntax and Exercise Tool Handlers Directly

Before registering the server in Hermes, test the class directly in Python to catch missing stdlib imports (`urllib.parse`, `shutil`, etc.) that only trigger inside specific tool branches:

```bash
chmod +x /home/aesc/.local/lib/<server_name>.py
/run/current-system/sw/bin/python3 -c "
import sys; sys.path.insert(0, '/home/aesc/.local/lib')
from <server_name> import ServerClass
srv = ServerClass()
print(srv.call_tool('<tool_name>', {}))
"
```

### 3. Register Non-Interactively with `hermes mcp add`

Pipe `yes` into `hermes mcp add` when registering from a non-interactive shell — `hermes mcp add` discovers the tools and prompts `Enable all N tools? [Y/n/select]:`, which aborts with `Cancelled.` on EOF if stdin is closed:

```bash
yes | hermes mcp add <server-slug> \
  --command /run/current-system/sw/bin/python3 \
  --args /home/aesc/.local/lib/<server_name>.py
```

### 4. Verify Handshake and Tool Discovery

Run `hermes mcp test` and `hermes mcp list` to confirm the server starts cleanly, completes the MCP handshake, and is enabled in `/home/aesc/.hermes/config.yaml`:

```bash
hermes mcp test <server-slug>
hermes mcp list
```

### 5. Updating Hermes Config Keys (`hermes config set`)

Direct file edits (`write_file` / `patch`) to `/home/aesc/.hermes/config.yaml` are refused by Hermes's security guard. Always use the CLI to set model aliases or config keys:

```bash
hermes config set model.aliases.lite "agy-rotator/gemini-3.1-flash-lite"
hermes config set model.aliases.flash "aistudio2api/gemini-3.8-flash"
```

### 6. Low-Latency Local LLM Endpoint Cascade Pitfalls

When building MCP tools or background chat responders that call local OpenAI-compatible endpoints (`127.0.0.1:8045`, `127.0.0.1:2048`, `127.0.0.1:8765`):
- Prefer the persistent HTTP proxy pool (`http://127.0.0.1:8045/v1/chat/completions` with `gemini-3.1-flash-lite` or `gemini-3.8-flash-low`) over the CLI-spawning bridge (`http://127.0.0.1:8765/v1/chat/completions`) — port 8765 spawns a fresh `agy` process per turn (~5.7s), whereas port 8045 responds in ~1.3s.
- Do not route instruction-following chat prompts to `tab_flash_lite_preview` — it is a tab-completion model that prematurely outputs `IGNORE` on system prompts with selective-response rules.
- Set `max_tokens >= 256` on Gemini 3.x / Gemma 4 local endpoints — low budgets (`50`–`90` tokens) get exhausted by internal thinking tokens and return an empty string `""`.
- In multi-endpoint fallback loops, `continue` to the next endpoint when `content` is empty (`if not ans: continue`) before checking sentinel strings like `IGNORE`.
