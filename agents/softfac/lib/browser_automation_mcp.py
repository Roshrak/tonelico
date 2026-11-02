#!/usr/bin/env python3
"""MCP server for Browser Automation, CDP Tab Reuse, YouTube Music Control, and Web Portals."""

from __future__ import annotations

import hashlib
import html.parser
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


def _ok(data: Any) -> dict:
    text = json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": msg}]}


class _HTMLTableParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: List[List[List[str]]] = []
        self._cur_table: List[List[str]] | None = None
        self._cur_row: List[str] | None = None
        self._cur_cell: List[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        t = tag.lower()
        if t == "table":
            self._cur_table = []
        elif t == "tr" and self._cur_table is not None:
            self._cur_row = []
        elif t in ("td", "th") and self._cur_row is not None:
            self._cur_cell = []

    def handle_data(self, data: str) -> None:
        if self._cur_cell is not None:
            self._cur_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("td", "th") and self._cur_cell is not None and self._cur_row is not None:
            self._cur_row.append(" ".join("".join(self._cur_cell).split()))
            self._cur_cell = None
        elif t == "tr" and self._cur_row is not None and self._cur_table is not None:
            if any(self._cur_row):
                self._cur_table.append(self._cur_row)
            self._cur_row = None
        elif t == "table" and self._cur_table is not None:
            if self._cur_table:
                self.tables.append(self._cur_table)
            self._cur_table = None


def _get_cdp_targets(port: int = 9222) -> List[dict]:
    for p in (port, 9222, 9229, 9333):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/json/list", timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
                if isinstance(data, list):
                    return data
        except Exception:
            continue
    return []


class BrowserAutomationMcpServer:
    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "browser_status_and_tabs",
                "description": "Inspect running Chromium/browser processes and open CDP tabs (title, URL, targetId).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cdp_port": {"type": "integer", "description": "CDP port (default 9222)"},
                    },
                },
            },
            {
                "name": "browser_open_or_reuse_url",
                "description": "Open a URL in Chromium reuse-first (reuses existing browser window or launches detached with remote-debugging-port).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target http/https URL"},
                        "close_existing_first": {"type": "boolean", "description": "If true, close old Chromium first to prevent audio/tab overlap"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "browser_close_all_chromium",
                "description": "Close all Chromium/Chrome windows cleanly and stop media playback, verifying zero remaining processes.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "browser_ytmusic_control",
                "description": "Control YouTube Music (play, pause, next, prev, search <query>, status) in the existing tab via ~/.local/bin/ytmusic_control.py.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "play, pause, next, prev, status, or search <song name>"},
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "browser_cdp_activate_tab",
                "description": "Activate (bring to front) a specific CDP browser tab by targetId or URL/title substring.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "targetId or substring of tab URL/title"},
                        "cdp_port": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "browser_cdp_close_tab",
                "description": "Close a specific CDP browser tab by targetId or URL/title substring without closing the whole browser.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "targetId or substring of tab URL/title"},
                        "cdp_port": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "browser_cdp_open_new_tab",
                "description": "Open a new tab via CDP HTTP endpoint (/json/new?<url>) in an already-running debuggable browser.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "cdp_port": {"type": "integer"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "browser_fetch_json_api",
                "description": "Execute an HTTP GET/POST JSON API request with custom headers and return status, headers, and parsed body.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "method": {"type": "string", "description": "GET or POST (default GET)"},
                        "headers": {"type": "object"},
                        "body_json": {"type": "object"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "browser_extract_html_tables",
                "description": "Fetch a web page URL or local HTML file and extract all HTML <table> elements as structured rows.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url_or_path": {"type": "string", "description": "http(s) URL or local file path"},
                    },
                    "required": ["url_or_path"],
                },
            },
            {
                "name": "browser_extract_links_and_forms",
                "description": "Extract all hyperlinks (<a href>) and form input fields from a URL or local HTML file.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url_or_path": {"type": "string"},
                    },
                    "required": ["url_or_path"],
                },
            },
            {
                "name": "browser_download_file",
                "description": "Download a file from a URL to a local path (e.g. ~/work files or ~/Downloads) and verify its SHA-256 hash and size.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "output_path": {"type": "string", "description": "Destination file path"},
                    },
                    "required": ["url", "output_path"],
                },
            },
            {
                "name": "browser_gpu_market_search",
                "description": "Run ~/.local/bin/gpu_market_search.py for concrete GPU/hardware listings, prices in VND, and visual comparison chart.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "GPU model or hardware search query (e.g. RX 7800 XT, RTX 4070 Super)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "browser_naric_diploma_lookup",
                "description": "Return verification portal details and lookup fields for Cục Quản lý Chất lượng (naric.edu.vn) diploma recognition.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "full_name": {"type": "string"},
                        "certificate_no": {"type": "string"},
                    },
                },
            },
            {
                "name": "browser_customs_portal_links",
                "description": "Get official Vietnam Customs (customs.gov.vn), National Single Window (vnsw.gov.vn), and FTA C/O verification portal URLs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "all, customs, vnsw, co_verification, tax"},
                    },
                },
            },
            {
                "name": "browser_check_site_headers",
                "description": "Inspect HTTP status code, redirect chain, server headers, and WAF/Cloudflare indicators for a URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "browser_wayback_snapshot_lookup",
                "description": "Check Internet Archive Wayback Machine availability for a blocked or offline URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                    },
                    "required": ["url"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> dict:
        try:
            if name == "browser_status_and_tabs":
                ps = subprocess.run(["pgrep", "-af", "chromium|chrome"], capture_output=True, text=True, timeout=5)
                procs = [ln for ln in ps.stdout.splitlines() if "browser_automation_mcp" not in ln]
                tabs = _get_cdp_targets(int(args.get("cdp_port", 9222)))
                return _ok({
                    "running": len(procs) > 0,
                    "process_count": len(procs),
                    "cdp_tabs_count": len(tabs),
                    "cdp_tabs": [
                        {"id": t.get("id"), "title": t.get("title"), "url": t.get("url"), "type": t.get("type")}
                        for t in tabs
                    ],
                })

            elif name == "browser_open_or_reuse_url":
                url = args["url"]
                if args.get("close_existing_first"):
                    subprocess.run("playerctl stop 2>/dev/null || true", shell=True, timeout=5)
                    subprocess.run("swaymsg '[app_id=\"chromium\"] kill' 2>/dev/null || pkill -f 'chrome|chromium' || true", shell=True, timeout=5)
                    time.sleep(0.4)
                cmd = f'nohup /run/current-system/sw/bin/chromium --remote-debugging-port=9222 "{url}" >/dev/null 2>&1 &'
                subprocess.Popen(cmd, shell=True)
                time.sleep(0.8)
                return self.call_tool("browser_status_and_tabs", {})

            elif name == "browser_close_all_chromium":
                subprocess.run("playerctl stop 2>/dev/null || true", shell=True, timeout=5)
                subprocess.run("swaymsg '[app_id=\"chromium\"] kill' 2>/dev/null || pkill -f 'chrome|chromium' || true", shell=True, timeout=5)
                time.sleep(0.4)
                ps = subprocess.run(["pgrep", "-af", "chromium|chrome"], capture_output=True, text=True, timeout=5)
                procs = [ln for ln in ps.stdout.splitlines() if "browser_automation_mcp" not in ln]
                return _ok({"closed": len(procs) == 0, "remaining_processes": len(procs)})

            elif name == "browser_ytmusic_control":
                script = Path("/home/aesc/.local/bin/ytmusic_control.py")
                cmd_str = args["command"].strip()
                if script.exists():
                    res = subprocess.run([str(script), *cmd_str.split()], capture_output=True, text=True, timeout=30)
                    return _ok({"exit_code": res.returncode, "stdout": res.stdout.strip(), "stderr": res.stderr.strip()})
                return _err("ytmusic_control.py not found")

            elif name == "browser_cdp_activate_tab":
                port = int(args.get("cdp_port", 9222))
                q = args["query"].lower()
                tabs = _get_cdp_targets(port)
                for t in tabs:
                    if q == str(t.get("id", "")).lower() or q in str(t.get("url", "")).lower() or q in str(t.get("title", "")).lower():
                        tid = t["id"]
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/activate/{tid}", timeout=3) as r:
                            return _ok({"activated": tid, "title": t.get("title"), "url": t.get("url"), "response": r.read().decode()})
                return _err(f"No CDP tab matching '{args['query']}'")

            elif name == "browser_cdp_close_tab":
                port = int(args.get("cdp_port", 9222))
                q = args["query"].lower()
                tabs = _get_cdp_targets(port)
                for t in tabs:
                    if q == str(t.get("id", "")).lower() or q in str(t.get("url", "")).lower() or q in str(t.get("title", "")).lower():
                        tid = t["id"]
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tid}", timeout=3) as r:
                            return _ok({"closed_tab": tid, "title": t.get("title"), "response": r.read().decode()})
                return _err(f"No CDP tab matching '{args['query']}'")

            elif name == "browser_cdp_open_new_tab":
                port = int(args.get("cdp_port", 9222))
                url = args["url"]
                req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{url}", method="PUT")
                with urllib.request.urlopen(req, timeout=5) as r:
                    return _ok(json.loads(r.read().decode("utf-8", "replace")))

            elif name == "browser_fetch_json_api":
                url = args["url"]
                method = args.get("method", "GET").upper()
                headers = {"User-Agent": "HermesAgent/2.0", **(args.get("headers") or {})}
                data = None
                if args.get("body_json") is not None:
                    data = json.dumps(args["body_json"]).encode("utf-8")
                    headers.setdefault("Content-Type", "application/json")
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        parsed = raw[:4000]
                    return _ok({"status": resp.status, "url": resp.geturl(), "data": parsed})

            elif name == "browser_extract_html_tables":
                src = args["url_or_path"]
                p = Path(src)
                if p.exists() and p.is_file():
                    raw_html = p.read_text(encoding="utf-8", errors="replace")
                else:
                    req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        raw_html = resp.read().decode("utf-8", "replace")
                parser = _HTMLTableParser()
                parser.feed(raw_html)
                return _ok({"table_count": len(parser.tables), "tables": parser.tables})

            elif name == "browser_extract_links_and_forms":
                src = args["url_or_path"]
                p = Path(src)
                if p.exists() and p.is_file():
                    raw_html = p.read_text(encoding="utf-8", errors="replace")
                else:
                    req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        raw_html = resp.read().decode("utf-8", "replace")
                links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw_html, re.I | re.S)
                inputs = re.findall(r'<input[^>]+>', raw_html, re.I)
                clean_links = [{"href": h, "text": re.sub(r"<[^>]+>", "", t).strip()} for h, t in links[:200]]
                return _ok({"link_count": len(clean_links), "links": clean_links, "input_count": len(inputs), "inputs": inputs[:100]})

            elif name == "browser_download_file":
                url = args["url"]
                out = Path(args["output_path"]).expanduser().resolve()
                out.parent.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    content = resp.read()
                out.write_bytes(content)
                return _ok({
                    "downloaded_to": str(out),
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                })

            elif name == "browser_gpu_market_search":
                script = Path("/home/aesc/.local/bin/gpu_market_search.py")
                res = subprocess.run([str(script), args["query"]], capture_output=True, text=True, timeout=120)
                return _ok({"exit_code": res.returncode, "output": res.stdout, "stderr": res.stderr})

            elif name == "browser_naric_diploma_lookup":
                return _ok({
                    "portal_url": "https://naric.edu.vn/front/tra-cuu-van-bang",
                    "authority": "Trung tâm Công nhận văn bằng (VN-NARIC) - Cục Quản lý Chất lượng - Bộ GD&ĐT",
                    "search_fields": {
                        "ho_va_ten": args.get("full_name", "Hoàng Văn Trọng"),
                        "so_vao_so": args.get("certificate_no", ""),
                    },
                })

            elif name == "browser_customs_portal_links":
                portals = {
                    "customs_vietnam": "https://www.customs.gov.vn",
                    "vnaccs_tariff_lookup": "https://www.customs.gov.vn/index.jsp?pageId=136&cid=1294",
                    "national_single_window_vnsw": "https://vnsw.gov.vn",
                    "ecosys_co_vietnam": "https://ecosys.gov.vn",
                    "co_form_e_china_check": "http://origin.customs.gov.cn",
                    "co_form_ak_korea_check": "https://www.customs.go.kr",
                    "eu_rex_validation": "https://ec.europa.eu/taxation_customs/dds2/eos/rex_validation.jsp",
                }
                return _ok(portals)

            elif name == "browser_check_site_headers":
                req = urllib.request.Request(args["url"], headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        hdrs = dict(resp.headers.items())
                        return _ok({"status": resp.status, "final_url": resp.geturl(), "headers": hdrs})
                except urllib.error.HTTPError as e:
                    return _ok({"status": e.code, "headers": dict(e.headers.items()), "error": str(e)})

            elif name == "browser_wayback_snapshot_lookup":
                api = f"https://archive.org/wayback/available?url={urllib.parse.quote(args['url'])}"
                with urllib.request.urlopen(api, timeout=15) as resp:
                    return _ok(json.loads(resp.read().decode("utf-8", "replace")))

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
                    "serverInfo": {"name": "browser-automation-mcp", "version": "1.0.0"},
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
    BrowserAutomationMcpServer().serve_stdio()
