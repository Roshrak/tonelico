#!/usr/bin/env python3
"""MCP server for Wayland/Hyprland/Niri/Sway Desktop Automation and Computer Use."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _ok(data: Any) -> dict:
    text = json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": msg}]}


def _wayland_env() -> dict:
    env = os.environ.copy()
    uid = os.getuid()
    xdg = env.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env["XDG_RUNTIME_DIR"] = xdg
    env.setdefault("WAYLAND_DISPLAY", "wayland-1")
    env.setdefault("DISPLAY", ":0")
    hypr_dir = Path(xdg) / "hypr"
    if hypr_dir.exists() and not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        dirs = sorted([d for d in hypr_dir.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
        if dirs:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = dirs[0].name
    if not env.get("NIRI_SOCKET"):
        niri_socks = sorted(Path(xdg).glob("niri*.sock"), key=lambda p: p.stat().st_mtime, reverse=True)
        if niri_socks:
            env["NIRI_SOCKET"] = str(niri_socks[0])
    if not env.get("SWAYSOCK"):
        sway_socks = sorted(Path(xdg).glob("sway-ipc*.sock"), key=lambda p: p.stat().st_mtime, reverse=True)
        if sway_socks:
            env["SWAYSOCK"] = str(sway_socks[0])
    return env


def _find_wtype() -> str | None:
    w = shutil.which("wtype")
    if w:
        return w
    matches = sorted(Path("/nix/store").glob("*-wtype-*/bin/wtype"))
    return str(matches[-1]) if matches else None


def _list_compositor_windows(env: dict) -> tuple[str, List[dict]]:
    # 1. Try Niri
    if shutil.which("niri") and env.get("NIRI_SOCKET"):
        r = subprocess.run(["niri", "msg", "-j", "windows"], env=env, capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            try:
                wins = json.loads(r.stdout)
                return "niri", wins
            except Exception:
                pass
    # 2. Try Hyprland
    if shutil.which("hyprctl") and env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        r = subprocess.run(["hyprctl", "clients", "-j"], env=env, capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            try:
                clients = json.loads(r.stdout)
                norm = [
                    {
                        "id": c.get("address"),
                        "app_id": c.get("class"),
                        "title": c.get("title"),
                        "pid": c.get("pid"),
                        "workspace": (c.get("workspace") or {}).get("name"),
                        "is_focused": c.get("focusHistoryID") == 0,
                    }
                    for c in clients
                ]
                return "hyprland", norm
            except Exception:
                pass
    # 3. Try Sway
    if shutil.which("swaymsg"):
        r = subprocess.run(["swaymsg", "-t", "get_tree"], env=env, capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            try:
                tree = json.loads(r.stdout)
                wins = []

                def walk(node):
                    if node.get("type") in ("con", "floating_con") and (node.get("app_id") or node.get("window_properties")):
                        wins.append({
                            "id": node.get("id"),
                            "app_id": node.get("app_id") or (node.get("window_properties") or {}).get("class"),
                            "title": node.get("name"),
                            "pid": node.get("pid"),
                            "is_focused": node.get("focused", False),
                        })
                    for child in node.get("nodes", []) + node.get("floating_nodes", []):
                        walk(child)

                walk(tree)
                return "sway", wins
            except Exception:
                pass
    return "unknown", []


class DesktopComputerUseMcpServer:
    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "cu_detect_session",
                "description": "Detect active Wayland compositor (Niri, Hyprland, Sway), WAYLAND_DISPLAY, session lock state, and input helpers.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "cu_list_windows",
                "description": "List all open desktop windows with ID, app_id, title, PID, and focus status across Niri/Hyprland/Sway.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filter_query": {"type": "string", "description": "Optional substring/regex filter on app_id or title"},
                    },
                },
            },
            {
                "name": "cu_focus_window",
                "description": "Focus a window by ID, app_id, or title substring and verify that focus changed.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "window_id": {"type": "string", "description": "Optional exact window ID"},
                        "app_id_or_title": {"type": "string", "description": "Substring matching app_id or title"},
                    },
                },
            },
            {
                "name": "cu_close_window",
                "description": "Close a desktop window by ID or app_id/title and verify removal.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "window_id": {"type": "string"},
                        "app_id": {"type": "string", "description": "Application class/app_id (e.g. chromium, discord)"},
                    },
                },
            },
            {
                "name": "cu_launch_detached",
                "description": "Launch a GUI application or visible Kitty terminal command on the monitor detached in background.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to execute"},
                        "in_kitty_monitor": {"type": "boolean", "description": "If true, launch inside `kitty --hold -e` visible on monitor"},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "cu_take_screenshot",
                "description": "Capture a Wayland desktop screenshot (full screen or region x,y,w,h) via grim and return the saved PNG path.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "description": "Optional grim geometry 'X,Y WxH' (e.g. '0,0 1920x1080')"},
                        "output_path": {"type": "string", "description": "Optional output PNG path"},
                    },
                },
            },
            {
                "name": "cu_screenshot_ocr",
                "description": "Capture a desktop screenshot (full screen or region) and run PaddleOCR to extract visible UI text.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "description": "Optional grim region 'X,Y WxH'"},
                    },
                },
            },
            {
                "name": "cu_type_text",
                "description": "Type text into the focused Wayland window using wtype or uinput_type.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text string to type"},
                        "press_enter": {"type": "boolean", "description": "Press Enter after typing (default false)"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "cu_send_key",
                "description": "Send a keyboard key or shortcut (e.g. Return, Escape, Tab, ctrl+l, ctrl+w, ctrl+k) via wtype.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Key name or modifier+key (e.g. Return, Escape, ctrl+k)"},
                    },
                    "required": ["key"],
                },
            },
            {
                "name": "cu_clipboard_get",
                "description": "Read current Wayland/X11 clipboard text content.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "cu_clipboard_set",
                "description": "Write text to the Wayland/X11 clipboard.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to copy to clipboard"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "cu_media_status",
                "description": "Get active media player playback status, track metadata (playerctl), and PipeWire volume (wpctl).",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "cu_media_control",
                "description": "Control media playback (play, pause, play-pause, stop, next, previous) via playerctl.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "play, pause, play-pause, stop, next, previous"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "cu_workspace_switch",
                "description": "Switch to a target workspace number or name in Niri, Hyprland, or Sway.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace": {"type": "string", "description": "Workspace number or name (e.g. '1', '2')"},
                    },
                    "required": ["workspace"],
                },
            },
            {
                "name": "cu_system_vitals",
                "description": "Inspect CPU load, RAM/Swap usage, disk free space, and top memory processes on this NixOS laptop.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "cu_send_desktop_notification",
                "description": "Send a desktop notification (notify-send) or Telegram alert (telegram_send.py).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "also_telegram": {"type": "boolean", "description": "If true, also send via ~/.local/bin/telegram_send.py"},
                    },
                    "required": ["title", "body"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> dict:
        env = _wayland_env()
        try:
            if name == "cu_detect_session":
                comp, wins = _list_compositor_windows(env)
                return _ok({
                    "compositor": comp,
                    "wayland_display": env.get("WAYLAND_DISPLAY"),
                    "niri_socket": env.get("NIRI_SOCKET"),
                    "hyprland_signature": env.get("HYPRLAND_INSTANCE_SIGNATURE"),
                    "window_count": len(wins),
                    "wtype_path": _find_wtype(),
                    "uinput_type_available": Path("/home/aesc/.local/bin/uinput_type").exists(),
                    "cua_driver_available": Path("/home/aesc/.local/bin/cua-driver").exists(),
                })

            elif name == "cu_list_windows":
                comp, wins = _list_compositor_windows(env)
                q = args.get("filter_query", "").strip().lower()
                if q:
                    wins = [
                        w for w in wins
                        if q in str(w.get("app_id", "")).lower() or q in str(w.get("title", "")).lower()
                    ]
                return _ok({"compositor": comp, "count": len(wins), "windows": wins})

            elif name == "cu_focus_window":
                comp, wins = _list_compositor_windows(env)
                target_id = args.get("window_id")
                query = args.get("app_id_or_title", "").lower()
                if not target_id and query:
                    for w in wins:
                        if query in str(w.get("app_id", "")).lower() or query in str(w.get("title", "")).lower():
                            target_id = str(w.get("id"))
                            break
                if not target_id:
                    return _err("No matching window found to focus")
                if comp == "niri":
                    subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(target_id)], env=env, timeout=5)
                elif comp == "hyprland":
                    subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{target_id}"], env=env, timeout=5)
                elif comp == "sway":
                    subprocess.run(["swaymsg", f"[con_id={target_id}] focus"], env=env, timeout=5)
                _, after_wins = _list_compositor_windows(env)
                focused = [w for w in after_wins if w.get("is_focused")]
                return _ok({"compositor": comp, "requested_id": target_id, "focused_window": focused[0] if focused else None})

            elif name == "cu_close_window":
                comp, _ = _list_compositor_windows(env)
                app_id = args.get("app_id")
                win_id = args.get("window_id")
                if comp == "niri" and win_id:
                    subprocess.run(["niri", "msg", "action", "close-window", "--id", str(win_id)], env=env, timeout=5)
                elif comp == "sway" and app_id:
                    subprocess.run(["swaymsg", f'[app_id="{app_id}"] kill'], env=env, timeout=5)
                elif app_id:
                    subprocess.run(["pkill", "-f", app_id], env=env, timeout=5)
                time.sleep(0.3)
                _, after_wins = _list_compositor_windows(env)
                return _ok({"remaining_window_count": len(after_wins), "windows": after_wins})

            elif name == "cu_launch_detached":
                cmd = args["command"]
                if args.get("in_kitty_monitor"):
                    full_cmd = f"nohup kitty --hold -e {cmd} >/dev/null 2>&1 &"
                else:
                    full_cmd = f"nohup {cmd} >/dev/null 2>&1 &"
                subprocess.Popen(full_cmd, shell=True, env=env)
                time.sleep(0.5)
                _, wins = _list_compositor_windows(env)
                return _ok({"launched": full_cmd, "window_count": len(wins)})

            elif name == "cu_take_screenshot":
                scratch = Path("/home/aesc/.hermes/cache/scratch")
                scratch.mkdir(parents=True, exist_ok=True)
                out = Path(args.get("output_path") or (scratch / f"screenshot_{int(time.time())}.png"))
                cmd = ["grim"]
                if args.get("region"):
                    cmd.extend(["-g", args["region"]])
                cmd.append(str(out))
                res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)
                if res.returncode != 0:
                    return _err(f"grim failed: {res.stderr}")
                return _ok({"screenshot_path": str(out), "size_bytes": out.stat().st_size})

            elif name == "cu_screenshot_ocr":
                shot = self.call_tool("cu_take_screenshot", {"region": args.get("region")})
                if shot.get("isError"):
                    return shot
                shot_data = json.loads(shot["content"][0]["text"])
                img_path = shot_data["screenshot_path"]
                ocr_py = "/home/aesc/.local/share/hermes-ocr/venv/bin/python"
                code = f"""
import sys, json
from pathlib import Path
sys.path.insert(0, "/home/aesc/.local/bin")
import scan_work_files as swf
lines = swf.extract_text_from_image(Path({json.dumps(img_path)}))
print(json.dumps({{"screenshot_path": {json.dumps(img_path)}, "line_count": len(lines), "lines": lines}}, ensure_ascii=False))
"""
                res = subprocess.run([ocr_py, "-c", code], capture_output=True, text=True, timeout=180)
                for ln in reversed(res.stdout.splitlines()):
                    if ln.startswith("{"):
                        return _ok(json.loads(ln))
                return _err(res.stderr or "OCR failed")

            elif name == "cu_type_text":
                wtype = _find_wtype()
                text = args["text"]
                if wtype:
                    cmd = [wtype, text]
                    if args.get("press_enter"):
                        cmd.extend(["-k", "Return"])
                    res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)
                    return _ok({"method": "wtype", "exit_code": res.returncode, "typed_chars": len(text)})
                uinput = Path("/home/aesc/.local/bin/uinput_type")
                if uinput.exists():
                    tokens = [f"type:{text}"]
                    if args.get("press_enter"):
                        tokens.extend(["sleep:150", "enter"])
                    res = subprocess.run([str(uinput), *tokens], env=env, capture_output=True, text=True, timeout=10)
                    return _ok({"method": "uinput_type", "exit_code": res.returncode, "typed_chars": len(text)})
                return _err("Neither wtype nor uinput_type binary found")

            elif name == "cu_send_key":
                wtype = _find_wtype()
                if not wtype:
                    return _err("wtype not found")
                key_spec = args["key"]
                if "+" in key_spec:
                    mod, k = key_spec.split("+", 1)
                    cmd = [wtype, "-M", mod.lower(), "-k", k, "-m", mod.lower()]
                else:
                    cmd = [wtype, "-k", key_spec]
                res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=10)
                return _ok({"key": key_spec, "exit_code": res.returncode})

            elif name == "cu_clipboard_get":
                res = subprocess.run(["wl-paste", "--no-newline"], env=env, capture_output=True, text=True, timeout=5)
                return _ok({"clipboard": res.stdout, "exit_code": res.returncode})

            elif name == "cu_clipboard_set":
                res = subprocess.run(["wl-copy"], input=args["text"], env=env, capture_output=True, text=True, timeout=5)
                return _ok({"copied_chars": len(args["text"]), "exit_code": res.returncode})

            elif name == "cu_media_status":
                p_stat = subprocess.run(["playerctl", "status"], env=env, capture_output=True, text=True, timeout=3)
                p_meta = subprocess.run(["playerctl", "metadata", "--format", "{{artist}} - {{title}} ({{playerName}})"], env=env, capture_output=True, text=True, timeout=3)
                vol = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], env=env, capture_output=True, text=True, timeout=3)
                return _ok({
                    "player_status": p_stat.stdout.strip() or "Stopped",
                    "track": p_meta.stdout.strip(),
                    "volume": vol.stdout.strip(),
                })

            elif name == "cu_media_control":
                act = args["action"]
                res = subprocess.run(["playerctl", act], env=env, capture_output=True, text=True, timeout=5)
                return _ok({"action": act, "exit_code": res.returncode, "stderr": res.stderr.strip()})

            elif name == "cu_workspace_switch":
                ws = str(args["workspace"])
                comp, _ = _list_compositor_windows(env)
                if comp == "niri":
                    res = subprocess.run(["niri", "msg", "action", "focus-workspace", ws], env=env, capture_output=True, text=True, timeout=5)
                elif comp == "hyprland":
                    res = subprocess.run(["hyprctl", "dispatch", "workspace", ws], env=env, capture_output=True, text=True, timeout=5)
                else:
                    res = subprocess.run(["swaymsg", f"workspace {ws}"], env=env, capture_output=True, text=True, timeout=5)
                return _ok({"compositor": comp, "workspace": ws, "exit_code": res.returncode})

            elif name == "cu_system_vitals":
                mem = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5).stdout
                df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5).stdout
                up = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5).stdout.strip()
                return _ok({"uptime": up, "memory": mem, "disk_root": df})

            elif name == "cu_send_desktop_notification":
                if shutil.which("notify-send"):
                    subprocess.run(["notify-send", args["title"], args["body"]], env=env, timeout=5)
                if args.get("also_telegram") and Path("/home/aesc/.local/bin/telegram_send.py").exists():
                    subprocess.run(["/home/aesc/.local/bin/telegram_send.py", f"{args['title']}\n{args['body']}"], timeout=15)
                return _ok({"sent": True, "title": args["title"]})

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
                    "serverInfo": {"name": "desktop-computer-use-mcp", "version": "1.0.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools()}}
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
    DesktopComputerUseMcpServer().serve_stdio()
