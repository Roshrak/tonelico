---
name: cdp-multi-tab-orchestrator
description: "Manage, activate, reuse, and close Chromium tabs over CDP."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [cdp, chromium, tabs, browser-automation, reuse]
---

# Chromium CDP Multi-Tab Orchestrator

## When to Use
- Inspecting open browser tabs, focusing an existing tab instead of opening duplicates, closing specific tabs, or closing all Chromium instances cleanly.

## Tools & MCP Integration
- `mcp_browser_automation_mcp_browser_status_and_tabs`: Lists running browser processes and open CDP tabs.
- `mcp_browser_automation_mcp_browser_cdp_activate_tab`: Brings a matching CDP tab to the front.
- `mcp_browser_automation_mcp_browser_cdp_close_tab`: Closes a specific tab by ID, title, or URL substring.
- `mcp_browser_automation_mcp_browser_close_all_chromium`: Closes all Chromium processes and stops media playback.

## Procedure
1. Call `browser_status_and_tabs` first to check if Chromium or the target URL is already open.
2. If already open, activate/reuse it via `browser_cdp_activate_tab` instead of creating tab sprawl.
3. If asked to close Chrome/Chromium and `running` is already `False`, report "Already closed" (No-Op rule).
4. After closing, verify `remaining_processes == 0`.

## Verification
- Post-action `browser_status_and_tabs` confirms the exact tab/process count.
