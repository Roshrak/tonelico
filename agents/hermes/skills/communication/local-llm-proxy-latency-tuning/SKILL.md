---
name: local-llm-proxy-latency-tuning
description: "Use when chat or local LLM proxy responses are slow."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [latency, aistudio2api, agy-rotator, fast-chat, gemini, inference, proxy]
---

# Local LLM Proxy & Chat Latency Tuning

## When to Use
- Interactive Hermes CLI or Gateway chat turns take >5–10 seconds to respond.
- Background chat responders (`mc-chat-responder.service`, `fast-chat-mcp`, Telegram/Discord bridges) exhibit multi-second lag or empty responses.
- Routing or benchmarking across the local inference proxy stack:
  - `127.0.0.1:2048` (`aistudio2api.service` — Camoufox browser-pool adapter for Google AI Studio).
  - `127.0.0.1:8045` (`agy-rotator` rootless Docker proxy — direct HTTP API pool).
  - `127.0.0.1:8765` (`agy-bridge.service` — CLI subprocess wrapper around `agy`).

## Procedure

### 1. Diagnose Interactive Hermes Chat Latency (`aistudio2api` on Port 2048)
1. Inspect recent request telemetry in the `aistudio2api` journal:
   ```bash
   journalctl --user -u aistudio2api -n 25 --no-pager | grep -E 'request\.finished|request\.progress'
   ```
   Check four fields on `request.finished` events:
   - `source`: Which Google account handled the turn. If `source` changes on every consecutive turn, `routing_strategy` is set to `round-robin`, which invalidates Google's server-side prompt cache (`cached_tokens`) on every message.
   - `queue_ms`: Time spent waiting for a Camoufox WAA browser worker rebuild or account switch after an HTTP 429 cooldown.
   - `parameters.thinking`: Thinking budget applied (`low`, `medium`, `high`, `xhigh`).
   - `first_event_ms`: Time to first streamed token.

2. Switch `aistudio2api` to sticky `fill-first` routing, `auto` first-event hedging, and SpiderMonkey WAA backend (both persistently in `/home/aesc/aistudio2api/.env` and live via `PUT /api/config`):
   - Update `/home/aesc/aistudio2api/.env`:
     - `ROUTING_STRATEGY=fill-first`
     - `FIRST_EVENT_HEDGE=auto`
     - `WAA_BACKEND=spidermonkey` (in-process engine saving ~400–600MB RAM per account vs browser workers)
     - `UPSTREAM_CHANNELS=playground` (bypasses deprecated build channel)
     - `WARM_WORKER_LIMIT=13`, `WARM_STARTUP_CONCURRENCY=13`, `PER_ACCOUNT_CONCURRENCY=4`
   - When configuring `PROXY_API_KEY` on `aistudio2api`, synchronize all calling clients (`~/.hermes/config.yaml`, `~/.local/bin/agy`, `~/.local/lib/fast_chat_mcp.py`) with matching tokens.
   - Apply live without restarting Camoufox workers by fetching the full config object from `GET http://127.0.0.1:2048/api/config` (using HTTP Basic Auth with `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `/home/aesc/aistudio2api/.env`), setting `"routing_strategy": "fill-first"` and `"first_event_hedge": "auto"`, and sending the complete modified JSON object back via `PUT http://127.0.0.1:2048/api/config`.

3. Lower Hermes reasoning effort for low-latency chat:
   - Run `hermes config set agent.reasoning_effort low --force`.
   - Restart `hermes-gateway.service` (`systemctl --user restart hermes-gateway.service`) so gateway sessions pick up `low` effort.
   - In an already-running interactive CLI session, instruct the user to run `/reasoning low` (and `/compress` or `/new` if `input_tokens` exceeds 100k), because the CLI caches `self.reasoning_effort` in memory at startup.

### 2. Tune Sub-Second / Fast-Chat Responder Cascade (`fast-chat-mcp` & `mc-chat-responder`)
1. Use a 3-tier response hierarchy for real-time chat bots:
   - **Tier 1 (0ms Reflex)**: Match deterministic commands (`/tpaccept`, `/spawn`, `/home`, `/warp`, jump) and frequent status questions (`where u`, `where is roshrak`, `who are you`, greetings) in-process before any network call.
   - **Tier 2 (0ms LRU Cache)**: Cache normalized `(sender, message)` or `(persona, message)` replies in memory with TTL expiration.
   - **Tier 3 (~1.2s–1.8s Fast LLM Cascade)**: Route to `http://127.0.0.1:8045/v1/chat/completions` (`agy-rotator`) using `gemini-3.1-flash-lite` first and `gemini-3.8-flash-low` second, with `max_tokens: 256` and `Authorization: Bearer <AGY_ROTATOR_API_KEY>`.
2. When deploying updates to `/home/aesc/.local/bin/mc_chat_responder.py`:
   - Edit the source of truth at `/home/aesc/tonelico/nixos/home/files/bin/mc_chat_responder.py`.
   - Unlink `/home/aesc/.local/bin/mc_chat_responder.py` (`rm -f`) before copying the updated script over, then `chmod +x` and run `systemctl --user restart mc-chat-responder.service`.
3. Verify end-to-end latency with `mcp__fast_chat_mcp__fast_chat_mc_responder_turbo(action="test_reply")` or `mcp__fast_chat_mcp__fast_chat_benchmark_endpoints`.

## Pitfalls
- Send the full configuration object returned by `GET /api/config` when calling `PUT http://127.0.0.1:2048/api/config` — partial JSON payloads fail validation with HTTP 400.
- Synchronize client API keys whenever configuring `PROXY_API_KEY` on `aistudio2api` — update `~/.hermes/config.yaml` (`api_key`), `~/.local/bin/agy` (`GEMINI_API_KEY`), and `~/.local/lib/fast_chat_mcp.py` to match, and clear any stale `"last_status": "exhausted"` / `401` entry under `credential_pool["custom:aistudio2api"]` in `~/.hermes/auth.json` so Hermes does not skip the primary provider for a transient 401 recorded during key rotation.
- Use explicit `-low` model IDs (e.g., `gemini-3.8-flash-low`) rather than bare model names (`gemini-3.8-flash` with `"reasoning_effort": "low"`) in fast-chat cascades when `MODEL_MAPPING` in `aistudio2api` maps bare model names to `(high)` — an explicit `(high)` target in `MODEL_MAPPING` overrides the request body's `reasoning_effort` parameter and forces high thinking latency.
- Avoid the deprecated `build` upstream channel in `aistudio2api`; set `UPSTREAM_CHANNELS=playground` to prevent timeouts and legacy schema deprecation errors.
- Set `WAA_BACKEND=spidermonkey` in `aistudio2api` to avoid heavy Camoufox browser processes and reclaim ~400–600MB RAM per account.
- Keep `aistudio2api-watchdog.timer` (every 30s) active and pin `Xvfb` at `~/.local/share/nix-roots/aistudio2api-xvfb` — if `aistudio2api` boots before DNS is ready or loses its internal generation worker (`Error 503: AIStudio2API 生成服务已停止`), the watchdog queries `GET http://127.0.0.1:2048/api/status` and triggers `POST http://127.0.0.1:2048/api/control/start` when `state == "STOPPED"`.
- Use `low` (not `minimal`) as `agent.reasoning_effort` when the active model is `gemini-4-argon` on `aistudio2api` — `gemini-4-argon` only declares `thinking_levels: ["LOW", "MEDIUM", "HIGH"]` in `/api/models`.
- Never place `tab_flash_lite_preview` at the top of a general chat responder cascade — it is a code tab-completion model that outputs `IGNORE` on instruction-heavy chat system prompts.
- Set `max_tokens >= 256` when calling thinking-capable Gemini or Gemma models (`gemma-4-26b-a4b-it`, `gemini-3.1-flash-lite`) and `continue` to the next fallback endpoint when `message.content` is empty (`""`) — small `max_tokens` budgets (`<=120`) get consumed by internal reasoning tokens, leaving `content` empty, and treating empty `content` the same as `"IGNORE"` silently drops the reply.
- Always `rm -f ~/.local/bin/mc_chat_responder.py` before copying over it — Home Manager links `~/.local/bin/mc_chat_responder.py` into `/nix/store`, so `cp` without `rm -f` fails on the read-only store target.
- When injecting keystrokes on Wayland/niri where `wtype` is absent, invoke `/home/aesc/.local/bin/uinput_type` with positional action tokens (`t`, `slash`, `sleep:<ms>`, `type:<text>`, `enter`, `esc`) rather than raw text or flags.
