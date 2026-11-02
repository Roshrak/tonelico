---
name: wayland-clipboard-file-bridge
description: "Read and write Wayland clipboard and bridge desktop alerts."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [clipboard, wl-copy, wl-paste, notifications, wayland]
---

# Wayland Clipboard & Desktop Notification Bridge

## When to Use
- Copying generated text, code snippets, customs declarations, or commands directly to the user's Wayland clipboard (`wl-copy`), reading clipboard contents (`wl-paste`), or sending desktop/Telegram notifications.

## Tools & MCP Integration
- `mcp_desktop_computer_use_mcp_cu_clipboard_get`: Reads clipboard via `wl-paste`.
- `mcp_desktop_computer_use_mcp_cu_clipboard_set`: Writes text to clipboard via `wl-copy`.
- `mcp_desktop_computer_use_mcp_cu_send_desktop_notification`: Sends native `notify-send` popup and optional Telegram alert.

## Procedure
1. Use `cu_clipboard_get` or `cu_clipboard_set` for instant clipboard transfer.
2. Read back with `cu_clipboard_get` to verify clipboard state when setting important payloads.

## Verification
- Clipboard read-back matches the written string length.
