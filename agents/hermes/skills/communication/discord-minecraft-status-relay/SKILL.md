---
name: discord-minecraft-status-relay
description: "Relay Minecraft server status and chat to Discord."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, minecraft, relay, server-status, webhook]
---

# Minecraft-to-Discord Server & Chat Relay

## When to Use
- Checking Minecraft server status (`alt.crazy-fools.co.uk:25565`) or recent in-game chat highlights from `latest.log` and posting a formatted status embed to Discord.

## Tools & MCP Integration
- `mcp_minecraft_ops_mcp_mc_server_ping`: Pings the Minecraft server for online status, latency, and player count.
- `mcp_minecraft_ops_mcp_mc_read_latest_log`: Reads recent `[CHAT]` lines from Minecraft.
- `mcp_discord_ops_mcp_discord_format_embed_json`: Formats server status and chat lines into a Discord embed.
- `mcp_discord_ops_mcp_discord_webhook_send`: Sends the embed to Discord.

## Procedure
1. Call `mc_server_ping` and `mc_read_latest_log(chat_only=True, lines=20)`.
2. Build a rich embed with `discord_format_embed_json` showing Server IP, Latency (ms), Players Online, and Recent Chat.
3. Send via `discord_webhook_send` or `discord_bot_send_message`.

## Verification
- Server ping data and chat lines are grounded in real log/socket output and delivered to Discord.
