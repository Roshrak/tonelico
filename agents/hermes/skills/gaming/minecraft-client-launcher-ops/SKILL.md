---
name: minecraft-client-launcher-ops
description: "Launch PrismLauncher Minecraft and verify focus and /spawn."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, prismlauncher, niri, launch, spawn]
---

# Minecraft PrismLauncher & Single-Window Join Protocol

## When to Use
- Launching Minecraft (`Fabulously Optimized` instance in PrismLauncher), checking if Minecraft is running, focusing the Minecraft window in Niri, or executing the verified `/spawn` join flow.

## Tools & MCP Integration
- `mcp_minecraft_ops_mcp_mc_instance_status`: Checks PrismLauncher instances, running Java PID, and `latest.log`.
- `mcp_minecraft_ops_mcp_mc_launch_and_spawn`: Runs `~/vivian/launch_mc_and_spawn.py` with session lock and window focus verification.
- `mcp_minecraft_ops_mcp_mc_list_mods_and_packs`: Lists installed `.jar` mods, resourcepacks, and shaderpacks.

## Procedure
1. Check `mc_instance_status` first to see if Minecraft is already running (Reuse Before Create).
2. Run `mc_launch_and_spawn` to launch or focus the unique Minecraft window and verify server join.
3. Confirm via `mc_read_latest_log` that the join and `/spawn` succeeded.

## Verification
- Unique Minecraft window owns focus in an unlocked session and `latest.log` confirms connection.
