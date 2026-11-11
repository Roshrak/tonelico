#!/usr/bin/env python3
"""MCP server for Parallel Order Orchestration, Live Task Steering, Isolated Batch Execution, and Argon Pool Telemetry."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

STATE_DIR = Path("/home/aesc/.hermes/cache/scratch")
LIVE_STATE_FILE = STATE_DIR / "parallel_orders_state.json"
IPC_COMMANDS_FILE = STATE_DIR / "parallel_orders_commands.jsonl"
STATE_DB_FILE = Path("/home/aesc/.hermes/state.db")
AISTUDIO_ENV_FILE = Path("/home/aesc/aistudio2api/.env")


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
        "structuredContent": payload,
        "isError": False,
    }


def _err(msg: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps({"error": msg}, ensure_ascii=False)}],
        "structuredContent": {"error": msg},
        "isError": True,
    }


class ParallelOpsMcpServer:
    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "parallel_list_active_orders",
                "description": "List all currently running primary and parallel orders in Hermes Gateway, plus recent parallel order history from state.db.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_recent_history": {
                            "type": "boolean",
                            "description": "Include the 10 most recent parallel orders from state.db (default true).",
                        }
                    },
                },
            },
            {
                "name": "parallel_steer_order",
                "description": "Inject/append an instruction directly into an already-running primary or parallel order without spawning a duplicate task.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Target task_id (e.g. 'par_233110_b20e8d', 'primary', or 'latest').",
                        },
                        "text": {
                            "type": "string",
                            "description": "Instruction or context to append to the running task.",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "parallel_cancel_order",
                "description": "Cleanly cancel/stop a specific running parallel order without interrupting other running orders.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Target parallel task_id to stop (or 'latest').",
                        }
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "parallel_batch_shell",
                "description": "Execute up to 16 independent shell commands concurrently in isolated subprocesses (zero shared bash session lock contention).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "commands": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of shell commands to run in parallel.",
                        },
                        "timeout_s": {
                            "type": "integer",
                            "description": "Per-command timeout in seconds (default 60).",
                        },
                    },
                    "required": ["commands"],
                },
            },
            {
                "name": "parallel_argon_pool_status",
                "description": "Check the real-time status and cooldown availability of gemini-4-argon across all 9 Google AI Pro worker accounts in aistudio2api.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "parallel_list_active_orders":
                live_data = {"updated_at": None, "active_count": 0, "runs": []}
                if LIVE_STATE_FILE.exists():
                    try:
                        live_data = json.loads(LIVE_STATE_FILE.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                recent_parallel = []
                if args.get("include_recent_history", True) and STATE_DB_FILE.exists():
                    conn = sqlite3.connect(str(STATE_DB_FILE))
                    rows = conn.execute(
                        """
                        SELECT session_id, role, substr(content, 1, 140), datetime(timestamp, 'unixepoch', 'localtime')
                        FROM messages
                        WHERE session_id LIKE 'par_%' AND role IN ('user', 'assistant') AND content != ''
                        ORDER BY id DESC LIMIT 12
                        """
                    ).fetchall()
                    conn.close()
                    for r in reversed(rows):
                        recent_parallel.append(
                            {
                                "session_id": r[0],
                                "role": r[1],
                                "preview": r[2],
                                "timestamp": r[3],
                            }
                        )
                return _ok({
                    "live_state": live_data,
                    "recent_parallel_messages": recent_parallel,
                })

            if name == "parallel_steer_order":
                text = str(args.get("text") or "").strip()
                if not text:
                    return _err("text is required")
                task_id = str(args.get("task_id") or "latest").strip()
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                cmd = {"action": "steer", "task_id": task_id, "text": text, "ts": time.time()}
                with IPC_COMMANDS_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
                return _ok({"queued": True, "action": "steer", "task_id": task_id, "text": text})

            if name == "parallel_cancel_order":
                task_id = str(args.get("task_id") or "").strip()
                if not task_id:
                    return _err("task_id is required")
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                cmd = {"action": "cancel", "task_id": task_id, "ts": time.time()}
                with IPC_COMMANDS_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
                return _ok({"queued": True, "action": "cancel", "task_id": task_id})

            if name == "parallel_batch_shell":
                commands = list(args.get("commands") or [])[:16]
                if not commands:
                    return _err("commands list cannot be empty")
                timeout_s = max(1, min(int(args.get("timeout_s") or 60), 300))
                env = os.environ.copy()
                nix_bins = "/run/wrappers/bin:/run/current-system/sw/bin:/etc/profiles/per-user/aesc/bin:/home/aesc/.nix-profile/bin:/home/aesc/.local/bin"
                env["PATH"] = f"{nix_bins}:{env.get('PATH', '')}"

                def _run_one(idx_cmd: tuple[int, str]) -> dict[str, Any]:
                    idx, cmd_str = idx_cmd
                    t0 = time.monotonic()
                    try:
                        proc = subprocess.run(
                            cmd_str,
                            shell=True,
                            executable="/run/current-system/sw/bin/bash",
                            capture_output=True,
                            text=True,
                            timeout=timeout_s,
                            env=env,
                        )
                        return {
                            "index": idx,
                            "command": cmd_str,
                            "exit_code": proc.returncode,
                            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                            "stdout": (proc.stdout or "")[:4000],
                            "stderr": (proc.stderr or "")[:2000],
                        }
                    except subprocess.TimeoutExpired:
                        return {
                            "index": idx,
                            "command": cmd_str,
                            "exit_code": 124,
                            "duration_ms": round((time.monotonic() - t0) * 1000, 1),
                            "error": f"Timed out after {timeout_s}s",
                        }

                t_batch = time.monotonic()
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(commands), 16)) as pool:
                    results = list(pool.map(_run_one, enumerate(commands)))
                return _ok({
                    "count": len(results),
                    "total_wall_ms": round((time.monotonic() - t_batch) * 1000, 1),
                    "results": results,
                })

            if name == "parallel_argon_pool_status":
                hermes_env = Path("/home/aesc/.hermes/.env")
                aistudio_key = ""
                agm_key = ""
                if hermes_env.exists():
                    for line in hermes_env.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if line.startswith("AISTUDIO2API_API_KEY="):
                            aistudio_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        elif line.startswith("AGY_ROTATOR_API_KEY="):
                            agm_key = line.split("=", 1)[1].strip().strip('"').strip("'")

                tiers = [
                    ("1_primary_aistudio_argon_high", "http://134.185.85.64:2048/v1/models", aistudio_key, "gemini-4-argon-high"),
                    ("2_fallback_antigravity_argon_high", "http://134.185.85.64:8045/v1/models", agm_key, "gemini-4-argon-high"),
                    ("3_fallback_aistudio_flash38_high", "http://134.185.85.64:2048/v1/models", aistudio_key, "gemini-3.8-flash-high"),
                    ("4_fallback_antigravity_flash38_high", "http://134.185.85.64:8045/v1/models", agm_key, "gemini-3.8-flash-high"),
                ]
                tier_status = []
                for label, url, key, target_model in tiers:
                    try:
                        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
                        with urllib.request.urlopen(req, timeout=4) as r:
                            models = [m.get("id", "") for m in json.loads(r.read().decode()).get("data", []) if isinstance(m, dict)]
                        available = target_model in models or any(target_model.replace("-high", "") in m for m in models)
                        tier_status.append({"tier": label, "model": target_model, "available": available, "status": "ready" if available else "missing"})
                    except Exception as exc:
                        tier_status.append({"tier": label, "model": target_model, "available": False, "status": f"error: {exc}"})

                return _ok({
                    "default_primary": "aistudio2api/gemini-4-argon-high",
                    "primary_retry_policy": {"retries": 5, "wait_seconds_per_retry": 180},
                    "cascade_order": tier_status,
                })

            return _err(f"Unknown tool: {name}")
        except Exception as e:
            return _err(f"{type(e).__name__}: {e}")

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params") or {}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "parallel-ops-mcp", "version": "1.0.0"},
                },
            }
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.tool_definitions(), "ttlMs": 604800000}}
        if method == "tools/call":
            result = self.call_tool(str(params.get("name") or ""), dict(params.get("arguments") or {}))
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    def serve_stdio(self) -> int:
        for line in sys.stdin:
            raw = line.strip()
            if not raw:
                continue
            try:
                req = json.loads(raw)
            except json.JSONDecodeError:
                continue
            resp = self.handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        return 0


if __name__ == "__main__":
    raise SystemExit(ParallelOpsMcpServer().serve_stdio())
