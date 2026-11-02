---
name: discord-desktop-gui-automation
description: "Launch, focus, OCR-read, and message in Discord desktop."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, desktop, gui, wayland, ocr]
---

# Discord Desktop Client GUI Automation

## When to Use
- Launching, focusing, closing, reading visible chat messages, or typing quick messages inside the local Discord / Vesktop desktop app on Wayland.

## Tools & MCP Integration
- `mcp_discord_ops_mcp_discord_app_status`: Checks if Discord desktop app is running.
- `mcp_discord_ops_mcp_discord_app_launch_or_focus`: Launches Discord detached or reuses existing instance.
- `mcp_discord_ops_mcp_discord_app_close`: Closes Discord cleanly and verifies termination.
- `mcp_discord_ops_mcp_discord_app_send_quick_message`: Uses `Ctrl+K` quick switcher + `wtype` to send a message.
- `mcp_discord_ops_mcp_discord_app_read_screen`: Captures screen and runs PaddleOCR on visible Discord messages.

## Procedure
1. Check `discord_app_status` and `cu_list_windows(filter_query="discord")`.
2. Focus the Discord window via `cu_focus_window` before calling `discord_app_send_quick_message` or `discord_app_read_screen`.
3. Verify the resulting window or screen state.

## Verification
- Process and window state are verified before and after every action.
