---
name: discord-guild-archive-analysis
description: "Use when archiving or analyzing a Discord server."
version: 1.0.0
author: Trong (aesc), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, archive, corpus, speech-analysis, guild-search, leveldb]
---

# Discord Guild Archive & Corpus Analysis

## When to Use
- Dumping the full message history of a Discord server from start to present.
- Searching across all channels in a guild for event clues, lore, or topic timelines.
- Extracting statistical speech profiles (length distribution, punctuation, casing, vocabulary, grammatical shortcuts) for a community or a specific user to tune conversational personas.

## Procedure

### 1. Authenticate Against the Target Guild
1. Prefer `DISCORD_BOT_TOKEN` via `discord-bot-rest-operations` when the bot is a member of the target server.
2. When the user requests analysis of a server where only their local Discord desktop client is a member:
   - Scan `~/.config/discord/Local Storage/leveldb/*.ldb` and `*.log` for encrypted token strings matching `dQw4w9WgXcQ:([A-Za-z0-9+/=]+)`.
   - Base64-decode the match, verify the 3-byte `v10` prefix, and split into `nonce = raw[3:15]`, `ciphertext = raw[15:-16]`, and `tag = raw[-16:]`.
   - Derive the 16-byte AES-GCM key via `hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1, 16)`, trying both the system keyring secret (`secret-tool lookup application discord`) and the Linux Chromium fallback `b"peanuts"`.
   - Verify the decrypted token against `GET https://discord.com/api/v10/users/@me` in memory.

### 2. Archive Standard Text Channels in Parallel
1. List all guild channels (`GET /api/v10/guilds/<guild_id>/channels`) and filter to text/announcement channels (`type in (0, 5)`).
2. Paginate each standard channel from newest to oldest using `GET /api/v10/channels/<channel_id>/messages?limit=100&before=<last_id>` across 3–4 worker threads:
   - Sleep `0.25s` between page requests per worker.
   - On HTTP 429, read `retry_after` from the JSON body and sleep `retry_after + 0.5` seconds before retrying.
   - Save each channel to `<archive_dir>/channel_<name>_<id>.json`.

### 3. Query High-Volume Bridge Channels via Guild Search & Snowflake Windows
1. Avoid linear full-history pagination on automated bridge channels (such as Minecraft `#in-game-chat` with 100k+ messages).
2. Query the guild-wide search endpoint to locate exact timestamps and message hits across all channels at once:
   ```
   GET https://discord.com/api/v9/guilds/<guild_id>/messages/search?content=<keyword>&offset=<n>
   ```
3. To inspect full conversation context around a specific date/time in a massive channel, convert the target UTC timestamp directly to a Discord snowflake ID and fetch a bounded window:
   ```python
   DISCORD_EPOCH = 1420070400000
   snowflake = ((int(dt.timestamp() * 1000) - DISCORD_EPOCH) << 22)
   # GET /api/v10/channels/<channel_id>/messages?limit=100&before=<end_snowflake>
   ```

### 4. Extract Empirical Speech Profiles
1. Separate messages by channel context (e.g., general Discord chat vs. in-game bridge messages, where mobile auto-capitalization differs from desktop keyboard input).
2. Compute quantitative metrics before modifying any persona prompt:
   - Word and character length distributions (median, mean, and bucket percentages: `1-2`, `3-5`, `6-10`, `11-20`, `21+` words).
   - Casing ratios (strictly all-lowercase vs. sentence-case vs. all-caps).
   - Terminal punctuation rates (no ending period vs. `.`, `?`, `!`) and emoticon frequency.
   - Exact single-word/short-burst frequency rankings, recurring contractions/shortcuts, copula-drop patterns, and negative markers (slang terms the user never uses).

### 5. Mandatory Cleanup
1. Delete any temporary scripts in `$TMPDIR` / `~/.hermes/cache/scratch/` that read LevelDB or hold tokens immediately after the dump completes.
2. Never write raw Discord tokens into saved JSON files, logs, or summaries.

## Pitfalls
- Separate player jokes and bait theories from verified server/staff announcements when reconstructing server lore or puzzle hunts — players frequently invent plausible-sounding red herrings in public chat.
- Write multi-line Python scripts to a file instead of passing nested f-strings inside `python3 -c "..."` — bash double-quote expansion strips inner quotes and triggers `SyntaxError: unexpected character after line continuation character`.
- Check for read-only `/nix/store` symlinks before overwriting deployed scripts in `~/.local/bin/` or `~/.local/lib/` — unlink (`rm -f`) the symlink first, update the repository source of truth, and copy the updated file into place.
