---
name: minecraft-map-and-bluemap-investigation
description: "Decode Xaero WorldMap cache files and BlueMap 3D tiles."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [minecraft, xaero, worldmap, bluemap, prbm, coordinates, forensics]
---

# Minecraft Map and BlueMap Forensic Investigation

## When to Use
- Locating player structures, secret bases, event builds, admin blocks (`command_block`, `lodestone`, `spawner`), or specific coordinate targets in multiplayer worlds.
- Extracting and decoding local client map cache files (Xaero's WorldMap `.zip` files containing `region.xaero`).
- Fetching and parsing remote web map 3D tiles (BlueMap `.prbm.gz` format) without needing an active client connection or full world download.

## Procedure

### 1. Fast Byte-Level Triage of Xaero WorldMap Files
1. Locate Xaero WorldMap cache directories under the active launcher profile (e.g. `~/.local/share/PrismLauncher/instances/<instance>/minecraft/xaero/world-map/<server>/<dim>/`).
2. Each region file `{rx}_{rz}.zip` contains `region.xaero` representing a 512×512 block region (`rx = X // 512`, `rz = Z // 512`).
3. **Decompression rule**: The first 6 bytes of `region.xaero` are a header (`ff 00 08 00 08 03`). Raw zlib stream begins at offset 6. Decompress via `zlib.decompress(data[6:])`.
4. Run an initial fast string/byte scan over decompressed buffers across all region zips to filter for target block names (e.g. `b"command_block"`, `b"lodestone"`, `b"sign"`, `b"red_wool"`, `b"nether_portal"`).

### 2. Exact Coordinate Extraction from `region.xaero`
1. The decompressed data starts with an NBT-encoded palette table of block states (Compound tag containing `palette` array of strings or block state compounds).
2. Followed by 64 tile chunks (8×8 grid, each 64×64 blocks). Each tile chunk contains 4×4 map tiles (16×16 blocks).
3. Compute exact world block coordinates:
   ```python
   world_x = rx * 512 + chunk_x * 64 + tile_x * 16 + block_x
   world_z = rz * 512 + chunk_z * 64 + tile_z * 16 + block_z
   ```
4. Record Y-levels (`height`) and overlays (`grass`, `carpet`, `snow_layer`) to pinpoint elevation and hidden sub-surface layers.

### 3. Remote 3D Tile Probing via BlueMap PRBM
1. BlueMap serves compressed 3D geometry tiles at:
   `https://<domain>/maps/<world>/tiles/0/x{tx}/z{tz}.prbm.gz`
   where `tx = X // 32` and `tz = Z // 32` (each tile is 32×32 blocks).
2. Decompress via `gzip.decompress()`.
3. Binary structure of PRBM:
   - Byte 0: version (usually 1).
   - Byte 1: flags (`flags = data[1]`, indexed geometry flag: `(flags >> 7) & 1`).
   - Bytes 2–5: unsigned 32-bit integer `vertex_count` (`<I`).
   - Bytes 6–7: padding / flags.
   - Position attribute: Starts at offset 8 with ASCII null-terminated string `b"position\x00"` (length 9).
   - Attribute header: 3 bytes at offset 17..19 (`type = data[17]` which is 33/0x21 for float32, cardinality, and component flags).
   - Position data payload: Begins at byte offset 20. Total byte length is `vertex_count * 12` bytes.
   - Vertices are packed as little-endian IEEE-754 floats (`<fff`):
     - `local_x`: float in `[0.0, 32.0]` relative to tile origin.
     - `y_val`: float representing absolute world elevation (Y).
     - `local_z`: float in `[0.0, 32.0]` relative to tile origin.
   - Absolute coordinates:
     ```python
     abs_x = tx * 32 + local_x
     abs_y = y_val
     abs_z = tz * 32 + local_z
     ```
   - Unpacking loop:
     ```python
     pos_start = 20
     for i in range(0, vertex_count * 12, 12):
         lx, y, lz = struct.unpack_from("<fff", data, pos_start + i)
         world_x = tx * 32 + lx
         world_z = tz * 32 + lz
     ```
   - Subsequent attributes follow sequentially: `normal\x00`, `color\x00`, `uv\x00`, `ao\x00`, `blocklight\x00`, `sunlight\x00`. Locate each by finding `b"<attr_name>\x00"`.
4. Query target `tx, tz` tiles and check minimum/maximum Y levels to identify underground voids, shafts, bedrock basements, or modified structures without rendering the web browser.

## Pitfalls
- Do not pass offset 0 to `zlib.decompress` on `region.xaero` — it fails with `zlib.error: Error -2 while decompressing data: inconsistent stream header`. Always slice at offset 6 (`data[6:]`).
- Tile coordinates in BlueMap URLs do not have digit-separating slashes (use `x{tx}/z{tz}.prbm.gz`, not `x/{tx}/z/{tz}`).
- PRBM position vertex data starts at fixed offset 20, not offset 23. Offset 8 is `b"position\x00"` (9 bytes, offsets 8..16), followed by 3 bytes of type/cardinality header (offsets 17..19). Unpacking at offset 23 misaligns IEEE floats and yields denormalized junk (`1e-39`). Always unpack position from offset 20.
- BlueMap surface tiles only capture blocks visible from above or down to standard surface lighting. Deep underground rooms fully encased in solid bedrock or stone without light sources are omitted from surface tile meshes. Use client Xaero cave layer caches (`caves/<layer>/`) for deep underground verification.
- In Xaero WorldMap cache directories, cave slices are indexed by integer layer numbers (`caves/<layer>/{rx}_{rz}.zip`). Layer 4 corresponds to standard surface elevations (Y ≈ 64..79), layer 3 covers upper underground (Y ≈ 48..63), layer 0 covers Y ≈ 0..15, and negative layers (`caves/-1..-4/`) cover deepslate void levels down to Y = -64. Always inspect specific cave layer folders when probing for subterranean vaults, bedrock rooms, or beds placed below surface terrain.
- Correlate player warp executions from client logs with region modification timestamps (`os.path.getmtime`) within a ±15-second window to resolve unmapped or private warp coordinates. A warp command that succeeds triggers immediate file writes/updates to the local Xaero region `.zip` corresponding to the destination chunk.
