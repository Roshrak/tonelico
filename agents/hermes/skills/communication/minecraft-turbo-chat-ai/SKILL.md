---
name: minecraft-turbo-chat-ai
description: "Operate the sub-second Turbo Minecraft Chat Responder."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, morgan-ai, chat-bot, turbo, low-latency]
---

# Minecraft Turbo Chat AI (Morgan AI Responder)

## When to Use
- Operating, testing, or tuning the upgraded `mc_chat_responder.py` (`mc-chat-responder.service`) for Crazy-Fools Minecraft chat.

## Tools & MCP Integration
- `mcp_fast_chat_mcp_fast_chat_mc_responder_turbo`: Checks service status, restarts the daemon, or runs live latency benchmarks (`action="test_reply"`).
- `mcp_minecraft_ops_mcp_mc_bot_responder_status`: Reads `~/.local/share/mc_chat_responder.log`.

## Architecture Upgrades
1. 50ms (`0.05s`) log polling interval (10x faster than the old 500ms loop).
2. 0ms instant reflex handler for `/tpaccept`, `/spawn`, `/home`, `/warp` (excluding "what/which warp" questions), jump requests, AFK/status questions, and CFUK server FAQs (e.g. `/warp mall` for mending books, silk touch vs fortune on melons).
3. Multi-tier no-compromise LLM cascade (`max_tokens: 1024`, `timeout: 12s`): `127.0.0.1:2048` (`gemini-4-argon`, dynamically synced High `>20%` / Low `<=20%`) -> `127.0.0.1:8045` (`gemini-3.8-flash-high`) -> `127.0.0.1:8045` (`claude-opus-4-6-thinking`) -> `127.0.0.1:8765` (`gemini-3.8-flash-high`), backed by a 128-entry LRU cache.
4. Empirical Roshrak In-Game Speech Fingerprint (`style_as_roshrak` + `SYSTEM_PROMPT`, from 3,104 CFUK messages):
   - 91.4% all-lowercase in-game, 93.6% no ending period, 0% exclamation marks (`!`), zero `:)` / `:D` / `xD` emoticons, never uses `fr` or `ngl`.
   - 3 to 10 words max, natural CFUK vocabulary (`yo`, `wb`, `ty`, `cya`, `alr`, `ye`, `nah`, `welp`, `hmm`, `bruh`, `imma`, `smth`, `sb`, `tbh`, `idk`, `ik`, `rn`, `rq`, `wdm`, `af`, copula drops like `it fine`, `it not`, `it the`).
   - Built-in CFUK player nickname map (`broonie` -> `boss`, `p0licy`/`edi______` -> `pol`, `astroy300` -> `astroy`, `hekatonkires` -> `heck`, `raelon225` -> `rae`, `404thread` -> `404`, `johnnyboy4200` -> `johnny`, `tuxedodolphin` -> `tux`, `warmerpenguin` -> `penguin`, `septleigh08` -> `sept`, `stinkybacon` -> `stinky`).
5. Tightened `uinput_type` keystroke delays (`120ms` instead of `250ms`).
