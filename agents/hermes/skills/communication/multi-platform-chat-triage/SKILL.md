---
name: multi-platform-chat-triage
description: "Triage CLI, Telegram, Discord, and Minecraft chat queues."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [triage, telegram, discord, minecraft, routing]
---

# Multi-Platform Chat Triage & Quick Dispatch

## When to Use
- Routing and answering incoming messages across CLI, Telegram, Discord, and Minecraft at the appropriate speed tier.

## Tools & MCP Integration
- `mcp_fast_chat_mcp_fast_chat_smart_triage`: Determines whether a message is `instant_reflex` (<1ms), `fast_llm` (~900ms), or `deep_agent` (tool-backed).
- `mcp_fast_chat_mcp_fast_chat_telegram_quick_reply`: Sends instant humanized text to Telegram.
- `mcp_fast_chat_mcp_fast_chat_discord_quick_reply`: Sends instant humanized text to Discord.

## Procedure
1. Classify incoming text with `fast_chat_smart_triage`.
2. Route `instant_reflex` and `fast_llm` messages immediately without blocking on heavy toolchains.
3. Route `deep_agent` requests to the appropriate domain MCP server (`doc-scanner-mcp`, `customs-legal-mcp`, `desktop-computer-use-mcp`, `browser-automation-mcp`, `minecraft-ops-mcp`, `discord-ops-mcp`).
