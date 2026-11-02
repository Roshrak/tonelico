---
name: discord-telegram-cross-bridge
description: "Broadcast alerts and reports to Discord and Telegram."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, telegram, bridge, alerts, cross-post]
---

# Discord & Telegram Cross-Platform Bridge

## When to Use
- Broadcasting completed OCR scan summaries, customs clearance alerts, long-running task 10-minute progress updates, or GPU market reports to both Telegram and Discord.

## Tools & MCP Integration
- `mcp_discord_ops_mcp_discord_telegram_bridge_send`: Sends a message simultaneously to Telegram (`~/.local/bin/telegram_send.py`) and a Discord Webhook or Channel.
- `mcp_discord_ops_mcp_discord_webhook_send_file`: Uploads file attachments to Discord.

## Procedure
1. Prepare a concise, plain-text or Markdown summary of the verified result.
2. Call `discord_telegram_bridge_send` with the message and target Discord webhook/channel.
3. Verify `telegram_sent` and `discord_sent` flags in the response.

## Verification
- Delivery status is confirmed for each configured destination channel.
