---
name: short-punchy-replies
description: "1-3 sentence high-speed response discipline for CLI/mobile."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [concise, short, punchy, cli, telegram]
---

# Short Punchy Reply Discipline

## When to Use
- Every interactive CLI, Telegram mobile, Discord, or in-game chat turn where speed and scannability matter.

## Tools & MCP Integration
- `mcp_fast_chat_mcp_fast_chat_humanize_message`: Enforces `max_sentences` cap and strips filler phrases.
- `mcp_fast_chat_mcp_fast_chat_context_compressor`: Compresses long message histories into compact context blocks.

## Rules
1. Lead with the answer or verified outcome in the very first sentence.
2. Keep routine answers to 1–3 sentences maximum.
3. One command at a time when guiding troubleshooting steps.
