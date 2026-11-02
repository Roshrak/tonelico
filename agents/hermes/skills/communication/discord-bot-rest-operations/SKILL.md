---
name: discord-bot-rest-operations
description: "Query guilds, channels, and messages via Discord API v10."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, bot, api, channels, messages]
---

# Discord Bot REST API v10 Operations

## When to Use
- Listing Discord servers (guilds), channels, reading channel message history, searching messages by author/keyword, or sending bot messages using `DISCORD_BOT_TOKEN`.

## Tools & MCP Integration
- `mcp_discord_ops_mcp_discord_bot_get_me`: Verifies bot identity (`/users/@me`).
- `mcp_discord_ops_mcp_discord_bot_list_guilds`: Lists joined Discord servers.
- `mcp_discord_ops_mcp_discord_bot_list_channels`: Lists channels in a guild.
- `mcp_discord_ops_mcp_discord_bot_read_messages`: Reads recent channel messages.
- `mcp_discord_ops_mcp_discord_bot_search_messages`: Filters channel messages by keyword or author.
- `mcp_discord_ops_mcp_discord_bot_send_message`: Posts a message, reply, or embed to a channel.

## Procedure
1. Verify bot credentials with `discord_bot_get_me`.
2. Discover `guild_id` and `channel_id` via `discord_bot_list_guilds` and `discord_bot_list_channels`.
3. Read or send messages and verify the returned message ID.

## Verification
- API returns a valid Discord message/channel object with snowflake ID.
