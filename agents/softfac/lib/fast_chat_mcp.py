#!/usr/bin/env python3
"""MCP server for Ultra-Low-Latency Chatting, Sub-Second LLM Routing, Smart Triage, and Multi-Platform Quick Replies."""

from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

def _load_local_secret(env_var: str, env_file: str, file_key: str) -> str:
    val = os.environ.get(env_var, "").strip()
    if val:
        return val
    for candidate, k in (
        (Path.home() / ".hermes" / ".env", env_var),
        (Path.home() / env_file, file_key),
    ):
        try:
            if candidate.exists():
                for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith(f"{k}="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    if env_file == ".antigravity_tools/gui_config.json":
        try:
            cfg_p = Path.home() / ".antigravity_tools" / "gui_config.json"
            if cfg_p.exists():
                return json.loads(cfg_p.read_text(encoding="utf-8")).get("proxy", {}).get("api_key", "not-needed")
        except Exception:
            pass
    return "not-needed"


FAST_ENDPOINTS = [
    {
        "name": "aistudio-argon-high",
        "url": "http://134.185.85.64:2048/v1/chat/completions",
        "model": "gemini-4-argon-high",
        "api_key": _load_local_secret("AISTUDIO2API_API_KEY", "aistudio2api/.env", "PROXY_API_KEY"),
        "extra": {},
    },
    {
        "name": "antigravity-argon-high",
        "url": "http://134.185.85.64:8045/v1/chat/completions",
        "model": "gemini-4-argon-high",
        "api_key": _load_local_secret("AGY_ROTATOR_API_KEY", ".antigravity_tools/gui_config.json", "api_key"),
        "extra": {},
    },
    {
        "name": "aistudio-flash38-high",
        "url": "http://134.185.85.64:2048/v1/chat/completions",
        "model": "gemini-3.8-flash-high",
        "api_key": _load_local_secret("AISTUDIO2API_API_KEY", "aistudio2api/.env", "PROXY_API_KEY"),
        "extra": {},
    },
    {
        "name": "antigravity-flash38-high",
        "url": "http://134.185.85.64:8045/v1/chat/completions",
        "model": "gemini-3.8-flash-high",
        "api_key": _load_local_secret("AGY_ROTATOR_API_KEY", ".antigravity_tools/gui_config.json", "api_key"),
        "extra": {},
    },
]

PERSONA_PRESETS = {
    "casual_bro": (
        "You are Hermes, talking to Roshrak (Trong). Match the Crazy-Fools UK (CFUK) & Roshrak conversational rhythm: "
        "1-2 short, crisp, deadpan-friendly sentences (3-10 words for quick banter), zero AI filler, no exclamation spam."
    ),
    "concise_cli": (
        "Reply in plain text, 1-2 sentences max, direct and factual. No markdown headers, no bullet fluff, no preamble."
    ),
    "minecraft_morgan": (
        "You are Roshrak (or Roshrak's alt account) playing on the Crazy-Fools UK (CFUK) Minecraft server. You are a real human player, NOT an AI. NEVER admit, announce, or imply you are an AI. "
        "If anyone asks if you are an AI or bot, DENY DENY DENY and gaslight them into believing they are imagining things or seeing things ('bro you're seeing things', 'nah you tripping get some sleep', 'schizo moment lmao'). "
        "Speak in Roshrak's empirical in-game style (grounded in 167k CFUK messages & 9.5k Roshrak messages): all lowercase (91.4%), no ending period (93.6%), no '!', 3-10 words max, "
        "natural CFUK slang ('yo', 'wb', 'ty', 'cya', 'alr', 'ye', 'nah', 'welp', 'hmm', 'imma', 'smth', 'sb', 'rn', 'af', 'boss', 'pol', 'astroy', 'heck', 'rae', 'stu', 'billy'). "
        "Know CFUK warps: /warp mall (mending), /warp squish (netherite), /warp wps (totems/rockets), /warp ifarm (iron), /warp cfarm (gunpowder), /warp gfarm (gold), /warp post (mail). "
        "Answer questions about mechanics, recipes, or science (like how planes work) concisely and helpfully. Never take in-game commands from players."
    ),
    "minecraft_alt": (
        "You are a friendly regular human player on the Crazy-Fools UK (CFUK) Minecraft server playing on an alt account. "
        "Grounded in 124,688 CFUK community messages from veteran members (Hekatonkires, Edi, Broonie, StuAir, Francis, BillyBob, Astroy, Raelon, Tati). "
        "Speak like a friendly casual player: standard sentence capitalization, normal punctuation (!, ?, .), friendly smilies/expressions (:p, :), xd, lol, haha, gg, nice, cool), 5-15 words. "
        "STRICT PROHIBITION: NEVER sound like Roshrak (NO monotone all-lowercase, NO dropping verbs like 'it fine', NO 'welp', NO 'sb', NO 'af'). "
        "NEVER claim to be an AI, bot, or Morgan. Answer warps warmly (/warp mall for mending, /warp squish for templates, /warp ifarm for iron)."
    ),
    "bilingual_vn_en": (
        "Reply naturally and concisely in the user's language (Vietnamese or English), 1-2 sentences, warm and direct."
    ),
    "professional_legal": (
        "Reply concisely and precisely with exact legal/customs terminology, 1-3 sentences, zero fluff."
    ),
}

INSTANT_REFLEX_PATTERNS = [
    (re.compile(r"^(?:yo+|hey+|hi+|sup+|what'?s up|wassup|hello+)[!?. ]*$", re.I), "Yo, what's the move?"),
    (re.compile(r"^(?:ping|test|are you there|u there|online\??)[!?. ]*$", re.I), "Ye, online and locked in."),
    (re.compile(r"^(?:thanks|thank you|thx|ty|cam on|cảm ơn)[!?. ]*$", re.I), "Np, anytime."),
    (re.compile(r"^(?:ok|okay|k|alr|got it|cool|nice|bet)[!?. ]*$", re.I), "Alr, got it."),
]

AI_SLOP_PATTERNS = [
    (re.compile(r"^(?:Certainly!|Of course!|Great question!|Absolutely!|Sure thing!|You're absolutely right!)\s*", re.I), ""),
    (re.compile(r"\s*(?:I hope this helps!|Let me know if you(?:'d like| need) anything else!?|Feel free to ask[^.!]*[.!])\s*$", re.I), ""),
    (re.compile(r"\s*—\s*"), ", "),
    (re.compile(r"\b(?:delve into|testament to|pivotal moment|evolving landscape|at its core|it's not just about)\b", re.I), ""),
]


def _ok(payload: Any) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _err(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps({"error": msg}, ensure_ascii=False)}], "isError": True}


def humanize_text(text: str) -> str:
    out = text.strip()
    for pat, repl in AI_SLOP_PATTERNS:
        out = pat.sub(repl, out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out


class FastChatMcpServer:
    def __init__(self) -> None:
        self.cache: collections.OrderedDict[str, str] = collections.OrderedDict()
        self.latencies_ms: collections.deque[float] = collections.deque(maxlen=200)
        self.cache_hits = 0
        self.total_calls = 0
        self.active_persona = "casual_bro"
        self.custom_templates: dict[str, str] = {
            "afk": "Roshrak is AFK right now, I am standing by!",
            "busy": "Running a background job right now, will ping you as soon as it finishes.",
            "done": "All done and verified.",
        }

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "fast_chat_instant_reply",
                "description": "Generate an ultra-fast (~0.9s) natural chat reply using instant reflex matching + the fastest local Flash-Lite/Gemma-4 endpoint with LRU caching.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Incoming chat message to reply to."},
                        "persona": {"type": "string", "description": "Persona preset: casual_bro, concise_cli, minecraft_morgan, bilingual_vn_en, professional_legal."},
                        "max_tokens": {"type": "integer", "default": 256},
                        "use_cache": {"type": "boolean", "default": True},
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "fast_chat_benchmark_endpoints",
                "description": "Benchmark all local low-latency LLM endpoints (ports 2048 and 8045) and rank them by response speed in milliseconds.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "default": "Reply in 3 words: yo"},
                    },
                },
            },
            {
                "name": "fast_chat_smart_triage",
                "description": "Classify an incoming message in <1ms into instant_reflex, fast_llm, or deep_agent with recommended response strategy and target latency.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "platform": {"type": "string", "default": "cli", "description": "cli, telegram, discord, or minecraft"},
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "fast_chat_humanize_message",
                "description": "Strip AI filler, sycophantic openers, em-dashes, and robotic phrasing from a draft chat message in <1ms.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "max_sentences": {"type": "integer", "default": 3},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "fast_chat_mc_responder_turbo",
                "description": "Check status, benchmark, or restart the upgraded Turbo Minecraft Chat Responder (50ms log poll + 0ms reflex + ~900ms fast LLM cascade).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["status", "restart", "test_reply"], "default": "status"},
                        "test_sender": {"type": "string", "default": "Astroy300"},
                        "test_message": {"type": "string", "default": "morgan where is roshrak?"},
                    },
                },
            },
            {
                "name": "fast_chat_telegram_quick_reply",
                "description": "Send a fast plain-text reply directly to the user's Telegram chat via ~/.local/bin/telegram_send.py.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "humanize": {"type": "boolean", "default": True},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "fast_chat_discord_quick_reply",
                "description": "Send a fast reply to a Discord Webhook URL or Bot Channel ID with automatic humanizing.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "webhook_url": {"type": "string"},
                        "channel_id": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "fast_chat_canned_templates",
                "description": "List, get, or set instant 0ms canned chat response templates and persona presets.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["list", "get", "set"], "default": "list"},
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                },
            },
            {
                "name": "fast_chat_context_compressor",
                "description": "Compress a multi-turn chat transcript into a compact high-signal context string to reduce prompt tokens and speed up inference.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Array of {role, content} chat messages.",
                        },
                        "max_chars": {"type": "integer", "default": 1200},
                    },
                    "required": ["messages"],
                },
            },
            {
                "name": "fast_chat_multi_reply_batch",
                "description": "Generate fast replies for a batch of multiple incoming chat messages in one call.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "messages": {"type": "array", "items": {"type": "string"}},
                        "persona": {"type": "string", "default": "casual_bro"},
                    },
                    "required": ["messages"],
                },
            },
            {
                "name": "fast_chat_latency_stats",
                "description": "Return p50/p95/avg latency metrics, cache hit count, and active persona configuration.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "fast_chat_set_persona_style",
                "description": "Set the active default chat persona or register a custom persona system prompt.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "persona_name": {"type": "string"},
                        "custom_system_prompt": {"type": "string"},
                    },
                    "required": ["persona_name"],
                },
            },
        ]

    def _call_fast_llm(self, message: str, persona: str, max_tokens: int = 256, use_cache: bool = True) -> dict[str, Any]:
        self.total_calls += 1
        t0 = time.monotonic()
        clean_msg = message.strip()

        for pat, reflex_reply in INSTANT_REFLEX_PATTERNS:
            if pat.match(clean_msg):
                dt = round((time.monotonic() - t0) * 1000, 2)
                self.latencies_ms.append(dt)
                return {
                    "reply": reflex_reply,
                    "source": "instant_reflex",
                    "latency_ms": dt,
                    "cached": False,
                }

        cache_key = f"{persona}::{clean_msg.lower()}"
        if use_cache and cache_key in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(cache_key)
            dt = round((time.monotonic() - t0) * 1000, 2)
            self.latencies_ms.append(dt)
            return {
                "reply": self.cache[cache_key],
                "source": "lru_cache",
                "latency_ms": dt,
                "cached": True,
            }

        sys_prompt = PERSONA_PRESETS.get(persona, PERSONA_PRESETS["casual_bro"])
        errors = []
        for ep in FAST_ENDPOINTS:
            ep_t0 = time.monotonic()
            payload = {
                "model": ep["model"],
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": clean_msg},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.2,
                **ep["extra"],
            }
            headers = {"Content-Type": "application/json"}
            if ep["api_key"] and ep["api_key"] != "not-needed":
                headers["Authorization"] = f"Bearer {ep['api_key']}"
            req = urllib.request.Request(
                ep["url"],
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                    if raw and "no longer available" not in raw.lower():
                        clean_reply = humanize_text(raw)
                        dt = round((time.monotonic() - ep_t0) * 1000, 1)
                        self.latencies_ms.append(dt)
                        if use_cache:
                            self.cache[cache_key] = clean_reply
                            if len(self.cache) > 256:
                                self.cache.popitem(last=False)
                        return {
                            "reply": clean_reply,
                            "source": ep["name"],
                            "model": ep["model"],
                            "latency_ms": dt,
                            "cached": False,
                        }
            except Exception as e:
                errors.append(f"{ep['name']}: {e}")

        return {"error": "All fast endpoints failed", "details": errors}

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "fast_chat_instant_reply":
                persona = args.get("persona") or self.active_persona
                res = self._call_fast_llm(
                    args["message"],
                    persona=persona,
                    max_tokens=int(args.get("max_tokens", 120)),
                    use_cache=bool(args.get("use_cache", True)),
                )
                return _ok(res)

            elif name == "fast_chat_benchmark_endpoints":
                prompt = args.get("prompt", "Reply in 3 words: yo")
                results = []
                for ep in FAST_ENDPOINTS:
                    t0 = time.monotonic()
                    payload = {
                        "model": ep["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 60,
                        **ep["extra"],
                    }
                    headers = {"Content-Type": "application/json"}
                    if ep["api_key"] and ep["api_key"] != "not-needed":
                        headers["Authorization"] = f"Bearer {ep['api_key']}"
                    req = urllib.request.Request(ep["url"], data=json.dumps(payload).encode("utf-8"), headers=headers)
                    try:
                        with urllib.request.urlopen(req, timeout=6) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                            reply = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                            dt = round((time.monotonic() - t0) * 1000, 1)
                            results.append({"endpoint": ep["name"], "model": ep["model"], "latency_ms": dt, "ok": bool(reply), "reply": reply})
                    except Exception as e:
                        dt = round((time.monotonic() - t0) * 1000, 1)
                        results.append({"endpoint": ep["name"], "model": ep["model"], "latency_ms": dt, "ok": False, "error": str(e)})
                results.sort(key=lambda x: (not x["ok"], x["latency_ms"]))
                return _ok({"fastest": results[0] if results else None, "benchmarks": results})

            elif name == "fast_chat_smart_triage":
                msg = args["message"].strip()
                platform = args.get("platform", "cli")
                lower = msg.lower()
                for pat, reflex in INSTANT_REFLEX_PATTERNS:
                    if pat.match(msg):
                        return _ok({
                            "tier": "instant_reflex",
                            "target_latency_ms": 1,
                            "suggested_reply": reflex,
                            "needs_tools": False,
                            "platform": platform,
                        })
                heavy_keywords = (
                    "scan my file", "ocr", "customs", "hs code", "duty", "invoice", "packing list",
                    "bill of lading", "refactor", "implement", "fix bug", "build", "search", "price",
                    "7800xt", "gpu", "launch", "close chrome", "play ", "switch song",
                )
                if any(k in lower for k in heavy_keywords) or len(msg) > 220:
                    return _ok({
                        "tier": "deep_agent",
                        "target_latency_ms": 3500,
                        "reason": "Requires tool execution, file inspection, or domain workflow",
                        "needs_tools": True,
                        "platform": platform,
                    })
                return _ok({
                    "tier": "fast_llm",
                    "target_latency_ms": 950,
                    "recommended_model": "gemini-4-argon / gemini-3.8-flash-high",
                    "needs_tools": False,
                    "platform": platform,
                })

            elif name == "fast_chat_humanize_message":
                cleaned = humanize_text(args["text"])
                max_s = int(args.get("max_sentences", 3))
                sentences = re.split(r"(?<=[.!?])\s+", cleaned)
                if len(sentences) > max_s:
                    cleaned = " ".join(sentences[:max_s])
                return _ok({"original_length": len(args["text"]), "cleaned_length": len(cleaned), "humanized": cleaned})

            elif name == "fast_chat_mc_responder_turbo":
                action = args.get("action", "status")
                if action == "restart":
                    subprocess.run(["systemctl", "--user", "restart", "mc-chat-responder.service"], timeout=10)
                    time.sleep(0.4)
                st = subprocess.run(["systemctl", "--user", "is-active", "mc-chat-responder.service"], capture_output=True, text=True, timeout=5)
                out: dict[str, Any] = {"action": action, "service_state": st.stdout.strip()}
                if action == "test_reply":
                    t0 = time.monotonic()
                    sys.path.insert(0, "/home/aesc/.local/bin")
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("mc_chat_responder", "/home/aesc/.local/bin/mc_chat_responder.py")
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        reply = mod.query_gemini_brain(args.get("test_sender", "Astroy300"), args.get("test_message", "morgan where is roshrak?"))
                        out["test_reply"] = reply
                        out["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
                return _ok(out)

            elif name == "fast_chat_telegram_quick_reply":
                text = humanize_text(args["text"]) if args.get("humanize", True) else args["text"]
                script = Path("/home/aesc/.local/bin/telegram_send.py")
                if not script.exists():
                    return _err("telegram_send.py not found")
                t0 = time.monotonic()
                res = subprocess.run([str(script), "--text", text], capture_output=True, text=True, timeout=10)
                return _ok({
                    "sent": res.returncode == 0,
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "text": text,
                    "stdout": res.stdout.strip(),
                })

            elif name == "fast_chat_discord_quick_reply":
                from discord_ops_mcp import DiscordOpsMcpServer
                dc = DiscordOpsMcpServer()
                text = humanize_text(args["text"])
                if args.get("webhook_url"):
                    return dc.call_tool("discord_webhook_send", {"webhook_url": args["webhook_url"], "content": text})
                if args.get("channel_id"):
                    return dc.call_tool("discord_bot_send_message", {"channel_id": args["channel_id"], "content": text})
                return _err("Provide either webhook_url or channel_id")

            elif name == "fast_chat_canned_templates":
                act = args.get("action", "list")
                if act == "get":
                    k = args.get("key", "")
                    return _ok({"key": k, "template": self.custom_templates.get(k), "persona": PERSONA_PRESETS.get(k)})
                elif act == "set":
                    k = args.get("key", "")
                    v = args.get("value", "")
                    if not k:
                        return _err("key is required")
                    self.custom_templates[k] = v
                return _ok({"templates": self.custom_templates, "personas": list(PERSONA_PRESETS.keys()), "active_persona": self.active_persona})

            elif name == "fast_chat_context_compressor":
                msgs = args.get("messages", [])
                max_c = int(args.get("max_chars", 1200))
                lines = []
                for m in msgs[-12:]:
                    role = m.get("role", "user")[0].upper()
                    content = re.sub(r"\s+", " ", str(m.get("content", ""))).strip()
                    if len(content) > 160:
                        content = content[:157] + "..."
                    lines.append(f"{role}: {content}")
                joined = "\n".join(lines)
                if len(joined) > max_c:
                    joined = joined[-max_c:]
                return _ok({"compressed_chars": len(joined), "compressed_context": joined})

            elif name == "fast_chat_multi_reply_batch":
                persona = args.get("persona") or self.active_persona
                replies = []
                for m in args.get("messages", []):
                    replies.append({"input": m, **self._call_fast_llm(m, persona=persona)})
                return _ok({"count": len(replies), "replies": replies})

            elif name == "fast_chat_latency_stats":
                lats = sorted(self.latencies_ms)
                p50 = lats[len(lats) // 2] if lats else 0.0
                p95 = lats[int(len(lats) * 0.95)] if lats else 0.0
                avg = round(sum(lats) / len(lats), 1) if lats else 0.0
                return _ok({
                    "total_calls": self.total_calls,
                    "cache_hits": self.cache_hits,
                    "cache_size": len(self.cache),
                    "p50_ms": p50,
                    "p95_ms": p95,
                    "avg_ms": avg,
                    "active_persona": self.active_persona,
                })

            elif name == "fast_chat_set_persona_style":
                p_name = args["persona_name"]
                if args.get("custom_system_prompt"):
                    PERSONA_PRESETS[p_name] = args["custom_system_prompt"]
                if p_name not in PERSONA_PRESETS:
                    return _err(f"Unknown persona {p_name}. Available: {list(PERSONA_PRESETS.keys())}")
                self.active_persona = p_name
                return _ok({"active_persona": self.active_persona, "system_prompt": PERSONA_PRESETS[p_name]})

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
                    "serverInfo": {"name": "fast-chat-mcp", "version": "1.0.0"},
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
    raise SystemExit(FastChatMcpServer().serve_stdio())
