---
name: discord-server-admin-moderation
description: "Manage Discord threads, channels, roles, and moderation."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, admin, threads, moderation, roles]
---

# Discord Server & Thread Administration

## When to Use
- Creating discussion threads for tasks/dossiers, organizing channels, or moderating a Discord server.

## Tools & MCP Integration
- `mcp_discord_ops_mcp_discord_bot_manage_thread`: Creates public threads with configurable `auto_archive_duration`.
- `mcp_discord_ops_mcp_discord_bot_list_channels`: Audits guild channel layout.
- `mcp_discord_ops_mcp_discord_bot_send_message`: Posts structured announcements into threads or channels.

## Procedure
1. List existing channels via `discord_bot_list_channels` to avoid duplicate channel/thread creation.
2. Create a thread with `discord_bot_manage_thread` and post the initial summary inside it.

## Verification
- Created thread ID and channel metadata are returned by the Discord API.
