---
name: local-llm-proxy-latency-tuning
description: "Use when local LLM proxies lag or accounts hit 429 limits."
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
- Auditing `aistudio2api` (`127.0.0.1:2048`) or `antigravity-manager` (`127.0.0.1:8045`) accounts to see which accounts hit quota/rate limits (HTTP 429) and which still have quota.
- Background chat responders (`mc-chat-responder.service`, `fast-chat-mcp`, Telegram/Discord bridges) exhibit multi-second lag or empty responses.
- Routing or benchmarking across the local inference proxy stack:
  - `127.0.0.1:2048` (`aistudio2api.service` — Camoufox/SpiderMonkey adapter for Google AI Studio).
  - `127.0.0.1:8045` (`antigravity-manager` rootless Docker proxy — direct HTTP API pool).

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

2. Audit per-account quota and HTTP 429 cooldown state across `aistudio2api`:
   - Query `GET http://127.0.0.1:2048/api/accounts` (for `id`, `benefit_tier`, `state`, and `models`) and `GET http://127.0.0.1:2048/api/cooldowns` (or `/home/aesc/aistudio2api/auth/<email>/runtime-state.json`) for active cooldown entries.
   - Parse `/home/aesc/aistudio2api/runtime/logs/aistudio2api.log` by `source` (`<email>`) for `429` / `账号冷却` / `Account cooldown` (`resume=`) and `request.finished` events since the last daily quota reset (`15:00 +07:00` / `08:00 UTC`) to classify each account into:
     1. Actively serving or clean (no 429 since last 15:00 +07:00 reset).
     2. Actively in `/api/cooldowns`.
     3. Rate-limited upstream (`HTTP 429` logged with `resume=` still in the future) whose local cooldown tag was wiped by a service restart, auth backup restore, or manual clear.

3. Switch `aistudio2api` to sticky `fill-first` routing, `auto` first-event hedging, and SpiderMonkey WAA backend (both persistently in `/home/aesc/aistudio2api/.env` and live via `PUT /api/config`):
   - Update `/home/aesc/aistudio2api/.env`:
     - `ROUTING_STRATEGY=fill-first`
     - `FIRST_EVENT_HEDGE=auto`
     - `WAA_BACKEND=spidermonkey` (in-process engine saving ~400–600MB RAM per account vs browser workers)
     - `UPSTREAM_CHANNELS=playground` (bypasses deprecated build channel)
     - `WARM_WORKER_LIMIT=2`, `MAX_ACTIVE_WORKERS=4`, `WARM_STARTUP_CONCURRENCY=2`, `PER_ACCOUNT_CONCURRENCY=4`, `REQUEST_BODY_LOG=false`, `LOG_MAX_TOTAL_MB=50` (with `fill-first` routing only 1–2 workers are active at a time; capping warm/active SpiderMonkey workers at 2/4 and setting `GOGC=50` + `GOMEMLIMIT=256MiB` in `aistudio2api.service` keeps RSS around ~200 MB instead of 600–893 MB)
   - When configuring `PROXY_API_KEY` on `aistudio2api`, synchronize all calling clients (`~/.hermes/config.yaml`, `~/.local/bin/agy`, `~/.local/lib/fast_chat_mcp.py`) with matching tokens.
   - Apply live without restarting Camoufox workers by fetching the full config object from `GET http://127.0.0.1:2048/api/config` (using HTTP Basic Auth with `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `/home/aesc/aistudio2api/.env`), setting `"routing_strategy": "fill-first"` and `"first_event_hedge": "auto"`, and sending the complete modified JSON object back via `PUT http://127.0.0.1:2048/api/config`.

4. Enforce the No-Compromise Argon High/Low Quota Router & Antigravity Manager Fallback Policy:
   - Run `/home/aesc/.local/bin/argon-quota-router.py` via `argon-quota-router.timer` (every 60s) to monitor remaining `gemini-4-argon` quota across all accounts in `aistudio2api` (`127.0.0.1:2048`):
     - When `>20%` Argon pool quota remains, map `gemini-4-argon` to `gemini-4-argon(high)` (`agent.reasoning_effort: high`).
     - When `<=20%` Argon pool quota remains, automatically switch `gemini-4-argon` to `gemini-4-argon(low)` (`agent.reasoning_effort: low`).
     - When `0%` Argon quota remains on `aistudio2api`, do not fall back to `antigravity-manager` for Argon; go straight to `gemini-3.8-flash-high` in strict order:
       1. `gemini-3.8-flash-high` via `aistudio2api` (`127.0.0.1:2048`)
       2. `gemini-3.8-flash-high` via `antigravity-manager` (`127.0.0.1:8045`)
       3. `claude-opus-4-6-thinking` via `antigravity-manager` (`127.0.0.1:8045`)
   - Enforce `gemini-3.8-flash-high` everywhere: whenever any tool, fallback, or client (`antigravity-manager`, `aistudio2api`, `agy`, `agy-control-mcp`, `mc_chat_responder.py`, `fast_chat_mcp.py`, `agy_bridge.py`) invokes `gemini-3.8-flash`, map and call `gemini-3.8-flash-high` (never `gemini-3.8-flash-low`).
   - Hot-reload gateway plugins in-place without restarting `hermes-gateway.service` or interrupting active turns by calling `from gateway.control_socket import reload_gateway_plugins; reload_gateway_plugins(get_hermes_home())`.

5. Orchestrate Concurrent Gateway Orders (`parallel-orders` & `parallel-ops-mcp`):
   - Route follow-up messages that reply directly to a running task's prompt/progress bubble, start with `+ ` / `steer:` / `add:`, or begin with continuation phrases (`"also ..."`, `"and ..."`, `"make sure ..."`, `"don't forget ..."`, `"instead ..."`) into the active agent via `agent.steer(...)` rather than spawning a duplicate parallel worker; prefix with `// ` or `parallel:` to force a separate parallel worker.
   - Cap parallel worker history snapshots (`<=10` recent messages / `16k` chars) and assign an isolated `session_id` (`par_<HHMMSS>_<hex>`) per worker so concurrent tasks neither trigger context compaction locks nor collide on the shared persistent bash session.
   - Use `parallel-ops-mcp` (`~/.local/lib/parallel_ops_mcp.py`) tools (`parallel_list_active_orders`, `parallel_steer_order`, `parallel_cancel_order`, `parallel_batch_shell`, `parallel_argon_pool_status`) to inspect/steer active orders or run up to 16 isolated shell commands in parallel.

### 2. Tune Sub-Second / Fast-Chat Responder Cascade (`fast-chat-mcp` & `mc-chat-responder`)
1. Use a 3-tier response hierarchy for real-time chat bots:
   - **Tier 1 (0ms Reflex)**: Match deterministic commands (`/tpaccept`, `/spawn`, `/home`, `/warp`, jump), frequent status questions (`where u`, `where is roshrak`, `who are you`, greetings), and server-specific FAQs in-process before any network call. Exclude interrogative phrases (`what warp`, `which warp`) from `/warp` command regexes so questions about warps do not trigger teleport commands.
   - **Tier 2 (0ms LRU Cache)**: Cache normalized `(sender, message)` or `(persona, message)` replies in memory with TTL expiration.
   - **Tier 3 (No-Compromise LLM Cascade)**: Route to `http://127.0.0.1:2048/v1/chat/completions` (`gemini-4-argon`) first, then `http://127.0.0.1:8045/v1/chat/completions` (`antigravity-manager`) using `gemini-3.8-flash-high` and `claude-opus-4-6-thinking`, with `max_tokens: 1024` and `timeout: 12`.
2. When deploying updates to `/home/aesc/.local/bin/mc_chat_responder.py`:
   - Edit the source of truth at `/home/aesc/tonelico/nixos/home/files/bin/mc_chat_responder.py`.
   - Unlink `/home/aesc/.local/bin/mc_chat_responder.py` (`rm -f`) before copying the updated script over, then `chmod +x` and run `systemctl --user restart mc-chat-responder.service`.
3. Verify end-to-end latency with `mcp__fast_chat_mcp__fast_chat_mc_responder_turbo(action="test_reply")` or `mcp__fast_chat_mcp__fast_chat_benchmark_endpoints`.

### 3. Provider Isolation & Antigravity-Manager Pool Synchronization
1. Keep only two LLM providers configured across Hermes (`~/.hermes/config.yaml`, `~/.hermes/auth.json`) and local coding clients (`~/.config/opencode/opencode.json`):
   - `aistudio2api` (`http://127.0.0.1:2048/v1`, key env `AISTUDIO2API_API_KEY`, primary model `gemini-4-argon`).
   - `antigravity-manager` (`http://127.0.0.1:8045/v1`, key env `AGY_ROTATOR_API_KEY`, default model `gemini-3.8-flash-high`, `transport: chat_completions`, `discover_models: true`).
2. Do not retain third-party provider credentials (`gemini`, `openai-codex`, `copilot`, `openrouter`, `anthropic`, `aioffer`, `orcarouter`, `miraiapi`) or backup config files containing private API keys.
3. To suppress `copilot` from auto-seeding `gh auth token` into `~/.hermes/auth.json`, run `hermes auth remove copilot <id>` so `suppressed_sources.copilot` is recorded in `auth.json`.
4. To upgrade `antigravity-manager` (`https://github.com/lbjlaq/Antigravity-Manager.git`), headlessly link all `aistudio2api` Google accounts into `antigravity-manager` using their existing Camoufox `storage-state.json` cookies, or export a portable 400-day account pool bundle (`AI_Pool_Bundle_*_400d.zip`), follow `references/antigravity-manager-account-sync.md`. For `antigravity-manager` (`http://127.0.0.1:8045`), the web dashboard login password (`WEB_PASSWORD`) and `/api/*` bearer token live at `proxy.admin_password` in `/home/aesc/.antigravity_tools/gui_config.json` (and `/home/aesc/agm-docker/.env`), while `proxy.api_key` (`API_KEY`) is the client key for `/v1/*` inference endpoints.

## Pitfalls
- Send the full configuration object returned by `GET /api/config` when calling `PUT http://127.0.0.1:2048/api/config` — partial JSON payloads fail validation with HTTP 400.
- Synchronize client API keys whenever configuring `PROXY_API_KEY` on `aistudio2api` — update `~/.hermes/config.yaml` (`api_key`), `~/.local/bin/agy` (`GEMINI_API_KEY`), and `~/.local/lib/fast_chat_mcp.py` to match, and clear any stale `"last_status": "exhausted"` / `401` entry under `credential_pool["custom:aistudio2api"]` in `~/.hermes/auth.json` so Hermes does not skip the primary provider for a transient 401 recorded during key rotation.
- Route bare `gemini-3.8-flash` and `gemini-3.8-flash-low` aliases to `gemini-3.8-flash-high` in both `antigravity-manager` (`custom_mapping`) and `aistudio2api` (`MODEL_MAPPING`) so every `3.8-flash` invocation runs at `high` reasoning effort.
- Set `max_tokens >= 1024` and `timeout >= 12` when calling High-thinking models (`gemini-4-argon` on High or `gemini-3.8-flash-high`) and `continue` to the next fallback endpoint when `message.content` is empty (`""`) — smaller `max_tokens` budgets (`<=256`) get consumed entirely by internal thinking tokens, returning an empty `content` string and causing premature fallback.
- Avoid the deprecated `build` upstream channel in `aistudio2api`; set `UPSTREAM_CHANNELS=playground` to prevent timeouts and legacy schema deprecation errors.
- Set `WAA_BACKEND=spidermonkey` in `aistudio2api` to avoid heavy Camoufox browser processes and reclaim ~400–600MB RAM per account.
- Keep `aistudio2api-watchdog.timer` (every 30s) active and pin `Xvfb` at `~/.local/share/nix-roots/aistudio2api-xvfb` — if `aistudio2api` boots before DNS is ready or loses its internal generation worker (`Error 503: AIStudio2API 生成服务已停止`), the watchdog queries `GET http://127.0.0.1:2048/api/status` and triggers `POST http://127.0.0.1:2048/api/control/start` when `state == "STOPPED"`.
- Use strict line regex `re.sub(r"default:\s*gemini-4-argon[^\n]*", ...)` rather than substring `.replace("default: gemini-4-argon", ...)` when automated scripts update Hermes `config.yaml` — prefix matching against `"default: gemini-4-argon"` matches inside already-suffixed lines (`default: gemini-4-argon-low`), continually appending `-low-low-low...` on every run and corrupting the config until requests 404.
- Route desktop launcher (`-open-ui`) and no-argument interactive calls in `/home/aesc/aistudio2api/aistudio2api` and `~/.local/share/applications/aistudio2api.desktop` to `/home/aesc/.local/bin/aistudio2api-ui` (`chromium --app=http://127.0.0.1:2048/`) instead of invoking `aistudio2api-core -open-ui` — when `aistudio2api.service` already holds `127.0.0.1:2048`, `aistudio2api-core -open-ui` exits immediately with `bind: address already in use` before opening the dashboard.
- Use `low` (not `minimal` or `high`) as `agent.reasoning_effort` when the active model is `gemini-4-argon` on `aistudio2api` — `gemini-4-argon` only declares `thinking_levels: ["LOW", "MEDIUM", "HIGH"]` in `/api/models`, and `high` adds ~16s of thinking delay while burning daily account quota.
- Handle both string and dict entries when inspecting `account["models"]` from `GET http://127.0.0.1:2048/api/accounts` (`m.get("id") if isinstance(m, dict) else str(m)`), and always join against `GET http://127.0.0.1:2048/api/cooldowns` by `account_id`/`account_label` — `/api/accounts` reports `state: "ready"` whenever the account session is initialized even while `gemini-4-argon` is in active HTTP 429 cooldown under `/api/cooldowns`.
- Cross-check `/home/aesc/aistudio2api/runtime/logs/aistudio2api.log` for per-account `HTTP 429` (`resume=`) events when auditing account limits on `aistudio2api` instead of relying on `GET /api/cooldowns` or `runtime-state.json` alone — service restarts, auth directory restores, and manual cooldown clears wipe local cooldown entries while upstream Google AI Studio daily limits remain in effect until `15:00 +07:00` (`08:00 UTC`), and `fill-first` routing does not probe later alphabetical accounts until earlier ones fail over.
- Avoid combining `@dataclasses.dataclass` with `from __future__ import annotations` inside Hermes Gateway plugins (`~/.hermes/plugins/*/__init__.py`) — `importlib.util.module_from_spec` executes the module before registering it in `sys.modules`, causing Python's `dataclasses._is_type` to fail on `sys.modules.get(cls.__module__).__dict__`.
- Store original mixin methods on the class once (e.g., `GatewayBusySessionMixin._orig_busy_handler_before_parallel`) and always re-bind the wrapper in `register(ctx)` instead of returning early on a boolean guard — returning early prevents `reload_gateway_plugins(get_hermes_home())` from hot-swapping updated plugin handlers into the running gateway process.
- Mark ephemeral progress bubble sends with a `contextvars.ContextVar` guard (`_IS_PROGRESS_SEND`) when wrapping `TelegramAdapter.send*` to sink active progress bubbles to the bottom of the chat — otherwise two concurrent progress bubbles treat each other's re-anchors as permanent messages and leapfrog indefinitely.
- Never place `tab_flash_lite_preview` at the top of a general chat responder cascade — it is a code tab-completion model that outputs `IGNORE` on instruction-heavy chat system prompts.
- Set `max_tokens >= 256` when calling thinking-capable Gemini or Gemma models (`gemma-4-26b-a4b-it`, `gemini-3.1-flash-lite`) and `continue` to the next fallback endpoint when `message.content` is empty (`""`) — small `max_tokens` budgets (`<=120`) get consumed by internal reasoning tokens, leaving `content` empty, and treating empty `content` the same as `"IGNORE"` silently drops the reply.
- Always `rm -f ~/.local/bin/mc_chat_responder.py` before copying over it — Home Manager links `~/.local/bin/mc_chat_responder.py` into `/nix/store`, so `cp` without `rm -f` fails on the read-only store target.
- When injecting keystrokes on Wayland/niri where `wtype` is absent, invoke `/home/aesc/.local/bin/uinput_type` with positional action tokens (`t`, `slash`, `sleep:<ms>`, `type:<text>`, `enter`, `esc`) rather than raw text or flags.
- Pull prebuilt `lbjlaq/antigravity-manager:v<X.Y.Z>` images from Docker Hub and re-tag to `antigravity-manager:<X.Y.Z>-local` instead of running `docker compose up -d --build` in `~/agm-docker` — building the Rust backend from source takes ~9 minutes. Always include explicit `dns: [1.1.1.1, 8.8.8.8, 100.100.100.100]` and `mem_limit: 256m` in `~/agm-docker/compose.yml` so container DNS never breaks with `Error 502 client error (Connect)` if host `/etc/resolv.conf` or `systemd-resolved` changes.
- Include `"ttlMs": 604800000` in the `tools/list` JSON-RPC result of local stdio MCP servers (`~/.local/lib/*_mcp.py`) when enabling `lazy: true` and `idle_timeout_seconds: 120` in `~/.hermes/config.yaml` — the MCP Python SDK defaults omitted `ttlMs` to `0`, which causes `~/.hermes/cache/mcp_schema_cache.json` entries to expire immediately and forces eager subprocess spawning on every Hermes startup.
- Pass `no_viewport=True` to `browser.new_context(...)`, `CAMOU_CONFIG_1=json.dumps(fp["config"])` in `env` (falling back to any existing `/home/aesc/aistudio2api/auth/*/camoufox-fingerprint.json` when a Chrome-imported account directory lacks its own `camoufox-fingerprint.json`), and normalize cookie `sameSite` values to `Strict|Lax|None` when driving `/home/aesc/aistudio2api/runtime/camoufox/camoufox-bin` with Playwright — Camoufox's Juggler protocol rejects `viewport.isMobile`, omits `navigator.userAgent` when `CAMOU_CONFIG_1` is empty `{}` (triggering Google's `/not-supported` redirect), and rejects lowercase `sameSite` values from `storage-state.json`.
- Keep `aistudio2api.oauth.refresh_token` in `storage-state.json` strictly for Chrome `MultiBearer` tokens (`1//0g...`) and never populate it with Antigravity Tools OAuth tokens (`1//06...`) — `OAuthMultilogin` (`https://accounts.google.com/oauth/multilogin`) rejects non-Reconcilor tokens with `HTTP 403 Forbidden`; for Camoufox-authenticated accounts without a `1//0g...` token, renew 400-day cookies via `ListAccounts` + `ServiceLogin` cookie rotation instead.
- Gate Google Account Chooser clicks (`[data-identifier]`, `[data-email]`) on `"accountchooser" in page.url` during automated OAuth flows — the subsequent `/signin/oauth/v3/firstparty/nativeapp` consent screen also renders a `[data-email]` badge at the top, so clicking `[data-email]` unconditionally loops instead of advancing through the consent button.
- Intercept `http://localhost:8045/**` via `page.route` and forward the OAuth callback to `http://127.0.0.1:8045` with header `Host: localhost:8045` when `antigravity-manager` binds `127.0.0.1:8045` — browsers resolving `localhost` to IPv6 `::1` otherwise fail to reach the callback listener.
- Call `POST http://127.0.0.1:8045/api/accounts/refresh` (`-H "Authorization: Bearer <admin_password>" -H "Content-Type: application/json" -d '{}'`) whenever an account in `GET http://127.0.0.1:8045/api/accounts` shows `"quota": null` or `"name": null` (~1.8 KB stub in `~/.antigravity_tools/accounts/<id>.json`) — newly linked OAuth accounts remain uninitialized in the dashboard until a quota refresh populates their profile name, `subscription_tier`, and model quota buckets.
