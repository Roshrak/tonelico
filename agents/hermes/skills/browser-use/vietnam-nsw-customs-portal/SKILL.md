---
name: vietnam-nsw-customs-portal
description: "Navigate Vietnam Customs, VNSW, ECOSYS, and C/O portals."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [customs-portal, vnsw, ecosys, tariff, browser]
---

# Vietnam Customs, VNSW & C/O Portal Navigator

## When to Use
- Looking up official Vietnam Customs (`customs.gov.vn`), National Single Window (`vnsw.gov.vn`), Electronic C/O (`ecosys.gov.vn`), or FTA origin verification portals.

## Tools & MCP Integration
- `mcp_browser_automation_mcp_browser_customs_portal_links`: Returns verified portal URLs for Vietnam Customs, VNSW, ECOSYS, China C/O Form E, Korea Form AK, and EU REX.
- `mcp_browser_automation_mcp_browser_extract_html_tables`: Extracts tariff or status tables from portal pages.
- `browser_exec`: Drives interactive portal searches when JavaScript or CAPTCHA handling is needed.

## Procedure
1. Retrieve the authoritative portal endpoint via `browser_customs_portal_links`.
2. Use `web_extract` or `browser_extract_html_tables` for public pages, or `browser_exec` for interactive form submission.
3. If a browser "Leave site?" (`beforeunload`) dialog appears, always accept/select "Leave".

## Verification
- All tariff rates or status records are cited with their exact portal URL.
