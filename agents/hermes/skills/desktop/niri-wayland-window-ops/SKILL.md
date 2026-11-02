---
name: niri-wayland-window-ops
description: "Control Niri/Hyprland/Sway windows, focus, and workspaces."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [niri, hyprland, sway, wayland, window-management]
---

# Niri, Hyprland & Sway Window Orchestrator

## When to Use
- Inspecting open desktop windows, focusing an application, closing a window, or switching workspaces on this NixOS Wayland desktop (`niri`, `hyprland`, or `sway`).

## Tools & MCP Integration
- `mcp_desktop_computer_use_mcp_cu_detect_session`: Detects active compositor (`niri`, `hyprland`, `sway`), sockets, and input helpers.
- `mcp_desktop_computer_use_mcp_cu_list_windows`: Lists all windows with ID, `app_id`, title, PID, and `is_focused`.
- `mcp_desktop_computer_use_mcp_cu_focus_window`: Focuses a window and verifies focus ownership.
- `mcp_desktop_computer_use_mcp_cu_close_window`: Closes a window and verifies removal from the compositor tree.
- `mcp_desktop_computer_use_mcp_cu_workspace_switch`: Switches active workspace.

## Procedure
1. Always Observe first: call `cu_list_windows` to inspect existing windows (Reuse Before Create; No-Op Detection if already satisfied).
2. Act: call `cu_focus_window`, `cu_close_window`, or `cu_workspace_switch`.
3. Verify: inspect the returned post-action window list to prove the state changed before reporting success.

## Verification
- Never claim a window was opened, focused, or closed without verifying the updated compositor window list.
