#!/usr/bin/env python3
"""MCP server for Minecraft Client Operations, Chat Responder Bot, PrismLauncher, Logs, and Anvil MCA World Inspection."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List

PRISM_INSTANCES_DIR = Path("/home/aesc/.local/share/PrismLauncher/instances")
DEFAULT_INSTANCE = "Fabulously Optimized"
DEFAULT_LOG_PATH = PRISM_INSTANCES_DIR / DEFAULT_INSTANCE / "minecraft" / "logs" / "latest.log"
BOT_LOG_PATH = Path("/home/aesc/.local/share/mc_chat_responder.log")
BOT_SCRIPT = Path("/home/aesc/tonelico/nixos/home/files/bin/mc_chat_responder.py")
LAUNCH_SCRIPT = Path("/home/aesc/vivian/launch_mc_and_spawn.py")
UINPUT_BIN = Path("/home/aesc/.local/bin/uinput_type")


def _ok(data: Any) -> dict:
    text = json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": msg}]}


def _clean_mc(text: str) -> str:
    return re.sub(r"§[0-9a-fk-or]", "", text)


def _pack_varint(val: int) -> bytes:
    out = bytearray()
    while True:
        byte = val & 0x7F
        val >>= 7
        if val:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _read_varint(sock: socket.socket) -> int:
    num = 0
    for i in range(5):
        b = sock.recv(1)
        if not b:
            raise EOFError("Socket closed")
        byte = b[0]
        num |= (byte & 0x7F) << (7 * i)
        if not (byte & 0x80):
            break
    return num


def _ping_mc_server(host: str, port: int = 25565, timeout: float = 5.0) -> dict:
    t0 = time.monotonic()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        host_bytes = host.encode("utf-8")
        handshake = (
            b"\x00"
            + _pack_varint(760)
            + _pack_varint(len(host_bytes))
            + host_bytes
            + struct.pack(">H", port)
            + b"\x01"
        )
        sock.sendall(_pack_varint(len(handshake)) + handshake)
        sock.sendall(b"\x01\x00")
        _ = _read_varint(sock)
        packet_id = _read_varint(sock)
        if packet_id != 0:
            raise RuntimeError(f"Unexpected packet id: {packet_id}")
        str_len = _read_varint(sock)
        data = bytearray()
        while len(data) < str_len:
            chunk = sock.recv(str_len - len(data))
            if not chunk:
                break
            data.extend(chunk)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        status = json.loads(data.decode("utf-8", "replace"))
        return {"online": True, "host": host, "port": port, "latency_ms": latency_ms, "status": status}


class MinecraftOpsMcpServer:
    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "mc_instance_status",
                "description": "Inspect PrismLauncher instances, running Minecraft client PID, and latest.log metadata.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "mc_launch_and_spawn",
                "description": "Run ~/vivian/launch_mc_and_spawn.py to launch or focus Minecraft (Fabulously Optimized) and verify /spawn.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string", "description": "Optional server address (default alt.crazy-fools.co.uk:25565)"},
                    },
                },
            },
            {
                "name": "mc_read_latest_log",
                "description": "Read the most recent lines from Minecraft's latest.log (with § formatting stripped), optionally filtering for [CHAT] lines.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "lines": {"type": "integer", "description": "Number of tail lines to read (default 100)"},
                        "chat_only": {"type": "boolean", "description": "If true, only return [CHAT] messages"},
                    },
                },
            },
            {
                "name": "mc_search_chat_history",
                "description": "Search Minecraft latest.log and archived logs/*.log.gz for player messages, keywords, or /tpa events.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Case-insensitive regex or keyword"},
                        "max_matches": {"type": "integer", "description": "Maximum matches (default 50)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "mc_send_chat_or_command",
                "description": "Send an in-game chat message or slash command (e.g. /spawn, /tpaccept, /msg) to Minecraft via uinput_type.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Chat text or slash command (e.g. '/spawn' or 'yo!')"},
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "mc_bot_responder_status",
                "description": "Check running status and recent activity log of mc_chat_responder.py.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tail_lines": {"type": "integer", "description": "Log lines to return (default 40)"},
                    },
                },
            },
            {
                "name": "mc_bot_responder_control",
                "description": "Activate (start), deactivate (stop), restart, or check status of mc_chat_responder (strictly via Telegram or Hermes CLI).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "start, stop, restart, or status"},
                        "account": {"type": "string", "description": "roshrak (main) or alt (Miracle_Involker). Default: roshrak"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "mc_list_mods_and_packs",
                "description": "List installed mods (.jar), resourcepacks, and shaderpacks in the PrismLauncher instance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instance": {"type": "string", "description": "Instance name (default 'Fabulously Optimized')"},
                    },
                },
            },
            {
                "name": "mc_coords_converter",
                "description": "Convert Minecraft Block coordinates (X, Y, Z) to Overworld<->Nether (1:8) coordinates, Chunk (X, Z), and Region file (r.X.Z.mca).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer", "description": "Optional Y coordinate (default 64)"},
                        "z": {"type": "integer"},
                        "dimension": {"type": "string", "description": "overworld or nether (default overworld)"},
                    },
                    "required": ["x", "z"],
                },
            },
            {
                "name": "mc_inspect_mca_region",
                "description": "Inspect a Minecraft Anvil .mca region file header (populated chunks count, chunk coordinates, compression, byte size).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mca_path": {"type": "string", "description": "Absolute path to r.X.Z.mca file"},
                    },
                    "required": ["mca_path"],
                },
            },
            {
                "name": "mc_list_saved_worlds",
                "description": "List local PrismLauncher singleplayer saves and ChunkLens/ChronoFinder test worlds on disk.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "mc_server_ping",
                "description": "Ping a Minecraft Java server via SLP protocol to check online status, latency, MOTD, version, and online players.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "description": "Server hostname (default alt.crazy-fools.co.uk)"},
                        "port": {"type": "integer", "description": "Server port (default 25565)"},
                    },
                },
            },
            {
                "name": "mc_player_uuid_lookup",
                "description": "Resolve a Minecraft username to its online Mojang UUID and offline-mode UUID.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                    },
                    "required": ["username"],
                },
            },
            {
                "name": "mc_crafting_and_enchant_ref",
                "description": "Query Minecraft enchantment max levels, incompatibilities, potion brewing recipes, and villager job blocks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "enchantments, potions, villagers, or redstone"},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "mc_rcon_command",
                "description": "Send an RCON command to a Minecraft server with RCON enabled.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string", "description": "RCON host (default 127.0.0.1)"},
                        "port": {"type": "integer", "description": "RCON port (default 25575)"},
                        "password": {"type": "string"},
                        "command": {"type": "string", "description": "Minecraft server command (without leading /)"},
                    },
                    "required": ["password", "command"],
                },
            },
            {
                "name": "mc_crash_log_analyzer",
                "description": "Scan Minecraft crash-reports or latest.log for exceptions, Mixin errors, and mod conflicts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "log_path": {"type": "string", "description": "Optional crash report path (defaults to latest crash report or latest.log)"},
                    },
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> dict:
        try:
            if name == "mc_instance_status":
                instances = [d.name for d in PRISM_INSTANCES_DIR.iterdir() if d.is_dir()] if PRISM_INSTANCES_DIR.exists() else []
                ps = subprocess.run(["pgrep", "-af", "minecraft|PrismLauncher"], capture_output=True, text=True, timeout=5)
                procs = [ln for ln in ps.stdout.splitlines() if "minecraft_ops_mcp" not in ln]
                return _ok({
                    "prism_instances": instances,
                    "running_processes": procs,
                    "latest_log_exists": DEFAULT_LOG_PATH.exists(),
                    "latest_log_size": DEFAULT_LOG_PATH.stat().st_size if DEFAULT_LOG_PATH.exists() else 0,
                })

            elif name == "mc_launch_and_spawn":
                if not LAUNCH_SCRIPT.exists():
                    return _err(f"Launch script not found: {LAUNCH_SCRIPT}")
                cmd = [sys.executable, str(LAUNCH_SCRIPT)]
                if args.get("server"):
                    cmd.extend(["--server", args["server"]])
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                return _ok({"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr})

            elif name == "mc_read_latest_log":
                if not DEFAULT_LOG_PATH.exists():
                    return _err(f"Log file not found: {DEFAULT_LOG_PATH}")
                raw_lines = DEFAULT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
                cleaned = [_clean_mc(ln) for ln in raw_lines]
                if args.get("chat_only"):
                    cleaned = [ln for ln in cleaned if "[CHAT]" in ln]
                n = int(args.get("lines", 100))
                return _ok({"total_matching_lines": len(cleaned), "lines": cleaned[-n:]})

            elif name == "mc_search_chat_history":
                pat = re.compile(args["query"], re.IGNORECASE)
                max_m = int(args.get("max_matches", 50))
                logs_dir = DEFAULT_LOG_PATH.parent
                matches = []
                if logs_dir.exists():
                    files = sorted(logs_dir.glob("*.log*"), key=lambda p: p.stat().st_mtime, reverse=True)
                    for fp in files:
                        try:
                            if fp.suffix == ".gz":
                                with gzip.open(fp, "rt", encoding="utf-8", errors="replace") as f:
                                    lines = f.readlines()
                            else:
                                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                            for ln in lines:
                                cl = _clean_mc(ln)
                                if pat.search(cl):
                                    matches.append({"file": fp.name, "line": cl})
                                    if len(matches) >= max_m:
                                        break
                        except Exception:
                            continue
                        if len(matches) >= max_m:
                            break
                return _ok({"query": args["query"], "match_count": len(matches), "matches": matches})

            elif name == "mc_send_chat_or_command":
                msg = args["message"].strip()
                if not UINPUT_BIN.exists():
                    return _err(f"uinput_type not found at {UINPUT_BIN}")
                if msg.startswith("/"):
                    cmd_name = msg.lstrip("/")
                    tokens = ["slash", "sleep:250", f"type:{cmd_name}", "sleep:250", "enter", "sleep:200"]
                else:
                    tokens = ["t", "sleep:250", f"type:{msg}", "sleep:250", "enter", "sleep:200"]
                res = subprocess.run([str(UINPUT_BIN), *tokens], capture_output=True, text=True, timeout=15)
                return _ok({"sent": msg, "tokens": tokens, "exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr})

            elif name == "mc_bot_responder_status":
                ps = subprocess.run(["pgrep", "-af", "mc_chat_responder"], capture_output=True, text=True, timeout=5)
                procs = [ln for ln in ps.stdout.splitlines() if "pgrep" not in ln]
                tail_n = int(args.get("tail_lines", 40))
                log_tail = []
                if BOT_LOG_PATH.exists():
                    log_tail = BOT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-tail_n:]
                return _ok({"running": len(procs) > 0, "processes": procs, "log_tail": log_tail})

            elif name == "mc_bot_responder_control":
                act = args["action"].lower().strip()
                acct = args.get("account", "roshrak").lower().strip()
                res = subprocess.run(
                    ["/home/aesc/.local/bin/mc_responder_ctl", act, acct],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if res.returncode != 0:
                    return _err(res.stderr or res.stdout or "mc_responder_ctl failed")
                return _ok(json.loads(res.stdout) if res.stdout.strip().startswith("{") else res.stdout)

            elif name == "mc_list_mods_and_packs":
                inst = args.get("instance", DEFAULT_INSTANCE)
                mc_dir = PRISM_INSTANCES_DIR / inst / "minecraft"
                mods = sorted([p.name for p in (mc_dir / "mods").glob("*.jar")]) if (mc_dir / "mods").exists() else []
                rpacks = sorted([p.name for p in (mc_dir / "resourcepacks").iterdir()]) if (mc_dir / "resourcepacks").exists() else []
                spacks = sorted([p.name for p in (mc_dir / "shaderpacks").iterdir()]) if (mc_dir / "shaderpacks").exists() else []
                return _ok({"instance": inst, "mod_count": len(mods), "mods": mods, "resourcepacks": rpacks, "shaderpacks": spacks})

            elif name == "mc_coords_converter":
                x = int(args["x"])
                y = int(args.get("y", 64))
                z = int(args["z"])
                dim = args.get("dimension", "overworld").lower()
                chunk_x, chunk_z = x >> 4, z >> 4
                reg_x, reg_z = chunk_x >> 5, chunk_z >> 5
                if dim == "nether":
                    ow_x, ow_z = x * 8, z * 8
                    ne_x, ne_z = x, z
                else:
                    ow_x, ow_z = x, z
                    ne_x, ne_z = round(x / 8), round(z / 8)
                return _ok({
                    "input": {"x": x, "y": y, "z": z, "dimension": dim},
                    "overworld_coords": {"x": ow_x, "y": y, "z": ow_z},
                    "nether_coords": {"x": ne_x, "y": y, "z": ne_z},
                    "chunk_coords": {"chunk_x": chunk_x, "chunk_z": chunk_z, "local_x": x & 15, "local_z": z & 15},
                    "region_file": f"r.{reg_x}.{reg_z}.mca",
                })

            elif name == "mc_inspect_mca_region":
                p = Path(args["mca_path"]).expanduser().resolve()
                if not p.exists():
                    return _err(f"MCA file not found: {p}")
                raw = p.read_bytes()
                if len(raw) < 8192:
                    return _err("MCA file smaller than 8KB header")
                populated = []
                for idx in range(1024):
                    loc = struct.unpack(">I", raw[idx * 4 : idx * 4 + 4])[0]
                    offset = loc >> 8
                    sectors = loc & 0xFF
                    ts = struct.unpack(">I", raw[4096 + idx * 4 : 4096 + idx * 4 + 4])[0]
                    if offset > 0 and sectors > 0:
                        cx = idx & 31
                        cz = idx >> 5
                        populated.append({"local_chunk": [cx, cz], "sector_offset": offset, "sector_count": sectors, "timestamp": ts})
                return _ok({
                    "file": str(p),
                    "size_bytes": len(raw),
                    "populated_chunk_count": len(populated),
                    "sample_chunks": populated[:25],
                })

            elif name == "mc_list_saved_worlds":
                worlds = []
                for base in [
                    PRISM_INSTANCES_DIR / DEFAULT_INSTANCE / "minecraft" / "saves",
                    Path("/home/aesc/ChunkLens-archive/golden-worlds"),
                    Path("/home/aesc/Projects/ChronoFinder/build"),
                ]:
                    if base.exists():
                        for mca in base.rglob("r.*.*.mca"):
                            worlds.append(str(mca.parent.parent))
                unique_worlds = sorted(set(worlds))
                return _ok({"world_count": len(unique_worlds), "worlds": unique_worlds})

            elif name == "mc_server_ping":
                host = args.get("host", "alt.crazy-fools.co.uk")
                port = int(args.get("port", 25565))
                return _ok(_ping_mc_server(host, port))

            elif name == "mc_player_uuid_lookup":
                uname = args["username"].strip()
                offline_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{uname}"))
                # Realistic Java OfflinePlayer MD5 UUID
                md5_bytes = bytearray(hashlib.md5(f"OfflinePlayer:{uname}".encode("utf-8")).digest())
                md5_bytes[6] = (md5_bytes[6] & 0x0F) | 0x30
                md5_bytes[8] = (md5_bytes[8] & 0x3F) | 0x80
                offline_java_uuid = str(uuid.UUID(bytes=bytes(md5_bytes)))
                online_data = None
                try:
                    with urllib.request.urlopen(f"https://api.mojang.com/users/profiles/minecraft/{uname}", timeout=5) as r:
                        online_data = json.loads(r.read().decode())
                except Exception:
                    pass
                return _ok({"username": uname, "offline_uuid": offline_java_uuid, "mojang_profile": online_data})

            elif name == "mc_crafting_and_enchant_ref":
                refs = {
                    "enchantments": {
                        "helmet": ["Protection IV", "Unbreaking III", "Mending", "Respiration III", "Aqua Affinity", "Thorns III"],
                        "elytra": ["Unbreaking III", "Mending"],
                        "sword": ["Sharpness V / Smite V", "Looting III", "Unbreaking III", "Mending", "Sweeping Edge III", "Fire Aspect II"],
                        "pickaxe": ["Efficiency V", "Fortune III / Silk Touch", "Unbreaking III", "Mending"],
                        "bow": ["Power V", "Flame", "Punch II", "Unbreaking III", "Infinity XOR Mending"],
                    },
                    "villagers": {
                        "Librarian": "Lectern (Mending, Unbreaking III, Efficiency V)",
                        "Armorer": "Blast Furnace (Diamond Armor)",
                        "Weaponsmith": "Grindstone (Diamond Axe/Sword)",
                        "Toolsmith": "Smithing Table (Diamond Pickaxe/Shovel/Hoe)",
                        "Fletcher": "Fletching Table (32 Sticks -> 1 Emerald)",
                        "Cleric": "Brewing Stand (Rotten Flesh -> Emerald, Ender Pearls)",
                    },
                }
                return _ok(refs.get(args["topic"].lower(), refs))

            elif name == "mc_rcon_command":
                host = args.get("host", "127.0.0.1")
                port = int(args.get("port", 25575))
                pw = args["password"].encode("utf-8")
                cmd_bytes = args["command"].encode("utf-8")
                with socket.create_connection((host, port), timeout=5) as s:
                    auth_pkt = struct.pack("<ii", 1, 3) + pw + b"\x00\x00"
                    s.sendall(struct.pack("<i", len(auth_pkt)) + auth_pkt)
                    resp_len = struct.unpack("<i", s.recv(4))[0]
                    auth_resp = s.recv(resp_len)
                    req_id, _ = struct.unpack("<ii", auth_resp[:8])
                    if req_id == -1:
                        return _err("RCON authentication failed")
                    cmd_pkt = struct.pack("<ii", 2, 2) + cmd_bytes + b"\x00\x00"
                    s.sendall(struct.pack("<i", len(cmd_pkt)) + cmd_pkt)
                    rlen = struct.unpack("<i", s.recv(4))[0]
                    rbody = s.recv(rlen)
                    text = rbody[8:-2].decode("utf-8", "replace")
                    return _ok({"command": args["command"], "response": _clean_mc(text)})

            elif name == "mc_crash_log_analyzer":
                target = Path(args["log_path"]) if args.get("log_path") else DEFAULT_LOG_PATH
                if not target.exists():
                    return _err(f"Log not found: {target}")
                txt = target.read_text(encoding="utf-8", errors="replace")
                exceptions = re.findall(r"(?:java\.lang\.\w+Exception|org\.spongepowered\.asm\.mixin\.[^\s:]+|Caused by:[^\n]+)", txt)
                return _ok({"file": str(target), "exception_count": len(exceptions), "exceptions": exceptions[:30]})

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
                    "serverInfo": {"name": "minecraft-ops-mcp", "version": "1.0.0"},
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
    MinecraftOpsMcpServer().serve_stdio()
