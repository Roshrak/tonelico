---
name: discord-webhook-rich-embeds
description: "Send formatted messages, embeds, and files to Discord."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, webhook, embeds, notifications, attachments]
---

# Discord Webhook & File Attachment Publisher

## When to Use
- Sending automated reports, rich embeds, OCR summaries, or file attachments (PDF, DOCX, PNG charts) to a Discord channel via Webhook URL without needing a running bot gateway.

## Tools & MCP Integration
- `mcp_discord_ops_mcp_discord_format_embed_json`: Builds validated Discord Rich Embed payloads with hex colors, fields, and timestamps.
- `mcp_discord_ops_mcp_discord_webhook_send`: Posts text and embeds to a Discord Webhook URL.
- `mcp_discord_ops_mcp_discord_webhook_send_file`: Uploads a local file attachment via `multipart/form-data`.

## Procedure
1. Format structured data into an embed using `discord_format_embed_json`.
2. Send the message/embed via `discord_webhook_send` or upload files via `discord_webhook_send_file`.
3. Check the returned HTTP status (`200` or `204`) to confirm delivery.

## Verification
- Webhook HTTP response code is 200/204.
