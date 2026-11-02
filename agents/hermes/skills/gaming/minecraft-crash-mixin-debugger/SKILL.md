---
name: minecraft-crash-mixin-debugger
description: "Analyze Minecraft logs and crash reports for mod errors."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, crash, mixin, fabric, debugging]
---

# Minecraft Crash Report & Mixin Conflict Debugger

## When to Use
- Diagnosing why a PrismLauncher Minecraft instance failed to launch, crashed mid-game, or threw a Fabric/Sodium/Iris Mixin error.

## Tools & MCP Integration
- `mcp_minecraft_ops_mcp_mc_crash_log_analyzer`: Scans `latest.log` or crash reports for Java exceptions and Mixin failures.
- `mcp_minecraft_ops_mcp_mc_list_mods_and_packs`: Lists all `.jar` mods in the instance.

## Procedure
1. Run `mc_crash_log_analyzer` to extract the root `Caused by:` stack trace and offending Mixin target.
2. Cross-reference the crashing package name against `mc_list_mods_and_packs` to identify the exact `.jar` file.
3. Recommend disabling, updating, or replacing the conflicting mod.

## Verification
- Root exception class and specific mod `.jar` filename are identified from log evidence.
