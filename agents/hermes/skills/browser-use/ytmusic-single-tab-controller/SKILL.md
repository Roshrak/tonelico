---
name: ytmusic-single-tab-controller
description: "Control YouTube Music with strict single-tab reuse."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [ytmusic, youtube-music, music, browser, audio]
---

# YouTube Music Single-Tab Controller

## When to Use
- User asks to play music, turn on music, pause music, or switch to a different song.

## Tools & MCP Integration
- `mcp_browser_automation_mcp_browser_ytmusic_control`: Runs `~/.local/bin/ytmusic_control.py` (`play`, `pause`, `next`, `prev`, `status`, `search <song>`).
- `mcp_browser_automation_mcp_browser_status_and_tabs`: Inspects open Chromium tabs.
- `mcp_desktop_computer_use_mcp_cu_media_status`: Verifies active `playerctl` playback state.

## Procedure
1. Always use YouTube Music (`https://music.youtube.com`) for music requests.
2. When switching songs, NEVER open a new tab or second browser instance. Reuse the existing YouTube Music tab via `mcp_browser_automation_mcp_browser_ytmusic_control`.
3. If opening a brand-new media URL via Chromium when another browser is playing, stop media (`playerctl stop`) and close the old browser first so audio never overlaps.
4. Verify playback status via `cu_media_status`.

## Verification
- Exactly one YouTube Music tab is active and `cu_media_status` confirms the requested song/state.
