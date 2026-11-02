---
name: minecraft-chat-bot-responder
description: "Manage mc_chat_responder.py and read Minecraft chat logs."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, chat-bot, logs, tpa, responder]
---

# Minecraft Chat Responder Bot & Log Monitor

## When to Use
- Checking, starting, stopping, or restarting the `mc_chat_responder.py` bot, or reading/searching in-game `[CHAT]` messages in `latest.log`.

## Tools & MCP Integration
- `mcp_minecraft_ops_mcp_mc_bot_responder_status`: Checks if `mc_chat_responder.py` is running and tails `~/.local/share/mc_chat_responder.log`.
- `mcp_minecraft_ops_mcp_mc_bot_responder_control`: Starts, stops, or restarts `mc_chat_responder.py`.
- `mcp_minecraft_ops_mcp_mc_read_latest_log`: Reads recent lines or `[CHAT]` messages from `latest.log`.
- `mcp_minecraft_ops_mcp_mc_search_chat_history`: Searches current and `.log.gz` archived logs for players, whispers, or `/tpa` requests.

## Procedure
1. Inspect bot state with `mc_bot_responder_status` and recent chat with `mc_read_latest_log(chat_only=True)`.
2. Use `mc_bot_responder_control` to start/stop/restart the responder daemon and verify the resulting PID list.

## Verification
- `mc_bot_responder_status` confirms the process state and recent log lines.
