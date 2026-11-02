#!/usr/bin/env python3
"""Zero-dependency stdlib MCP server template over stdio (JSON-RPC 2.0 / MCP 2024-11-05)."""

from __future__ import annotations

import json
import sys
from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "example_echo",
        "description": "Echo back the provided message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"}
            },
            "required": ["message"],
        },
    }
]


def _ok(payload: Any) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps({"error": msg}, ensure_ascii=False)}], "isError": True}


class StdlibMcpServer:
    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        try:
            if name == "example_echo":
                return _ok({"echo": args["message"]})
            return _err(f"Unknown tool: {name}")
        except Exception as exc:
            return _err(str(exc))

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stdlib-mcp-server", "version": "1.0.0"},
                },
            }
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            result = self.call_tool(str(params.get("name") or ""), dict(params.get("arguments") or {}))
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        if msg_id is not None:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return None


def main() -> int:
    server = StdlibMcpServer()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}), flush=True)
            continue
        resp = server.handle_message(msg)
        if resp is not None:
            print(json.dumps(resp), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
