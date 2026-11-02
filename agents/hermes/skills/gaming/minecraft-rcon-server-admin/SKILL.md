---
name: minecraft-rcon-server-admin
description: "Ping Minecraft servers, lookup UUIDs, and run RCON."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, server, ping, rcon, uuid]
---

# Minecraft Server Ping, UUID & RCON Administrator

## When to Use
- Checking if a Minecraft server (`alt.crazy-fools.co.uk:25565` or any server) is online, checking latency and player count, resolving Mojang/Offline player UUIDs, or sending RCON commands.

## Tools & MCP Integration
- `mcp_minecraft_ops_mcp_mc_server_ping`: Pings any Java server via Server List Ping (SLP) protocol.
- `mcp_minecraft_ops_mcp_mc_player_uuid_lookup`: Computes offline UUID and queries Mojang API for online UUID.
- `mcp_minecraft_ops_mcp_mc_rcon_command`: Executes authenticated RCON commands.
- `mcp_minecraft_ops_mcp_mc_crafting_and_enchant_ref`: Looks up optimal enchantment loadouts and villager trades.

## Procedure
1. Call `mc_server_ping` to check server status, MOTD, version, and online players.
2. Use `mc_player_uuid_lookup` for UUID resolution or `mc_rcon_command` for server administration.

## Verification
- Server latency, version, and player counts come directly from live SLP socket handshake.
