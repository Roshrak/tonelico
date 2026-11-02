---
name: gpu-hardware-market-research
description: "Search concrete GPU/hardware listings with VND prices."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gpu, marketplace, hardware, price-comparison, telegram]
---

# GPU & Hardware Marketplace Price Researcher

## When to Use
- User asks to find GPU/hardware prices, sellers, or second-hand deals (e.g. "Tìm giá card...", "Tìm người bán RX 7800 XT...", "RTX 4070 price in HCM").

## Tools & MCP Integration
- `mcp_browser_automation_mcp_browser_gpu_market_search`: Runs `/home/aesc/.local/bin/gpu_market_search.py "<query>"` to fetch real listings, generate a visual comparison chart, send it to Telegram, and output the structured table.

## Procedure
1. Immediately invoke `mcp_browser_automation_mcp_browser_gpu_market_search` (or `/home/aesc/.local/bin/gpu_market_search.py "<query>"` via `terminal`).
2. Report CONCRETE INDIVIDUAL LISTINGS with:
   - Seller / Shop name
   - Exact Variant & Condition (e.g. Sapphire Pulse vs Nitro+, Box, Warranty date)
   - Exact Asking Price in VNĐ
   - Location / Pickup area
   - Source / Link reference
3. Include a visual ASCII/text Price Comparison Bar Chart ranking all offers from lowest to highest.

##Verification
- Output contains concrete individual listings grounded in tool output plus a ranked price comparison chart.
