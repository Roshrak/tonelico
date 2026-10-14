"""MCP frontend for the installed Hermes Software Factory v2 pipeline."""

from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure factory library is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from hermes_factory_v2 import (
    APPROVED_AGY_SHA256,
    SUPPORTED_AGY_VERSION,
    Config,
    FactoryEngine,
    FactoryError,
    resolve_agy_executable,
    split_files,
)


class FactoryMcpServer:
    def __init__(self, engine: FactoryEngine | None = None) -> None:
        self.engine = engine or FactoryEngine()

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "factory_health",
                "description": "Read-only local SoftFac runtime check: platform, AGY identity, and Linux isolation availability.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "factory_plan",
                "description": "Create an Astra master plan for a coding task. Does not edit repository files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "Git repository top-level path"},
                        "request": {"type": "string", "description": "Implementation request"},
                        "files": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "string"},
                            ],
                            "description": "Hard boundary allowed file paths",
                        },
                        "test_cmd": {"type": "string", "description": "Optional test command"},
                        "prior_run": {"type": "string", "description": "Optional related factory run ID for bounded HoH evidence"},
                        "agy_bin": {"type": "string", "description": "Optional pinned AGY executable path"},
                    },
                    "required": ["repo", "request"],
                },
            },
            {
                "name": "factory_run",
                "description": "Run the fail-closed Astra plan, isolated AGY build, tests, Sol review, and task commit pipeline.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "Git repository top-level path"},
                        "request": {"type": "string", "description": "Implementation request"},
                        "files": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "string"}},
                                {"type": "string"},
                            ],
                            "description": "Hard boundary allowed file paths",
                        },
                        "test_cmd": {"type": "string", "description": "Optional test command"},
                        "prior_run": {"type": "string", "description": "Optional related factory run ID for bounded HoH evidence"},
                        "agy_bin": {"type": "string", "description": "Optional pinned AGY executable path"},
                    },
                    "required": ["repo", "request"],
                },
            },
            {
                "name": "factory_execute",
                "description": "Execute an existing Astra plan through isolated Builder, tests, and Sol review.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "description": "Planned run identifier"},
                    },
                    "required": ["run_id"],
                },
            },
            {
                "name": "factory_status",
                "description": "Check status and audit evidence of a factory run.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "description": "Run identifier"},
                    },
                    "required": ["run_id"],
                },
            },
            {
                "name": "factory_resume",
                "description": "Resume a previously planned or interrupted factory run.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "description": "Run identifier"},
                    },
                    "required": ["run_id"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any] | None) -> dict:
        arguments = arguments or {}
        try:
            if name == "factory_health":
                path = resolve_agy_executable(None)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                version = subprocess.run(
                    [str(path), "--version"], capture_output=True, text=True, timeout=8, check=False
                )
                observed = version.stdout.strip() if version.returncode == 0 else None
                status = {
                    "platform": sys.platform,
                    "agy_path": str(path),
                    "agy_version": observed,
                    "agy_version_approved": observed == SUPPORTED_AGY_VERSION,
                    "agy_identity_approved": digest == APPROVED_AGY_SHA256,
                    "linux_bubblewrap_available": bool(shutil.which("bwrap")) if sys.platform.startswith("linux") else None,
                    "ready_for_preflight": observed == SUPPORTED_AGY_VERSION
                    and digest == APPROVED_AGY_SHA256
                    and (not sys.platform.startswith("linux") or bool(shutil.which("bwrap"))),
                }
                return {"content": [{"type": "text", "text": json.dumps(status)}]}
            if name in {"factory_plan", "factory_run"}:
                if "repo" not in arguments or "request" not in arguments:
                    return {"isError": True, "content": [{"type": "text", "text": "Missing required parameters: repo and request"}]}
                files = arguments.get("files")
                if isinstance(files, str):
                    files = [files]
                if files is not None and (
                    not isinstance(files, list) or any(not isinstance(item, str) for item in files)
                ):
                    return {"isError": True, "content": [{"type": "text", "text": "files must be a list of paths or a comma-separated string"}]}
                config_kwargs: dict[str, Any] = {
                    "repo": arguments["repo"],
                    "request": arguments["request"],
                    "requested_files": split_files(files) if files else None,
                    "test_command": arguments.get("test_cmd") or arguments.get("test_command"),
                    "prior_run": arguments.get("prior_run"),
                }
                for int_key in ("max_task_attempts", "max_debug_attempts", "max_review_cycles", "role_timeout", "builder_timeout", "test_timeout"):
                    if int_key in arguments:
                        val = arguments[int_key]
                        if isinstance(val, int):
                            config_kwargs[int_key] = val
                        elif isinstance(val, str) and val.isdigit():
                            config_kwargs[int_key] = int(val)
                for str_key in (
                    "builder_model", "planner_model", "reviewer_model", "sol_model",
                    "planner_provider", "reviewer_provider", "sol_provider", "agy_bin",
                    "agy_navigation_recovery", "planner_reasoning", "reviewer_reasoning",
                ):
                    if str_key in arguments and isinstance(arguments[str_key], str) and arguments[str_key].strip():
                        config_kwargs[str_key] = arguments[str_key].strip()
                config = Config(**config_kwargs)

                if name == "factory_plan":
                    run_id = self.engine.plan(config)
                    return {"content": [{"type": "text", "text": json.dumps({"run_id": run_id, "phase": "planned"})}]}
                else:
                    run_id = self.engine.plan(config)
                    result = self.engine.execute(run_id)
                    return {"content": [{"type": "text", "text": json.dumps(result)}]}

            elif name in {"factory_execute", "factory_status", "factory_resume"}:
                raw_run_id = arguments.get("run_id")
                if raw_run_id is None:
                    return {"isError": True, "content": [{"type": "text", "text": "Missing required parameter: run_id"}]}
                run_id = str(raw_run_id).strip()
                if not run_id:
                    return {"isError": True, "content": [{"type": "text", "text": "Parameter run_id cannot be empty"}]}
                if name == "factory_execute":
                    result = self.engine.execute(run_id)
                elif name == "factory_status":
                    result = self.engine.status(run_id)
                else:
                    result = self.engine.resume(run_id)
                return {"content": [{"type": "text", "text": json.dumps(result)}]}

            else:
                return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
        except FactoryError as exc:
            return {"isError": True, "content": [{"type": "text", "text": f"Factory {exc.category}: {exc}"}]}
        except Exception as exc:
            return {"isError": True, "content": [{"type": "text", "text": f"Error: {exc}"}]}

    def handle_request(self, request: dict) -> dict | None:
        method = request.get("method")
        req_id = request.get("id")

        if "id" not in request:
            if method == "tools/call":
                params = request.get("params")
                if isinstance(params, dict):
                    tool_name = params.get("name", "")
                    args = params.get("arguments")
                    self.call_tool(tool_name, args if isinstance(args, dict) else {})
            return None

        if not method:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: missing method"},
            }

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "hermes-factory-mcp", "version": "2.2.0-linux"},
                },
            }
        elif method == "notifications/initialized":
            return None
        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.list_tools()},
            }
        elif method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": []},
            }
        elif method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": []},
            }
        elif method == "tools/call":
            params = request.get("params")
            if not isinstance(params, dict):
                params = {}
            tool_name = params.get("name", "")
            args = params.get("arguments")
            if not isinstance(args, dict):
                args = {}
            result = self.call_tool(tool_name, args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except Exception:
                sys.stdout.write(
                    json.dumps({
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    })
                    + "\n"
                )
                sys.stdout.flush()
                continue
            try:
                if isinstance(req, list):
                    if not req:
                        sys.stdout.write(
                            json.dumps({
                                "jsonrpc": "2.0",
                                "id": None,
                                "error": {"code": -32600, "message": "Invalid Request: empty batch"},
                            })
                            + "\n"
                        )
                        sys.stdout.flush()
                        continue
                    batch_resps = []
                    for single_req in req:
                        if isinstance(single_req, dict):
                            r = self.handle_request(single_req)
                            if r is not None:
                                batch_resps.append(r)
                        else:
                            batch_resps.append({
                                "jsonrpc": "2.0",
                                "id": None,
                                "error": {"code": -32600, "message": "Invalid Request: expected object"},
                            })
                    if batch_resps:
                        sys.stdout.write(json.dumps(batch_resps) + "\n")
                        sys.stdout.flush()
                elif isinstance(req, dict):
                    resp = self.handle_request(req)
                    if resp is not None:
                        sys.stdout.write(json.dumps(resp) + "\n")
                        sys.stdout.flush()
                else:
                    sys.stdout.write(
                        json.dumps({
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32600, "message": "Invalid Request: expected object or array"},
                        })
                        + "\n"
                    )
                    sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"Error processing request: {exc}\n")


if __name__ == "__main__":
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            import signal
            libc = ctypes.CDLL("libc.so.6")
            PR_SET_PDEATHSIG = 1
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
        except Exception:
            pass
    server = FactoryMcpServer()
    server.serve_stdio()
