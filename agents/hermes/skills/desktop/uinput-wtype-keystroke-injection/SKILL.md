---
name: uinput-wtype-keystroke-injection
description: "Inject keystrokes and shortcuts via wtype and uinput_type."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [wtype, uinput, keyboard, wayland, computer-use]
---

# Safe Wayland & uinput Keystroke Injection

## When to Use
- Typing text or sending keyboard shortcuts (`Return`, `Escape`, `Ctrl+K`, `Ctrl+L`, `Ctrl+W`) into native Wayland/XWayland GUI apps or games.

## Tools & MCP Integration
- `mcp_desktop_computer_use_mcp_cu_type_text`: Types text via `wtype` with optional Enter key.
- `mcp_desktop_computer_use_mcp_cu_send_key`: Sends key chords (`ctrl+k`, `Return`, `Escape`).
- `mcp_desktop_computer_use_mcp_cu_focus_window`: Verifies target window owns focus before typing.
- `~/.local/bin/uinput_type`: Kernel-level input helper for games like Minecraft.

## Procedure
1. Focus the target window with `cu_focus_window` and confirm `is_focused: true`.
2. For standard Wayland apps (Chromium, Discord, Kitty), use `cu_type_text` or `cu_send_key`.
3. For raw input games (Minecraft), use `uinput_type` (`mcp_minecraft_ops_mcp_mc_send_chat_or_command`).

## Verification
- Confirm focus ownership before sending input and verify resulting UI/log state afterward.
