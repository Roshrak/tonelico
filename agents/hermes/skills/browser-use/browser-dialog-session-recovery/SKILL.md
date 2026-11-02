---
name: browser-dialog-session-recovery
description: "Handle Leave-site dialogs, WAF blocks, and Wayback cache."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [browser, dialogs, wayback, headers, recovery]
---

# Browser Dialog Policy & Blocked Page Recovery

## When to Use
- Handling `beforeunload` ("Leave site?") browser dialogs, diagnosing HTTP 403/429/Cloudflare blocks, or retrieving archived snapshots from the Wayback Machine.

## Tools & MCP Integration
- `mcp_browser_automation_mcp_browser_check_site_headers`: Inspects HTTP status, redirects, and WAF headers.
- `mcp_browser_automation_mcp_browser_wayback_snapshot_lookup`: Checks Internet Archive Wayback Machine snapshots.
- `browser_exec`: Executes CDP commands and handles JS dialogs.

## Procedure
1. Per standing user policy, whenever a "Leave site?" (`beforeunload`) dialog appears during browser navigation, always select "Leave" (accept navigation).
2. If a URL fails with 403/429, run `browser_check_site_headers` to identify the block, then try `browser_wayback_snapshot_lookup` or `browser_exec`.

## Verification
- Navigation completes to the target URL or a verified archive snapshot is retrieved.
