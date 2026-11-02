---
name: pipewire-playerctl-media-ops
description: "Control desktop audio volume, PipeWire sinks, and playerctl."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [audio, pipewire, playerctl, volume, media]
---

# PipeWire Audio & Playerctl Media Controller

## When to Use
- Checking what song/video is currently playing, pausing/stopping media, skipping tracks, or reading/adjusting PipeWire audio volume.

## Tools & MCP Integration
- `mcp_desktop_computer_use_mcp_cu_media_status`: Returns `playerctl` playback status, artist/title metadata, and `wpctl` default sink volume.
- `mcp_desktop_computer_use_mcp_cu_media_control`: Executes `play`, `pause`, `play-pause`, `stop`, `next`, `previous`.
- `mcp_browser_automation_mcp_browser_ytmusic_control`: Controls YouTube Music tab specifically.

## Procedure
1. Observe current media state via `cu_media_status`.
2. If the requested state is already active (e.g. already paused/stopped), report No-Op immediately.
3. Otherwise execute `cu_media_control` or `browser_ytmusic_control`, then re-check `cu_media_status` to verify.

## Verification
- `cu_media_status` after the action confirms the new playback state or track title.
