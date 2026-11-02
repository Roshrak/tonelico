---
name: minecraft-anvil-mca-inspector
description: "Inspect Minecraft .mca region files and convert coords."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, mca, anvil, chunks, coordinates, nether]
---

# Minecraft Anvil MCA Region & Coordinate Inspector

## When to Use
- Converting block coordinates between Overworld and Nether (1:8 ratio), finding chunk coordinates (`x >> 4`, `z >> 4`) and region filenames (`r.X.Z.mca`), or inspecting `.mca` files in `ChunkLens-archive` / `ChronoFinder` / local saves.

## Tools & MCP Integration
- `mcp_minecraft_ops_mcp_mc_coords_converter`: Converts block `(X, Y, Z)` to Overworld, Nether, Chunk, and `r.X.Z.mca`.
- `mcp_minecraft_ops_mcp_mc_inspect_mca_region`: Parses the 8KB Anvil `.mca` header to count populated chunks, sector offsets, and timestamps.
- `mcp_minecraft_ops_mcp_mc_list_saved_worlds`: Lists all local worlds and golden world fixtures.

## Procedure
1. Use `mc_coords_converter` to map block coordinates to the exact `r.X.Z.mca` region file.
2. Locate worlds with `mc_list_saved_worlds` and inspect region headers with `mc_inspect_mca_region`.

## Verification
- Region filename, chunk count, and coordinate math are deterministically computed.
