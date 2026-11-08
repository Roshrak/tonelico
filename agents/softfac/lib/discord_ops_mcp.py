#!/usr/bin/env python3
"""MCP server for Discord Desktop GUI Control, Webhooks, Bot REST API v10, Rich Embeds, and Telegram Bridge."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _ok(data: Any) -> dict:
    text = json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": msg}]}


def _get_bot_token(override: str | None = None) -> str:
    if override:
        return override
    tok = os.environ.get("DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_TOKEN") or ""
    if not tok:
        env_file = Path("/home/aesc/.hermes/.env")
        if env_file.exists():
            for ln in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.startswith("DISCORD_BOT_TOKEN=") or ln.startswith("DISCORD_TOKEN="):
                    tok = ln.split("=", 1)[1].strip().strip("\"'")
                    break
    return tok


def _discord_api(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    tok = _get_bot_token(token)
    if not tok:
        raise RuntimeError("DISCORD_BOT_TOKEN not set in environment or ~/.hermes/.env")
    url = f"https://discord.com/api/v10{path}"
    headers = {
        "Authorization": f"Bot {tok}",
        "User-Agent": "DiscordBot (https://hermes-agent.nousresearch.com, 1.0)",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if raw else {"status": resp.status}


class DiscordOpsMcpServer:
    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "discord_app_status",
                "description": "Check whether the Discord / Vesktop desktop client is running and inspect its process and window state.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "discord_app_launch_or_focus",
                "description": "Launch Discord desktop client detached in background (or focus existing window reuse-first).",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "discord_app_close",
                "description": "Close the Discord desktop client cleanly and verify termination.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "discord_app_send_quick_message",
                "description": "Type and send a message into the focused Discord desktop window (optionally switching channel via Ctrl+K first).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_Jump": {"type": "string", "description": "Optional channel/user name to jump to via Ctrl+K"},
                        "message": {"type": "string", "description": "Message text to send"},
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "discord_app_read_screen",
                "description": "Capture the active desktop screen and run PaddleOCR to read visible Discord chat messages.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "discord_webhook_send",
                "description": "Send a message or rich embed to a Discord Webhook URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "webhook_url": {"type": "string"},
                        "content": {"type": "string"},
                        "username": {"type": "string"},
                        "embeds": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["webhook_url"],
                },
            },
            {
                "name": "discord_webhook_send_file",
                "description": "Upload a file attachment (PDF, DOCX, PNG chart, OCR transcript) to a Discord Webhook URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "webhook_url": {"type": "string"},
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["webhook_url", "file_path"],
                },
            },
            {
                "name": "discord_bot_get_me",
                "description": "Query Discord API /users/@me to verify bot user identity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "token": {"type": "string", "description": "Optional override DISCORD_BOT_TOKEN"},
                    },
                },
            },
            {
                "name": "discord_bot_list_guilds",
                "description": "List all Discord servers (guilds) accessible to the bot token.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "discord_bot_list_channels",
                "description": "List all channels in a Discord guild.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "guild_id": {"type": "string"},
                    },
                    "required": ["guild_id"],
                },
            },
            {
                "name": "discord_bot_read_messages",
                "description": "Fetch recent messages from a Discord channel via REST API v10.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string"},
                        "limit": {"type": "integer", "description": "Number of messages (1-100, default 25)"},
                    },
                    "required": ["channel_id"],
                },
            },
            {
                "name": "discord_bot_send_message",
                "description": "Send a text message or rich embed to a Discord channel via REST API v10.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string"},
                        "content": {"type": "string"},
                        "embed": {"type": "object"},
                        "reply_to_message_id": {"type": "string"},
                    },
                    "required": ["channel_id", "content"],
                },
            },
            {
                "name": "discord_bot_search_messages",
                "description": "Fetch and filter Discord channel messages by author username or keyword.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string"},
                        "query": {"type": "string"},
                        "author": {"type": "string"},
                    },
                    "required": ["channel_id"],
                },
            },
            {
                "name": "discord_bot_manage_thread",
                "description": "Create a new thread in a Discord channel or archive/unarchive an existing thread.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel_id": {"type": "string"},
                        "thread_name": {"type": "string"},
                        "auto_archive_duration": {"type": "integer", "description": "60, 1440, 4320, or 10080 minutes"},
                    },
                    "required": ["channel_id", "thread_name"],
                },
            },
            {
                "name": "discord_format_embed_json",
                "description": "Construct a validated Discord Rich Embed object with title, description, color hex, and fields.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "color_hex": {"type": "string", "description": "Hex color e.g. #5865F2"},
                        "fields": {"type": "array", "items": {"type": "object"}},
                        "footer": {"type": "string"},
                    },
                    "required": ["title", "description"],
                },
            },
            {
                "name": "discord_telegram_bridge_send",
                "description": "Broadcast a notification or document summary to both Telegram (telegram_send.py) and a Discord Webhook/Channel.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "discord_webhook_url": {"type": "string"},
                        "discord_channel_id": {"type": "string"},
                    },
                    "required": ["message"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> dict:
        try:
            if name == "discord_app_status":
                ps = subprocess.run(["pgrep", "-af", "Discord|discord|vesktop|webcord"], capture_output=True, text=True, timeout=5)
                procs = [ln for ln in ps.stdout.splitlines() if "discord_ops_mcp" not in ln and "pgrep" not in ln]
                bin_path = shutil.which("discord") or shutil.which("vesktop") or "/run/current-system/sw/bin/discord"
                return _ok({
                    "running": len(procs) > 0,
                    "process_count": len(procs),
                    "processes": procs[:15],
                    "discord_binary": bin_path if Path(bin_path).exists() else None,
                })

            elif name == "discord_app_launch_or_focus":
                status = json.loads(self.call_tool("discord_app_status", {})["content"][0]["text"])
                if not status["running"]:
                    bin_path = status.get("discord_binary") or "discord"
                    subprocess.Popen(f"nohup {bin_path} >/dev/null 2>&1 &", shell=True)
                    time.sleep(1.5)
                return self.call_tool("discord_app_status", {})

            elif name == "discord_app_close":
                subprocess.run("pkill -f 'Discord|vesktop|webcord' || true", shell=True, timeout=5)
                time.sleep(0.4)
                return self.call_tool("discord_app_status", {})

            elif name == "discord_app_send_quick_message":
                wtype_matches = sorted(Path("/nix/store").glob("*-wtype-*/bin/wtype"))
                wtype = shutil.which("wtype") or (str(wtype_matches[-1]) if wtype_matches else None)
                uinput = Path("/home/aesc/.local/bin/uinput_type")
                if wtype:
                    if args.get("channel_Jump"):
                        subprocess.run([wtype, "-M", "ctrl", "-k", "k", "-m", "ctrl"], timeout=5)
                        time.sleep(0.3)
                        subprocess.run([wtype, args["channel_Jump"], "-k", "Return"], timeout=5)
                        time.sleep(0.4)
                    res = subprocess.run([wtype, args["message"], "-k", "Return"], timeout=5)
                    return _ok({"method": "wtype", "sent": args["message"], "exit_code": res.returncode})
                if uinput.exists():
                    tokens = [f"type:{args['message']}", "sleep:150", "enter"]
                    res = subprocess.run([str(uinput), *tokens], timeout=10)
                    return _ok({"method": "uinput_type", "sent": args["message"], "exit_code": res.returncode})
                return _err("Neither wtype nor uinput_type found")

            elif name == "discord_app_read_screen":
                from desktop_computer_use_mcp import DesktopComputerUseMcpServer
                return DesktopComputerUseMcpServer().call_tool("cu_screenshot_ocr", {})

            elif name == "discord_webhook_send":
                payload: Dict[str, Any] = {}
                if args.get("content"):
                    payload["content"] = args["content"]
                if args.get("username"):
                    payload["username"] = args["username"]
                if args.get("embeds"):
                    payload["embeds"] = args["embeds"]
                req = urllib.request.Request(
                    args["webhook_url"],
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", "User-Agent": "HermesAgent/2.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return _ok({"status": resp.status, "sent": True})

            elif name == "discord_webhook_send_file":
                fpath = Path(args["file_path"]).expanduser().resolve()
                if not fpath.exists():
                    return _err(f"File not found: {fpath}")
                boundary = f"----HermesBoundary{uuid.uuid4().hex}"
                mime = mimetypes.guess_type(fpath.name)[0] or "application/octet-stream"
                body = bytearray()
                if args.get("content"):
                    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"content\"\r\n\r\n{args['content']}\r\n".encode("utf-8"))
                body.extend(
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fpath.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8")
                )
                body.extend(fpath.read_bytes())
                body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
                req = urllib.request.Request(
                    args["webhook_url"],
                    data=bytes(body),
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "HermesAgent/2.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return _ok({"status": resp.status, "uploaded": str(fpath)})

            elif name == "discord_bot_get_me":
                return _ok(_discord_api("GET", "/users/@me", token=args.get("token")))

            elif name == "discord_bot_list_guilds":
                return _ok(_discord_api("GET", "/users/@me/guilds"))

            elif name == "discord_bot_list_channels":
                return _ok(_discord_api("GET", f"/guilds/{args['guild_id']}/channels"))

            elif name == "discord_bot_read_messages":
                limit = max(1, min(100, int(args.get("limit", 25))))
                return _ok(_discord_api("GET", f"/channels/{args['channel_id']}/messages?limit={limit}"))

            elif name == "discord_bot_send_message":
                payload: Dict[str, Any] = {"content": args["content"]}
                if args.get("embed"):
                    payload["embeds"] = [args["embed"]]
                if args.get("reply_to_message_id"):
                    payload["message_reference"] = {"message_id": args["reply_to_message_id"]}
                return _ok(_discord_api("POST", f"/channels/{args['channel_id']}/messages", body=payload))

            elif name == "discord_bot_search_messages":
                msgs = _discord_api("GET", f"/channels/{args['channel_id']}/messages?limit=100")
                q = args.get("query", "").lower()
                auth = args.get("author", "").lower()
                filtered = []
                for m in msgs if isinstance(msgs, list) else []:
                    c_ok = (not q) or (q in str(m.get("content", "")).lower())
                    a_ok = (not auth) or (auth in str((m.get("author") or {}).get("username", "")).lower())
                    if c_ok and a_ok:
                        filtered.append({
                            "id": m.get("id"),
                            "author": (m.get("author") or {}).get("username"),
                            "content": m.get("content"),
                            "timestamp": m.get("timestamp"),
                        })
                return _ok({"match_count": len(filtered), "messages": filtered})

            elif name == "discord_bot_manage_thread":
                payload = {
                    "name": args["thread_name"],
                    "auto_archive_duration": int(args.get("auto_archive_duration", 1440)),
                    "type": 11,
                }
                return _ok(_discord_api("POST", f"/channels/{args['channel_id']}/threads", body=payload))

            elif name == "discord_format_embed_json":
                color_str = args.get("color_hex", "#5865F2").lstrip("#")
                embed = {
                    "title": args["title"],
                    "description": args["description"],
                    "color": int(color_str, 16) if color_str else 0x5865F2,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if args.get("fields"):
                    embed["fields"] = args["fields"]
                if args.get("footer"):
                    embed["footer"] = {"text": args["footer"]}
                return _ok(embed)

            elif name == "discord_telegram_bridge_send":
                msg = args["message"]
                tg_ok = False
                dc_ok = False
                tg_script = Path("/home/aesc/.local/bin/telegram_send.py")
                if tg_script.exists():
                    r = subprocess.run([str(tg_script), msg], capture_output=True, text=True, timeout=15)
                    tg_ok = r.returncode == 0
                if args.get("discord_webhook_url"):
                    res = self.call_tool("discord_webhook_send", {"webhook_url": args["discord_webhook_url"], "content": msg})
                    dc_ok = not res.get("isError")
                elif args.get("discord_channel_id"):
                    res = self.call_tool("discord_bot_send_message", {"channel_id": args["discord_channel_id"], "content": msg})
                    dc_ok = not res.get("isError")
                return _ok({"telegram_sent": tg_ok, "discord_sent": dc_ok})

            return _err(f"Unknown tool: {name}")
        except Exception as exc:
            return _err(f"Error in {name}: {exc}")

    def handle_request(self, request: dict) -> dict | None:
        method = request.get("method")
        req_id = request.get("id")
        if "id" not in request:
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "discord-ops-mcp", "version": "1.0.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools(), "ttlMs": 604800000}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}
        if method == "tools/call":
            params = request.get("params") or {}
            res = self.call_tool(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": req_id, "result": res}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                if isinstance(req, dict):
                    resp = self.handle_request(req)
                    if resp is not None:
                        sys.stdout.write(json.dumps(resp) + "\n")
                        sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"Error: {exc}\n")


if __name__ == "__main__":
    DiscordOpsMcpServer().serve_stdio()
