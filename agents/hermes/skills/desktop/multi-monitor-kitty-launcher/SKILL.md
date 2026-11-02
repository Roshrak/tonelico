---
name: multi-monitor-kitty-launcher
description: "Launch visible Kitty terminals and GUI apps on the monitor."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [kitty, monitor, gui, launch, detached]
---

# Monitor Display & Detached Kitty Launcher

## When to Use
- User asks to display a command or dashboard on the monitor (e.g. "Fastfetch on the monitor", "Show htop on screen", "Open app X on the desktop").

## Tools & MCP Integration
- `mcp_desktop_computer_use_mcp_cu_launch_detached`: Launches `<command>` detached or inside `nohup kitty --hold -e <command> >/dev/null 2>&1 &` and verifies window count.
- `mcp_desktop_computer_use_mcp_cu_list_windows`: Verifies the new Kitty or GUI window appeared in the compositor.

## Procedure
1. Check `cu_list_windows` first to avoid duplicate launches.
2. Call `cu_launch_detached` with `in_kitty_monitor=True` for CLI commands meant to stay visible on the user's screen.
3. Call `cu_list_windows` to verify the new window is present and report the verified outcome.

## Verification
- The launched process/window appears in `cu_list_windows` and the tool call returns immediately without blocking.
