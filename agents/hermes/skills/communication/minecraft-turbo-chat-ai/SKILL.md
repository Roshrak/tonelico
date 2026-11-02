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
2. 0ms instant reflex handler for `/tpaccept`, `/spawn`, `/home`, `/warp`, jump requests, and AFK/status questions ("where u", "where is roshrak", "who are you").
3. Multi-tier fast LLM cascade: `127.0.0.1:2048` (`gemma-4-26b-a4b-it`, ~900ms) -> `127.0.0.1:8045` (`tab_flash_lite_preview` / `gemini-3.1-flash-lite`, ~1000ms) -> `127.0.0.1:8765` fallback, backed by a 128-entry LRU cache.
4. Tightened `uinput_type` keystroke delays (`120ms` instead of `250ms`).
