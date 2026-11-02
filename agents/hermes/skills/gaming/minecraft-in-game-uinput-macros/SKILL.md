---
name: minecraft-in-game-uinput-macros
description: "Send chat messages and slash commands into Minecraft."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, uinput, commands, chat, tpaccept]
---

# Minecraft In-Game uinput Command & Chat Sender

## When to Use
- Sending a chat message or slash command (`/spawn`, `/tpaccept`, `/home`, `/msg`, `/tpa`) into the running Minecraft client.

## Tools & MCP Integration
- `mcp_minecraft_ops_mcp_mc_send_chat_or_command`: Sends chat/commands via `/home/aesc/.local/bin/uinput_type`.
- `mcp_desktop_computer_use_mcp_cu_focus_window`: Ensures the Minecraft window is focused before global `uinput` keystrokes fire.
- `mcp_minecraft_ops_mcp_mc_read_latest_log`: Verifies the message or command effect in `latest.log`.

## Procedure
1. Focus the Minecraft window via `cu_focus_window(app_id_or_title="minecraft")` and verify `is_focused: true`.
2. Call `mc_send_chat_or_command` with the message or slash command.
3. Read `mc_read_latest_log(lines=20)` to verify the command/chat appeared in the game log.

## Verification
- `latest.log` shows the transmitted chat line or server command response.
